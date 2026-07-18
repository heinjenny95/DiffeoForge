from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.reference_preparation_reconciliation_verification as verification_module
from diffeoforge.config import ConfigurationError
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
from diffeoforge.reference_preparation_reconciliation_verification import (
    serialize_reference_preparation_reconciliation_verification,
    verify_saved_reference_preparation_reconciliation,
    write_reference_preparation_reconciliation_verification,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Saved Status Verification Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _approval(root: Path) -> tuple[Path, str]:
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id="saved-status-001")
    request = create_reference_preparation_approval(
        config,
        run_id="saved-status-001",
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    path = write_reference_preparation_approval(
        request,
        root / "review" / "approval.json",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _report(root: Path, approval: Path, approval_sha256: str) -> dict:
    return reconcile_reference_preparation(
        approval,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=approval_sha256,
    )


def _saved_report(tmp_path: Path) -> tuple[Path, Path, Path, dict, bytes, str]:
    root = _project(tmp_path)
    approval, approval_sha256 = _approval(root)
    report = _report(root, approval, approval_sha256)
    report_bytes = serialize_reference_preparation_reconciliation(report)
    path = root / "review" / "status-Käfer.json"
    path.write_bytes(report_bytes)
    return root, approval, path, report, report_bytes, approval_sha256


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, _sha256(path.read_bytes()))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_verify_saved_status_is_deterministic_and_reads_no_recorded_state(
    tmp_path: Path,
) -> None:
    root, approval, path, report, report_bytes, _approval_sha256 = _saved_report(tmp_path)
    approval.unlink()
    (root / "atlas.yaml").unlink()
    before = _inventory(root)
    expected = _sha256(report_bytes)

    first = verify_saved_reference_preparation_reconciliation(
        path,
        expected_report_sha256=expected.upper(),
    )
    second = verify_saved_reference_preparation_reconciliation(
        path,
        expected_report_sha256=expected,
    )

    assert first == second
    assert _inventory(root) == before
    assert first["schema_version"] == "0.1"
    assert first["status"] == "verified_saved_reference_preparation_reconciliation"
    assert first["report"]["sha256"] == expected
    assert first["report"]["expected_sha256"] == expected
    assert first["report"]["matches_deterministic_serialization"] is True
    assert first["report"]["mutation_performed"] is False
    assert first["report"]["state_stable_across_observations"] is True
    assert first["recorded_observation"]["run_id"] == "saved-status-001"
    assert first["recorded_observation"]["approval_sha256"] == report[
        "approval_request"
    ]["sha256"]
    assert "reads no current config" in first["scientific_boundary"]


def test_verify_saved_status_rejects_duplicate_trailing_and_nonfinite_json(
    tmp_path: Path,
) -> None:
    _root, _approval_path, path, report, _report_bytes, _approval_sha256 = _saved_report(
        tmp_path
    )
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)

    duplicate = ('{"schema_version":"0.1",' + encoded.lstrip()[1:]).encode()
    path.write_bytes(duplicate)
    with pytest.raises(ConfigurationError, match="duplicate JSON object key"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(duplicate)
        )

    trailing = encoded.encode() + b"\n{}\n"
    path.write_bytes(trailing)
    with pytest.raises(ConfigurationError, match="not one valid JSON document"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(trailing)
        )

    nonfinite = b'{"value": NaN}\n'
    path.write_bytes(nonfinite)
    with pytest.raises(ConfigurationError, match="unsupported JSON constant"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(nonfinite)
        )


