from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reviewed_run import (
    DesktopReviewedRunError,
    build_reviewed_worker_request,
    check_reviewed_run_readiness,
)
from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest, sha256_file
from diffeoforge.private_runs import (
    MARKER_NAME,
    PrivateRunDiscovery,
    acquire_private_run_lease,
)


def _review(config_path: Path, *, engine: DesktopEngine = DesktopEngine.MODERN_CPU):
    return ProjectReviewResult(
        engine=engine,
        project_name="reviewed",
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        report_path=config_path.with_suffix(".html"),
        report_label="report",
        subject_count=2,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="test boundary",
    )


def test_reviewed_run_rejects_changed_configuration(tmp_path: Path) -> None:
    config = tmp_path / "modern-atlas.yaml"
    config.write_text("first\n", encoding="utf-8")
    review = _review(config)
    config.write_text("changed\n", encoding="utf-8")

    with pytest.raises(DesktopReviewedRunError, match="changed after parameter review"):
        build_reviewed_worker_request(review, request_id="desktop-test")


def test_reviewed_run_rejects_reference_engine(tmp_path: Path) -> None:
    config = tmp_path / "atlas.yaml"
    config.write_text("reference\n", encoding="utf-8")

    with pytest.raises(DesktopReviewedRunError, match="only for Modern CPU"):
        build_reviewed_worker_request(
            _review(config, engine=DesktopEngine.DEFORMETRICA_REFERENCE),
            request_id="desktop-test",
        )


def test_reviewed_run_returns_only_request_with_same_hash(monkeypatch, tmp_path: Path) -> None:
    config = (tmp_path / "modern-atlas.yaml").resolve()
    destination = (tmp_path / "result").resolve()
    config.write_text("reviewed bytes\n", encoding="utf-8")
    review = _review(config)

    def fake_build(source: Path, *, request_id: str) -> DesktopWorkerRequest:
        assert Path(source) == config
        return DesktopWorkerRequest(
            request_id=request_id,
            config_path=config,
            destination=destination,
            expected_config_sha256=review.config_sha256,
        )

    monkeypatch.setattr("diffeoforge.desktop.reviewed_run.build_worker_request", fake_build)

    request = build_reviewed_worker_request(review, request_id="desktop-test")

    assert request.request_id == "desktop-test"
    assert request.expected_config_sha256 == review.config_sha256


def test_reviewed_readiness_binds_clear_exact_destination(monkeypatch, tmp_path: Path) -> None:
    config = (tmp_path / "modern-atlas.yaml").resolve()
    destination = (tmp_path / "result with spaces").resolve()
    config.write_text("reviewed bytes\n", encoding="utf-8")
    review = _review(config)

    monkeypatch.setattr(
        "diffeoforge.desktop.reviewed_run.build_worker_request",
        lambda source, *, request_id: DesktopWorkerRequest(
            request_id=request_id,
            config_path=Path(source),
            destination=destination,
            expected_config_sha256=review.config_sha256,
        ),
    )

    readiness = check_reviewed_run_readiness(review, request_id="desktop-ready")

    assert readiness.request.destination == destination
    assert readiness.discovery.destination == destination
    assert readiness.discovery.status == "clear"
    assert readiness.ready_for_worker is True


def test_reviewed_readiness_reports_active_private_state_without_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    config = (tmp_path / "modern-atlas.yaml").resolve()
    destination = (tmp_path / "result").resolve()
    private = tmp_path / f".{destination.name}.tmp-{'a' * 32}"
    config.write_text("reviewed bytes\n", encoding="utf-8")
    private.mkdir()
    review = _review(config)
    monkeypatch.setattr(
        "diffeoforge.desktop.reviewed_run.build_worker_request",
        lambda source, *, request_id: DesktopWorkerRequest(
            request_id=request_id,
            config_path=Path(source),
            destination=destination,
            expected_config_sha256=review.config_sha256,
        ),
    )
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")
    marker_before = (private / MARKER_NAME).read_bytes()
    try:
        readiness = check_reviewed_run_readiness(review, request_id="desktop-blocked")
    finally:
        lease.close()

    assert readiness.ready_for_worker is False
    assert [candidate.status for candidate in readiness.discovery.candidates] == ["active"]
    assert (private / MARKER_NAME).read_bytes() == marker_before


def test_reviewed_readiness_rejects_mismatched_request_and_discovery_targets(
    tmp_path: Path,
) -> None:
    from diffeoforge.desktop.reviewed_run import DesktopReviewedRunReadiness

    request = DesktopWorkerRequest(
        request_id="desktop-mismatch",
        config_path=(tmp_path / "modern.yaml").resolve(),
        destination=(tmp_path / "requested").resolve(),
        expected_config_sha256="a" * 64,
    )

    with pytest.raises(ValueError, match="different paths"):
        DesktopReviewedRunReadiness(
            request=request,
            discovery=PrivateRunDiscovery((tmp_path / "other").resolve(), False, ()),
        )
