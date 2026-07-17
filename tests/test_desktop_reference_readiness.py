from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reference_readiness import (
    DesktopReferenceReadinessError,
    check_reference_environment,
)
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.diagnostics import DoctorCheck, DoctorReport

ROOT = Path(__file__).resolve().parents[1]


def _review(path: Path, *, engine: DesktopEngine = DesktopEngine.DEFORMETRICA_REFERENCE):
    return ProjectReviewResult(
        engine=engine,
        project_name="reference",
        config_path=path.resolve(),
        config_sha256=sha256_file(path),
        report_path=path.with_suffix(".html"),
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="test boundary",
    )


def _doctor(workspace: Path, engine: str, image: str) -> DoctorReport:
    return DoctorReport(
        status="ready",
        workspace=str(workspace.resolve()),
        engine=engine,
        image=image,
        checks=(DoctorCheck("reference_image", "Reference image", "pass", "sha256:test"),),
    )


def test_reference_readiness_uses_exact_reviewed_container_settings(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "atlas.yaml"
    source = ROOT / "examples" / "minimal-atlas-container.yaml"
    text = source.read_text(encoding="utf-8").replace(
        "diffeoforge-deformetrica:4.3.0-cpu", "local-reference:test"
    )
    config.write_text(text, encoding="utf-8")
    calls = []

    def fake_doctor(workspace, *, engine, image):
        calls.append((Path(workspace), engine, image))
        return _doctor(Path(workspace), engine, image)

    monkeypatch.setattr(
        "diffeoforge.desktop.reference_readiness.run_doctor", fake_doctor
    )

    readiness = check_reference_environment(_review(config))

    assert calls == [(tmp_path.resolve(), "docker", "local-reference:test")]
    assert readiness.config_path == config.resolve()
    assert readiness.config_sha256 == sha256_file(config)
    assert readiness.ready is True
    assert readiness.report.checks[0].summary == "sha256:test"


def test_reference_readiness_rejects_configuration_changed_before_probe(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    review = _review(config)
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    called = False

    def fake_doctor(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("doctor must not run")

    monkeypatch.setattr(
        "diffeoforge.desktop.reference_readiness.run_doctor", fake_doctor
    )

    with pytest.raises(DesktopReferenceReadinessError, match="changed after parameter review"):
        check_reference_environment(review)

    assert called is False


def test_reference_readiness_discards_probe_if_config_changes_during_doctor(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    review = _review(config)

    def changing_doctor(workspace, *, engine, image):
        config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return _doctor(Path(workspace), engine, image)

    monkeypatch.setattr(
        "diffeoforge.desktop.reference_readiness.run_doctor", changing_doctor
    )

    with pytest.raises(DesktopReferenceReadinessError, match="changed while"):
        check_reference_environment(review)


def test_reference_readiness_rejects_unimplemented_native_route(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas.yaml", config)
    monkeypatch.setattr(
        "diffeoforge.desktop.reference_readiness.run_doctor",
        lambda *_args, **_kwargs: pytest.fail("doctor must not run"),
    )

    with pytest.raises(DesktopReferenceReadinessError, match="container launcher only"):
        check_reference_environment(_review(config))


def test_reference_readiness_rejects_modern_review(tmp_path: Path) -> None:
    config = tmp_path / "atlas.yaml"
    config.write_text("not parsed\n", encoding="utf-8")

    with pytest.raises(DesktopReferenceReadinessError, match="reference review"):
        check_reference_environment(_review(config, engine=DesktopEngine.MODERN_CPU))
