"""Test the path from a saved comparison to one explicitly prepared trial."""

import pytest
from test_guided_feedback import attempted
from test_pilot_region_feedback import patch

from diffeoforge import guided_feedback, guided_fit_direction, guided_strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def comparison(tmp_path, monkeypatch):
    earlier, current = attempted(tmp_path, monkeypatch)
    identifier = "guided-varifold"
    form = current.plan.selected_pilot_subjects[0]
    original = guided_feedback.reference(current, identifier)
    alternative = guided_feedback.reference(earlier, identifier)
    direction = dict(mode="compare", identifier=identifier, current=original,
                     current_cp=40, alternative_cp=40, alternative=alternative,
                     target=form.filename, reason="Compare saved fits")
    monkeypatch.setattr(guided_fit_direction, "preview", lambda *_: direction)
    return earlier, current, identifier, form, direction


def test_marked_comparison_suggests_only_the_named_start_and_never_runs(tmp_path, monkeypatch):
    from test_interactive_pilot import geometry_receipt

    earlier, current, identifier, form, direction = comparison(tmp_path, monkeypatch)
    geometry_receipt(earlier, identifier, monkeypatch)
    before = {p: sha256_file(p) for p in earlier.study_directory.rglob("*") if p.is_file()}
    state = guided_strategy.prepare_proposals(current, guided_strategy.state(current))
    assert state["fit_direction"]["mode"] == "compare"
    chosen = guided.next_action(
        current.study_directory, "adaptive_working_start", identifier, goal=dict(
            reference=direction["alternative"],
            display_scopes={form.filename: "preview"}, inspected_subjects=[form.filename],
            problem_regions={form.filename: [patch(form.sha256)]},
        ),
    )
    state = guided_strategy.prepare_proposals(chosen, guided_strategy.state(chosen))
    plan = state["fit_direction"]
    assert plan["mode"] == "trial" and plan["request"]["request"] == "goal:detail"
    assert plan["request"]["reference"] == direction["alternative"]
    assert not chosen.visual_reviews
    journal = chosen.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    stale = plan["request"] | {"reference": direction["current"]}
    with pytest.raises(ValueError, match="suggested trial changed"):
        guided.next_action(chosen.study_directory, "adaptive_recover_start", identifier, goal=stale)
    stale = plan["request"] | {"regions": []}
    with pytest.raises(ValueError, match="marked areas changed"):
        guided.next_action(chosen.study_directory, "adaptive_recover_start", identifier, goal=stale)
    assert sha256_file(journal) == digest
    prepared = guided.next_action(
        chosen.study_directory, "adaptive_recover_start", identifier, goal=plan["request"],
    )
    assert prepared.attachment_comparison["refinement"]["reference"] == direction["alternative"]
    assert all(c.attempts == 0 for c in prepared.candidates) and not prepared.visual_reviews
    assert all(sha256_file(p) == digest for p, digest in before.items())


def test_choosing_other_method_in_same_study_advances_from_comparison(tmp_path, monkeypatch):
    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import reject

    snapshot = reject(reject(run_batch(initial(tmp_path), monkeypatch), "guided-current"),
                      "guided-varifold")
    current = guided_feedback.reference(snapshot, "guided-current")
    alternative = guided_feedback.reference(snapshot, "guided-varifold")
    target = alternative["target"]
    direction = dict(mode="compare", identifier="guided-current", current=current,
                     alternative=alternative)
    monkeypatch.setattr(guided_fit_direction, "preview", lambda *_: direction)
    chosen = guided.next_action(
        snapshot.study_directory, "adaptive_working_start", "guided-current", goal=dict(
            reference=alternative, display_scopes={target: "preview"}, inspected_subjects=[target],
            problem_regions={},
        ),
    )
    state = guided_strategy.prepare_proposals(chosen, guided_strategy.state(chosen))
    result = state["fit_direction"]
    assert result["mode"] == "inputs" and result["current"] == alternative


