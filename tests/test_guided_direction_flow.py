"""Test the path from a saved comparison to one explicitly prepared trial."""

import time

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
    assert result["mode"] == "trial" and result["current"] == alternative
    assert result["request"]["reference"] == alternative
    assert result["identifier"] == "guided-current"


def _selected_other_method(tmp_path, monkeypatch, *, selected_symptom=None,
                           stale_current_alignment=False):
    from test_guided_pilot import run_batch
    from test_interactive_pilot import geometry_receipt, initial
    from test_pilot_region_feedback import reject

    snapshot = reject(reject(run_batch(initial(tmp_path), monkeypatch), "guided-current"),
                      "guided-varifold")
    for identifier in ("guided-current", "guided-varifold"):
        geometry_receipt(snapshot, identifier, monkeypatch)
    current = guided_feedback.reference(snapshot, "guided-current")
    alternative = guided_feedback.reference(snapshot, "guided-varifold")
    target = alternative["target"]
    if stale_current_alignment:
        snapshot = guided_feedback.save_feedback(snapshot.study_directory, "guided-current", dict(
            comparison=alternative, outcome="same", symptom="alignment", note="Old current review",
            inspected_subjects=[target], display_scopes={target: "preview"},
            problem_regions={},
        ))
    form = snapshot.plan.selected_pilot_subjects[0]
    marks = [patch(form.sha256, symptom=selected_symptom)] if selected_symptom else []
    selected = guided.next_action(snapshot.study_directory, "adaptive_working_start",
        "guided-current", goal=dict(reference=alternative, display_scopes={target: "preview"},
            inspected_subjects=[target], problem_regions={target: marks} if marks else {}))
    return selected, current, alternative, marks


def test_new_explicit_other_method_choice_supersedes_stale_current_alignment_feedback(
    tmp_path, monkeypatch,
):
    snapshot, old, selected, _ = _selected_other_method(
        tmp_path, monkeypatch, stale_current_alignment=True)
    journal = snapshot.study_directory / study.STUDY_EVENTS
    before = journal.read_bytes()
    approvals = dict(snapshot.visual_reviews)
    state = guided_strategy.prepare_proposals(snapshot, guided_strategy.state(snapshot))
    result = state["fit_direction"]
    assert result["mode"] == "trial" and result["current"] == selected
    assert result["request"]["reference"] == selected
    assert result["current"] != old
    assert "alignment issue" not in result["reason"].lower()
    assert journal.read_bytes() == before and snapshot.visual_reviews == approvals


@pytest.mark.parametrize("symptom", ["alignment", "topology"])
def test_explicit_selected_fit_input_concern_keeps_a_named_input_action(
    tmp_path, monkeypatch, symptom,
):
    snapshot, _, selected, marks = _selected_other_method(
        tmp_path, monkeypatch, selected_symptom=symptom)
    state = guided_strategy.prepare_proposals(snapshot, guided_strategy.state(snapshot))
    result = state["fit_direction"]
    assert result["mode"] == "inputs" and result["current"] == selected
    assert "Varifold" in result["reason"] or "selected" in result["reason"].lower()
    assert ("alignment" in result["reason"].lower() if symptom == "alignment"
            else any(word in result["reason"].lower()
                     for word in ("opening", "connection", "topology")))
    assert state["feedback"]["guided-current"]["problem_regions"][selected["target"]] == marks


def test_selected_no_mark_footer_prepares_exact_working_fit_without_starting_optimizer(
    tmp_path, monkeypatch,
):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    snapshot, _, selected, _ = _selected_other_method(tmp_path, monkeypatch)
    approvals = dict(snapshot.visual_reviews)
    journal = snapshot.study_directory / study.STUDY_EVENTS
    prefix = journal.read_bytes()
    preserved = {p: sha256_file(p) for p in snapshot.study_directory.rglob("*")
                 if p.is_file() and p != journal}
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Navigation started an optimizer"))
    app = QApplication.instance() or QApplication([])
    view = ReferenceCalibrationDialog(snapshot.study_directory)
    view.show()
    try:
        wait_pilot_view(view)
        footer = view.next_step_button
        assert footer.isVisible() and footer.isEnabled()
        assert "Varifold" in footer.text() and "alignment" not in footer.text().lower()
        assert view._guided_footer_action == (
            snapshot.study_directory, "adaptive_recover_start", "guided-current")
        goal = view._guided_footer_goal
        assert goal["reference"] == selected and not goal["regions"]
        assert [b for b in view.findChildren(QPushButton, "primary")
                if b.isVisible() and b.isEnabled()] == [footer]
        footer.click()
        deadline = time.monotonic() + 20
        while view._worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        assert view._worker is None
        wait_pilot_view(view)
        prepared = view._snapshot
        assert prepared.study_directory != snapshot.study_directory
        assert prepared.attachment_comparison["refinement"]["reference"] == selected
        assert set(prepared.attachment_comparison["methods"].values()) == {"varifold"}
        assert prepared.plan.pilot_subject_count == len(prepared.candidates) == 1
        assert all(c.status == "pending" and c.attempts == 0 for c in prepared.candidates)
        assert not prepared.visual_reviews
        assert study.load_reference_calibration_study(snapshot.study_directory).visual_reviews == (
            approvals)
        assert journal.read_bytes().startswith(prefix)
        assert all(sha256_file(path) == digest for path, digest in preserved.items())
    finally:
        view.close()
        app.processEvents()


