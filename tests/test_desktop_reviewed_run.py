from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reviewed_run import (
    DesktopReviewedRunError,
    build_reviewed_worker_request,
)
from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest, sha256_file


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