def test_saved_comparison_opens_from_the_fixed_footer_without_preparing_fit(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication
    from test_pilot_region_feedback import reject

    from diffeoforge.desktop import guided_fit_direction as dialog
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, current, identifier, _form, direction = comparison(tmp_path, monkeypatch)
    current = reject(current, identifier)
    observed = []
    monkeypatch.setattr(dialog, "open_comparison", lambda window, paired: observed.append(paired))
    view = ReferenceCalibrationDialog(current.study_directory)
    journal = current.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    view.show()
    try:
        wait_pilot_view(view)
        assert view.next_step_button.isVisible() and view.next_step_button.isEnabled()
        assert view.next_step_button.text() == "Compare saved fits"
        view.next_step_button.click()
        assert observed == [direction]
        assert not view._worker and sha256_file(journal) == digest
    finally:
        view.close()
        app.processEvents()


def _regional_trial(tmp_path, monkeypatch, *, base=None, mark_count=1):
    import shutil
    from types import SimpleNamespace

    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial

    from diffeoforge import regional_frame, result_report
    from diffeoforge.config import load_config
    from diffeoforge.surface_io import load_surface_mesh

    identifier = "guided-varifold"
    base = base or run_batch(initial(tmp_path), monkeypatch)
    manifest = study._verify_manifest(base.study_directory)
    target = base.plan.selected_pilot_subjects[0]
    original = base.study_directory / manifest["inputs"]["subjects"][0]["copy"]
    vertices = load_surface_mesh(original).geometry.vertices
    marks = [patch(target.sha256, center=list(max(vertices, key=lambda point: point[axis])),
                   radius=.25) for axis in range(mark_count)]
    base = study.record_reference_calibration_candidate_review(
        base.study_directory, candidate_id=identifier, approved=False,
        reviewed_subjects=(target.filename,), subject_decisions={target.filename: "fail"},
        problem_regions={target.filename: marks},
    )

    candidate = next(c for c in base.candidates if c.candidate_id == identifier)
    run = candidate.run_directory
    template = base.study_directory / manifest["inputs"]["template"]["copy"]
    output = run / "output"
    output.mkdir(exist_ok=True)
    config = load_config(candidate.config_path)
    object_id = config["model"]["object_id"]
    endpoint = output / f"Fixture__Reconstruction__{object_id}__subject_{target.filename}.vtk"
    shutil.copyfile(template, endpoint)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _: SimpleNamespace(
        inventory=[dict(path=endpoint.name, sha256=sha256_file(endpoint))],
        manifest=dict(effective_config=config),
    ))
    if not (run / "manifest.json").exists():
        (run / "manifest.json").write_text("{}")

    controls = tmp_path / "qualified-controls.txt"
    momenta = tmp_path / "qualified-momenta.txt"
    controls.write_text("synthetic controls")
    momenta.write_text("synthetic momenta")
    # The controller is synthetic. Native frame verification has its own tests.
    monkeypatch.setattr(regional_frame, "qualify", lambda *_a, **_k: dict(
        source_run=str(run), source_manifest_sha256=sha256_file(run / "manifest.json"),
        endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)),
        reference_source=dict(path=str(template), sha256=sha256_file(template)),
        timepoints=73, precision="float64", integrator="rk2",
        starting_frame_qualification=dict(temporal_stable=True),
        field_paths=dict(control_points=str(controls), momenta=str(momenta)),
        controls_sha256=sha256_file(controls), momenta_sha256=sha256_file(momenta),
    ))
    trial = guided.next_action(
        base.study_directory, "adaptive_recover", identifier, goal="regional:detail"
    )
    assert trial.attachment_comparison["regional_objective"]
    return base, trial, identifier


def _complete_with_regions(snapshot, monkeypatch, outcome, *, failed_guard=False):
    from test_reference_attachment_comparison import _detail
    from test_reference_calibration_study import _CompletedController

    from diffeoforge import reference_attachment_comparison as methods

    feedback = guided.record(snapshot)["feedback"]

    def measure(_root, manifest, _candidate, _run, **_options):
        names = [row["filename"] for row in manifest["inputs"]["subjects"]]
        metrics = _detail(names)
        subject = metrics["subjects"][feedback["target"]]
        if outcome is not None:
            subject["marked_regions"] = dict(measurements=feedback["baseline"], outcome=outcome)
        if failed_guard:
            subject["regional_quality"] = dict(
                numerical_selection_suitable=False, transition_preserved=True,
                outside_preserved=True, shape_preserved=False,
            )
        return dict(attachment_comparison=metrics, fit_scope="full_targets",
                    original_surface_fit={
                        name: dict(p95=.01, p99=.02, mean=.005, diagonal=1)
                        for name in names
                    })

    monkeypatch.setattr(methods, "measure", measure)
    return study.ReferenceCalibrationStudyRunner(
        snapshot.study_directory, controller_factory=_CompletedController,
    ).run_current_stage()


