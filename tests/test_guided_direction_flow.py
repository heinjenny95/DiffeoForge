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
