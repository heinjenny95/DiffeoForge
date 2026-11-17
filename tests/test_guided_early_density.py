"""Early paired density trials. The fixtures never execute a native optimizer."""

import math
from copy import deepcopy
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from guided_field_fixture import field_fixture
from test_guided_pilot import _CompletedController, approve, run_batch
from test_interactive_pilot import geometry_receipt
from test_pilot_control_capacity import origin
from test_pilot_region_feedback import reject

from diffeoforge import guided_early_density, guided_feedback, guided_strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_density import controls_for
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_sequential_fit import resume_directory
from diffeoforge.runs import prepare_run, verify_prepared_run

METHOD = "guided-varifold"
REFERENCE = "density-reference"


def first_trial(tmp_path, monkeypatch, disparity="extreme"):
    source = origin(tmp_path, disparity)
    snapshot = run_batch(guided.prepare(source.study_directory), monkeypatch)
    return source, snapshot


def density_preview(snapshot):
    return guided_early_density.preview(snapshot, METHOD, guided_strategy.state(snapshot))


def before_outcome(snapshot, identifier):
    return next(candidate for candidate in snapshot.candidates
                if candidate.candidate_id == identifier)


def _marked_rejection(snapshot, monkeypatch):
    rejected = reject(snapshot, METHOD, marked=True)
    geometry_receipt(rejected, METHOD, monkeypatch)
    return rejected


@pytest.mark.parametrize("disparity", ["high", "extreme"])
def test_first_marked_rejection_offers_matched_density_trials(tmp_path, monkeypatch, disparity):
    source, snapshot = first_trial(tmp_path, monkeypatch, disparity)
    assert density_preview(snapshot) is None
    selected = _marked_rejection(snapshot, monkeypatch)
    baseline_count = selected.attachment_comparison["controls"]["count"]
    values = selected.plan.effective_values
    assert values["initial_control_point_spacing"] == values["deformation_kernel_width"]
    suggestion = density_preview(selected)
    retained = guided_feedback.reference(selected, METHOD)
    assert suggestion["available"] and suggestion["reference"] == retained
    assert suggestion["initial_control_count"] == baseline_count
    assert suggestion["denser_control_count"] == math.ceil(baseline_count * 1.5)
    source_pins = {p: sha256_file(p) for p in source.study_directory.rglob("*") if p.is_file()}
    old_pins = {p: sha256_file(p) for p in selected.study_directory.rglob("*")
                if p.is_file() and p.name != study.STUDY_EVENTS}

    with monkeypatch.context() as guard:
        guard.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                      lambda *_a, **_k: pytest.fail("Preparation started a fit"))
        pair = guided.next_action(selected.study_directory, "adaptive_density_comparison", METHOD)

    record = pair.attachment_comparison
    marker = record["early_density_comparison"]
    assert marker["version"] == "guided-early-density-v1"
    assert marker["reference_candidate_id"] == REFERENCE
    assert marker["denser_candidate_id"] == METHOD
    assert marker["initial_control_count"] == baseline_count
    assert record["refinement"]["reference"] == retained
    assert record["iterations"] == 40
    assert record["methods"] == {REFERENCE: "varifold", METHOD: "varifold"}
    assert pair.plan.pilot_subject_count == 1
    target = pair.plan.selected_pilot_subjects[0].filename
    assert guided.record(pair)["feedback"]["regions"] == selected.problem_regions[METHOD][target]
    assert not pair.visual_reviews and not pair.selected_candidate_ids
    assert all(c.status == "pending" and c.attempts == 0 for c in pair.candidates)

    baseline_field = field_fixture(before_outcome(selected, METHOD).run_directory)
    settings = []
    native = []
    arms = [(REFERENCE, baseline_count), (METHOD, suggestion["denser_control_count"])]
    for identifier, count in arms:
        candidate = before_outcome(pair, identifier)
        config = load_config(candidate.config_path)
        deformation = config["model"]["deformation"]
        controls = np.loadtxt(deformation["initial_control_points"], ndmin=2)
        momenta = read_deformetrica_momenta(deformation["initial_momenta"], allow_singleton=True)
        assert controls_for(record, identifier)["count"] == len(controls) == count
        np.testing.assert_array_equal(controls[:baseline_count], baseline_field.control_points)
        np.testing.assert_array_equal(momenta[:, :baseline_count], baseline_field.momenta)
        assert momenta.shape == (1, count, 3) and not momenta[:, baseline_count:].any()
        assert deformation["initial_momenta_subjects"] == [target]
        assert config["optimization"]["max_iterations"] == 40
        scientific = deepcopy({k: config[k] for k in ("model", "optimization", "runtime")})
        for key in ("initial_control_points", "initial_momenta", "initial_control_point_spacing"):
            del scientific["model"]["deformation"][key]
        settings.append(scientific)
        run = prepare_run(candidate.config_path, output_directory=tmp_path / "prepared",
                          run_id=identifier)
        manifest = verify_prepared_run(run)
        model = ET.parse(run / "engine/model.xml")
        native.append((
            manifest["inputs"],
            model.findtext("deformation-parameters/number-of-timepoints"),
            (run / "engine/optimization_parameters.xml").read_bytes(),
        ))

    assert settings[0] == settings[1]
    def input_identity(items):
        return [(r["role"], r["geometry"]["sha256"]) for r in items]

    assert input_identity(native[0][0]) == input_identity(native[1][0])
    assert native[0][1:] == native[1][1:]
    assert all(sha256_file(p) == digest for p, digest in (source_pins | old_pins).items())
    reopened = study.load_reference_calibration_study(resume_directory(selected.study_directory))
    assert reopened.study_directory == pair.study_directory
    assert all(c.attempts == 0 for c in reopened.candidates)
    original = study.load_reference_calibration_study(selected.study_directory)
    assert original.visual_reviews == selected.visual_reviews
    assert original.problem_regions == selected.problem_regions
    with pytest.raises(ValueError, match="newer"):
        guided.next_action(selected.study_directory, "adaptive_density_comparison", METHOD)