@pytest.mark.parametrize("feedback_outcome, measured_outcome, failed_guard, offers_inputs", [
    ("same", "improved", False, True),
    (None, "regression", False, True),
    pytest.param(None, None, True, True, id="guard-rejected"),
    pytest.param("better", None, True, False, id="guard-better"),
])
def test_rejected_protected_fit_offers_bound_input_check(
        tmp_path, monkeypatch, feedback_outcome, measured_outcome, failed_guard, offers_inputs):
    from test_guided_feedback import decision
    from test_pilot_region_feedback import reject

    base, trial, identifier = _regional_trial(tmp_path, monkeypatch)
    trial = _complete_with_regions(trial, monkeypatch, measured_outcome, failed_guard=failed_guard)
    trial = reject(trial, identifier)
    if feedback_outcome:
        trial = guided_feedback.save_feedback(
            trial.study_directory, identifier, decision(base, trial, feedback_outcome),
        )

    journal = trial.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    reopened = study.load_reference_calibration_study(trial.study_directory)
    guidance = guided_strategy.prepare_proposals(reopened, guided_strategy.state(reopened))
    direction = guidance["fit_direction"]
    assert sha256_file(journal) == digest
    if not offers_inputs:
        assert direction is None
        return
    assert direction["mode"] == "inputs"
    assert direction["current"] == guided_feedback.reference(reopened, identifier)
    if feedback_outcome == "same" or failed_guard:
        _assert_read_only_input_footer(reopened, direction, monkeypatch)


def test_rejected_density_pair_offers_its_seed_after_both_reviews(tmp_path, monkeypatch):
    from test_guided_early_density import METHOD, REFERENCE, _marked_rejection, first_trial
    from test_pilot_region_feedback import reject

    _, initial = first_trial(tmp_path, monkeypatch)
    initial = _marked_rejection(initial, monkeypatch)
    pair = guided.next_action(initial.study_directory, "adaptive_density_comparison", METHOD)
    pair = _complete_with_regions(pair, monkeypatch, "unclear")
    partial = reject(pair, REFERENCE)
    guidance = guided_strategy.prepare_proposals(partial, guided_strategy.state(partial))
    assert (guidance["fit_direction"] or {}).get("mode") != "return"

    pair = reject(partial, METHOD)
    journal = pair.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    guidance = guided_strategy.prepare_proposals(pair, guided_strategy.state(pair))
    direction = guidance["fit_direction"]
    assert direction["mode"] == "return"
    assert direction["current"] == guided_feedback.reference(initial, METHOD)
    assert sha256_file(journal) == digest


