import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from diffeoforge.mesh import sha256_file
from diffeoforge.pca_media import MEDIA_VERSION, _archive_gallery, _write_gallery, verify_media


def test_offline_gallery_embeds_exact_scores_and_rejects_raw_files(tmp_path):
    gallery = tmp_path / "PCA-Gallery"
    (gallery / "thumbnails").mkdir(parents=True)
    scores = np.array([[-1.25, 2, 0], [1.25, -2, 0]], dtype=np.float64)
    for i in (1, 2):
        Image.new("RGB", (20, 20), "teal").save(gallery / f"thumbnails/{i}.png")
    pca = SimpleNamespace(scores=scores, explained_variance_ratio=np.array([0.6, 0.4, 0]))
    _write_gallery(gallery, [], [], pca)
    data = json.loads((gallery / "mesh-pca.json").read_text())
    np.testing.assert_array_equal([item["scores"] for item in data], scores)
    page = (gallery / "mesh-pca.html").read_text(encoding="utf-8")
    assert "data:image/png;base64," in page and "http://" not in page and "https://" not in page
    raw = gallery / "private-momenta.txt"
    raw.write_text("Must not be included")
    with pytest.raises(ValueError, match="Unexpected file"):
        _archive_gallery(gallery, tmp_path / "refused.zip")
    assert not (tmp_path / "refused.zip").exists()
    raw.unlink()
    target = tmp_path / "ready.zip"
    _archive_gallery(gallery, target)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert all(name.startswith("PCA-Gallery/") for name in archive.namelist())
        assert not any(
            name.endswith((".vtk", ".txt", ".log", ".csv")) for name in archive.namelist()
        )


@pytest.mark.parametrize("changed", ["source", "output", "wrong_run"])
def test_media_reuse_checks_current_source_and_output_bytes(tmp_path, changed):
    run, root = tmp_path / "run", tmp_path / "cache"
    run.mkdir()
    root.mkdir()
    source, output = run / "manifest.json", root / "figure.png"
    source.write_text("Immutable source")
    output.write_bytes(b"Verified output")

    def record(path):
        return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}

    data = {
        "version": MEDIA_VERSION,
        "status": "complete",
        "source_run": str(run),
        "sources": [record(source)],
        "files": [{**record(output), "path": "figure.png"}],
    }
    (root / "media.json").write_text(json.dumps(data))
    (root / "media.sha256").write_text(sha256_file(root / "media.json"))
    assert verify_media(root, source_run=run) == data
    if changed == "source":
        source.write_text("Altered source")
    elif changed == "output":
        output.write_bytes(b"Altered output")
    else:
        run = tmp_path / "another-run"
    with pytest.raises(ValueError):
        verify_media(root, source_run=run)


def test_gallery_export_refuses_changed_archive_and_preserves_destination(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop import visualization_panel as ui

    app = QApplication.instance() or QApplication([])
    panel = ui.VisualizationPanel()
    source, target = tmp_path / "PCA-Gallery.zip", tmp_path / "shared.zip"
    source.write_bytes(b"Verified archive")
    panel.directory = tmp_path
    panel._source_run = tmp_path / "protected-source"
    panel._zip_record = {"bytes": source.stat().st_size, "sha256": sha256_file(source)}
    target.write_bytes(b"Existing colleague copy")
    target = tmp_path.parent / (tmp_path.name + "-export.zip")
    target.write_bytes(b"Existing colleague copy")
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    warnings = []
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: warnings.append(args))
    source.write_bytes(b"Modified archive")
    panel._export()
    from concurrent.futures import wait

    wait([panel._export_future], timeout=5)
    panel._export_finished()
    assert len(warnings) == 1 and "changed since verification" in warnings[0][-1]
    assert target.read_bytes() == b"Existing colleague copy"
    assert not list(tmp_path.glob("*.tmp"))
    panel.close()
    app.processEvents()
