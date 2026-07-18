from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.desktop.reference_preparation_worker_harness as harness_module
import diffeoforge.runs as runs_module
from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
    build_reference_preparation_request,
)
from diffeoforge.desktop.reference_preparation_worker_harness import (
    main,
    run_reference_preparation_worker_harness,
)
from diffeoforge.desktop.reference_preparation_worker_protocol import (
    DesktopReferencePreparationWorkerEvent,
    ReferencePreparationWorkerEventLedger,
)
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)
from diffeoforge.runs import verify_prepared_run

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Preparation Worker Harness Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _request(root: Path, run_id: str = "worker-harness-001") -> DesktopReferencePreparationRequest:
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id=run_id)
    approval = create_reference_preparation_approval(
        config,
        run_id=run_id,
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    approval_path = write_reference_preparation_approval(
        approval,
        root / "review" / "approval.json",
    )
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()
    return build_reference_preparation_request(
        approval_path,
        config,
        expected_approval_sha256=approval_hash,
        request_id=f"request-{run_id}",
    )


def _run(request: DesktopReferencePreparationRequest):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_reference_preparation_worker_harness(
        stdin=io.StringIO(json.dumps(request.as_dict(), sort_keys=True) + "\n"),
        stdout=stdout,
        stderr=stderr,
    )
    events = [
        DesktopReferencePreparationWorkerEvent.from_dict(json.loads(line))
        for line in stdout.getvalue().splitlines()
    ]
    return code, events, stdout.getvalue(), stderr.getvalue()


def test_harness_prepares_exact_run_and_emits_verified_stop_before_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request = _request(root)

    def forbidden_engine_process(*_args, **_kwargs):
        raise AssertionError("preparation worker must not launch an engine process")

    monkeypatch.setattr(runs_module.subprocess, "run", forbidden_engine_process)
    code, events, stdout, stderr = _run(request)
    ledger = ReferencePreparationWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)
    terminal = ledger.reconcile()

    assert code == 0
    assert stderr == ""
    assert all(ord(character) < 128 for character in stdout)
    assert [event.kind for event in events] == [
        "accepted",
        "phase",
        "phase",
        "phase",
        "terminal",
    ]
    assert [event.payload["phase"] for event in events[1:4]] == [
        "verify_request",
        "prepare_approved",
        "verify_prepared_run",
    ]
    assert terminal.payload["outcome"] == "prepared_not_executed"
    assert terminal.payload["engine_execution_started"] is False
    assert terminal.payload["preparation_evidence"]["prepared_run"][
        "output_empty"
    ] is True
    verify_prepared_run(request.destination)
    assert list((request.destination / "output").iterdir()) == []
    assert not (request.destination / "result.json").exists()
    assert not (request.destination / "logs" / "deformetrica.log").exists()


def test_harness_reports_stale_inputs_without_preparation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request = _request(root)
    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")

    code, events, _, stderr = _run(request)
    ledger = ReferencePreparationWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)
    terminal = ledger.reconcile()

    assert code == 1
    assert stderr == ""
    assert [event.kind for event in events] == ["accepted", "phase", "terminal"]
    assert terminal.payload["outcome"] == "failed"
    assert terminal.payload["destination_exists"] is False
    assert terminal.payload["engine_execution_started"] is False
    assert not request.destination.exists()


def test_harness_preserves_schema_valid_failure_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request = _request(root)

    def reject_postpublication(_destination) -> None:
        raise RuntimeError("synthetic postpublication verification failure")

    monkeypatch.setattr(harness_module, "verify_prepared_run", reject_postpublication)
    code, events, _, stderr = _run(request)
    ledger = ReferencePreparationWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)
    terminal = ledger.reconcile()

    assert code == 1
    assert stderr == ""
    assert terminal.payload["outcome"] == "failed"
    assert terminal.payload["destination_exists"] is True
    assert terminal.payload["preparation_evidence"] is None
    assert request.destination.exists()
    verify_prepared_run(request.destination)


def test_harness_rejects_duplicate_keys_extra_input_missing_lf_and_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _project(tmp_path)
    request = _request(root)

    for transport, message in (
        ('{"request_id":"a","request_id":"b"}\n', "duplicate JSON object key"),
        (json.dumps(request.as_dict()) + "\n{}\n", "exactly one request"),
        (json.dumps(request.as_dict()), "LF-terminated"),
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run_reference_preparation_worker_harness(
            stdin=io.StringIO(transport),
            stdout=stdout,
            stderr=stderr,
        )
        assert code == 2
        assert stdout.getvalue() == ""
        assert message in stderr.getvalue()

    assert main(["unexpected"]) == 2
    assert "arguments are not supported" in capsys.readouterr().err
    assert not request.destination.exists()


def test_harness_real_pipe_round_trip_prepares_without_execution(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request = _request(root, run_id="real-pipe-approved")
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_path, environment.get("PYTHONPATH", "")) if item
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge.desktop.reference_preparation_worker_harness",
        ],
        input=json.dumps(request.as_dict(), sort_keys=True) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=ROOT,
        env=environment,
        timeout=30,
        check=False,
    )
    events = [
        DesktopReferencePreparationWorkerEvent.from_dict(json.loads(line))
        for line in completed.stdout.splitlines()
    ]
    ledger = ReferencePreparationWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert ledger.reconcile().payload["outcome"] == "prepared_not_executed"
    assert ledger.terminal.payload["engine_execution_started"] is False
    verify_prepared_run(request.destination)