def test_return_to_the_partial_local_fit_after_worse_control_point_trials(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace

    from test_guided_early_density import METHOD, REFERENCE, first_trial
    from test_guided_feedback import decision
    from test_interactive_pilot import geometry_receipt
    from test_pilot_region_feedback import reject

    from diffeoforge import regional_evaluation, result_report
    from diffeoforge.config import load_config
    from diffeoforge.pilot_regions import EDIT_VERSION

    _, root = first_trial(tmp_path, monkeypatch)
    base, local, identifier = _regional_trial(tmp_path, monkeypatch, base=root, mark_count=3)
    marks = guided.record(local)["feedback"]["regions"]
    assert len(marks) == 3
    source = local.plan.selected_pilot_subjects[0]
    target = source.filename
    remaining = dict(marks[-1], radius=marks[-1]["radius"] * 1.01)
    local = _complete_with_regions(local, monkeypatch, "regression", failed_guard=True)
    local = study.record_reference_calibration_candidate_review(
        local.study_directory, candidate_id=identifier, approved=False,
        reviewed_subjects=(target,), subject_decisions={target: "fail"},
        problem_regions={target: [remaining]},
    )
    retained = guided_feedback.reference(local, METHOD)
    local_direction = guided_strategy.prepare_proposals(local, guided_strategy.state(local))[
        "fit_direction"]
    assert local_direction["mode"] == "return" and local_direction["current"] == retained
    assert "preservation of the marked part shape" in local_direction["reason"]

    geometry_receipt(base, METHOD, monkeypatch)
    pair = guided.next_action(local.study_directory, "adaptive_density_comparison", METHOD)
    assert pair.attachment_comparison["refinement"]["reference"] == guided_feedback.reference(
        base, METHOD)
    pair = _complete_with_regions(pair, monkeypatch, "regression")
    for arm in (REFERENCE, METHOD):
        pair = reject(pair, arm, marked=True)
        pair = guided_feedback.save_feedback(
            pair.study_directory, arm, decision(base, pair, "worse"),
        )
        direction = guided_strategy.prepare_proposals(pair, guided_strategy.state(pair))[
            "fit_direction"]
        if arm == REFERENCE:
            assert (direction or {}).get("mode") != "return"
    assert direction["mode"] == "return" and direction["current"] == retained

    # Opening the footer routes to the exact earlier reconstruction without a write.
    _assert_working_footer(pair, direction, monkeypatch)
    local_candidate = local.candidates[0]
    local_run = local_candidate.run_directory
    config = load_config(local_candidate.config_path)
    local_row = study._verify_manifest(local.study_directory)["inputs"]["subjects"][0]
    endpoint = (local_run / "output" /
                f"Fixture__Reconstruction__{config['model']['object_id']}__subject_{target}.vtk")
    endpoint.parent.mkdir(exist_ok=True)
    shutil.copyfile(local.study_directory / local_row["copy"], endpoint)
    local_report = SimpleNamespace(
        inventory=[dict(path=endpoint.name, sha256=sha256_file(endpoint))],
        manifest=dict(effective_config=config),
    )
    base_report = result_report.collect_run_report
    base_endpoint = regional_evaluation.endpoint
    monkeypatch.setattr(result_report, "collect_run_report",
                        lambda path: local_report if path == local_run else base_report(path))
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda candidate, subject=None:
        dict(path=str(endpoint), sha256=local_report.inventory[0]["sha256"])
        if candidate.run_directory == local_run else base_endpoint(candidate, subject))
    local_pins = {p: sha256_file(p) for p in local.study_directory.rglob("*") if p.is_file()}
    selected_marks = [dict(mark, version=EDIT_VERSION, purpose="fixed") for mark in marks[:2]]
    selected_marks.append(remaining)
    chosen = guided.next_action(
        pair.study_directory, "adaptive_working_start", direction["identifier"], goal=dict(
            reference=retained, display_scopes={target: "preview"},
            inspected_subjects=[target], problem_regions={target: selected_marks},
        ),
    )
    direction = guided_strategy.prepare_proposals(chosen, guided_strategy.state(chosen))[
        "fit_direction"]
    assert direction["mode"] == "trial"
    assert direction["request"]["reference"] == retained
    assert direction["request"]["regions"] == selected_marks
    assert "preservation of the marked part shape" in direction["reason"]
    assert chosen.visual_reviews == pair.visual_reviews
    base_reference = guided_feedback.reference(base, METHOD)
    selected_other = guided.next_action(
        chosen.study_directory, "adaptive_working_start", direction["identifier"], goal=dict(
            reference=base_reference, display_scopes={target: "preview"},
            inspected_subjects=[target], problem_regions={target: [remaining]},
        ),
    )
    other_direction = guided_strategy.prepare_proposals(
        selected_other, guided_strategy.state(selected_other),
    )["fit_direction"]
    assert other_direction["mode"] == "trial"
    assert other_direction["request"]["reference"] == base_reference
    assert not other_direction["quality_warning"]
    assert all(sha256_file(path) == digest for path, digest in local_pins.items())


def _assert_working_footer(snapshot, direction, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    view = ReferenceCalibrationDialog(snapshot.study_directory)
    observed = []
    monkeypatch.setattr(view, "_open_guided_working_fit", lambda *args: observed.append(args))
    journal = snapshot.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    view.show()
    try:
        wait_pilot_view(view)
        assert view.next_step_button.isVisible() and view.next_step_button.isEnabled()
        assert view.next_step_button.text() == f"Work from saved fit · {direction['start_label']}"
        view.next_step_button.click()
        assert observed == [(direction["identifier"], direction["current"])]
        assert not view._worker and sha256_file(journal) == digest
    finally:
        view.close()
        app.processEvents()


def _assert_read_only_input_footer(snapshot, direction, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    view = ReferenceCalibrationDialog(snapshot.study_directory)
    observed = []
    monkeypatch.setattr(view._viewer_preparation, "request_operation",
                        lambda key, prepare: observed.append((key, prepare())))
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Input inspection started an optimizer"))
    journal = snapshot.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    view.show()
    try:
        wait_pilot_view(view)
        assert view.next_step_button.isVisible() and view.next_step_button.isEnabled()
        assert view.next_step_button.text() == "Inspect template and alignment"
        view.next_step_button.click()
        ((key, (parent, candidate, (pair,))),) = observed
        assert key == ("guided-inputs", snapshot.study_directory, direction["current"])
        assert parent.study_directory == snapshot.study_directory
        assert candidate.candidate_id == direction["current"]["candidate_id"]
        manifest = study._verify_manifest(parent.study_directory)
        inputs = manifest["inputs"]
        assert pair.original_path == parent.study_directory / inputs["subjects"][0]["copy"]
        assert pair.reconstruction_path == parent.study_directory / inputs["template"]["copy"]
        assert sha256_file(pair.original_path) == pair.original_sha256
        assert sha256_file(pair.reconstruction_path) == pair.reconstruction_sha256
        assert not view._worker and sha256_file(journal) == digest
    finally:
        view.close()
        app.processEvents()