def test_later_explicit_method_card_choice_supersedes_an_older_cross_method_saved_start(
    tmp_path, monkeypatch,
):
    snapshot, current, old_selected, _ = _selected_other_method(tmp_path, monkeypatch)
    approvals = dict(snapshot.visual_reviews)
    preferred = guided.next_action(snapshot.study_directory, "adaptive_prefer", "guided-current")
    assert guided_feedback.selection(preferred, "guided-current") == current
    state = guided_strategy.prepare_proposals(preferred, guided_strategy.state(preferred))
    result = state["fit_direction"]
    assert result["mode"] == "trial"
    assert result["request"]["reference"] == current
    assert result["request"]["reference"] != old_selected
    assert state["preferred"] == "current"
    assert preferred.visual_reviews == approvals


def test_method_card_choice_exposes_green_reference_confirmation_before_a_new_trial(
    tmp_path, monkeypatch,
):
    from diffeoforge.retained_mark_source import context as retained_context

    snapshot, current, retained, _ = _selected_other_method(tmp_path, monkeypatch)
    form = snapshot.plan.selected_pilot_subjects[0]
    marks = [patch(form.sha256, center=[-.7, 0., 0.], radius=.3,
                   version="surface-region-v2", purpose="problem"),
             patch(form.sha256, center=[.7, 0., 0.], radius=.3,
                   version="surface-region-v2", purpose="fixed")]
    marked = guided.next_action(snapshot.study_directory, "adaptive_working_start",
        "guided-current", goal=dict(reference=retained,
            inspected_subjects=[form.filename], display_scopes={form.filename: "preview"},
            problem_regions={form.filename: marks}))
    assert retained_context(marked, "guided-current")["reference"] == retained
    switched = guided.next_action(marked.study_directory, "adaptive_prefer", "guided-current")
    prefix = (switched.study_directory / study.STUDY_EVENTS).read_bytes()
    state = guided_strategy.prepare_proposals(switched, guided_strategy.state(switched))
    result = state["fit_direction"]
    assert result["mode"] == "return" and result["current"] == current
    assert "green" in result["reason"].lower() and "confirm" in result["reason"].lower()
    assert "alignment" not in result["reason"].lower()
    assert retained_context(switched, "guided-current")["reference"] == retained
    assert (switched.study_directory / study.STUDY_EVENTS).read_bytes() == prefix
    confirmed = guided.next_action(switched.study_directory, "adaptive_working_start",
        "guided-current", goal=dict(reference=current,
            inspected_subjects=[form.filename], display_scopes={form.filename: "preview"},
            problem_regions={form.filename: marks}))
    assert retained_context(confirmed, "guided-current")["reference"] == current
    assert confirmed.visual_reviews == snapshot.visual_reviews
    assert all(c.attempts == 1 for c in confirmed.candidates)


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


