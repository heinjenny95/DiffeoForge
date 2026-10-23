"""No native fits: nested-field algebra and the owner's exhausted recovery route."""

import math

import numpy as np
import pytest
from test_guided_feedback import decision
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial
from test_pilot_region_feedback import reject

from diffeoforge import guided_feedback, guided_strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import read_deformetrica_momenta


def exhausted(tmp_path, monkeypatch):
    base = reject(reject(run_batch(initial(tmp_path), monkeypatch), "guided-current"),
                  "guided-varifold")
    child = base
    for goal in ("detail", "weight", "local_motion"):
        child = guided.next_action(child.study_directory, "adaptive_recover", "guided-varifold",
                                   goal="goal:" + goal)
        child = run_batch(child, monkeypatch)
        child = guided_feedback.save_feedback(child.study_directory, "guided-varifold",
                                              decision(base, child, "same"))
    return base, child


def test_exhausted_route_prepares_nested_density_and_retains_initial_velocity(
    tmp_path, monkeypatch
):
    base, child = exhausted(tmp_path, monkeypatch)
    old_controls = np.loadtxt(base.study_directory / base.attachment_comparison["controls"]["copy"])
    proposal = guided_strategy.trial_proposal(child, "guided-varifold", "detail")
    assert proposal["available"] and proposal["goal"] == "density"
    assert proposal["initialization"] == "nested"
    retained = guided_feedback.reference(base, "guided-varifold")
    assert proposal["anchor"] == retained
    protected = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    seed = guided.next_action(child.study_directory, "adaptive_recover", "guided-varifold",
                             goal="detail")
    cfg = load_config(seed.candidates[0].config_path)
    new = np.loadtxt(cfg["model"]["deformation"]["initial_control_points"])
    weights = read_deformetrica_momenta(
        cfg["model"]["deformation"]["initial_momenta"], allow_singleton=True)
    record = seed.attachment_comparison["refinement"]
    old_weights = read_deformetrica_momenta(seed.study_directory / record["source_momenta"]["copy"],
                                          allow_singleton=True)
    assert record["initialization"] == "nested"
    assert len(new) == math.ceil(len(old_controls) * 1.5)
    assert np.array_equal(new[:len(old_controls)], old_controls)
    assert np.array_equal(weights[:, :len(old_controls)], old_weights)
    assert not weights[:, len(old_controls):].any()
    sample = np.random.default_rng(9).normal(size=(30, 3))
    width = cfg["model"]["deformation"]["kernel_width"]
    def velocity(points, momenta):
        kernel = np.exp(-np.sum((sample[:, None] - points[None]) ** 2, axis=2) / width ** 2)
        return kernel @ momenta[0]
    np.testing.assert_allclose(velocity(new, weights), velocity(old_controls, old_weights),
                               rtol=1e-14, atol=1e-14)
    assert seed.plan.pilot_subject_count == 1 and seed.candidates[0].attempts == 0
    assert not seed.visual_reviews
    assert all(sha256_file(p) == digest for p, digest in protected.items())
    assert study.load_reference_calibration_study(seed.study_directory)
    completed = approve(run_batch(seed, monkeypatch))
    next_form = guided.next_action(completed.study_directory, "adaptive_confirm", "guided-varifold")
    assert next_form.attachment_comparison["controls"]["sha256"] == sha256_file(
        seed.study_directory / seed.attachment_comparison["controls"]["copy"])
    assert next_form.plan.effective_values == seed.plan.effective_values
    assert "initial_momenta" not in load_config(next_form.candidates[0].config_path)["model"][
        "deformation"]
    while guided.record(next_form)["phase"] != "joint":
        next_form = approve(run_batch(next_form, monkeypatch))
        next_form = guided.next_action(next_form.study_directory, "adaptive_confirm",
                                       "guided-varifold")
    assert next_form.attachment_comparison["controls"]["sha256"] == seed.attachment_comparison[
        "controls"]["sha256"]
    assert next_form.plan.effective_values == seed.plan.effective_values


def test_unsuitable_density_exposes_diagnostics_not_a_stale_disabled_action(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.info_disclosure import InfoDisclosure
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    base, child = exhausted(tmp_path, monkeypatch)
    child = guided.next_action(child.study_directory, "adaptive_recover", "guided-varifold",
                               goal="detail")
    child = run_batch(child, monkeypatch)
    child = guided_feedback.save_feedback(child.study_directory, "guided-varifold",
                                          decision(base, child, "same"))
    plan = guided_strategy.trial_proposal(child, "guided-varifold", "detail")
    assert not plan["available"]
    dialog = ReferenceCalibrationDialog(child.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        assert not any(b.isVisible() and "prepare 1 trial" in b.text()
                       for b in dialog.content.findChildren(QPushButton))
        diagnostic = next(d for d in dialog.findChildren(InfoDisclosure)
                          if d.title == "Saved attempts and input checks")
        assert diagnostic.toggle_button.isChecked()
        assert diagnostic.panel.isVisible()
        assert any("control points" in x.text() for x in diagnostic.findChildren(QLabel))
        other = next(b for b in dialog.content.findChildren(QPushButton)
                     if b.text() == "Inspect saved fit with the other method")
        assert other.isEnabled()
        calls = []
        monkeypatch.setattr(dialog, "_open_guided_saved_fit", calls.append)
        other.click()
        assert calls and calls[0]["method"] == "current"
        queued = []
        monkeypatch.setattr(dialog._viewer_preparation, "request_operation",
                            lambda key, function: queued.append((key, function)))
        source = next(b for b in diagnostic.findChildren(QPushButton)
                      if b.text().startswith("Inspect original template alignment"))
        before = {p: sha256_file(p) for p in child.study_directory.rglob("*") if p.is_file()}
        source.click()
        key, prepare = queued.pop()
        parent, candidate, pairs = prepare()
        assert key[0] == "guided-inputs" and len(pairs) == 1
        assert pairs[0].reconstruction_path.parent.name == "template"
        assert pairs[0].original_path.name == guided.record(base)["target"]
        assert all(sha256_file(p) == digest for p, digest in before.items())
    finally:
        dialog.close()
        app.processEvents()


def test_density_rejects_tampered_appended_momentum(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:density")
    cfg = load_config(child.candidates[0].config_path)
    with open(cfg["model"]["deformation"]["initial_momenta"], "a") as file:
        file.write("1 1 1\n")
    with pytest.raises(ValueError, match="field bytes changed"):
        study.load_reference_calibration_study(child.study_directory)