@pytest.mark.parametrize("chosen", [REFERENCE, METHOD])
def test_density_arm_requires_explicit_approval_and_retains_its_own_basis(
    tmp_path, monkeypatch, chosen
):
    _, snapshot = first_trial(tmp_path, monkeypatch)
    snapshot = _marked_rejection(snapshot, monkeypatch)
    pair = guided.next_action(snapshot.study_directory, "adaptive_density_comparison", METHOD)
    pair = run_batch(pair, monkeypatch)
    assert all(c.attempts == 1 and c.status == "completed" for c in pair.candidates)
    assert not pair.visual_reviews and not pair.selected_candidate_ids
    assert density_preview(pair) is None
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(pair.study_directory, "adaptive_confirm", chosen)
    pair = approve(pair, chosen)
    next_form = guided.next_action(pair.study_directory, "adaptive_confirm", chosen)
    control_hash = controls_for(pair.attachment_comparison, chosen)["sha256"]
    while guided.record(next_form)["phase"] != "joint":
        assert next_form.attachment_comparison["controls"]["sha256"] == control_hash
        assert all(c.attempts == 0 for c in next_form.candidates)
        next_form = approve(run_batch(next_form, monkeypatch))
        next_form = guided.next_action(next_form.study_directory, "adaptive_confirm", METHOD)
    assert next_form.attachment_comparison["controls"]["sha256"] == control_hash
    assert all(c.attempts == 0 for c in next_form.candidates)
    reopened = study.load_reference_calibration_study(pair.study_directory)
    assert reopened.visual_reviews == {chosen: True}
    assert study.load_reference_calibration_study(snapshot.study_directory).visual_reviews == {
        METHOD: False}


def test_restart_after_first_completed_arm_only_runs_the_missing_arm(tmp_path, monkeypatch):
    _, snapshot = first_trial(tmp_path, monkeypatch)
    snapshot = _marked_rejection(snapshot, monkeypatch)
    pair = guided.next_action(snapshot.study_directory, "adaptive_density_comparison", METHOD)
    runner = study.ReferenceCalibrationStudyRunner(pair.study_directory,
                                                    controller_factory=_CompletedController)
    partial = runner.run_current_stage(candidate_ids={REFERENCE})
    assert before_outcome(partial, REFERENCE).status == "completed"
    assert before_outcome(partial, METHOD).attempts == 0
    reopened = study.load_reference_calibration_study(pair.study_directory)
    completed = run_batch(reopened, monkeypatch)
    assert all(c.attempts == 1 and c.status == "completed" for c in completed.candidates)
    assert not completed.visual_reviews


