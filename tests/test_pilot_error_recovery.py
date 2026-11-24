"""Exercise failure, re-verification, and the exact selected-fit repair action."""

import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pilot_view_helpers import wait_pilot_view
from test_guided_feedback import attempted, decision
from test_guided_pilot import origin
from test_guided_working_fit import payload
from test_interactive_pilot import geometry_receipt
from test_reconstruction_material_lineage import chain as chain

from diffeoforge import guided_feedback as feedback
from diffeoforge import reference_guided_pilot as guided


def settle(app, dialog):
    deadline = time.monotonic() + 20
    while dialog._view_loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert not dialog._view_loading


def test_failed_verification_can_retry_after_reopen_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop import reference_calibration_dialog as ui

    app = QApplication.instance() or QApplication([])
    snapshot = guided.prepare(origin(tmp_path).study_directory)
    original = ui.prepare_pilot_view
    calls = []

    def fail_once(root, state):
        calls.append(root)
        if len(calls) == 1:
            raise ValueError("Saved subject identity changed")
        return original(root, state)

    monkeypatch.setattr(ui, "prepare_pilot_view", fail_once)
    dialog = ui.ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    monkeypatch.setattr(dialog, "_start", lambda: pytest.fail("Retry started a fit"))
    try:
        settle(app, dialog)
        assert "Saved subject identity changed" in dialog.operation_error.text()
        assert dialog.operation_error.isVisible() and dialog.status.isHidden()
        assert dialog.retry_view_button.isVisible() and dialog.retry_view_button.isEnabled()
        assert not dialog.start_button.isEnabled() and not dialog._thread_pool.indicator.tasks
        dialog.retry_view_button.click()
        wait_pilot_view(dialog)
        assert len(calls) == 2 and dialog._prepared_view.snapshot.study_directory == calls[-1]
        assert dialog.operation_error.isHidden() and dialog.retry_view_button.isHidden()
        assert dialog.content.isEnabled() and not dialog._thread_pool.indicator.tasks
    finally:
        dialog.close()


def test_material_failure_reopens_selected_marks_and_rechecks_on_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge import guided_strategy, result_report
    from diffeoforge.desktop import reference_calibration_dialog as ui
    from diffeoforge.desktop.mesh_preview import load_mesh_preview
    from diffeoforge.reconstruction_feedback import ReconstructionMaterialUnavailable, bind
    from diffeoforge.reference_calibration_study import STUDY_EVENTS

    app = QApplication.instance() or QApplication([])
    base, trial = attempted(tmp_path, monkeypatch)
    identifier = "guided-varifold"
    geometry_receipt(base, identifier, monkeypatch)
    reviewed = feedback.save_feedback(trial.study_directory, identifier,
                                      decision(base, trial, "worse"))
    editing = payload(base, trial)
    reference = editing["reference"]
    row = editing["problem_regions"][reference["target"]][0]
    output = next(c for c in base.candidates if c.candidate_id == identifier).run_directory
    from diffeoforge.mesh import sha256_file

    fixture_mesh = next((output / "output").glob("Fixture__Reconstruction*.vtk"))
    staged = fixture_mesh.with_name(
        f"Fixture__Reconstruction__surface__subject_{reference['target']}.vtk")
    staged.write_bytes(fixture_mesh.read_bytes())
    report = SimpleNamespace(manifest=dict(effective_config=dict(model=dict(object_id="surface"))),
                             inventory=[dict(path=staged.name, sha256=sha256_file(staged))])
    monkeypatch.setattr(result_report, "collect_run_report", lambda _root: report)
    fit = load_mesh_preview(staged)
    row["center"] = np.mean([fit.vertices[i] for i in fit.triangles[0]], axis=0).tolist()
    row["reconstruction"] = bind(row, fit)
    chosen = guided.next_action(reviewed.study_directory, "adaptive_working_start",
                                identifier, goal=editing)
    journal = chosen.study_directory / STUDY_EVENTS
    before = journal.read_bytes()
    dialog = ui.ReferenceCalibrationDialog(chosen.study_directory)
    dialog.show()
    wait_pilot_view(dialog)
    calls = []

    def edit(source, ref, *, require_selected):
        assert require_selected
        calls.append((source, ref))

    monkeypatch.setattr(dialog, "_open_guided_working_fit", edit)
    try:
        with monkeypatch.context() as stage:
            stage.setattr(ui, "prepare_pilot_view",
                          lambda *_a: pytest.fail("Rejected preparation reloaded the entire pilot"))
            dialog._worker = SimpleNamespace(guided_action=("adaptive_recover_start", identifier,
                                                             {"reference": reference}))
            dialog._failed("ReconstructionMaterialUnavailable: Changed material")
            assert dialog._worker is None and not dialog._view_loading
            assert dialog.operation_error.isVisible() and dialog.status.isHidden()
            assert dialog.next_step_button.text() == "Review marks on the selected starting fit…"
            dialog.next_step_button.click()
            assert calls == [(identifier, reference)]
    finally:
        dialog.close()

    def fail_proposals(*_args):
        raise ReconstructionMaterialUnavailable("Changed material during proposal preparation")

    monkeypatch.setattr(guided_strategy, "prepare_proposals", fail_proposals)
    reopened = ui.ReferenceCalibrationDialog(chosen.study_directory)
    reopened.show()
    try:
        settle(app, reopened)
        assert reopened._worker is None and reopened.status.isHidden()
        assert reopened.next_step_button.isEnabled() and reopened.next_step_button.isVisible()
        assert reopened.operation_error.isVisible() and reopened.retry_view_button.isVisible()
        monkeypatch.setattr(reopened, "_open_guided_working_fit", edit)
        reopened.next_step_button.click()
        assert calls == [(identifier, reference)] * 2
        assert journal.read_bytes() == before
    finally:
        reopened.close()


