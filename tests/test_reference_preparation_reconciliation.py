from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.reference_preparation_reconciliation as reconciliation_module
from diffeoforge.cli import main
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
from diffeoforge.reference_preparation_reconciliation import (
    reconcile_reference_preparation,
    serialize_reference_preparation_reconciliation,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Reconciliation Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _approval(
    root: Path,
    run_id: str = "reconcile-001",
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


def _report(root: Path, request_path: Path, request_hash: str) -> dict:
    return reconcile_reference_preparation(
        request_path,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=request_hash,
    )


def test_reconciliation_reports_clear_without_creating_output_root(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    before = request_path.read_bytes()

    report = _report(root, request_path, request_hash)

    assert report["status"] == "clear_to_prepare"
    assert report["action_required"] is False
    assert report["mutation_performed"] is False
    assert report["destination"]["status"] == "absent"
    assert report["private_stages"] == []
    assert report["state_stable_across_observations"] is True
    assert report["current_plan"]["exactly_matches_approved"] is True
    assert not Path(request["plan"]["run"]["output_root"]).exists()
    assert request_path.read_bytes() == before


def test_reconciliation_serialization_is_deterministic_utf8_json(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, _, request_hash = _approval(root)
    report = _report(root, request_path, request_hash)

    first = serialize_reference_preparation_reconciliation(report)
    second = serialize_reference_preparation_reconciliation(dict(reversed(report.items())))

    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first) == report
    assert "Käfer".encode() in first


def test_reconciliation_verifies_published_prepared_not_executed_run(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    evidence = prepare_approved_reference_run(
        request_path,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=request_hash,
    )
    destination = Path(request["plan"]["run"]["destination"])
    before_manifest = (destination / "manifest.json").read_bytes()

    report = _report(root, request_path, request_hash)

    assert report["status"] == "published_prepared_not_executed_verified"
    assert report["action_required"] is False
    assert report["destination"]["status"] == "verified_prepared_not_executed"
    assert report["destination"]["manifest_sha256"] == evidence["prepared_run"][
        "manifest_sha256"
    ]
    assert report["destination"]["engine_execution_started"] is False
    assert report["private_stages"] == []
    assert (destination / "manifest.json").read_bytes() == before_manifest


def test_reconciliation_identifies_complete_unpublished_private_stage(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    prepare_approved_reference_run(
        request_path,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=request_hash,
    )
    destination = Path(request["plan"]["run"]["destination"])
    private = destination.parent / (
        f".diffeoforge-preparing-{request['plan']['run']['run_id']}-{'a' * 32}"
    )
    destination.rename(private)
    before_manifest = (private / "manifest.json").read_bytes()

    report = _report(root, request_path, request_hash)

    assert report["status"] == "attention_required"
    assert report["action_required"] is True
    assert report["destination"]["status"] == "absent"
    assert len(report["private_stages"]) == 1
    stage = report["private_stages"][0]
    assert stage["status"] == "verified_complete_unpublished"
    assert stage["token"] == "a" * 32
    assert stage["engine_execution_started"] is False
    assert not destination.exists()
    assert (private / "manifest.json").read_bytes() == before_manifest


def test_reconciliation_preserves_and_reports_incomplete_exact_stage(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    private = destination.parent / (
        f".diffeoforge-preparing-{request['plan']['run']['run_id']}-{'b' * 32}"
    )
    private.mkdir(parents=True)
    sentinel = private / "partial.txt"
    sentinel.write_text("preserve crash evidence\n", encoding="utf-8")

    report = _report(root, request_path, request_hash)

    assert report["status"] == "attention_required"
    assert report["private_stages"][0]["status"] == "incomplete_or_mismatched"
    assert sentinel.read_text(encoding="utf-8") == "preserve crash evidence\n"


def test_reconciliation_ignores_near_match(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, _, request_hash = _approval(root)
    near = root / "runs" / f".diffeoforge-preparing-other-run-{'c' * 32}"
    near.mkdir(parents=True)

    report = _report(root, request_path, request_hash)

    assert report["status"] == "clear_to_prepare"
    assert report["private_stages"] == []
    assert near.is_dir()


def test_reconciliation_does_not_follow_stage_link(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    destination.parent.mkdir()
    target = root / "unrelated"
    target.mkdir()
    candidate = destination.parent / (
        f".diffeoforge-preparing-{request['plan']['run']['run_id']}-{'d' * 32}"
    )
    try:
        candidate.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic-link creation is unavailable on this runner: {error}")

    report = _report(root, request_path, request_hash)

    assert len(report["private_stages"]) == 1
    assert report["private_stages"][0]["status"] == "unsafe_link"
    assert target.is_dir()


def test_reconciliation_does_not_follow_destination_link(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])
    destination.parent.mkdir()
    target = root / "unrelated-destination"
    target.mkdir()
    try:
        destination.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic-link creation is unavailable on this runner: {error}")

    report = _report(root, request_path, request_hash)

    assert report["status"] == "attention_required"
    assert report["destination"]["status"] == "unsafe_link"
    assert target.is_dir()


def test_reconciliation_rejects_wrong_hash_and_stale_current_plan(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    destination = Path(request["plan"]["run"]["destination"])

    with pytest.raises(ConfigurationError, match="independently recorded"):
        _report(root, request_path, "0" * 64)

    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError, match="does not exactly match"):
        _report(root, request_path, request_hash)

    assert not destination.exists()


def test_reconciliation_rejects_state_change_between_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    request_path, _, request_hash = _approval(root)
    original = reconciliation_module._observe
    calls = 0

    def changing(plan):
        nonlocal calls
        calls += 1
        value = original(plan)
        if calls == 2:
            value["destination"]["reason"] += " changed"
        return value

    monkeypatch.setattr(reconciliation_module, "_observe", changing)

    with pytest.raises(ConfigurationError, match="changed during read-only inspection"):
        _report(root, request_path, request_hash)


def test_cli_status_has_json_human_and_attention_exit_codes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _project(tmp_path)
    request_path, request, request_hash = _approval(root)
    common = [
        "reference-preparation-status",
        str(request_path),
        "--current-config",
        str(root / "atlas.yaml"),
        "--expect-request-sha256",
        request_hash,
    ]

    assert main([*common, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "clear_to_prepare"

    destination = Path(request["plan"]["run"]["destination"])
    private = destination.parent / (
        f".diffeoforge-preparing-{request['plan']['run']['run_id']}-{'e' * 32}"
    )
    private.mkdir(parents=True)
    assert main(common) == 1
    output = capsys.readouterr()
    assert "[incomplete_or_mismatched]" in output.out
    assert "No files were deleted, renamed, published" in output.out
    assert output.err == ""


def test_reconciliation_module_imports_without_optional_compute_or_qt() -> None:
    code = (
        "import sys; import diffeoforge.reference_preparation_reconciliation; "
        "assert 'torch' not in sys.modules; assert 'PySide6' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
