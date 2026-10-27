"""Explanatory controls preserve choices; R handoffs stay off the GUI thread."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

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


def test_alignment_help_covers_every_real_size_policy_and_reflections():
    from diffeoforge.desktop.workflow_guidance import alignment_description
    from diffeoforge.mesh_scaling_contract import MeshScalingMode

    for mode in (MeshScalingMode.PAMS_AREA_WEIGHTED, MeshScalingMode.PAMS_VERTEX_CENTROID,
                 MeshScalingMode.PRESERVE_SIZE, MeshScalingMode.LANDMARK_CENTROID_LEGACY):
        text = alignment_description(mode, enabled=True, reflections=False)
        assert "Reflections are off" in text
        assert "selected size treatment" not in text
        assert "Reflections are allowed" in alignment_description(
            mode, enabled=True, reflections=True)
    assert "No new landmark alignment" in alignment_description(
        MeshScalingMode.PRESERVE_SIZE, enabled=False, reflections=False)


def test_method_help_preserves_real_preset_selection(qapp):
    from diffeoforge.analysis.method_labels import shape_method_description
    from diffeoforge.desktop.widgets import _ShapeSpaceComparisonDialog
    from diffeoforge.reference_shape_space_comparison import ALL_METHOD_IDS, QUICK_METHOD_IDS

    dialog = _ShapeSpaceComparisonDialog(24)
    assert dialog.method_ids == QUICK_METHOD_IDS
    assert all("Read the saved method" not in shape_method_description(m) for m in ALL_METHOD_IDS)
    dialog._checks["diffusion_map"].setChecked(True)
    assert dialog.method_ids == (*QUICK_METHOD_IDS, "diffusion_map")
    dialog.reject()


def test_visualization_help_and_export_follow_selected_view(qapp):
    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    for index, text in enumerate(("2D scores:", "PC shapes:", "Maps:", "Movies:", "3D scores:")):
        panel.tabs.setCurrentIndex(index)
        assert panel.view_description.text().startswith(text)
        assert panel.mesh_size.isHidden() is (index != 0)
    observed = []
    panel.r_export_requested.connect(lambda: observed.append(True))
    panel.export_r.click()
    assert observed == [True] and panel.directory is None
    panel.clear()
    panel.close()


def test_r_dialog_disables_unavailable_sources_and_shows_input_roles(qapp, tmp_path):
    from diffeoforge.desktop.r_export_dialog import RExportDialog

    empty = RExportDialog()
    assert not empty.export_button.isEnabled()
    empty.reject()
    meshes = tuple(tmp_path / name for name in ("template.vtk", "one.vtk", "two.vtk"))
    dialog = RExportDialog(landmarks=tmp_path / "landmarks.csv", meshes=meshes)
    assert dialog.mode.currentData() == "geomorph" and dialog.export_button.isEnabled()
    assert "2 subjects" in dialog.source.text()
    assert not dialog.mode.model().item(0).isEnabled()
    dialog.reject()


def test_r_export_keeps_event_loop_live_and_refuses_duplicate_start(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    from diffeoforge.desktop import r_export_dialog as module

    gate, entered = threading.Event(), threading.Event()
    calls, ticks = [], []

    def export(review, target):
        calls.append(threading.get_ident())
        entered.set()
        assert gate.wait(5)
        return target

    monkeypatch.setattr(module, "export_pca_to_r", export)
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        lambda *args: (str(tmp_path / "data.zip"), "ZIP (*.zip)"))
    dialog = module.RExportDialog(review=SimpleNamespace(
        project_name="Synthetic", pca_method_label="Saved method"))
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        dialog._export()
        assert entered.wait(1)
        dialog._export()
        deadline = time.monotonic()+.1
        while time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.005)
        assert ticks and len(calls) == 1 and calls[0] != threading.get_ident()
        dialog.reject()
        assert dialog.future is not None
    finally:
        gate.set()
        dialog.future.result(timeout=5)
        dialog._finished()
        timer.stop()
        dialog.reject()


def test_template_help_does_not_start_analysis_or_change_selection(qapp, tmp_path):
    from PySide6.QtWidgets import QLineEdit, QWidget

    from diffeoforge.desktop.template_suggestion import TemplateSuggestionPanel

    owner = QWidget()
    owner._worker = None
    owner.mesh_edit = QLineEdit(str(tmp_path))
    owner.template_edit = QLineEdit("chosen.vtk")
    owner.pattern_edit = QLineEdit("*.vtk")
    panel = TemplateSuggestionPanel(owner)
    assert panel.result is None and owner.template_edit.text() == "chosen.vtk"
    assert panel.loader._active is None
    panel.close()
    owner.close()


def test_2d_axis_padding_preserves_scores_and_does_not_jitter_coincident_samples(qapp):
    from PySide6.QtGui import QPixmap

    from diffeoforge.desktop.visualization_panel import VisualizationPanel

    panel = VisualizationPanel()
    data = [(-2., 1., 0.), (0., 1., 0.), (2., 1., 0.), (2., 1., 0.)]
    panel._items = [{"id": i+1, "scores": list(v)} for i, v in enumerate(data)]
    panel._thumbnails = {i+1: QPixmap(16, 16) for i in range(len(data))}
    panel._show_plot()
    glyphs = sorted((i for i in panel.plot_view.scene().items() if i.data(0)),
                    key=lambda i: i.toolTip())
    positions = [i.pos() for i in glyphs]
    assert 0 < positions[0].x() < positions[-1].x() < 1000
    assert positions[1].x() == pytest.approx((positions[0].x()+positions[2].x())/2)
    assert all(p.y() == pytest.approx(350.) for p in positions)
    assert positions[2] == positions[3]
    assert [item["scores"] for item in panel._items] == [list(v) for v in data]
    panel.clear()
    panel.close()


def test_all_three_main_window_export_buttons_pass_explicit_sources(qapp, tmp_path, monkeypatch):
    from diffeoforge.desktop import r_export_dialog, widgets

    queued, opened = [], []
    monkeypatch.setattr(widgets.ActivityPool, "start", lambda self, worker: queued.append(worker))

    class Dialog:
        def __init__(self, parent, **options):
            opened.append(options)

        def exec(self):
            return 0

    monkeypatch.setattr(r_export_dialog, "RExportDialog", Dialog)
    window = widgets.DiffeoForgeWindow(recording_allowed=False)
    meshes = Path(__file__).parents[1] / "examples/synthetic/meshes"
    window.mesh_edit.setText(str(meshes))
    window.template_edit.setText(str(meshes / "template.vtk"))
    window.landmarks_edit.setText(str(tmp_path / "landmarks.csv"))
    window.units_combo.setCurrentIndex(window.units_combo.findData("millimeter"))
    window.export_r_landmarks_button.click()
    assert opened[-1]["review"] is None
    assert opened[-1]["meshes"][0].name == "template.vtk"
    assert len(opened[-1]["meshes"]) == 6 and opened[-1]["unit"] == "millimeter"
    review = object()
    window._result_review = review
    window.export_r_results_button.click()
    window.visualization_panel.export_r.click()
    assert len(opened) == 3 and all(o["review"] is review for o in opened[1:])
    window._result_review = None
    window.close()
    qapp.processEvents()
