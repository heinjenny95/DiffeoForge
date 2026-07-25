import hashlib
from pathlib import Path

import pytest

from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_calibration_report import (
    export_reference_calibration_plan,
    render_reference_calibration_plan_html,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _plan():
    recommendation = recommend_reference_parameters(
        (
            MESH_DIRECTORY / "template.vtk",
            *sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
        ),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )
    return build_reference_calibration_plan(
        recommendation,
        coordinate_unit="millimeter",
        requested_pilot_subject_count=4,
        smallest_relevant_feature=1.2,
    )


def test_calibration_html_is_self_contained_and_explicitly_non_approving() -> None:
    plan = _plan()

    html = render_reference_calibration_plan_html(plan)

    assert html.startswith("<!doctype html>")
    assert plan.fingerprint in html
    assert plan.recommendation_fingerprint in html
    assert "PLANNED — NOT EXECUTED" in html
    assert "Deterministic pilot cohort" in html
    assert "Surface-matching detail" in html
    assert "Data-fit versus regularity weight" in html
    assert "Full-cohort confirmation required" in html
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_calibration_export_is_exact_and_non_overwriting(tmp_path: Path) -> None:
    plan = _plan()

    result = export_reference_calibration_plan(plan, tmp_path / "calibration")

    assert result.json_path.is_file()
    assert result.html_path.is_file()
    assert result.sha256_path.is_file()
    assert result.json_sha256 == hashlib.sha256(result.json_path.read_bytes()).hexdigest()
    assert result.sha256_path.read_text(encoding="ascii") == (
        f"{result.json_sha256}  {result.json_path.name}\n"
    )
    original = result.json_path.read_bytes()
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        export_reference_calibration_plan(plan, tmp_path / "calibration")
    assert result.json_path.read_bytes() == original


def test_explicit_export_overwrite_replaces_the_complete_bundle(tmp_path: Path) -> None:
    plan = _plan()
    destination = tmp_path / "calibration"
    first = export_reference_calibration_plan(plan, destination)
    first.html_path.write_text("stale", encoding="utf-8")

    second = export_reference_calibration_plan(plan, destination, overwrite=True)

    assert second.json_sha256 == first.json_sha256
    assert second.html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert not list(destination.glob(".*.tmp"))
