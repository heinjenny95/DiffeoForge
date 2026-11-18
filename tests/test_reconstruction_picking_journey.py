"""Real mouse clicks follow the selected surface through overlay correction."""

from dataclasses import replace

import numpy as np
import pytest
from test_reconstruction_feedback import bridge

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from surface_frame_helpers import wait_for_frame

from diffeoforge.desktop.display_proxy import DisplayProxy
from diffeoforge.desktop.pilot_preview import load_pilot_preview
from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
from diffeoforge.desktop.region_marking_geometry import (
    RegionMarkingGeometry,
    load_region_marking_mesh,
)
from diffeoforge.mesh import sha256_file


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["reconstruction-click-journey"])


def _display_subset(model, faces):
    faces = np.asarray(faces, dtype=np.int64)
    edges = np.unique(np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, (2, 0)])),
                              axis=1), axis=0)
    proxy = DisplayProxy(np.asarray(model.vertices), faces, edges,
                         len(model.triangles), len(faces),
                         "bounded surface display subset")
    assert proxy.reduced
    return replace(model, display_proxy=proxy)


def _reduced(marking):
    # A real subset of the exact original faces. The centre remains an opening;
    # only the reconstruction has material there. Counts and coordinates are real.
    return RegionMarkingGeometry(_display_subset(marking.model, marking.model.triangles[::2]))


def _dialog(tmp_path, monkeypatch, application, *, reduced=True, fit_display_hole=False):
    original_path, fit_path, *_ = bridge(tmp_path)
    original = load_region_marking_mesh(original_path, sha256_file(original_path))
    fit = load_region_marking_mesh(fit_path, sha256_file(fit_path))
    if reduced:
        original = _reduced(original)
    fit_preview = load_pilot_preview(fit_path)
    assert fit_preview.edge_count > 0
    if fit_display_hole:
        centres = fit.model.vertices[fit.model.triangles].mean(axis=1)
        faces = fit.model.triangles[np.linalg.norm(centres, axis=1) > .45]
        fit_preview = _display_subset(fit_preview, faces)
    # Diagnosis has its own tests; clicking must not launch a distance worker.
    monkeypatch.setattr(RegionFeedbackDialog, "_queue_diagnosis", lambda self: None)
    dialog = RegionFeedbackDialog(original, fit_preview=fit_preview)
    dialog.show()
    wait_for_frame(application, lambda: dialog._fit_marking is not None, dialog.canvas)
    dialog.canvas.set_view_preset("front")
    return dialog, original, fit


def _click(application, dialog, *, pos=None):
    canvas = dialog.canvas
    wait_for_frame(application, lambda: canvas.picking_ready, canvas)
    if pos is None:
        pos = QPoint(canvas.width() // 2, canvas.height() // 2)
    exact = canvas.pick_at(QPointF(pos))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pos)
    application.processEvents()
    return exact


def _purple_centre_pixels(canvas):
    image = canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine() // 4, 4)
    cy, cx = image.height() // 2, image.width() // 2
    patch = pixels[cy-14:cy+15, cx-14:cx+15, :3].astype(np.int16)
    red, green, blue = patch[..., 0], patch[..., 1], patch[..., 2]
    return int(((red > green + 12) & (blue > red + 12)).sum())


