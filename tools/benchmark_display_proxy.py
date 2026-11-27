"""Read-only, opt-in rendering observation for a user-supplied large mesh.

Images and measurements are engineering evidence, not anatomical validation.
Use an output directory outside the source repository for private specimens.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from diffeoforge.desktop.landmark_3d_widget import camera_rotation  # noqa: E402
from diffeoforge.desktop.mesh_preview import load_mesh_preview  # noqa: E402
from diffeoforge.desktop.surface_rendering import (  # noqa: E402
    SurfaceLayer,
    SurfaceScene,
    render_surface_scene,
)
from diffeoforge.mesh import sha256_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    app = QApplication.instance() or QApplication([])
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    before = sha256_file(args.mesh)
    start = time.perf_counter()
    model = load_mesh_preview(args.mesh)
    prepare_seconds = time.perf_counter() - start
    proxy = model.display_proxy
    if proxy is None:
        raise RuntimeError(model.display_proxy_error)
    vertices, faces = np.asarray(model.vertices), np.asarray(model.triangles)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    center, scale = (low + high) / 2, float((high - low).max())
    images, render_seconds = [], []
    for layer in (SurfaceLayer(vertices, faces), SurfaceLayer(proxy.vertices, proxy.triangles)):
        start = time.perf_counter()
        rendered = render_surface_scene(
            SurfaceScene(700, 600, center, scale, camera_rotation(-0.55, 0.30),
                         1.0, (0, 0), (layer,)), threading.Event())
        render_seconds.append(time.perf_counter() - start)
        assert rendered is not None
        images.append(rendered)
    board = QImage(1400, 645, QImage.Format.Format_ARGB32)
    board.fill(QColor("white"))
    painter = QPainter(board)
    painter.setFont(QFont("Arial", 12))
    for index, image in enumerate(images):
        painter.drawImage(index * 700, 45, image)
        painter.setPen(QColor("#123b3a"))
        label = f"Original: {len(faces):,} faces" if index == 0 else (
            f"Display only: {len(proxy.triangles):,} faces; inspect original for small details"
        )
        painter.drawText(index * 700 + 12, 27, label)
    painter.end()
    assert board.save(str(args.output / "original-vs-display-proxy.png"))
    after = sha256_file(args.mesh)
    report = {
        "source_unchanged": before == after,
        "source_sha256": before,
        "original_faces": len(faces), "display_faces": len(proxy.triangles),
        "display_budget": proxy.budget, "method": proxy.method,
        "prepare_seconds_including_source_load": prepare_seconds,
        "original_render_seconds": render_seconds[0], "proxy_render_seconds": render_seconds[1],
        "display_array_bytes": proxy.vertices.nbytes + proxy.triangles.nbytes + proxy.edges.nbytes,
        "scope": "single-view engineering observation; not validation of hidden anatomical detail",
    }
    (args.output / "observation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    app.processEvents()


if __name__ == "__main__":
    main()
