import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage

from diffeoforge.desktop import mesh_view as mv
from diffeoforge.desktop.morphospace_3d import MorphospaceCanvas
from diffeoforge.desktop.visualization_panel import VisualizationPanel
from diffeoforge.mesh import sha256_file
from diffeoforge.pca_media import _archive_gallery, _write_gallery


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def wait_for(qapp, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_warm_preview_shows_intermediate_input_without_waiting_for_drag_to_end(qapp, monkeypatch):
    from diffeoforge.analysis import pca_media_rendering as rendering

    started, release = threading.Event(), threading.Event()
    contexts, calls = [], []

    class Renderer:
        def __init__(self, size):
            contexts.append(threading.get_ident())

        def render(self, mesh, bounds, view):
            calls.append(np.array(view[1]))
            if len(calls) == 1:
                started.set()
                assert release.wait(5)
            return Image.new("RGBA", (84, 72), "teal")

        def close(self):
            contexts.append(threading.get_ident())

    monkeypatch.setattr(rendering, "SurfaceRenderer", Renderer)
    monkeypatch.setattr(rendering, "with_points", lambda *args: object())
    session = mv.PreviewSession((None, np.zeros((2, 4, 3)), None, None))
    try:
        session.request(np.eye(3), 0)
        assert started.wait(5)
        for angle in range(100):
            session.request(mv.turn_view(np.eye(3), angle), 1)
        release.set()
        wait_for(qapp, lambda: len(calls) == 2)
        frame = session.take()
        assert frame[:2] == (101, 1) and not frame[2].isNull()
        np.testing.assert_array_equal(calls[-1], mv.turn_view(np.eye(3), 99)[2])
        assert len(contexts) == 1  # Warm renderer reused, pending input is bounded.
        session.request(np.eye(3), 0)
        wait_for(qapp, lambda: len(calls) == 3)
        assert session.take()[1] == 0
    finally:
        session.close()
        session.future.result(timeout=5)
    assert len(contexts) == 2 and contexts[0] == contexts[1]


def test_dialog_coalesces_continuous_events_and_close_never_waits_for_renderer(qapp, monkeypatch):
    class Session:
        def __init__(self, data):
            self.requests, self.closed = [], False

        def request(self, rotation, index):
            self.requests.append((rotation, index))

        def take(self):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(mv, "PreviewSession", Session)
    controller = mv.MeshViewController()
    controller.data = (None, None, None, np.zeros((2, 3)))
    dialog = mv.MeshViewDialog(controller, ["A", "B"])
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        dialog._turn(1, 0)
        qapp.processEvents()
        time.sleep(0.003)
    assert len(dialog.session.requests) >= 3  # A restartable debounce would starve here.
    dialog.reject()
    assert dialog.session.closed and not dialog.frames.isActive()
    assert not controller.selected


def test_full_media_apply_is_atomic_and_cancel_does_not_save_view(qapp, tmp_path, monkeypatch):
    controller = mv.MeshViewController()
    controller.all_media = True
    controller.directory = tmp_path / "base"
    controller.path, controller.identity = tmp_path / "views.json", "one"
    controller.data = (None, np.zeros((2, 4, 3)), None, np.zeros((2, 3)))
    release = threading.Event()
    published = []

    def render(directory, rotation, name, cancelled, progress):
        assert release.wait(5)
        if cancelled.is_set():
            raise RuntimeError("cancelled")
        return [QImage(40, 30, QImage.Format.Format_RGB32)] * 2, tmp_path / name

    monkeypatch.setattr(mv, "render_all_media", render)
    controller.media_changed.connect(published.append)
    controller.request(np.eye(3), name="Chosen")
    assert not published and not controller.path.exists()
    release.set()
    wait_for(qapp, lambda: controller.future is None)
    assert published == [tmp_path / "Chosen"]
    saved = controller.path.read_bytes()
    controller.request(np.eye(3), name="Discard")
    controller.clear()
    qapp.processEvents()
    assert controller.path.read_bytes() == saved and len(published) == 1


def test_large_3d_glyph_hover_uses_visible_pixels_and_frontmost_specimen(qapp):
    canvas = MorphospaceCanvas()
    canvas.resize(800, 600)
    scores = np.zeros((2, 3))
    canvas.set_data(
        (scores, np.zeros((2, 3, 3)), np.array([[0, 1, 2]]), [0.6, 0.3, 0.1]),
        ["specimen-A", "specimen-B"],
    )
    canvas.glyph_size = 0.2
    image = QImage(84, 72, QImage.Format.Format_RGBA8888)
    image.fill(QColor("teal"))
    transparent = QImage(image)
    transparent.fill(Qt.GlobalColor.transparent)
    canvas.set_images([image, transparent])
    _, scene = canvas._scene()
    position = canvas._project(scores, scene)[0]
    point = QPointF(float(position[0] + 60), float(position[1]))
    assert canvas._pick(point) == 0  # Well outside the old 25px centre-only threshold.
    assert canvas._label(0).startswith("specimen-A")
    canvas.set_images([image, image])
    assert canvas._pick(point) == 1
    assert canvas._pick(QPointF(0, 0)) == -1


def test_all_pca_sd_and_heatmaps_keep_individual_selection_and_hover_ids(qapp, tmp_path):
    panel = VisualizationPanel()
    panel._items = [{"id": 1, "scores": [-1.0, 2.0, 3.0]}, {"id": 2, "scores": [1.0, -2.0, -3.0]}]
    panel._specimen_labels = ["specimen-A", "specimen-B"]
    from PySide6.QtGui import QPixmap

    image = QPixmap(80, 60)
    image.fill(QColor("teal"))
    panel._thumbnails = {1: image, 2: image}
    panel.plot_combo.setCurrentIndex(3)
    glyphs = [item for item in panel.plot_view.scene().items() if item.data(0)]
    assert len(glyphs) == 6
    assert sum(item.data(0).startswith("specimen-A") for item in glyphs) == 3
    for combo, view in ((panel.sd_combo, panel.sd_view), (panel.heat_combo, panel.heat_view)):
        for i in range(3):
            path = tmp_path / f"{i}.png"
            Image.new("RGB", (420, 300), (30 * i, 100, 130)).save(path)
            combo.addItem(f"PC{i + 1}", path)
        combo.addItem("All", "all")
        combo.setCurrentIndex(3)
        assert len([item for item in view.scene().items() if hasattr(item, "pixmap")]) == 3
        combo.setCurrentIndex(1)
        assert len(view.scene().items()) == 1
    panel.all_heatmaps_button.setEnabled(True)
    panel.all_heatmaps_button.click()
    assert panel.heat_combo.currentData() == "all"
    assert len([item for item in panel.heat_view.scene().items()
                if hasattr(item, "pixmap")]) == 3
    panel.close()


def test_offline_gallery_hover_embeds_specimen_labels_with_exact_scores(tmp_path):
    gallery = tmp_path / "PCA-Gallery"
    (gallery / "thumbnails").mkdir(parents=True)
    scores = np.array([[-1.0, 2.0, 3.0], [1.0, -2.0, -3.0]])
    for i in (1, 2):
        Image.new("RGBA", (84, 72), "teal").save(gallery / f"thumbnails/{i}.png")
    _write_gallery(
        gallery,
        [],
        [],
        SimpleNamespace(
            scores=scores,
            explained_variance_ratio=np.array([0.6, 0.3, 0.1]),
            sample_labels=["RATIOS", "DATA</script>"],
        ),
    )
    items = json.loads((gallery / "mesh-pca.json").read_text())
    assert [item["label"] for item in items] == ["RATIOS", "DATA</script>"]
    np.testing.assert_array_equal([item["scores"] for item in items], scores)
    assert "canvas.title=item.label" in (gallery / "mesh-pca.html").read_text()
    page = (gallery / "mesh-pca.html").read_text()
    embedded = page.split("const items=", 1)[1].split(",ratios=", 1)[0]
    assert [item["label"] for item in json.loads(embedded)] == ["RATIOS", "DATA</script>"]
    assert "DATA</script>" not in page
    _archive_gallery(gallery, tmp_path / "export.zip")


def test_method_view_images_follow_specimen_order_and_cannot_cross_runs(qapp, tmp_path):
    from diffeoforge.desktop.method_results import MethodResultsPanel

    panel = MethodResultsPanel()
    red = QImage(40, 30, QImage.Format.Format_RGB32)
    red.fill(QColor("red"))
    blue = QImage(red)
    blue.fill(QColor("blue"))
    applied = []
    viewer = SimpleNamespace(
        labels=["B", "A"], set_images=applied.append, canvas=SimpleNamespace(mesh_view_label="")
    )
    dialog = SimpleNamespace(viewer=viewer, review=SimpleNamespace(run_directory=tmp_path / "one"))
    panel.set_mesh_images(["A", "B"], [red, blue], "Chosen", tmp_path / "two")
    panel.apply_mesh_images(dialog)
    assert not applied
    panel.set_mesh_images(["A", "B"], [red, blue], "Chosen", tmp_path / "one")
    panel.apply_mesh_images(dialog)
    assert applied == [[blue, red]] and viewer.canvas.mesh_view_label == "Chosen"


def test_combined_video_export_has_shared_frames_and_preserves_verified_sources(qapp, tmp_path):
    import imageio.v2 as imageio

    from diffeoforge.desktop.media_comparison import VideoComparison
    from diffeoforge.desktop.video_export import export_video_comparison

    entries = []
    for i, color in enumerate(([220, 30, 20], [20, 30, 220])):
        path = tmp_path / f"PC{i + 1}.mp4"
        with imageio.get_writer(path, fps=12, codec="libx264", macro_block_size=1) as writer:
            for frame in range(6):
                pixels = np.full((48, 64, 3), color, dtype=np.uint8)
                pixels[frame : frame + 4, :8] = 255
                writer.append_data(pixels)
        entries.append((path, {"bytes": path.stat().st_size, "sha256": sha256_file(path)}))
    comparison = VideoComparison()
    comparison.load([(path.stem, path) for path, _ in entries])
    assert len(comparison.players) == 2
    wait_for(qapp, lambda: all(player.duration() > 0 for player in comparison.players))
    comparison.toggle()
    wait_for(qapp, lambda: all(player.position() > 200 for player in comparison.players))
    comparison.pause()
    comparison.seek(100)
    assert [player.position() for player in comparison.players] == [100, 100]
    comparison.clear()
    assert not comparison.players and not comparison.clock.isActive()
    target = export_video_comparison(tmp_path / "all.mp4", entries)
    with imageio.get_reader(target) as reader:
        assert reader.count_frames() == 6
        frame = reader.get_data(3)
        assert frame.shape == (456, 1280, 3)
        assert frame[50, 300, 0] > frame[50, 300, 2]
        assert frame[50, 940, 2] > frame[50, 940, 0]
    before = target.read_bytes()
    entries[0][0].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        export_video_comparison(target, entries)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".*.mp4"))
