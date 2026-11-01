"""An earlier suitable local shape can advance a rejected common-model trial."""

import pytest
from test_guided_pilot import approve, run_batch
from test_pilot_form_progress import local_fit
from test_pilot_region_feedback import reject

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import pilot_form_progress as progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def selected_local_after_common_failure(tmp_path, monkeypatch):
    _, local = local_fit(tmp_path, monkeypatch)
    current = guided.next_action(local.study_directory, "adaptive_next_form", "guided-varifold")
    total = len(guided.record(local)["pilot_order"])
    for _ in range(total - 1):
        current = approve(run_batch(current, monkeypatch), "guided-varifold")
        current = guided.next_action(
            current.study_directory, "adaptive_next_form", "guided-varifold"
        )
    current = guided.next_action(
        current.study_directory, "adaptive_form_model_check", "guided-varifold"
    )
    current = reject(run_batch(current, monkeypatch), "guided-varifold")
    selected = feedback.select(
        current.study_directory, "guided-varifold", feedback.reference(local, "guided-varifold")
    )
    return local, selected


def test_selected_local_keeps_current_ledger_and_prepares_only_common_check(tmp_path, monkeypatch):
    local, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    old = progress.marker(current)
    before = {p: sha256_file(p) for p in local.study_directory.rglob("*") if p.is_file()}
    context = strategy.state(current)
    proposed = context["feedback"]["guided-varifold"]["starting_form_progress"]
    assert proposed["available"] and proposed["action"] == "form_model_check"
    assert proposed["shapes"] == len(guided.record(current)["pilot_order"])
    assert proposed["checked"] < proposed["total"] and not proposed["joint"]
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Navigation dispatched an optimizer"),
    )
    child = guided.next_action(current.study_directory, "adaptive_confirm_start", "guided-varifold")
    info = guided.record(child)
    assert info["target"] == proposed["target"] and info["goal"] == "form_model_check"
    assert progress.marker(child)["protocol"] == old["protocol"]
    assert progress.marker(child)["reviews"] == old["reviews"]
    assert not child.attachment_comparison.get("regional_objective")
    assert not child.attachment_comparison.get("refinement")
    assert not info["feedback"] and not child.visual_reviews
    assert (
        not {"baseline", "anchor", "regional_recipe", "regional_continuation"}
        & info["strategy"].keys()
    )
    assert child.candidates[0].attempts == 0 and child.attachment_comparison["iterations"] == 120
    assert (
        "initial_momenta"
        not in load_config(child.candidates[0].config_path)["model"]["deformation"]
    )
    assert all(sha256_file(p) == digest for p, digest in before.items())
    assert (
        study.load_reference_calibration_study(current.study_directory).visual_reviews[
            "guided-varifold"
        ]
        is False
    )
    assert guided._approved_record(local, "guided-varifold") not in info["approved"]


def test_unapproved_selected_local_cannot_advance_or_create_a_child(tmp_path, monkeypatch):
    _, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    # The rejected current result is inspected and selectable, but not approved.
    current = feedback.select(
        current.study_directory, "guided-varifold", feedback.reference(current, "guided-varifold")
    )
    before = set(current.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match="approve"):
        guided.next_action(current.study_directory, "adaptive_confirm_start", "guided-varifold")
    assert set(current.study_directory.parent.iterdir()) == before


def test_selected_progress_button_names_target_and_dispatches_without_fitting(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop.guided_feedback import render_starting_fits

    _, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    calls = []
    root._start_pilot = lambda **kwargs: calls.append(kwargs)
    data = strategy.state(current)["feedback"]["guided-varifold"]
    expected = data["starting_form_progress"]["label"]
    render_starting_fits(root, current, "guided-varifold", layout, data)
    button = next(b for b in root.findChildren(QPushButton) if b.text() == expected)
    assert data["starting_form_progress"]["target"] in button.text()
    assert button.isEnabled()
    button.click()
    assert calls == [
        dict(adaptive=False, guided_action=("adaptive_confirm_start", "guided-varifold", None))
    ]
    root.close()
    app.processEvents()