@pytest.mark.parametrize("view,reduced,full_detail", [
    pytest.param("overlay", True, False, id="reduced-original-overlay-reco-only"),
    pytest.param("overlay", False, False, id="unreduced-overlay-reco-only"),
    pytest.param("fit", True, False, id="fit-only-reco-only"),
    pytest.param("overlay", True, True, id="full-detail-overlay-reco-only"),
])
def test_actual_click_on_extra_reconstruction_material_saves_exact_binding(
    tmp_path, monkeypatch, application, view, reduced, full_detail,
):
    dialog, original, fit = _dialog(tmp_path, monkeypatch, application, reduced=reduced)
    try:
        dialog.view.setCurrentIndex(dialog.view.findData(view))
        dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
        dialog.canvas.original_detail.setChecked(full_detail)
        if view == "overlay":
            assert dialog.canvas._overlay is dialog._fit_preview
            assert len(dialog._fit_preview.edges)
            wait_for_frame(application, lambda: dialog.canvas.picking_ready, dialog.canvas)
            assert _purple_centre_pixels(dialog.canvas) > 0
        centre = QPoint(dialog.canvas.width() // 2, dialog.canvas.height() // 2)
        assert original.pick((0, 0, 1), (0, 0, -1)) is None
        assert fit.pick((0, 0, 1), (0, 0, -1)) == pytest.approx((0, 0, 0))
        exact = _click(application, dialog, pos=centre)
        assert exact is not None
        assert len(dialog._rows) == 1
        row = dialog._rows[0]
        assert row["center"] == pytest.approx(exact, abs=1e-10)
        assert row["reconstruction"]["sha256"] == fit.model.sha256
        assert row["reconstruction"]["face_ids"]
        assert row["source_sha256"] == original.model.sha256
        assert original.count(row) == 0
        assert dialog.save.isEnabled()
        dialog.save.click()
        assert dialog.regions == [row]
        reopened = RegionFeedbackDialog(original, fit_preview=dialog._fit_preview,
                                        regions=dialog.regions)
        try:
            reopened.show()
            wait_for_frame(application, lambda: reopened._fit_marking is not None,
                           reopened.canvas)
            assert reopened._rows == [row] and reopened.save.isEnabled()
        finally:
            reopened.close()
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("tool", ["original-red", "original-green", "reconstruction-red"])
def test_selected_exact_surface_rejects_empty_space(tmp_path, monkeypatch, application, tool):
    dialog, _, _ = _dialog(tmp_path, monkeypatch, application)
    try:
        if tool == "reconstruction-red":
            dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
            pos = QPoint(5, dialog.canvas.height() // 2)
        else:
            if tool == "original-green":
                next(b for b in dialog.click_modes.buttons()
                     if b.text() == "Green · Keep unchanged").click()
            pos = None  # Exact original has a true opening at its centre.
        _click(application, dialog, pos=pos)
        assert dialog._rows == []
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("full_detail", [False, True])
def test_reconstruction_display_opening_does_not_accept_hidden_exact_material(
    tmp_path, monkeypatch, application, full_detail,
):
    dialog, _, fit = _dialog(tmp_path, monkeypatch, application, fit_display_hole=True)
    try:
        dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
        assert fit.pick((0, 0, 1), (0, 0, -1)) is not None
        dialog.canvas.original_detail.setChecked(full_detail)
        _click(application, dialog)
        assert dialog._rows == []
        assert "No active surface" in dialog.canvas._pick_error
    finally:
        dialog.close()
        application.processEvents()


def test_reconstruction_without_drawable_preview_cannot_accept_a_hidden_click(
    tmp_path, monkeypatch, application,
):
    original_path, fit_path, *_ = bridge(tmp_path)
    original = _reduced(load_region_marking_mesh(original_path, sha256_file(original_path)))
    fit = load_region_marking_mesh(fit_path, sha256_file(fit_path))
    assert fit.model.display_proxy is None and not hasattr(fit.model, "edges")
    monkeypatch.setattr(RegionFeedbackDialog, "_queue_diagnosis", lambda self: None)
    dialog = RegionFeedbackDialog(original, fit_preview=fit.model)
    try:
        dialog.show()
        wait_for_frame(application, lambda: dialog._fit_marking is not None, dialog.canvas)
        dialog.canvas.set_view_preset("front")
        dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
        _click(application, dialog)
        assert dialog._rows == []
        assert "active surface preview is not ready" in dialog.canvas._pick_error
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("tool", ["original-red", "original-green"])
def test_switch_from_reconstruction_does_not_keep_its_picker(
    tmp_path, monkeypatch, application, tool,
):
    from diffeoforge.desktop.landmark_3d_widget import _projection_pixels

    dialog, original, _ = _dialog(tmp_path, monkeypatch, application)
    try:
        dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("reconstruction"))
        _click(application, dialog)
        assert len(dialog._rows) == 1 and dialog._rows[0].get("reconstruction")
        if tool == "original-green":
            next(b for b in dialog.click_modes.buttons()
                 if b.text() == "Green · Keep unchanged").click()
        else:
            dialog.pick_surface.setCurrentIndex(dialog.pick_surface.findData("original"))
        assert dialog._active_surface() == "original"
        _click(application, dialog)
        assert len(dialog._rows) == 1  # The original's centre really is empty.

        # Choose a visible solid original patch. Full detail here avoids the
        # intentionally sparse test display subset's unrelated small openings.
        canvas = dialog.canvas
        canvas.original_detail.setChecked(True)
        factor = _projection_pixels(canvas.width(), canvas.height(), canvas.zoom)
        x = canvas.width() / 2 + .7 * factor / canvas._scale
        _click(application, dialog, pos=QPoint(round(x), canvas.height() // 2))
        assert len(dialog._rows) == 2
        row = dialog._rows[1]
        assert not row.get("reconstruction") and original.count(row) > 0
        assert row["purpose"] == ("fixed" if tool == "original-green" else "problem")
        dialog.save.click()
        assert dialog.regions == dialog._rows
    finally:
        dialog.close()
        application.processEvents()
