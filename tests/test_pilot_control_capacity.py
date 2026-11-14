"""Bounded model-capacity journeys; no native optimizer or private geometry."""

import copy

import numpy as np
import pytest
from test_guided_pilot import approve, run_batch
from test_pilot_region_feedback import reject
from test_reference_calibration_study import _project

from diffeoforge import pilot_control_capacity as capacity
from diffeoforge import reference_attachment_comparison as methods
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_recommendation import recommend_reference_parameters


def origin(tmp_path, disparity):
    path = _project(tmp_path)
    config = load_config(path)
    inputs = validate_input_paths(config, path)
    recommendation = recommend_reference_parameters(
        (inputs.template, *inputs.subjects), alignment_basis="declared_gpa",
        surface_detail_intent="balanced", deformation_scale_intent="balanced",
        expected_shape_disparity=disparity)
    plan = build_reference_calibration_plan(recommendation, coordinate_unit="unitless",
                                          requested_pilot_subject_count=3)
    config["project"]["parameter_provenance"]["recommendation"] = dict(
        recommendation.provenance, calibration_plan=plan.provenance)
    config["project"]["parameter_provenance"]["attachment_selection"] = dict(
        version=methods.VERSION, mode="auto", state="pending", workflow=guided.ADAPTIVE_VERSION)
    study._write_yaml(path, config, overwrite=True)
    return study.create_reference_calibration_study(path, tmp_path / "capacity-pilot")


@pytest.mark.parametrize("disparity", ["high", "extreme"])
def test_new_high_disparity_method_screen_binds_actual_kernel_spaced_capacity(
    tmp_path, monkeypatch, disparity
):
    parent = origin(tmp_path, disparity)
    pins = {p: sha256_file(p) for p in parent.study_directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation started fitting"))
    child = guided.prepare(parent.study_directory)
    request = child.attachment_comparison["control_capacity"]
    controls = child.attachment_comparison["controls"]
    points = np.loadtxt(child.study_directory / controls["copy"])
    assert np.array_equal(points, capacity.grid(request))
    assert len(points) == request["count"] == controls["count"] <= capacity.MAX_CONTROLS
    assert controls["spacing"] == child.plan.effective_values["deformation_kernel_width"]
    assert child.attachment_comparison["iterations"] == 120
    assert len(child.candidates) == 2 and not child.visual_reviews
    for candidate in child.candidates:
        config = load_config(candidate.config_path)
        assert config["optimization"]["max_iterations"] == 120
        assert config["model"]["deformation"]["initial_control_point_spacing"] == controls[
            "spacing"]
        assert "initial_momenta" not in config["model"]["deformation"]
    assert all(sha256_file(p) == digest for p, digest in pins.items())
    assert study.load_reference_calibration_study(child.study_directory)


def test_fresh_movement_test_carries_its_chosen_grid_through_coverage_and_joint(
    tmp_path, monkeypatch
):
    child = reject(run_batch(guided.prepare(origin(tmp_path, "extreme").study_directory),
                             monkeypatch), "guided-varifold")
    config_before = load_config(child.candidates[1].config_path)
    changed = guided.next_action(child.study_directory, "adaptive_recover", "guided-varifold",
                                 goal="goal:local_motion")
    record = changed.attachment_comparison
    assert record["refinement"]["initialization"] == "fresh"
    assert record["controls"]["count"] > child.attachment_comparison["controls"]["count"]
    assert record["control_capacity"]["spacing"] == changed.plan.effective_values[
        "deformation_kernel_width"]
    actual = load_config(changed.candidates[0].config_path)
    assert actual["runtime"] == config_before["runtime"]
    assert actual["optimization"] == config_before["optimization"]
    for key in ("timepoints", "use_rk2"):
        assert actual["model"]["deformation"][key] == config_before["model"]["deformation"][key]
    assert not changed.visual_reviews and changed.candidates[0].attempts == 0
    chosen = record["controls"]["sha256"]
    following = guided.next_action(approve(run_batch(changed, monkeypatch)).study_directory,
                                   "adaptive_confirm", "guided-varifold")
    while guided.record(following)["phase"] != "joint":
        assert following.attachment_comparison["controls"]["sha256"] == chosen
        config = load_config(following.candidates[0].config_path)
        assert "initial_momenta" not in config["model"]["deformation"]
        following = guided.next_action(approve(run_batch(following, monkeypatch)).study_directory,
                                       "adaptive_confirm", "guided-varifold")
    assert following.attachment_comparison["controls"]["sha256"] == chosen
    assert not following.visual_reviews and following.candidates[0].attempts == 0


def test_capacity_limit_does_not_allocate_or_silently_coarsen_requested_model():
    requested = capacity.describe((0, 100, 0, 80, 0, 90), .01)
    assert not requested["available"] and requested["spacing"] == .01
    with pytest.raises(ValueError, match="resource limit"):
        capacity.grid(requested)
    good = capacity.describe((0, 1, 0, 0, 0, 2), .5)
    assert np.isfinite(capacity.grid(good)).all()
    tampered = copy.deepcopy(good)
    tampered["count"] += 1
    with pytest.raises(ValueError):
        capacity.grid(tampered)
    bounded = capacity.bounded_movement((0, 1, 0, 1, 0, 1), .01, .4)
    assert bounded["available"] and .01 < bounded["spacing"] < .4
    assert bounded["spacing"] == bounded["kernel_width"]
    assert len(capacity.grid(bounded)) == bounded["count"] <= capacity.MAX_CONTROLS


def test_moderate_new_screen_and_historical_grid_keep_their_existing_contract(tmp_path):
    parent = origin(tmp_path, "moderate")
    child = guided.prepare(parent.study_directory)
    assert "control_capacity" not in child.attachment_comparison
    pins = {p: sha256_file(p) for p in child.study_directory.rglob("*") if p.is_file()}
    assert study.load_reference_calibration_study(child.study_directory)
    assert all(sha256_file(p) == digest for p, digest in pins.items())
