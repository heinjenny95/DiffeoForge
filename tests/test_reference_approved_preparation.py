from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.reference_approved_preparation as approved_module
import diffeoforge.runs as runs_module
from diffeoforge.config import ConfigurationError
from diffeoforge.reference_approved_preparation import prepare_approved_reference_run
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
    root = tmp_path / "Approved Preparation Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _approval(
    root: Path,
    run_id: str = "approved-preparation-001",
) -> tuple[Path, dict, str]:
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id=run_id)
    request = create_reference_preparation_approval(
        config,
        run_id=run_id,
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    request_path = write_reference_preparation_approval(
        request,
        root / "review" / "approval.json",
    )
    request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
    return request_path, request, request_hash


def _temporary_runs(root: Path) -> list[Path]:
    runs = root / "runs"
    return [] if not runs.exists() else list(runs.glob(".diffeoforge-preparing-*"))


def test_prepare_approved_run_matches_exact_plan_and_stops_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    original_request = request_path.read_bytes()

    def forbidden_process(*_args, **_kwargs):
        raise AssertionError("approved preparation must not launch a process")

    monkeypatch.setattr(runs_module.subprocess, "run", forbidden_process)
    evidence = prepare_approved_reference_run(
        request_path,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=request_hash.upper(),
    )

    run = Path(evidence["prepared_run"]["path"])
    manifest = verify_prepared_run(run)
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]

    assert evidence["status"] == "prepared_approved_reference_run_not_executed"
    assert evidence["approval_request"]["sha256"] == request_hash
    assert evidence["approval_request"]["expected_sha256"] == request_hash
    assert evidence["approved_plan"]["canonical_fingerprint"] == request["approval"][
        "approved_plan_fingerprint"
    ]
    assert evidence["prepared_run"]["engine_execution_started"] is False
    assert evidence["prepared_run"]["output_empty"] is True
    assert evidence["prepared_run"]["lifecycle_last_event"] == "prepared"
    assert manifest["protected_artifacts"] == [
        {key: item[key] for key in ("path", "bytes", "sha256")}
        for item in request["plan"]["protected_files"]
    ]
    assert events == [
        {
            "event": "prepared",
            "run_id": request["plan"]["run"]["run_id"],
            "timestamp": events[0]["timestamp"],
        }
    ]
    assert list((run / "output").iterdir()) == []
    assert not (run / "result.json").exists()
    assert not (run / "logs" / "deformetrica.log").exists()
    assert request_path.read_bytes() == original_request


def test_prepare_rejects_wrong_external_request_hash_before_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request, _ = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])

    with pytest.raises(ConfigurationError, match="independently recorded SHA-256"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256="0" * 64,
        )

    assert not destination.exists()
    assert not (root / "runs").exists()


def test_prepare_rejects_stale_current_mesh_before_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")

    with pytest.raises(ConfigurationError, match="does not exactly match"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert not destination.exists()
    assert not (root / "runs").exists()


def test_prepare_rejects_request_change_before_publication_and_cleans_private_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    original_append = runs_module._append_event

    def append_then_change_request(path: Path, event: dict) -> None:
        original_append(path, event)
        request_path.write_bytes(request_path.read_bytes() + b" ")

    monkeypatch.setattr(runs_module, "_append_event", append_then_change_request)

    with pytest.raises(ConfigurationError, match="changed before atomic publication"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert not destination.exists()
    assert _temporary_runs(root) == []


def test_prepare_rejects_private_staged_byte_mismatch_without_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    original_generate = runs_module.generate_engine_files

    def generate_then_tamper(*args, **kwargs):
        paths = original_generate(*args, **kwargs)
        paths[0].write_bytes(paths[0].read_bytes() + b"\n")
        return paths

    monkeypatch.setattr(runs_module, "generate_engine_files", generate_then_tamper)

    with pytest.raises(ConfigurationError, match="does not exactly match"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert not destination.exists()
    assert _temporary_runs(root) == []


def test_prepare_rejects_input_race_after_fresh_plan_without_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    original_prepare = approved_module.prepare_run_against_plan

    def change_mesh_then_prepare(*args, **kwargs):
        subject = root / "synthetic" / "meshes" / "subject-01.vtk"
        subject.write_bytes(subject.read_bytes() + b"\n")
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(
        approved_module,
        "prepare_run_against_plan",
        change_mesh_then_prepare,
    )

    with pytest.raises(ConfigurationError, match="does not exactly match"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert not destination.exists()
    assert _temporary_runs(root) == []


def test_prepare_validates_evidence_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])

    def reject_evidence(_value) -> None:
        raise ConfigurationError("synthetic evidence schema failure")

    monkeypatch.setattr(approved_module, "_validate_evidence", reject_evidence)

    with pytest.raises(ConfigurationError, match="evidence schema failure"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert not destination.exists()
    assert _temporary_runs(root) == []


def test_prepare_never_replaces_destination_appearing_before_atomic_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    original_append = runs_module._append_event

    def append_then_reserve_destination(path: Path, event: dict) -> None:
        original_append(path, event)
        destination.mkdir()
        (destination / "owner.txt").write_text("unrelated content\n", encoding="utf-8")

    monkeypatch.setattr(runs_module, "_append_event", append_then_reserve_destination)

    with pytest.raises(ConfigurationError, match="appeared before atomic publication"):
        prepare_approved_reference_run(
            request_path,
            current_config_path=root / "atlas.yaml",
            expected_request_sha256=request_hash,
        )

    assert (destination / "owner.txt").read_text(encoding="utf-8") == "unrelated content\n"
    assert list(destination.iterdir()) == [destination / "owner.txt"]
    assert _temporary_runs(root) == []


def test_reference_prepare_approved_cli_is_ascii_safe_in_unicode_paths(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root, run_id="Freigabe Käfer 002")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-prepare-approved",
            str(request_path),
            "--current-config",
            str(root / "atlas.yaml"),
            "--expect-request-sha256",
            request_hash,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    assert all(byte < 128 for byte in completed.stdout)
    evidence = json.loads(completed.stdout.decode("ascii"))
    assert evidence["approved_plan"]["run_id"] == request["plan"]["run"]["run_id"]
    assert evidence["prepared_run"]["engine_execution_started"] is False
    verify_prepared_run(evidence["prepared_run"]["path"])