def test_verify_saved_status_rejects_hash_schema_and_serialization_tampering(
    tmp_path: Path,
) -> None:
    _root, _approval_path, path, report, report_bytes, _approval_sha256 = _saved_report(
        tmp_path
    )

    with pytest.raises(ConfigurationError, match="independently recorded SHA-256"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256="0" * 64
        )

    noncanonical = (
        json.dumps(report, indent=4, ensure_ascii=True, sort_keys=False) + "\n"
    ).encode("ascii")
    path.write_bytes(noncanonical)
    with pytest.raises(ConfigurationError, match="deterministic DiffeoForge serialization"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(noncanonical)
        )

    invalid = dict(report)
    invalid["status"] = "unsupported"
    invalid_bytes = (
        json.dumps(invalid, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(invalid_bytes)
    with pytest.raises(ConfigurationError, match="reconciliation schema violation"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(invalid_bytes)
        )

    assert report_bytes != path.read_bytes()


def test_verify_saved_status_detects_file_change_during_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _root, _approval_path, path, _report, report_bytes, _approval_sha256 = _saved_report(
        tmp_path
    )
    original = verification_module.serialize_reference_preparation_reconciliation

    def serialize_then_change(value):
        rendered = original(value)
        path.write_bytes(path.read_bytes() + b" ")
        return rendered

    monkeypatch.setattr(
        verification_module,
        "serialize_reference_preparation_reconciliation",
        serialize_then_change,
    )

    with pytest.raises(ConfigurationError, match="changed during verification"):
        verify_saved_reference_preparation_reconciliation(
            path, expected_report_sha256=_sha256(report_bytes)
        )


def test_verification_evidence_serializes_and_writes_exactly_once(
    tmp_path: Path,
) -> None:
    root, _approval_path, report_path, _report, report_bytes, _approval_sha256 = (
        _saved_report(tmp_path)
    )
    evidence = verify_saved_reference_preparation_reconciliation(
        report_path,
        expected_report_sha256=_sha256(report_bytes),
    )
    payload = serialize_reference_preparation_reconciliation_verification(evidence)
    destination = root / "review" / "verification-Käfer.json"

    written = write_reference_preparation_reconciliation_verification(
        evidence,
        destination,
    )

    assert written == destination.absolute()
    assert written.read_bytes() == payload
    assert all(byte < 128 for byte in payload)
    assert json.loads(payload)["report"]["sha256"] == _sha256(report_bytes)
    assert list(destination.parent.glob("verification-Käfer.json*")) == [destination]

    preserved = destination.read_bytes()
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_reference_preparation_reconciliation_verification(
            evidence,
            destination,
        )
    assert destination.read_bytes() == preserved


def test_status_cli_emits_exact_verifiable_utf8_bytes_in_unicode_path(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    approval, approval_sha256 = _approval(root)
    expected_report = serialize_reference_preparation_reconciliation(
        _report(root, approval, approval_sha256)
    )
    status_command = [
        sys.executable,
        "-m",
        "diffeoforge",
        "reference-preparation-status",
        str(approval),
        "--current-config",
        str(root / "atlas.yaml"),
        "--expect-request-sha256",
        approval_sha256,
        "--json",
    ]

    status = subprocess.run(
        status_command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert status.returncode == 0, status.stderr.decode(errors="replace")
    assert status.stderr == b""
    assert status.stdout == expected_report
    assert "Käfer".encode() in status.stdout

    saved = root / "review" / "cli-status-Käfer.json"
    conflicting = subprocess.run(
        [*status_command, "--output", str(saved)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert conflicting.returncode == 2
    assert not saved.exists()

    file_status = subprocess.run(
        [*status_command[:-1], "--output", str(saved)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert file_status.returncode == 0, file_status.stderr.decode(errors="replace")
    assert file_status.stderr == b""
    assert saved.read_bytes() == status.stdout
    assert _sha256(status.stdout).encode() in file_status.stdout

    preserved = saved.read_bytes()
    duplicate = subprocess.run(
        [*status_command[:-1], "--output", str(saved)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert duplicate.returncode == 2
    assert saved.read_bytes() == preserved
    assert b"will not be overwritten" in duplicate.stderr

    before = _inventory(root)
    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-preparation-status-verify",
            str(saved),
            "--expect-report-sha256",
            _sha256(status.stdout),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert verify.returncode == 0, verify.stderr.decode(errors="replace")
    assert verify.stderr == b""
    assert all(byte < 128 for byte in verify.stdout)
    evidence = json.loads(verify.stdout.decode("ascii"))
    evidence_bytes = serialize_reference_preparation_reconciliation_verification(
        evidence
    )
    assert verify.stdout == evidence_bytes
    assert evidence["report"]["matches_deterministic_serialization"] is True
    assert evidence["recorded_observation"]["run_id"] == "saved-status-001"
    assert _inventory(root) == before

    evidence_path = root / "review" / "cli-verification-Käfer.json"
    file_verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-preparation-status-verify",
            str(saved),
            "--expect-report-sha256",
            _sha256(status.stdout),
            "--output",
            str(evidence_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert file_verify.returncode == 0, file_verify.stderr.decode(errors="replace")
    assert file_verify.stderr == b""
    assert evidence_path.read_bytes() == evidence_bytes
    assert _sha256(evidence_bytes).encode() in file_verify.stdout

    preserved_evidence = evidence_path.read_bytes()
    after_export = _inventory(root)
    duplicate_evidence = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-preparation-status-verify",
            str(saved),
            "--expect-report-sha256",
            _sha256(status.stdout),
            "--output",
            str(evidence_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert duplicate_evidence.returncode == 2
    assert b"will not be overwritten" in duplicate_evidence.stderr
    assert evidence_path.read_bytes() == preserved_evidence
    assert _inventory(root) == after_export


def test_saved_status_verifier_imports_without_optional_compute_or_qt() -> None:
    code = (
        "import sys; "
        "import diffeoforge.reference_preparation_reconciliation_verification; "
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