def test_rejected_same_spacing_screen_prepares_finer_matching_from_the_only_primary(
    tmp_path, monkeypatch,
):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton
    from test_guided_early_density import METHOD, first_trial
    from test_pilot_region_feedback import reject

    from diffeoforge.desktop.info_disclosure import InfoDisclosure
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.guided_density import controls_for

    app = QApplication.instance() or QApplication([])
    _, initial = first_trial(tmp_path, monkeypatch)
    snapshot = reject(reject(initial, "guided-current"), METHOD)
    snapshot = guided.next_action(snapshot.study_directory, "adaptive_prefer", METHOD)
    values = snapshot.plan.effective_values
    assert values["initial_control_point_spacing"] == values["deformation_kernel_width"]
    guidance = guided_strategy.prepare_proposals(snapshot, guided_strategy.state(snapshot))
    assert all(guidance["proposals"][key]["unsure"]["goal"] == "detail"
               for key in snapshot.visual_reviews)
    assert set(guidance["density_comparisons"]) == set(snapshot.visual_reviews)
    journal = snapshot.study_directory / study.STUDY_EVENTS
    journal_prefix = journal.read_bytes()
    preserved = {p: sha256_file(p) for p in snapshot.study_directory.rglob("*")
                 if p.is_file() and p != journal}
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Preparation started an optimizer"))

    view = ReferenceCalibrationDialog(snapshot.study_directory)
    view.show()
    try:
        wait_pilot_view(view)
        footer = view.next_step_button
        assert footer.isVisible() and footer.isEnabled()
        assert footer.text().startswith("Test finer surface matching")
        start, action, identifier = view._guided_footer_action
        assert start == snapshot.study_directory
        assert identifier == METHOD
        assert action in {"adaptive_recover", "adaptive_recover_start"}
        goal = view._guided_footer_goal
        assert goal["request"] == "unsure" and goal["goal"] == "detail"
        assert goal["reference"] == guided_feedback.reference(snapshot, identifier)

        optional = next(w for w in view.content.findChildren(InfoDisclosure)
                        if w.title == "Optional control-point test")
        assert not optional.toggle_button.isChecked()
        optional.toggle_button.setChecked(True)
        for detail in view.content.findChildren(InfoDisclosure):
            if detail.title == "Other adjustments and input checks":
                detail.toggle_button.setChecked(True)
        density = [b for b in optional.findChildren(QPushButton)
                   if b.isVisible() and b.isEnabled() and b.text().endswith("control points")]
        assert density and all(b.objectName() != "primary" for b in density)
        assert [b for b in view.findChildren(QPushButton, "primary")
                if b.isVisible() and b.isEnabled()] == [footer]
        assert not any(b.isVisible() and b.text().startswith("Test finer surface matching")
                       for b in view.content.findChildren(QPushButton))
        assert journal.read_bytes() == journal_prefix

        footer.click()
        deadline = time.monotonic() + 20
        while view._worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        wait_pilot_view(view)
        assert view.study_directory != snapshot.study_directory, view.operation_error.text()
        prepared = study.load_reference_calibration_study(view.study_directory)
        assert prepared.attachment_comparison["refinement"]["reference"] == goal["reference"]
        assert guided.record(prepared)["goal"] == "detail"
        assert len(prepared.candidates) == prepared.plan.pilot_subject_count == 1
        candidate = prepared.candidates[0]
        assert candidate.status == "pending" and candidate.attempts == 0
        assert controls_for(prepared.attachment_comparison, candidate.candidate_id)["sha256"] == (
            controls_for(snapshot.attachment_comparison, identifier)["sha256"])
        after = dict(prepared.plan.effective_values)
        assert after.pop("attachment_kernel_width") == pytest.approx(
            values["attachment_kernel_width"] * .9)
        assert after == {k: v for k, v in values.items() if k != "attachment_kernel_width"}
        assert not prepared.visual_reviews
        assert study.load_reference_calibration_study(snapshot.study_directory).visual_reviews == (
            snapshot.visual_reviews)
        assert all(sha256_file(path) == digest for path, digest in preserved.items())
        assert journal.read_bytes().startswith(journal_prefix)
        assert study._load_events(snapshot.study_directory)[-1]["optimizer_started"] is False
    finally:
        view.close()
        app.processEvents()


def _marked_fit(tmp_path, monkeypatch, *, base=None, mark_count=1, symptom="detail"):
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
                   radius=.25, symptom=symptom) for axis in range(mark_count)]
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
    return base, identifier


def _regional_trial(tmp_path, monkeypatch, *, base=None, mark_count=1):
    base, identifier = _marked_fit(tmp_path, monkeypatch, base=base, mark_count=mark_count)
    trial = guided.next_action(
        base.study_directory, "adaptive_recover", identifier, goal="regional:detail"
    )
    assert trial.attachment_comparison["regional_objective"]
    return base, trial, identifier


