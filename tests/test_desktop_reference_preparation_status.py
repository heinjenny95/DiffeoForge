from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reference_preparation_status import (
    DesktopReferencePreparationStatusError,
    review_reference_preparation_status,
)
from diffeoforge.reference_approved_preparation import prepare_approved_reference_run
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Desktop Status KÃ¤fer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _review(
    config: Path,
    *,
    engine: DesktopEngine = DesktopEngine.DEFORMETRICA_REFERENCE,
) -> ProjectReviewResult:
    return ProjectReviewResult(
        engine=engine,
        project_name="reference-status",
        config_path=config.resolve(),
        config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        report_path=config.with_suffix(".html"),
        report_label="Preflight-Report",
        subject_count=5,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="test boundary",
    )


def _approval(root: Path) -> tuple[Path, str, dict]:
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id="desktop-status-001")
    request = create_reference_preparation_approval(
        config,
        run_id="desktop-status-001",
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    path = write_reference_preparation_approval(
        request,
        root / "review" / "approval.json",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), request


def _surface(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    paths = tuple(sorted(path.relative_to(root).as_posix() for path in root.rglob("*")))
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    return paths, files


def test_desktop_status_maps_clear_report_without_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval, approval_hash, request = _approval(root)
    before = _surface(root)

    status = review_reference_preparation_status(
        _review(root / "atlas.yaml"),
        approval,
        approval_hash,
    )

    assert status.status == "clear_to_prepare"
    assert status.action_required is False
    assert status.destination_status == "absent"
    assert status.private_stages == ()
    assert status.mutation_performed is False
    assert status.state_stable_across_observations is True
    assert status.plan_fingerprint == request["approval"]["approved_plan_fingerprint"]
    assert not Path(request["plan"]["run"]["output_root"]).exists()
    assert _surface(root) == before


def test_desktop_status_maps_verified_published_run(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval, approval_hash, _request = _approval(root)
    prepared = prepare_approved_reference_run(
        approval,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=approval_hash,
    )
    before = _surface(root)

    status = review_reference_preparation_status(
        _review(root / "atlas.yaml"),
        approval,
        approval_hash,
    )

    assert status.status == "published_prepared_not_executed_verified"
    assert status.destination_status == "verified_prepared_not_executed"
    assert status.manifest_sha256 == prepared["prepared_run"]["manifest_sha256"]
    assert status.engine_execution_started is False
    assert status.action_required is False
    assert _surface(root) == before


def test_desktop_status_maps_verified_private_stage_as_attention(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    approval, approval_hash, request = _approval(root)
    prepare_approved_reference_run(
        approval,
        current_config_path=root / "atlas.yaml",
        expected_request_sha256=approval_hash,
    )
    destination = Path(request["plan"]["run"]["destination"])
    private = destination.parent / (
        ".diffeoforge-preparing-desktop-status-001-"
        "dddddddddddddddddddddddddddddddd"
    )
    destination.rename(private)
    before = _surface(root)

    status = review_reference_preparation_status(
        _review(root / "atlas.yaml"),
        approval,
        approval_hash,
    )

    assert status.status == "attention_required"
    assert status.action_required is True
    assert status.destination_status == "absent"
    assert len(status.private_stages) == 1
    assert status.private_stages[0].path == private
    assert status.private_stages[0].status == "verified_complete_unpublished"
    assert status.private_stages[0].engine_execution_started is False
    assert _surface(root) == before


def test_desktop_status_rejects_config_changed_after_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    approval, approval_hash, _request = _approval(root)
    review = _review(root / "atlas.yaml")
    review.config_path.write_text(
        review.config_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.reference_preparation_status.reconcile_reference_preparation",
        lambda *_args, **_kwargs: pytest.fail("reconciliation must not run"),
    )

    with pytest.raises(
        DesktopReferencePreparationStatusError,
        match="changed after parameter review",
    ):
        review_reference_preparation_status(review, approval, approval_hash)


def test_desktop_status_rejects_mutating_core_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    approval, approval_hash, _request = _approval(root)
    monkeypatch.setattr(
        "diffeoforge.desktop.reference_preparation_status.reconcile_reference_preparation",
        lambda *_args, **_kwargs: {"mutation_performed": True},
    )

    with pytest.raises(
        DesktopReferencePreparationStatusError,
        match="read-only contract",
    ):
        review_reference_preparation_status(
            _review(root / "atlas.yaml"),
            approval,
            approval_hash,
        )


def test_desktop_status_rejects_modern_review(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval, approval_hash, _request = _approval(root)

    with pytest.raises(
        DesktopReferencePreparationStatusError,
        match="Deformetrica reference review",
    ):
        review_reference_preparation_status(
            _review(root / "atlas.yaml", engine=DesktopEngine.MODERN_CPU),
            approval,
            approval_hash,
        )
