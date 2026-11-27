"""Guard real template freshness and only offer saved visualization dimensions."""

import json
import shutil
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def qapp(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    return QApplication.instance() or QApplication([])


def wait(qapp, condition):
    end = time.monotonic()+10
    while not condition() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(.005)
    assert condition()


def template_panel(tmp_path, *, unreadable=False):
    from PySide6.QtWidgets import QLineEdit, QWidget

    from diffeoforge.desktop.template_suggestion import TemplateSuggestionPanel
    from diffeoforge.pilot_design import suggest_templates

    folder = tmp_path / "meshes"
    folder.mkdir()
    source = Path(__file__).parents[1] / "examples/synthetic/meshes"
    for name in ("template.vtk", "subject-01.vtk", "subject-02.vtk"):
        shutil.copyfile(source / name, folder / name)
    if unreadable:
        (folder / "needs-inspection.vtk").write_text("Not a valid surface\n")
    owner = QWidget()
    owner._worker = None
    owner.mesh_edit = QLineEdit(str(folder))
    owner.template_edit = QLineEdit("")
    owner.pattern_edit = QLineEdit("*.vtk")
    owner.project_edit = QLineEdit("")
    owner._adopt_template_format_pattern = lambda path: None
    panel = TemplateSuggestionPanel(owner)
    panel._loaded(panel._paths(), suggest_templates(panel._paths()))
    return owner, panel


def test_template_acceptance_checks_changed_non_candidate_mesh(qapp, tmp_path):
    owner, panel = template_panel(tmp_path)
    candidate = Path(panel.alternatives.currentData()["path"])
    other = next(p for p in panel._paths() if p != candidate)
    other.write_bytes(other.read_bytes()+b"\n")
    panel._apply()
    wait(qapp, lambda: not getattr(panel, "_busy", False))
    assert owner.template_edit.text() == ""
    assert "changed" in panel.status.text().lower()
    panel.close()
    owner.close()


@pytest.mark.parametrize("field,value", [("pattern_edit", "*.ply"),
                                        ("project_edit", "another-project")])
def test_template_context_change_retires_old_recommendation(qapp, tmp_path, field, value):
    owner, panel = template_panel(tmp_path)
    getattr(owner, field).setText(value)
    assert panel.result is None and panel.cancelled.is_set()
    assert not panel.use.isEnabled() and panel.alternatives.isHidden()
    assert owner.template_edit.text() == ""
    panel.close()
    owner.close()


def test_template_check_is_cancellable_off_thread_and_single_dispatch(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    from diffeoforge.desktop import template_suggestion as module

    owner, panel = template_panel(tmp_path)
    gate, entered = threading.Event(), threading.Event()
    calls, ticks = [], []
    original = module._verify_selection

    def delayed(*args):
        calls.append(threading.get_ident())
        entered.set()
        assert gate.wait(5)
        return original(*args)

    monkeypatch.setattr(module, "_verify_selection", delayed)
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        panel._apply()
        assert entered.wait(1)
        panel._apply()
        end = time.monotonic()+.1
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(.005)
        assert ticks and len(calls) == 1 and calls[0] != threading.get_ident()
        panel._cancel()
        assert panel.result is None and not panel._busy
    finally:
        gate.set()
        wait(qapp, lambda: panel.loader._active is None)
        timer.stop()
    assert owner.template_edit.text() == ""
    assert "cancelled" in panel.status.text()
    panel.close()
    owner.close()


def test_template_input_changed_after_hash_check_cannot_slip_into_selection(
    qapp, tmp_path, monkeypatch,
):
    from diffeoforge.desktop import template_suggestion as module

    owner, panel = template_panel(tmp_path)
    original = module._verify_selection
    path = panel._paths()[-1]

    def change_after_check(*args):
        result = original(*args)
        path.write_bytes(path.read_bytes()+b"\n")
        return result

    monkeypatch.setattr(module, "_verify_selection", change_after_check)
    panel._apply()
    wait(qapp, lambda: not panel._busy)
    assert owner.template_edit.text() == "" and "changed" in panel.status.text().lower()
    panel.close()
    owner.close()


def test_unreadable_inputs_stay_visible_and_content_bound(qapp, tmp_path):
    owner, panel = template_panel(tmp_path, unreadable=True)
    assert panel.result["unreadable_meshes"][0]["sha256"]
    assert "not excluded" in panel.status.text()
    bad = Path(panel.result["unreadable_meshes"][0]["path"])
    bad.write_bytes(bad.read_bytes()+b"\n")
    panel._apply()
    wait(qapp, lambda: not panel._busy)
    assert owner.template_edit.text() == "" and "changed" in panel.status.text().lower()
    panel.close()
    owner.close()


def test_r_export_explains_missing_sources_and_does_not_offer_a_missing_csv(qapp, tmp_path):
    from diffeoforge.desktop.r_export_dialog import RExportDialog

    paths = tuple(tmp_path / p for p in ("template.vtk", "one.vtk", "two.vtk"))
    dialog = RExportDialog(landmarks=tmp_path / "missing.csv", meshes=paths)
    assert not dialog.export_button.isEnabled()
    assert not dialog.mode.model().item(1).isEnabled()
    assert "reviewed atlas" in dialog.availability.text()
    assert "existing landmark CSV" in dialog.availability.text()
    assert "package" not in dialog.export_button.text()
    dialog.reject()


def test_all_pairs_respects_two_saved_axes_and_no_blank_export(qapp, tmp_path):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel._use_media(media(tmp_path, 2))
    panel.plot_combo.setCurrentIndex(3)
    glyphs = [i for i in panel.plot_view.scene().items() if i.data(0)]
    assert len(glyphs) == 2 and all("PC3" not in i.toolTip() for i in glyphs)
    assert panel.export_current.isEnabled()
    panel.clear()
    assert not panel.export_current.isEnabled() and not panel.export.isEnabled()
    assert "Open a reviewed" in panel.status.text()
    panel.close()


def test_failed_3d_loading_disables_export_and_releases_future(qapp, tmp_path):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel._use_media(media(tmp_path, 3))
    panel._records["morphospace-3d.npz"] = {}
    panel._available_views()
    panel.tabs.setCurrentIndex(4)
    assert not panel.export_current.isEnabled()
    panel.morphospace.future = Future()
    panel.morphospace.future.set_exception(ValueError("Synthetic geometry failure"))
    panel.morphospace._poll()
    assert panel.morphospace.future is None
    assert panel.morphospace.canvas.data is None and not panel.export_current.isEnabled()
    panel.clear()
    panel.close()


def test_completed_3d_loading_enables_only_the_current_ready_view(qapp, tmp_path):
    import numpy as np

    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel._use_media(media(tmp_path, 3))
    panel._records["morphospace-3d.npz"] = {}
    panel._available_views()
    panel.tabs.setCurrentIndex(4)
    assert not panel.export_current.isEnabled()
    panel.morphospace.labels = ["A", "B"]
    panel.morphospace.future = Future()
    panel.morphospace.future.set_result((
        np.array([[-1., 2., -.5], [1., -2., .5]]),
        np.array([[[0., 0, 0], [1., 0, 0], [0., 1, 0]]] * 2),
        np.array([[0, 1, 2]]), np.array([.6, .3, .1]),
    ))
    panel.morphospace._poll()
    assert panel.morphospace.future is None and panel.export_current.isEnabled()
    panel._view_busy(True)
    assert not panel.export_current.isEnabled()
    panel._view_busy(False)
    assert panel.export_current.isEnabled()
    panel.clear()
    panel.close()


def test_new_analysis_cannot_apply_the_previous_result(qapp, tmp_path, monkeypatch):
    owner, panel = template_panel(tmp_path)
    monkeypatch.setattr(panel.loader, "request_operation", lambda *args: None)
    panel._suggest()
    assert panel.result is None
    assert not panel.use.isEnabled() and not panel.preview.isEnabled()
    panel.close()
    owner.close()


def media(tmp_path, components):
    from test_desktop_v141_mesh_views import fixture_media

    from diffeoforge.mesh import sha256_file

    directory, *_ = fixture_media(tmp_path, components=components)
    path = directory / "media.json"
    metadata = json.loads(path.read_text())
    archive = directory / "PCA-Gallery.zip"
    metadata["files"].append({"path": archive.name, "bytes": archive.stat().st_size,
                              "sha256": sha256_file(archive)})
    metadata["pca_method"] = "LDDMM-metric tangent PCA"
    path.write_text(json.dumps(metadata))
    return directory


def test_two_axis_media_disables_pc3_and_missing_media(qapp, tmp_path):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel._use_media(media(tmp_path, 2))
    index = next(i for i in range(panel.plot_combo.count())
                 if tuple(panel.plot_combo.itemData(i) or ()) == (0, 2))
    item = panel.plot_combo.model().item(index)
    assert not item.isEnabled()
    assert not panel.tabs.isTabEnabled(1)  # No SD images were exported.
    assert not panel.tabs.isTabEnabled(4)  # No third saved coordinate / 3D geometry.
    panel.clear()
    panel.close()


def test_single_axis_media_shows_exact_scores_without_fabricating_pc2(qapp, tmp_path):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    panel._use_media(media(tmp_path, 1))
    glyphs = [item for item in panel.plot_view.scene().items() if item.data(0)]
    assert len(glyphs) == 2
    assert tuple(panel.plot_combo.currentData()) == (0, None)
    assert all("PC2" not in item.toolTip() for item in glyphs)
    panel.clear()
    panel.close()