@pytest.mark.parametrize("symptom", ["detail", "unsure", "distortion"])
def test_marked_area_is_the_only_primary_next_action_and_does_not_run(
    tmp_path, monkeypatch, symptom,
):
    from dataclasses import replace

    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QPushButton
    from test_guided_early_density import first_trial
    from test_pilot_region_feedback import reject

    from diffeoforge.desktop.info_disclosure import InfoDisclosure
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, snapshot = first_trial(tmp_path, monkeypatch)
    snapshot = reject(snapshot, "guided-current")
    snapshot, identifier = _marked_fit(tmp_path, monkeypatch, base=snapshot, symptom=symptom)
    snapshot = guided.next_action(snapshot.study_directory, "adaptive_prefer", identifier)
    journal = snapshot.study_directory / study.STUDY_EVENTS
    journal_prefix = journal.read_bytes()
    original = {p: sha256_file(p) for p in snapshot.study_directory.rglob("*") if p.is_file()}
    target = snapshot.plan.selected_pilot_subjects[0]
    calls = []
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: calls.append("optimizer started"))
    view = ReferenceCalibrationDialog(snapshot.study_directory)
    view.show()
    try:
        wait_pilot_view(view)
        assert view.next_step_button.isVisible() and view.next_step_button.isEnabled()
        assert view.next_step_button.objectName() == "primary"
        assert "marked areas" in view.next_step_button.text()
        assert "local test that protects" in view.status.text()
        origin, dispatch, subject = view._guided_footer_action
        assert origin == snapshot.study_directory and subject == identifier
        assert dispatch in {"adaptive_recover", "adaptive_recover_start"}
        goal = view._guided_footer_goal
        assert goal["reference"] == guided_feedback.reference(snapshot, identifier)
        assert goal["goal"] == "regional" and goal["request"] == "regional:" + symptom
        assert [row["source_sha256"] for row in goal["regions"]] == [target.sha256]
        secondary_titles = {
            "Optional control-point test", "Other adjustments and input checks",
        }
        secondary = [w for w in view.content.findChildren(InfoDisclosure)
                     if w.title in secondary_titles]
        assert {w.title for w in secondary} == secondary_titles
        for disclosure in secondary:
            assert not disclosure.toggle_button.isChecked()
            disclosure.toggle_button.setChecked(True)
        density = next(w for w in secondary if w.title == "Optional control-point test")
        assert any(b.isVisible() and b.text().endswith("control points")
                   for b in density.findChildren(QPushButton))
        assert [b for b in view.findChildren(QPushButton, "primary")
                if b.isVisible() and b.isEnabled()] == [view.next_step_button]
        assert not any(b.isVisible() and "Improve marked areas" in b.text()
                       for b in view.content.findChildren(QPushButton))
        with pytest.raises(ValueError, match="marked areas changed"):
            guided.next_action(snapshot.study_directory, dispatch, identifier,
                               goal=goal | {"regions": []})
        with pytest.raises(ValueError, match="saved reviews changed"):
            guided_strategy._plan_transition(
                replace(snapshot, visual_reviews={identifier: False}),
                "recover", identifier, goal=goal,
            )

        view.next_step_button.click()
        deadline = time.monotonic() + 20
        while (view._worker or view._view_loading) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        wait_pilot_view(view)
        assert view.study_directory != snapshot.study_directory, view.operation_error.text()
        prepared = study.load_reference_calibration_study(view.study_directory)
        record = prepared.attachment_comparison
        assert record["regional_objective"]
        assert record["guided"]["strategy"]["baseline"] == goal["reference"]
        assert record["guided"]["feedback"]["regions"] == goal["regions"]
        assert all(c.attempts == 0 for c in prepared.candidates)
        assert not calls and all(sha256_file(p) == digest for p, digest in original.items()
                                 if p != journal)
        assert journal.read_bytes().startswith(journal_prefix)
        events = study._load_events(snapshot.study_directory)
        assert events[-1]["event"] == "guided_pilot_decision"
        assert events[-1]["optimizer_started"] is False
    finally:
        view.close()
        app.processEvents()


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
    draft = guided_fit_direction.partial_mark_draft(local, retained)
    assert draft["remaining"] == 1 and draft["suggested"] == 2
    selected_marks = draft["marks"]
    assert selected_marks == [remaining, *(
        dict(mark, version=EDIT_VERSION, purpose="fixed") for mark in marks[:2])]
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
    assert not other_direction.get("quality_warning")
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
    monkeypatch.setattr(view, "_open_guided_working_fit",
                        lambda *args, **kwargs: observed.append((args, kwargs)))
    journal = snapshot.study_directory / study.STUDY_EVENTS
    digest = sha256_file(journal)
    view.show()
    try:
        wait_pilot_view(view)
        assert view.next_step_button.isVisible() and view.next_step_button.isEnabled()
        assert view.next_step_button.text() == f"Work from saved fit · {direction['start_label']}"
        view.next_step_button.click()
        assert observed == [((direction["identifier"], direction["current"]),
                             {"restore_partial": True} if direction["partial"] else {})]
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
