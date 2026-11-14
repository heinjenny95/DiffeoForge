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


def test_actual_qt_provisional_prepare_and_exhaustion_keep_starting_cards(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    snapshot = rejected_fixture(tmp_path, monkeypatch)
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        buttons = dialog.content.findChildren(QPushButton)
        initial = [b for b in buttons if "as starting method" in b.text() and not b.isHidden()]
        assert len(initial) == 2
        button = next(
            b for b in buttons if b.text().startswith("No clear winner yet") and not b.isHidden()
        )
        assert button.isEnabled() and button.objectName() == "secondary"
        invoked = []
        monkeypatch.setattr(dialog, "_start_pilot", lambda *a, **k: invoked.append((a, k)))
        assert not invoked
        button.click()
        assert invoked == [
            ((), dict(adaptive=False, guided_action=("adaptive_compare_unresolved", None, None)))
        ]
        prepared = dialog._prepared_view
        prepared.guidance["provisional_comparison"] = dict(
            eligible=True,
            available=False,
            target=None,
            explanation=(
                "All selected forms have already been screened. "
                "Choose a starting method and refine the marked problems."
            ),
        )
        dialog._render(prepared=prepared)
        app.processEvents()
        assert not [
            b
            for b in dialog.content.findChildren(QPushButton)
            if b.text().startswith("No clear winner yet") and not b.isHidden()
        ]
        assert (
            len(
                [
                    b
                    for b in dialog.content.findChildren(QPushButton)
                    if "as starting method" in b.text() and not b.isHidden()
                ]
            )
            == 2
        )
        assert any(
            "All selected forms have already been screened" in label.text() and not label.isHidden()
            for label in dialog.content.findChildren(QLabel)
        )
        assert len(invoked) == 1 and not dialog._worker
    finally:
        dialog.close()
        app.processEvents()
