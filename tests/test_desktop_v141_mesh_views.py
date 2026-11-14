import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor, QImage

from diffeoforge.desktop import mesh_view as mv
from diffeoforge.desktop.mesh_view_export import export_oriented_gallery
from diffeoforge.desktop.morphospace_3d import MorphospaceCanvas
from diffeoforge.mesh import sha256_file
from diffeoforge.pca_media import _archive_gallery, _write_gallery


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def record(path, name=None):
    return {"path": name or str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def fixture_media(tmp_path, components=3):
    root, media = tmp_path / "run", tmp_path / "visualizations" / "media"
    root.mkdir()
    gallery = media / "PCA-Gallery"
    (gallery / "thumbnails").mkdir(parents=True)
    (gallery / "figures").mkdir()
    (gallery / "videos").mkdir()
    sources = []
    for index, label in enumerate(("A", "B"), 1):
        mesh = root / f"Atlas__Reconstruction__shape__subject_{label}.vtk"
        mesh.write_text(
            "# vtk DataFile Version 3.0\nAsymmetric display fixture\nASCII\n"
            "DATASET POLYDATA\nPOINTS 4 double\n"
            f"0 0 0\n{index * 2} 0 0\n0 1 0\n0.2 0.3 0.8\n"
            "POLYGONS 4 16\n3 0 2 1\n3 0 1 3\n3 1 2 3\n3 2 0 3\n"
        )
        sources.append(record(mesh))
        Image.new("RGBA", (84, 72), (20, 100, 130, 255)).save(gallery / f"thumbnails/{index}.png")
    scores = np.array([[-1.25, 2, -0.5], [1.25, -2, 0.5]])[:, :components]
    ratios = np.array([0.6, 0.3, 0.1])[:components]
    _write_gallery(gallery, [], [], SimpleNamespace(scores=scores, explained_variance_ratio=ratios))
    _archive_gallery(gallery, media / "PCA-Gallery.zip")
    metadata = {
        "specimen_labels": ["A", "B"],
        "source_run": str(root),
        "sources": sources,
        "files": [record(gallery / "mesh-pca.json", "PCA-Gallery/mesh-pca.json")],
    }
    (media / "media.json").write_text(json.dumps(metadata))
    (media / "media.sha256").write_text(sha256_file(media / "media.json"))
    return media, scores, ratios, sources


def pump(qapp, controller):
    deadline = time.monotonic() + 10
    while controller.future is not None and time.monotonic() < deadline:
        qapp.processEvents()
        controller._poll()
        time.sleep(0.005)
    assert controller.future is None


def test_camera_presets_are_rotations_and_saved_views_bind_result(tmp_path):
    views = mv.preset_views()
    assert len(views) == 6
    for i in (0, 2, 4):
        np.testing.assert_array_equal(views[i][1][2], -views[i + 1][1][2])
    for invalid in (np.diag([-1, 1, 1]), np.eye(3) * 2, np.full((3, 3), np.nan)):
        with pytest.raises(ValueError, match="rotation"):
            mv.checked_rotation(invalid)
    path = tmp_path / "view.json"
    saved = mv.save_view(path, "result-one", [], "Inner surface", views[2][1])
    mv.save_view(path, "result-one", saved, "Side", mv.turn_view(views[2][1], 30, 20, 5))
    names, selected = mv.read_views(path, "result-one")
    assert [v["name"] for v in names] == ["Inner surface", "Side"]
    assert selected == "Side"
    with pytest.raises(ValueError, match="different result"):
        mv.read_views(path, "result-two")
    assert not list(tmp_path.glob("*.tmp"))


def test_source_bound_views_keep_exact_scores_common_scale_and_originals(qapp, tmp_path):
    media, scores, _, sources = fixture_media(tmp_path)
    before = {p: sha256_file(p) for p in media.rglob("*") if p.is_file()}
    data = mv.load_surfaces(media, scores, threading.Event())
    np.testing.assert_array_equal(data[3], scores)
    assert np.ptp(data[1][1, :, 0]) == 2 * np.ptp(data[1][0, :, 0])
    first = mv.render_views(data, mv.preset_views()[0][1], [0, 1], threading.Event())
    opposite = mv.render_views(data, mv.preset_views()[1][1], [0], threading.Event())
    assert first[0].size() == first[1].size()
    assert first[0] != opposite[0]  # The anatomical camera actually changes the surface view.
    assert {p: sha256_file(p) for p in before} == before
    assert all(sha256_file(Path(s["path"])) == s["sha256"] for s in sources)


@pytest.mark.parametrize("tamper", ["scores", "source", "inventory"])
def test_mismatched_source_or_scores_never_render(tmp_path, tamper):
    media, scores, _, sources = fixture_media(tmp_path)
    if tamper == "scores":
        scores = scores[::-1]
    elif tamper == "source":
        Path(sources[0]["path"]).write_text("replaced reconstruction")
    else:
        (media / "PCA-Gallery/mesh-pca.json").write_text("[]")
    with pytest.raises(ValueError):
        mv.load_surfaces(media, scores, threading.Event())


def test_preview_cancel_and_latest_apply_publish_only_complete_views(qapp, tmp_path, monkeypatch):
    controller = mv.MeshViewController()
    controller.path, controller.identity = tmp_path / "view.json", "one"
    controller.data = (None, np.empty((2, 1, 3)), None, np.zeros((2, 3)))
    events = []
    controller.images_changed.connect(lambda images: events.append(images))

    def render(data, rotation, indices, cancelled):
        # A deliberately slower old request must not win over a newer view.
        for _ in range(10):
            time.sleep(0.002)
            if cancelled.is_set():
                raise RuntimeError("cancelled")
        images = []
        for index in indices:
            image = QImage(40, 30, QImage.Format.Format_ARGB32)
            image.fill(QColor("red" if index == 0 else "blue"))
            images.append(image)
        return images

    monkeypatch.setattr(mv, "render_views", render)
    controller.request(np.eye(3), preview=0)
    pump(qapp, controller)
    assert not controller.path.exists() and not events
    controller.request(np.eye(3), name="Old")
    controller.request(mv.turn_view(np.eye(3), 20), name="Chosen")
    pump(qapp, controller)
    assert len(events) == 1 and len(events[0]) == 2
    assert controller.selected == controller.label == "Chosen"
    assert mv.read_views(controller.path, "one")[1] == "Chosen"
    saved = controller.path.read_bytes()
    controller.request(np.eye(3), name="Discard")
    controller.clear()
    qapp.processEvents()
    assert controller.path.read_bytes() == saved and len(events) == 1


def test_pca_camera_never_turns_image_glyphs_or_changes_scores(qapp):
    canvas = MorphospaceCanvas()
    canvas.resize(800, 600)
    scores = np.array([[-1.25, 2, -0.5], [1.25, -2, 0.5]])
    canvas.set_data(
        (scores.copy(), np.zeros((2, 3, 3)), np.array([[0, 1, 2]]), [0.6, 0.3, 0.1]), []
    )
    image = QImage(84, 72, QImage.Format.Format_ARGB32)
    image.fill(QColor("teal"))
    canvas.set_images([image, image])
    original = canvas.snapshot()
    _, scene = canvas._scene()
    assert not scene.layers  # No flat 128-triangle specimen mesh is drawn in this mode.
    canvas.yaw += 0.75
    assert canvas.snapshot() != original
    assert canvas.glyph_images == [image, image]
    np.testing.assert_array_equal(canvas.data[0], scores)
    canvas.cache.clear()


@pytest.mark.parametrize("components", [2, 3])
def test_named_gallery_export_keeps_scores_images_and_sealed_cache(qapp, tmp_path, components):
    media, scores, ratios, _ = fixture_media(tmp_path, components)
    data = mv.load_surfaces(media, scores, threading.Event())
    rotation = mv.preset_views()[2][1]
    images = mv.render_views(data, rotation, [0, 1], threading.Event())
    before = {p: sha256_file(p) for p in media.rglob("*") if p.is_file()}
    source = media / "PCA-Gallery.zip"
    kwargs = dict(
        source=source,
        expected=record(source),
        items=json.loads((media / "PCA-Gallery/mesh-pca.json").read_text()),
        images=images,
        rotation=rotation,
        name="Relevant surface",
        protected=(media,),
    )
    target = export_oriented_gallery(tmp_path / "view.zip", **kwargs)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all("PC" in n for n in names if n.endswith(".pdf"))
        assert sum(n.endswith(".pdf") for n in names) == (3 if components == 3 else 1)
        assert json.loads(archive.read("PCA-Gallery/mesh-view.json"))["name"] == "Relevant surface"
        rows = json.loads(archive.read("PCA-Gallery/mesh-pca.json"))
        np.testing.assert_array_equal([row["scores"] for row in rows], scores)
        assert not any(n.endswith((".vtk", ".npz", ".log")) for n in names)
    assert {p: sha256_file(p) for p in before} == before
    old = target.read_bytes()
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        export_oriented_gallery(target, **kwargs)
    assert target.read_bytes() == old
    assert not list(tmp_path.glob(".pca-view-*"))
