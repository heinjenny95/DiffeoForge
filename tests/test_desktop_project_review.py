from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.desktop.project_review import review_project
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.mesh import read_vtk_polydata

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _write_landmarks(path: Path) -> Path:
    meshes = [MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk"))]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in meshes:
            points = read_vtk_polydata(mesh).vertices
            for label, index in zip(("a", "b", "c"), (0, 40, 80), strict=True):
                writer.writerow((mesh.name, label, *points[index]))
    return path


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
    assert review.config_sha256 == sha256_file(setup.config_path)
    assert review.subject_count == 5
    assert review.report_path == setup.report_path
    assert review.report_path.is_file()
    assert values["Coordinate unit"] == "millimeter"
    assert values["Attachment"].startswith("current · width ")
    assert "line search 10" in values["Optimizer safeguards"]
    assert "Sobolev yes" in values["Regularization and updates"]
    assert values["Output cadence"].startswith("save every 100")
    assert evidence["Attachment / template scale"] == "10.000%"
    assert evidence["Deformation / template scale"] == "15.000%"
    assert evidence["Compute cost"] == "not modeled"
    assert any("exploratory" in warning for warning in review.warnings)


def test_reference_review_verifies_and_exposes_procrustes_evidence(tmp_path: Path) -> None:
    setup = create_project(
        ProjectSetupRequest(
            mesh_directory=MESH_DIRECTORY,
            project_directory=tmp_path / "aligned reference review",
            units="unitless",
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            landmarks_file=_write_landmarks(tmp_path / "landmarks.csv"),
            procrustes_scale_to_unit_centroid_size=False,
            procrustes_allow_reflection=True,
            procrustes_tolerance=1e-8,
            procrustes_max_iterations=250,
        )
    )

    review = review_project(setup.config_path, setup.engine)

    values = {item.label: item.value for item in review.parameters}
    assert values["Landmark alignment"] == (
        "generalized Procrustes · 3 landmarks · 6 meshes"
    )
    assert "unit centroid size no" in values["Procrustes settings"]
    assert "reflections yes" in values["Procrustes settings"]
    assert "max. 250 iterations" in values["Procrustes settings"]

    evidence_path = setup.preprocessing_report_path
    assert evidence_path is not None
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["meshes"][0]["aligned_sha256"] = "0" * 64
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(RuntimeError, match="aligned mesh no longer matches"):
        review_project(setup.config_path, setup.engine)


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
    assert review.config_sha256 == sha256_file(setup.config_path)
    assert review.subject_count == 5
    assert review.report_path.name == "workload.html"
    assert review.report_path.is_file()
    report_json = review.report_path.with_name("workload.json")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert values["Execution"].startswith("CPU · float64")
    assert values["Pairwise evaluation"].startswith("dense")
    assert values["Optimization blocks"].endswith("max. 3 cycles")
    assert values["Convergence rule"] == "every block gradient ≤ 1e-08"
    assert evidence["Dataset"] == "5 subjects + 1 template"
    assert evidence["Objective/gradient upper bound"] == str(
        report["optimizer_bound"]["objective_gradient_evaluation_upper_bound"]
    )
    assert evidence["Peak RAM and computation time"] == (
        "unknown · pilot measurement required"
    )
    assert "not a peak-RAM predictor" in review.scientific_boundary

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