def test_editor_identifies_only_unmapped_mark_and_accepts_its_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_reconstruction_feedback import bridge

    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh
    from diffeoforge.mesh import sha256_file

    app = QApplication.instance() or QApplication([])
    a, b, _, _, row = bridge(tmp_path)
    original = load_region_marking_mesh(a, sha256_file(a))
    reconstruction = load_region_marking_mesh(b, sha256_file(b))
    green = {k: v for k, v in row.items() if k != "reconstruction"}
    green.update(purpose="fixed", symptom="unsure", center=[.65, .65, 0])
    stale = deepcopy(row)
    stale["reconstruction"]["topology_sha256"] = "a" * 64
    dialog = RegionFeedbackDialog(original, regions=[green, stale],
                                  fit_preview=reconstruction.model)
    try:
        dialog._fit_ready(reconstruction.model.sha256, reconstruction)
        assert not dialog.save.isEnabled()
        assert dialog.listing.item(1).text().startswith("B ·")
        assert "place again" in dialog.listing.item(1).text()
        assert "place again" not in dialog.listing.item(0).text()
        assert "Could not locate B" in dialog.status.text()
        dialog.listing.setCurrentRow(1)
        dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
        dialog.move.setChecked(True)
        dialog._picked([0, 0, 0])
        assert dialog.save.isEnabled() and dialog._rows[0] == green
        assert dialog._rows[1]["reconstruction"] == row["reconstruction"]
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("change_symptom", [False, True])
def test_mark_editor_keeps_exact_ancestral_faces_across_edits(chain, monkeypatch, change_symptom):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh
    from diffeoforge.mesh import sha256_file
    from diffeoforge.pilot_regions import EDIT_VERSION
    from diffeoforge.reconstruction_feedback import bind
    from diffeoforge.regional_fit import _save

    app = QApplication.instance() or QApplication([])
    source = chain["root"]["reference_source"]
    original = load_region_marking_mesh(Path(source["path"]), source["sha256"])
    moved_mesh = Path(source["path"]).with_name("moved-fit.vtk")
    _save(moved_mesh, chain["vertices"][-1] + [1., -1., 2.], chain["faces"][-1])
    fit = load_region_marking_mesh(moved_mesh, sha256_file(moved_mesh))
    evaluation = dict(chain["last"], endpoint={"path": str(moved_mesh), "sha256": fit.model.sha256})
    candidate = SimpleNamespace(metrics={"attachment_comparison": {"subjects": {
        "target": {"regional_quality": {"evaluation": evaluation}}}}})
    vertices, faces = chain["vertices"][0], chain["faces"][0]
    red = dict(version=EDIT_VERSION, source_sha256=original.model.sha256,
               space="original_mesh_coordinates", center=vertices[faces[0]].mean(0).tolist(),
               radius=.12, purpose="problem", symptom="distortion")
    red["reconstruction"] = bind(red, original.model)
    green = dict(red, center=vertices[faces[-1]].mean(0).tolist(),
                 purpose="fixed", symptom="unsure")
    del green["reconstruction"]
    dialog = RegionFeedbackDialog(original, regions=[red, green], fit_preview=fit.model,
                                  candidate=candidate, subject="target")
    try:
        deadline = time.monotonic() + 12
        while dialog._fit_marking is None and not dialog._fit_error and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.002)
        assert dialog._fit_marking is not None, dialog._fit_error
        expected = np.zeros(len(faces), dtype=bool)
        expected[red["reconstruction"]["face_ids"]] = True
        for mapping in chain["parents"]:
            expected = expected[mapping]
        mapped = dialog._fit_marking.material_faces(dialog._rows[0])
        np.testing.assert_array_equal(mapped, np.flatnonzero(expected))
        assert len(mapped) > len(red["reconstruction"]["face_ids"])
        assert "place again" not in dialog.listing.item(0).text() and dialog.save.isEnabled()
        centres = fit.model.vertices[fit.model.triangles[mapped]].mean(axis=1)
        assert np.any(np.all(centres == dialog.canvas._markers["A"], axis=1))
        assert not np.allclose(dialog.canvas._markers["A"], red["center"])
        assert len(dialog.canvas._surface_region[1]) == 1  # Only the green spatial brush.
        assert "one face in this area" in dialog.status.text()
        dialog.view.setCurrentIndex(dialog.view.findData("original"))
        assert "A" not in dialog.canvas._markers and "B" in dialog.canvas._markers
        dialog.view.setCurrentIndex(dialog.view.findData("overlay"))
        if change_symptom:
            dialog.listing.setCurrentRow(0)
            dialog.action.setCurrentIndex(dialog.action.findData("problem:unsure"))
        dialog.listing.setCurrentRow(1)
        dialog.move.setChecked(True)
        moved = vertices[faces[3]].mean(0).tolist()
        dialog._picked(moved)
        dialog._save()
        saved_red = dict(red, symptom="unsure") if change_symptom else red
        assert dialog.regions[0] == saved_red and dialog.regions[1]["center"] == moved
    finally:
        dialog.close()
