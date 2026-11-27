"""Manual inclusion is mandatory, provenance-bound, and not an outlier label."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_calibration import (
    PilotSubjectDeclaration,
    build_reference_calibration_plan,
    reference_calibration_plan_from_provenance,
)
from diffeoforge.reference_calibration_report import render_reference_calibration_plan_html
from diffeoforge.reference_recommendation import recommend_reference_parameters


@pytest.fixture
def recommendation():
    meshes = Path(__file__).parents[1] / "examples" / "synthetic" / "meshes"
    return recommend_reference_parameters(
        (meshes / "template.vtk", *sorted(meshes.glob("subject-*.vtk"))),
        alignment_basis="declared_gpa",
        surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )


def test_manual_subject_is_retained_and_distinct_from_biological_extreme(recommendation):
    original = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=2
    )
    original_names = {item.filename for item in original.selected_pilot_subjects}
    required = next(
        item.filename for item in recommendation.observations[1:]
        if item.filename not in original_names
    )
    plan = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=2,
        required_subject_filenames=(required.upper(),),
    )
    assert plan.pilot_subject_count == 2
    assert plan.required_subject_filenames == (required,)
    assert plan.selected_pilot_subjects[0].filename == required
    assert plan.selected_pilot_subjects[0].selection_role == "researcher-selected mandatory subject"
    assert not plan.pilot_subject_declarations
    assert original.fingerprint != plan.fingerprint
    assert reference_calibration_plan_from_provenance(plan.provenance) == plan
    assert "Manually included subjects" in plan.summary_text()
    assert "Manually included subjects" in render_reference_calibration_plan_html(plan)
    assert "required_subject_filenames" not in original.provenance


def test_manual_and_csv_coverage_combine_without_duplicate_slots(recommendation):
    names = [item.filename for item in recommendation.observations[1:5]]
    declarations = (
        PilotSubjectDeclaration(names[0], "first", True),
        PilotSubjectDeclaration(names[1], "second", False),
        PilotSubjectDeclaration(names[2], "second", False),
    )
    plan = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=3,
        required_subject_filenames=(names[0], names[2]),
        pilot_subject_declarations=declarations,
    )
    assert len({item.filename for item in plan.selected_pilot_subjects}) == 3
    assert {names[0], names[2]}.issubset(item.filename for item in plan.selected_pilot_subjects)
    assert reference_calibration_plan_from_provenance(plan.provenance) == plan
    reordered = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=3,
        required_subject_filenames=(names[2], names[0]),
        pilot_subject_declarations=declarations,
    )
    assert reordered.fingerprint == plan.fingerprint


@pytest.mark.parametrize("invalid", [("missing.stl",), ("template.vtk",), "subject-01.vtk", (123,)])
def test_unknown_template_or_malformed_manual_selection_is_rejected(recommendation, invalid):
    with pytest.raises((ConfigurationError, TypeError)):
        build_reference_calibration_plan(
            recommendation, coordinate_unit="unitless", required_subject_filenames=invalid
        )


def test_manual_subjects_cannot_be_dropped_for_small_pilot(recommendation):
    names = tuple(item.filename for item in recommendation.observations[1:4])
    with pytest.raises(ConfigurationError, match="need 3, requested 2"):
        build_reference_calibration_plan(
            recommendation, coordinate_unit="unitless", requested_pilot_subject_count=2,
            required_subject_filenames=names,
        )
    with pytest.raises(ConfigurationError, match="Duplicate"):
        build_reference_calibration_plan(
            recommendation, coordinate_unit="unitless",
            required_subject_filenames=(names[0], names[0].upper()),
        )


@pytest.mark.parametrize("rehash", [False, True])
def test_stored_plan_cannot_claim_missing_manual_subject(recommendation, rehash):
    plan = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=2
    )
    manifest = deepcopy(plan.provenance)
    manifest["required_subject_filenames"] = ["not-selected.vtk"]
    if rehash:
        payload = {k: v for k, v in manifest.items() if k not in {
            "fingerprint", "status", "pilot_subject_count"
        }}
        manifest["fingerprint"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False).encode("utf-8")
        ).hexdigest()
    with pytest.raises(ConfigurationError):
        reference_calibration_plan_from_provenance(manifest)
