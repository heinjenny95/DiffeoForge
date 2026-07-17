from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import review_project
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def test_reference_review_uses_effective_preflight_parameters(tmp_path: Path) -> None:
    setup = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "reference review",
            units="millimeter",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        )
    )

    review = review_project(setup.config_path, setup.engine)

    values = {item.label: item.value for item in review.parameters}
    evidence = {item.label: item.value for item in review.workload}
    assert review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
    assert review.subject_count == 5
    assert review.report_path == setup.report_path
    assert review.report_path.is_file()
    assert values["Koordinateneinheit"] == "millimeter"
    assert values["Attachment"].startswith("current · Breite ")
    assert evidence["Attachment / Template-Skala"] == "10.000%"
    assert evidence["Deformation / Template-Skala"] == "15.000%"
    assert evidence["Rechenaufwand"] == "nicht modelliert"
    assert any("explorativ" in warning for warning in review.warnings)


def test_modern_review_publishes_existing_exact_workload_contract(tmp_path: Path) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")
    setup = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "modern review",
            units="micrometer",
            engine=DesktopEngine.MODERN_CPU,
        )
    )

    review = review_project(setup.config_path, setup.engine)

    values = {item.label: item.value for item in review.parameters}
    evidence = {item.label: item.value for item in review.workload}
    assert review.engine is DesktopEngine.MODERN_CPU
    assert review.subject_count == 5
    assert review.report_path.name == "workload.html"
    assert review.report_path.is_file()
    report_json = review.report_path.with_name("workload.json")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert values["Ausführung"].startswith("CPU · float64")
    assert values["Paarweise Auswertung"].startswith("dense")
    assert evidence["Datensatz"] == "5 Probanden + 1 Template"
    assert evidence["Objective/Gradient-Obergrenze"] == str(
        report["optimizer_bound"]["objective_gradient_evaluation_upper_bound"]
    )
    assert evidence["Peak-RAM und Laufzeit"] == "unbekannt · Pilotmessung erforderlich"
    assert "keine Peak-RAM-Prognose" in review.scientific_boundary

    refreshed = review_project(setup.config_path, setup.engine)
    assert refreshed.report_path == review.report_path
    assert (
        json.loads(report_json.read_text(encoding="utf-8"))["source_config"]
        == report["source_config"]
    )


def test_modern_review_refreshes_only_recognized_generated_report(tmp_path: Path) -> None:
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("torch") is None:
        pytest.skip("modern-engine dependencies are not installed")
    setup = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "owned report",
            units="unitless",
            engine=DesktopEngine.MODERN_CPU,
        )
    )
    report_directory = setup.config_path.with_suffix(".workload")
    report_directory.mkdir()
    owned = report_directory / "notes.txt"
    owned.write_text("researcher owned\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Refusing to replace"):
        review_project(setup.config_path, setup.engine)

    assert owned.read_text(encoding="utf-8") == "researcher owned\n"
