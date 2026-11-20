import threading

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor, QImage

from diffeoforge.desktop.appearance import (
    Appearance,
    AppearanceController,
    _contrast,
    contrast_text,
    readable_accent,
    themed_style,
)
from diffeoforge.desktop.media_export import export_media
from diffeoforge.desktop.morphospace_3d import MorphospaceCanvas, load_geometry
from diffeoforge.desktop.surface_rendering import render_surface_scene
from diffeoforge.mesh import sha256_file


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_theme_and_arbitrary_accent_contrast():
    for color, foreground in [("#ffffff", "#000000"), ("#000000", "#ffffff")]:
        assert contrast_text(QColor(color)) == foreground
        style = themed_style(
            "QWidget {background: #ffffff; color: #17252a;}", Appearance("dark", color)
        )
        assert "+QPushButton" not in style
        assert f"color: {foreground}" in style
    with pytest.raises(ValueError):
        Appearance("dark", "invalid")


def test_appearance_persists_and_keeps_focus_links_legible(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    settings = QSettings(str(tmp_path / "appearance.ini"), QSettings.Format.IniFormat)
    first, second = QWidget(), QWidget()
    one = AppearanceController(first, "QWidget {color: #17252a;}", settings)
    selected = Appearance("dark", "#ffff00")
    one.apply(selected, save=True)
    two = AppearanceController(second, "QWidget {color: #17252a;}", settings)
    assert two.current == selected
    for dark in (False, True):
        for color in ("#ffff00", "#ffffff", "#000000", "#0000ff", "#ef017a"):
            assert (
                _contrast(
                    readable_accent(QColor(color), dark), QColor("#202832" if dark else "#ffffff")
                )
                >= 4.5
            )
    one.apply(Appearance())
    assert two.load() == selected  # Preview/reset without Save does not overwrite preferences.
    first.deleteLater()
    second.deleteLater()
    qapp.processEvents()


def test_individual_exports_decode_and_cannot_overwrite_source(tmp_path):
    image = QImage(90, 60, QImage.Format.Format_RGB32)
    image.fill(QColor("#237c69"))
    for suffix in ("png", "jpg"):
        path = export_media(tmp_path / f"view.{suffix}", image=image)
        assert QImage(str(path)).size() == image.size()
    protected = tmp_path / "result"
    protected.mkdir()
    with pytest.raises(ValueError, match="outside"):
        export_media(protected / "overwrite.png", image=image, protected=(protected,))
    video = tmp_path / "saved.mp4"
    video.write_bytes(b"sealed media")
    record = {"bytes": video.stat().st_size, "sha256": sha256_file(video)}
    assert (
        export_media(tmp_path / "copy.mp4", source=video, expected=record).read_bytes()
        == video.read_bytes()
    )
    video.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        export_media(tmp_path / "refused.mp4", source=video, expected=record)


def test_3d_uses_exact_scores_common_scale_and_camera(qapp, tmp_path):
    scores = np.array([[1.0, 2.0, 3.0], [5.0, 6.0, 7.0]])
    triangle = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    vertices = np.array([triangle, triangle * 2])
    path = tmp_path / "display.npz"
    np.savez(
        path, vertices=vertices, faces=np.array([[0, 1, 2]]), scores=scores, ratios=[0.5, 0.3, 0.1]
    )
    canvas = MorphospaceCanvas()
    canvas.resize(640, 480)
    canvas.set_data(load_geometry(path), ["A", "B"])
    _, scene = canvas._scene()
    placed = scene.layers[0].vertices.reshape(2, 3, 3)
    np.testing.assert_allclose((placed.min(1) + placed.max(1)) / 2, scores)
    assert np.ptp(placed[1, :, 0]) == pytest.approx(2 * np.ptp(placed[0, :, 0]))
    assert not render_surface_scene(scene, threading.Event()).isNull()
    canvas.yaw += 0.5
    _, rotated = canvas._scene()
    assert not np.array_equal(scene.rotation, rotated.rotation)
    np.testing.assert_array_equal(canvas.data[0], scores)
    canvas.cache.clear()
