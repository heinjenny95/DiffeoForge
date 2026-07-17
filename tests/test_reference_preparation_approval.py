from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import diffeoforge.reference_preparation_approval as approval_module
from diffeoforge.config import ConfigurationError
from diffeoforge.reference_preparation_approval import (
    APPROVAL_STATEMENT,
    create_reference_preparation_approval,
    serialize_reference_preparation_approval,
    verify_saved_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Preparation Approval Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _reviewed_fingerprint(config: Path, run_id: str) -> str:
    plan = plan_reference_preparation(config, run_id=run_id)
    return reference_preparation_plan_fingerprint(plan)


def _saved_request(root: Path, run_id: str = "approval-001") -> tuple[Path, dict]:
    config = root / "atlas.yaml"
    fingerprint = _reviewed_fingerprint(config, run_id)
    request = create_reference_preparation_approval(
        config,
        run_id=run_id,
        approved_fingerprint=fingerprint,
    )
    path = write_reference_preparation_approval(request, root / "review" / "approval.json")
    return path, request


def test_create_approval_is_deterministic_preparation_only_and_does_not_prepare(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    fingerprint = _reviewed_fingerprint(config, "approved-plan")
    before = _inventory(root)

    first = create_reference_preparation_approval(
        config,
        run_id="approved-plan",
        approved_fingerprint=fingerprint.upper(),
    )
    second = create_reference_preparation_approval(
        config,
        run_id="approved-plan",
        approved_fingerprint=f"  {fingerprint}  ",
    )

    assert first == second
    assert _inventory(root) == before
    assert not (root / "runs").exists()
    assert first["status"] == "approved_reference_preparation_not_prepared"
    assert first["approval"] == {
        "scope": "preparation_only",
        "statement": APPROVAL_STATEMENT,
        "approved_plan_fingerprint": fingerprint,
        "engine_execution_authorized": False,
    }
    assert first["plan"]["run"]["destination_exists"] is False
    assert "launches no process" in first["scientific_boundary"]
    assert "does not validate parameters" in first["scientific_boundary"]


def test_create_rejects_wrong_or_stale_reviewed_fingerprint(tmp_path: Path) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    reviewed = _reviewed_fingerprint(config, "stale-review")

    with pytest.raises(ConfigurationError, match="differs from the explicitly approved"):
        create_reference_preparation_approval(
            config,
            run_id="stale-review",
            approved_fingerprint="0" * 64,
        )

    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError, match="differs from the explicitly approved"):
        create_reference_preparation_approval(
            config,
            run_id="stale-review",
            approved_fingerprint=reviewed,
        )
    assert not (root / "runs").exists()


def test_write_is_exclusive_and_exactly_matches_deterministic_serialization(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request = _saved_request(root)
    original = request_path.read_bytes()

    assert original == serialize_reference_preparation_approval(request)
    assert original == serialize_reference_preparation_approval(deepcopy(request))
    assert all(byte < 128 for byte in original)
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_reference_preparation_approval(request, request_path)
    assert request_path.read_bytes() == original
    assert not (root / "runs").exists()


def test_verify_request_internally_and_against_fresh_current_state_is_read_only(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request = _saved_request(root)
    before = _inventory(root)

    internal = verify_saved_reference_preparation_approval(request_path)
    current = verify_saved_reference_preparation_approval(
        request_path,
        current_config_path=root / "atlas.yaml",
    )

    assert _inventory(root) == before
    assert internal["current_state"] is None
    assert current["current_state"]["matches_approved_plan"] is True
    assert current["current_state"]["destination_absent"] is True
    assert current["approval"]["approved_plan_fingerprint"] == request["approval"][
        "approved_plan_fingerprint"
    ]
    assert current["recorded_plan"]["subjects"] == 5
    assert "grants no preparation or execution permission" in current["scientific_boundary"]
    assert not (root / "runs").exists()


def test_verify_rejects_stale_current_state_without_changing_request(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, _ = _saved_request(root)
    original = request_path.read_bytes()
    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")

    with pytest.raises(ConfigurationError, match="does not match the approved plan"):
        verify_saved_reference_preparation_approval(
            request_path,
            current_config_path=root / "atlas.yaml",
        )

    assert request_path.read_bytes() == original
    assert not (root / "runs").exists()


def test_verify_rejects_tampering_and_weakened_boundary(tmp_path: Path) -> None:
    root = _project(tmp_path)
    request_path, request = _saved_request(root)

    tampered_plan = deepcopy(request)
    tampered_plan["plan"]["protected_files"][0]["sha256"] = "0" * 64
    request_path.write_text(json.dumps(tampered_plan), encoding="ascii")
    with pytest.raises(ConfigurationError, match="fingerprint does not match"):
        verify_saved_reference_preparation_approval(request_path)

    weakened = deepcopy(request)
    weakened["scientific_boundary"] = "Engine execution is allowed."
    request_path.write_text(json.dumps(weakened), encoding="ascii")
    with pytest.raises(ConfigurationError, match="schema violation"):
        verify_saved_reference_preparation_approval(request_path)


def test_verify_rejects_duplicate_keys_trailing_data_and_nonfinite_constants(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    request_path, request = _saved_request(root)
    encoded = json.dumps(request, ensure_ascii=True, sort_keys=True)

    request_path.write_text(
        '{"schema_version":"0.1",' + encoded.lstrip()[1:],
        encoding="ascii",
    )
    with pytest.raises(ConfigurationError, match="duplicate JSON object key"):
        verify_saved_reference_preparation_approval(request_path)

    request_path.write_text(encoded + "\n{}\n", encoding="ascii")
    with pytest.raises(ConfigurationError, match="not one valid JSON document"):
        verify_saved_reference_preparation_approval(request_path)

    request_path.write_text('{"value": NaN}\n', encoding="ascii")
    with pytest.raises(ConfigurationError, match="unsupported JSON constant"):
        verify_saved_reference_preparation_approval(request_path)


def test_verify_detects_request_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path)
    request_path, _ = _saved_request(root)
    original_read = approval_module._read_required_file
    calls = 0

    def read_and_change_on_final_check(path: Path, label: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(path.read_bytes() + b" ")
        return original_read(path, label)

    monkeypatch.setattr(approval_module, "_read_required_file", read_and_change_on_final_check)

    with pytest.raises(ConfigurationError, match="changed during verification"):
        verify_saved_reference_preparation_approval(request_path)


def test_approval_cli_round_trip_is_ascii_safe_and_does_not_prepare(tmp_path: Path) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    run_id = "Freigabe Käfer 001"
    fingerprint = _reviewed_fingerprint(config, run_id)
    request_path = root / "Überprüfung" / "Freigabe.json"

    created = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan-approve",
            str(config),
            "--run-id",
            run_id,
            "--approve-fingerprint",
            fingerprint,
            "--output",
            str(request_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert created.returncode == 0, created.stderr.decode(errors="replace")
    assert all(byte < 128 for byte in created.stdout)
    assert all(byte < 128 for byte in created.stderr)
    request = json.loads(created.stdout.decode("ascii"))
    assert request_path.read_bytes() == serialize_reference_preparation_approval(request)
    assert created.stderr.decode("ascii").strip() == (
        "Reference preparation approval: "
        f"{json.dumps(str(request_path.resolve()), ensure_ascii=True)}"
    )

    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan-approval-verify",
            str(request_path),
            "--current-config",
            str(config),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert verified.returncode == 0, verified.stderr.decode(errors="replace")
    assert verified.stderr == b""
    assert all(byte < 128 for byte in verified.stdout)
    evidence = json.loads(verified.stdout.decode("ascii"))
    assert evidence["status"] == "verified_reference_preparation_approval"
    assert evidence["current_state"]["matches_approved_plan"] is True
    assert not (root / "runs").exists()
