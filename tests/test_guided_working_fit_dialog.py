"""The editable working view uses a saved fit without writing a historical QC."""

from types import SimpleNamespace


def test_working_view_needs_settled_pair_and_saves_workspace_areas(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from test_full_review_geometry import model, wait

    from diffeoforge.desktop.guided_working_fit import viewer
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair

    app = QApplication.instance() or QApplication([])
    requests = []
    monkeypatch.setattr(PreviewMeshLoader, "request_paths",
                        lambda self, *a, **kw: requests.append((a, kw)))
    old, current = tmp_path / "saved", tmp_path / "current"
    original, fitted = old / "original.vtk", old / "reconstruction.vtk"
    pair = CalibrationQcPair("pair", "saved", original, fitted, True, "0" * 64, "0" * 64)
    candidate = SimpleNamespace(candidate_id="guided-varifold", run_directory=old,
                                status="completed", metrics=dict(invalid_face_count=0))
    ref = dict(directory=str(old), candidate_id=candidate.candidate_id, target=original.name)
    context = dict(reference=ref, target=original.name, label="Test 18 · saved fit",
                   problem_regions={}, cleared_region_subjects=[])
    dialog = viewer(None, current, SimpleNamespace(study_directory=old),
                    candidate, (pair,), {}, context)
    dialog.show()
    try:
        save = next(b for b in dialog.findChildren(QPushButton)
                    if b.text().startswith("Use this fit and save"))
        assert not save.isEnabled()
        assert dialog._preview_cache == current / "display-cache"
        assert "Selected starting fit" in dialog.findChild(QLabel, "title").text()
        dialog._pair_loaded(0, (model(original, True), model(fitted, True)))
        wait(app, lambda: dialog.canvas.comparison_ready and save.isEnabled())
        assert not dialog.review_recorded and not dialog.complete_button.isVisible()
        # Parent editor commits only in memory. The workspace action journals it later.
        rows = [dict(version="surface-region-v2", source_sha256="0" * 64,
                     space="original_mesh_coordinates", center=[0, 0, 0], radius=.3,
                     purpose="problem", symptom="detail"),
                dict(version="surface-region-v2", source_sha256="0" * 64,
                     space="original_mesh_coordinates", center=[.5, 0, 0], radius=.3,
                     purpose="fixed", symptom="detail")]
        dialog.problem_regions = {original.name: rows}
        save.click()
        assert dialog.working_decision == dict(reference=ref, inspected_subjects=[original.name],
            display_scopes={original.name: "preview"}, problem_regions={original.name: rows})
        assert not dialog.review_recorded and not old.exists() and not current.exists()
    finally:
        dialog.close()
        app.processEvents()
