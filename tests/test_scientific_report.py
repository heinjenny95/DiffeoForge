from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_workflow import (  # noqa: E402
    load_modern_workflow_config,
    run_modern_workflow,
)
from diffeoforge.scientific_report import (  # noqa: E402
    SCIENTIFIC_CLAIMS_CSV,
    SCIENTIFIC_METHODS_TEXT,
    SCIENTIFIC_REPORT_HTML,
    SCIENTIFIC_REPORT_JSON,
    SCIENTIFIC_SUBJECTS_CSV,
    ScientificReportError,
    collect_scientific_atlas_report,
    verify_scientific_atlas_report,
    write_scientific_atlas_report,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-08-30T12:00:00+00:00"


def _run_result(tmp_path: Path) -> Path:
    config = copy.deepcopy(load_modern_workflow_config(EXAMPLE_CONFIG))
    meshes = ROOT / "examples" / "synthetic" / "meshes"
    config["input"]["directory"] = str(meshes)
    config["input"]["template"] = str(meshes / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = str(tmp_path / "unused")
    source = tmp_path / "modern.yaml"
    source.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return run_modern_workflow(
        source,
        destination=tmp_path / "modern-result",
        created_at=FIXED_TIME,
    )


def test_scientific_report_is_bounded_complete_and_source_verified(tmp_path: Path) -> None:
    run = _run_result(tmp_path)

    report = collect_scientific_atlas_report(run, created_at=FIXED_TIME)

    assert report.engine_label == "DiffeoForge Modern Engine"
    assert len(report.subjects) == 5
    assert [item.rank for item in report.subjects] == list(range(1, 6))
    assert all(item.researcher_decision == "unreviewed" for item in report.subjects)
    statuses = {claim.claim_id: claim.status for claim in report.claims}
    assert statuses["execution_integrity"] == "supported"
    assert statuses["optimizer_convergence"] == "not_supported"
    assert statuses["parameter_sensitivity"] == "not_assessed"
    assert statuses["template_robustness"] == "not_assessed"
    assert statuses["biological_validity"] == "not_assessed"
    assert "no landmark atlas attachment term was used" in report.methods_text

    artifact = write_scientific_atlas_report(report, tmp_path / "scientific")
    assert verify_scientific_atlas_report(artifact.directory).directory == artifact.directory
    assert {
        SCIENTIFIC_REPORT_JSON,
        SCIENTIFIC_REPORT_HTML,
        SCIENTIFIC_METHODS_TEXT,
        SCIENTIFIC_SUBJECTS_CSV,
        SCIENTIFIC_CLAIMS_CSV,
    } <= {path.name for path in artifact.directory.iterdir()}
    payload = json.loads((artifact.directory / SCIENTIFIC_REPORT_JSON).read_text("utf-8"))
    assert payload["registration_qc"]["subject_count"] == 5
    assert payload["claim_matrix"][-1]["claim_id"] == "biological_validity"
    rendered = (artifact.directory / SCIENTIFIC_REPORT_HTML).read_text("utf-8")
    assert "data:image/svg+xml;base64," in rendered
    assert "GPA landmarks and downstream helix measurements" in rendered


def test_scientific_report_refuses_overwrite_and_detects_tampering(tmp_path: Path) -> None:
    report = collect_scientific_atlas_report(_run_result(tmp_path), created_at=FIXED_TIME)
    destination = tmp_path / "scientific"
    artifact = write_scientific_atlas_report(report, destination)

    with pytest.raises(ScientificReportError, match="already exists"):
        write_scientific_atlas_report(report, destination)

    report_json = artifact.directory / SCIENTIFIC_REPORT_JSON
    report_json.write_bytes(report_json.read_bytes() + b"\n")
    with pytest.raises(ScientificReportError, match="artifact changed"):
        verify_scientific_atlas_report(artifact.directory)


def test_scientific_report_verify_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = collect_scientific_atlas_report(_run_result(tmp_path), created_at=FIXED_TIME)
    artifact = write_scientific_atlas_report(report, tmp_path / "scientific")

    assert main(["scientific-report-verify", str(artifact.directory)]) == 0
    assert "Scientific report verified" in capsys.readouterr().out
