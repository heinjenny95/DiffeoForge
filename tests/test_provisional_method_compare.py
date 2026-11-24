"""Synthetic metadata and ordinary preparation tests; never a native optimizer."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file
from diffeoforge.method_comparison_followup import provisional_comparison


def fake():
    values = dict(attachment_kernel_width=0.3, noise_std=0.1)
    info = dict(
        version=guided.ADAPTIVE_VERSION,
        phase="screen",
        goal=None,
        target="a.vtk",
        pilot_order=["a.vtk", "b.vtk", "c.vtk"],
        approved=[],
        history=[],
    )
    candidates = tuple(
        SimpleNamespace(
            candidate_id="guided-" + m,
            status="completed",
            metrics=dict(completed=True, invalid_face_count=0, subject_reconstruction_count=1),
        )
        for m in ("current", "varifold")
    )
    return SimpleNamespace(
        candidates=candidates,
        visual_reviews={c.candidate_id: False for c in candidates},
        attachment_comparison=dict(
            guided=info,
            methods={
                c.candidate_id: m for c, m in zip(candidates, ("current", "varifold"), strict=True)
            },
        ),
        plan=SimpleNamespace(pilot_subject_count=1, effective_values=values),
        current_stage=SimpleNamespace(
            candidates=[
                SimpleNamespace(values=values.copy()),
                SimpleNamespace(values=values.copy()),
            ]
        ),
    )


def test_both_needing_improvement_can_compare_metadata_without_approval(monkeypatch):
    s = fake()
    from diffeoforge import surface_io

    monkeypatch.setattr(
        surface_io,
        "load_surface_mesh",
        lambda *_a, **_k: pytest.fail("Metadata preview loaded a mesh"),
    )
    result = provisional_comparison(s, context=dict(cases=[]))
    assert result["eligible"] and result["available"] and result["target"] == "b.vtk"
    assert s.visual_reviews == {"guided-current": False, "guided-varifold": False}
    assert not s.attachment_comparison["guided"]["approved"]


@pytest.mark.parametrize(
    "invalid",
    (
        "uninspected",
        "pending",
        "incomplete",
        "invalid_faces",
        "wrong_count",
        "duplicate_methods",
        "different_values",
        "regional",
        "refined",
        "validate",
        "legacy",
        "multiple_subjects",
    ),
)
def test_noninitial_or_unreviewed_or_invalid_pairs_are_not_eligible(invalid):
    s = fake()
    r = s.attachment_comparison
    info = r["guided"]
    c = s.candidates[0]
    if invalid == "uninspected":
        s.visual_reviews.clear()
    elif invalid == "pending":
        c.status = "pending"
    elif invalid == "incomplete":
        c.metrics["completed"] = False
    elif invalid == "invalid_faces":
        c.metrics["invalid_face_count"] = 1
    elif invalid == "wrong_count":
        c.metrics["subject_reconstruction_count"] = 2
    elif invalid == "duplicate_methods":
        r["methods"]["guided-current"] = "varifold"
    elif invalid == "different_values":
        s.current_stage.candidates[0].values["noise_std"] = 0.9
    elif invalid == "regional":
        r["regional_objective"] = {"version": "regional-fit-v1"}
    elif invalid == "refined":
        r["refinement"] = {"version": "guided-refinement-v1"}
    elif invalid == "validate":
        info["phase"] = "validate"
    elif invalid == "legacy":
        info["version"] = guided.VERSION
    elif invalid == "multiple_subjects":
        s.plan.pilot_subject_count = 2
    if invalid == "uninspected":
        from unittest.mock import patch

        with patch("diffeoforge.guided_feedback.inspected", return_value=False):
            result = provisional_comparison(s, context=dict(cases=[]))
    else:
        result = provisional_comparison(s, context=dict(cases=[]))
    assert not result["eligible"] and not result["available"]


def test_order_skips_rejected_or_other_method_history_and_exhaustion_guides_refinement():
    s = fake()
    before = deepcopy(s.attachment_comparison)
    cases = [dict(target="b.vtk", method="current", outcome="rejected", values={"other": 1})]
    result = provisional_comparison(s, context=dict(cases=cases))
    assert result["target"] == "c.vtk" and result["tested"] == ["a.vtk", "b.vtk"]
    result = provisional_comparison(s, context=dict(cases=cases + [dict(target="c.vtk")]))
    assert result["eligible"] and not result["available"] and result["target"] is None
    assert "starting method" in result["explanation"] and "refine" in result["explanation"]
    assert s.attachment_comparison == before


def rejected_fixture(tmp_path, monkeypatch, *, marked=False):
    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import reject

    s = run_batch(initial(tmp_path), monkeypatch)
    s = reject(reject(s, "guided-current", marked=marked), "guided-varifold", marked=marked)
    return s


def test_real_batch_preparation_is_fresh_and_adds_no_approval_or_execution(tmp_path, monkeypatch):
    s = rejected_fixture(tmp_path, monkeypatch, marked=True)
    before = {p: sha256_file(p) for p in s.study_directory.rglob("*") if p.is_file()}
    original = guided.record(s)
    old_events = study._load_events(s.study_directory)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("Preparation executed"),
    )
    from diffeoforge import surface_io

    loaded = []
    real_load = surface_io.load_surface_mesh

    def load_template_only(path, *args, **kwargs):
        loaded.append(Path(path))
        assert Path(path).name == s.plan.template_filename
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr(surface_io, "load_surface_mesh", load_template_only)
    result = guided.next_action(s.study_directory, "adaptive_compare_unresolved")
    assert loaded and all(p.name == s.plan.template_filename for p in loaded)
    assert (
        s.problem_regions
        and study.load_reference_calibration_study(s.study_directory).problem_regions
        == s.problem_regions
    )
    info = guided.record(result)
    assert result.plan.pilot_subject_count == 1 and set(
        result.attachment_comparison["methods"].values()
    ) == {"current", "varifold"}
    assert info["target"] == original["pilot_order"][1] and info["phase"] == "screen"
    assert (
        info["approved"] == original["approved"] == []
        and not result.visual_reviews
        and not result.selected_candidate_ids
    )
    assert info["feedback"] is None and info["goal"] is None and info["screen_trials_spent"] == 4
    assert all(c.status == "pending" and c.attempts == 0 for c in result.candidates)
    assert result.plan.effective_values == s.plan.effective_values
    assert not any(
        info["strategy"].get(k)
        for k in (
            "baseline",
            "anchor",
            "control_basis",
            "regional_recipe",
            "optimization",
            "regional_continuation",
            "preference",
        )
    )
    from diffeoforge.config import load_config

    for c in result.candidates:
        config = load_config(c.config_path)
        assert not config["model"]["deformation"].get("initial_momenta")
    assert info["history"][-1]["outcome"] == "adaptive_compare_unresolved"
    assert (
        info["history"][-1]["manifest_sha256"] == before[s.study_directory / study.STUDY_MANIFEST]
    )
    assert all(sha256_file(p) == h for p, h in before.items() if p.name != study.STUDY_EVENTS)
    assert study._load_events(s.study_directory)[: len(old_events)] == old_events


def test_genuine_both_approved_tie_flow_keeps_approval_credit(tmp_path, monkeypatch):
    from test_guided_pilot import approve, run_batch
    from test_interactive_pilot import initial

    s = run_batch(initial(tmp_path), monkeypatch)
    s = approve(approve(s, "guided-current"), "guided-varifold")
    result = guided.next_action(s.study_directory, "adaptive_tie")
    assert len(guided.record(result)["approved"]) == 2
    assert guided.record(result)["history"][-1]["outcome"] == "adaptive_tie"
    assert all(c.attempts == 0 for c in result.candidates)


@pytest.mark.parametrize("choice", ["Current", "Varifold", "No clear winner"])
def test_reviewed_method_choice_through_real_footer(tmp_path, monkeypatch, choice):
    import time

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton
    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import reject

    from diffeoforge import pilot_capped_direction
    from diffeoforge.desktop.info_disclosure import InfoDisclosure
    from diffeoforge.desktop.pilot_assistant_context import context_for_view
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.pilot_assistant import reply

    app = QApplication.instance() or QApplication([])
    snapshot = run_batch(initial(tmp_path), monkeypatch, capped=True)
    snapshot = reject(reject(snapshot, "guided-current"), "guided-varifold")
    # Only one arm has evidence for continuing past its cap. It cannot choose the method.
    monkeypatch.setattr(pilot_capped_direction, "_objective_tail", lambda c:
                        ((115, -20.), (120, -19.)) if c.candidate_id == "guided-varifold" else None)
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Choice launched a fit"))
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    journal = snapshot.study_directory / study.STUDY_EVENTS
    prefix = journal.read_bytes()

    def choose(invoke, label):
        seen = []

        def inspect():
            modal = app.activeModalWidget()
            if modal:
                try:
                    buttons = modal.findChildren(QPushButton)
                    seen.extend(b.text() for b in buttons if b.isVisible())
                    if label:
                        next(b for b in buttons if b.text().startswith(label)).click()
                    else:
                        modal.findChild(QDialogButtonBox).button(
                            QDialogButtonBox.StandardButton.Cancel).click()
                finally:
                    if modal.isVisible():
                        modal.reject()

        QTimer.singleShot(0, inspect)
        invoke()
        assert "Current fit better" in seen and "Varifold fit better" in seen
        return seen

    try:
        wait_pilot_view(dialog)
        footer = dialog.next_step_button
        prepared = dialog._prepared_view
        assert prepared.guidance["fit_direction"] is None
        assert [b for b in dialog.findChildren(QPushButton, "primary")
                if b.isVisible() and b.isEnabled()] == [footer]
        assert not any(w.title == "Optional control-point test"
                       for w in dialog.content.findChildren(InfoDisclosure))
        assert {b.text() for b in dialog.content.findChildren(QPushButton)
                if b.isVisible() and b.text().startswith("Inspect ")} >= {
            "Inspect Current fit", "Inspect Varifold fit"}
        context, callbacks = context_for_view(dialog, prepared)
        for question in ("Which fit was better?", "More CP?", "What next?"):
            answer = reply(context, question)
            assert answer["verified"] and answer["actions"] == ("choose_method",)
        comparison = prepared.guidance["provisional_comparison"]
        prepared.guidance["provisional_comparison"] = dict(
            comparison, available=False, target=None,
            explanation="All selected forms have already been screened.")
        dialog._render(prepared=prepared)
        assert "All selected forms" in dialog.status.text()
        assert not any("No clear winner" in s for s in choose(footer.click, None))
        prepared.guidance["provisional_comparison"] = comparison
        dialog._render(prepared=prepared)
        assert any("No clear winner" in s for s in choose(callbacks["choose_method"], None))
        assert journal.read_bytes() == prefix

        choose(footer.click, choice)
        deadline = time.monotonic() + 30
        while (dialog._worker or dialog._view_loading) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        assert dialog._prepared_view, dialog.operation_error.text()
        wait_pilot_view(dialog)
        assert not dialog._worker, dialog.operation_error.text()
        saved = study.load_reference_calibration_study(snapshot.study_directory)
        assert saved.visual_reviews == snapshot.visual_reviews
        assert saved.problem_regions == snapshot.problem_regions
        if choice == "No clear winner":
            successor = dialog._prepared_view.snapshot
            assert successor.study_directory != snapshot.study_directory
            assert guided.record(successor)["target"] == comparison["target"]
            methods = successor.attachment_comparison["methods"].values()
            assert set(methods) == {"current", "varifold"}
            assert not guided.record(successor)["approved"]
            assert all(c.status == "pending" and c.attempts == 0 for c in successor.candidates)
        else:
            guidance = dialog._prepared_view.guidance
            assert dialog.study_directory == snapshot.study_directory
            assert guidance["preferred"] == choice.lower() and not guidance["method_choice_pending"]
            assert guidance["fit_direction"]["identifier"] == "guided-" + choice.lower()
            assert all(c.attempts == 1 for c in saved.candidates)
    finally:
        dialog.close()
        app.processEvents()