def test_density_offer_stays_accessible_during_pending_review(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop.info_disclosure import InfoDisclosure
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, snapshot = first_trial(tmp_path, monkeypatch)
    snapshot = _marked_rejection(snapshot, monkeypatch)
    offer = density_preview(snapshot)
    label = (f"Compare {offer['initial_control_count']} and {offer['denser_control_count']} "
             "control points")
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        assert dialog.review_next_button.isVisible() and dialog.review_next_button.isEnabled()
        assert dialog.review_next_button.objectName() == "primary"
        assert not dialog.next_step_button.isVisible()
        optional = next(w for w in dialog.content.findChildren(InfoDisclosure)
                        if w.title == "Optional control-point test")
        optional.toggle_button.setChecked(True)
        assert any(b.isVisible() and b.isEnabled() and b.text() == label
                   for b in optional.findChildren(QPushButton))
    finally:
        dialog.close()
        app.processEvents()


def test_wide_spacing_keeps_density_as_the_only_primary_trial(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton
    from test_reference_calibration_study import _project

    from diffeoforge import reference_attachment_comparison as methods
    from diffeoforge.config import validate_input_paths
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.reference_calibration import build_reference_calibration_plan
    from diffeoforge.reference_recommendation import recommend_reference_parameters

    path = _project(tmp_path)
    config = load_config(path)
    inputs = validate_input_paths(config, path)
    recommendation = recommend_reference_parameters(
        (inputs.template, *inputs.subjects), alignment_basis="declared_gpa",
        surface_detail_intent="balanced", deformation_scale_intent="balanced",
        expected_shape_disparity="extreme",
    )
    plan = build_reference_calibration_plan(recommendation, coordinate_unit="unitless",
                                            requested_pilot_subject_count=3)
    config["project"]["parameter_provenance"].update(
        recommendation=dict(recommendation.provenance, calibration_plan=plan.provenance),
        attachment_selection=dict(version=methods.VERSION, mode="auto", state="pending",
                                  workflow=guided.VERSION),
    )
    study._write_yaml(path, config, overwrite=True)
    source = study.create_reference_calibration_study(path, tmp_path / "wide-pilot")
    initial = run_batch(guided.prepare(source.study_directory), monkeypatch)
    snapshot = reject(reject(initial, "guided-current"), METHOD)
    snapshot = guided.next_action(snapshot.study_directory, "adaptive_prefer", METHOD)
    values = snapshot.plan.effective_values
    assert values["initial_control_point_spacing"] > 1.1 * values["deformation_kernel_width"]
    guidance = guided_strategy.prepare_proposals(snapshot, guided_strategy.state(snapshot))
    assert guidance["proposals"][METHOD]["unsure"]["goal"] == "density"
    offer = guidance["density_comparisons"][METHOD]
    label = (f"Compare {offer['initial_control_count']} and {offer['denser_control_count']} "
             "control points")
    app = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        footer = dialog.next_step_button
        assert footer.text() == label
        assert dialog._guided_footer_action == (
            snapshot.study_directory, "adaptive_density_comparison", METHOD,
        )
        assert "control spacing wider" in dialog.status.text()
        assert [b for b in dialog.findChildren(QPushButton, "primary")
                if b.isVisible() and b.isEnabled()] == [footer]
        assert not any(b.isVisible() and b.text() == label
                       for b in dialog.content.findChildren(QPushButton))
    finally:
        dialog.close()
        app.processEvents()


def test_moderate_and_an_accepted_fit_do_not_offer_early_density(tmp_path, monkeypatch):
    _, moderate = first_trial(tmp_path / "moderate", monkeypatch, "moderate")
    moderate = _marked_rejection(moderate, monkeypatch)
    assert density_preview(moderate) is None
    _, extreme = first_trial(tmp_path / "extreme", monkeypatch)
    extreme = approve(_marked_rejection(extreme, monkeypatch), "guided-current")
    assert density_preview(extreme) is None


def test_spatial_regression_is_reported_even_with_lower_whole_shape_p95():
    from diffeoforge.pilot_regions import comparison

    original = dict(p95=.1, p99=.2, regional_tail=.3, regions={"0:1": {"tail": .2}})
    denser = dict(original, p95=.095, regions={"0:1": {"tail": .23}})
    before = dict(repeats=[original, original], diagonal=1.0)
    after = dict(repeats=[denser, denser], diagonal=1.0)
    assert comparison([], [], before, after) == "regression"
