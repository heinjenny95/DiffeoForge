from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_preparation_status_verification import (
    DesktopSavedReferencePreparationStatusVerificationError,
    review_saved_reference_preparation_status,
)
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
    write_reference_preparation_reconciliation,
)

ROOT = Path(__file__).parents[1]


def _saved_report(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "Desktop Saved Status Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    config = root / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    plan = plan_reference_preparation(config, run_id="desktop-saved-status-001")
    request = create_reference_preparation_approval(
        config,
        run_id="desktop-saved-status-001",
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    approval = write_reference_preparation_approval(
        request,
        root / "approval.json",
    )
    approval_hash = hashlib.sha256(approval.read_bytes()).hexdigest()
    report = reconcile_reference_preparation(
        approval,
        current_config_path=config,
        expected_request_sha256=approval_hash,
    )
    report_path = write_reference_preparation_reconciliation(
        report,
        root / "status-Käfer.json",
    )
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    return config, approval, report_path, report_hash


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_desktop_saved_status_verification_requires_no_current_project_state(
    tmp_path: Path,
) -> None:
    config, approval, report_path, report_hash = _saved_report(tmp_path)
    config.unlink()
    approval.unlink()
    before = _inventory(report_path.parent)

    result = review_saved_reference_preparation_status(
        report_path,
        report_hash.upper(),
    )

    assert result.report_path == report_path.resolve()
    assert result.report_byte_count == report_path.stat().st_size
    assert result.report_sha256 == report_hash
    assert result.expected_report_sha256 == report_hash
    assert result.report_schema_version == "0.1"
    assert result.report_status == "clear_to_prepare"
    assert result.action_required is False
    assert result.mutation_performed is False
    assert result.state_stable_across_observations is True
    assert result.matches_deterministic_serialization is True
    assert result.run_id == "desktop-saved-status-001"
    assert result.destination_status == "absent"
    assert result.manifest_sha256 is None
    assert result.engine_execution_started is None
    assert result.private_stage_count == 0
    assert result.verification_status == (
        "verified_saved_reference_preparation_reconciliation"
    )
    assert "reads no current config" in result.scientific_boundary
    assert _inventory(report_path.parent) == before


def test_desktop_saved_status_verification_fails_closed_and_preserves_files(
    tmp_path: Path,
) -> None:
    _config, _approval, report_path, _report_hash = _saved_report(tmp_path)
    before = _inventory(report_path.parent)

    with pytest.raises(
        DesktopSavedReferencePreparationStatusVerificationError,
        match="independently recorded SHA-256",
    ):
        review_saved_reference_preparation_status(report_path, "0" * 64)

    assert _inventory(report_path.parent) == before


def test_desktop_saved_status_view_rejects_inconsistent_fields(tmp_path: Path) -> None:
    _config, _approval, report_path, report_hash = _saved_report(tmp_path)
    result = review_saved_reference_preparation_status(report_path, report_hash)

    with pytest.raises(ValueError, match="Expected and observed"):
        replace(result, expected_report_sha256="0" * 64)
    with pytest.raises(ValueError, match="action flag"):
        replace(result, action_required=True)
    with pytest.raises(ValueError, match="never report mutation"):
        replace(result, mutation_performed=True)
    with pytest.raises(ValueError, match="checks are incomplete"):
        replace(result, checks=result.checks[:-1])


def test_desktop_saved_status_service_imports_without_qt_or_compute() -> None:
    code = (
        "import sys; "
        "import diffeoforge.desktop.reference_preparation_status_verification; "
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
