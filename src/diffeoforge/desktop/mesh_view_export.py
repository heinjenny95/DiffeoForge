"""Presentation-only gallery export using the selected shared PCA mesh view."""

from __future__ import annotations

import html
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice

from diffeoforge.desktop.mesh_view import checked_rotation
from diffeoforge.mesh import sha256_file


def export_oriented_gallery(
    target, *, source, expected, items, images, rotation, name, ratios=None, protected=()
):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from PIL import Image

    from diffeoforge.pca_media import _archive_gallery, _write_gallery

    target, source = Path(target).expanduser(), Path(source)
    if target.is_symlink():
        raise ValueError("Choose a regular ZIP destination")
    target = target.resolve()
    if (
        target.suffix.lower() != ".zip"
        or target.is_symlink()
        or any(target.is_relative_to(Path(p).resolve()) for p in protected)
    ):
        raise ValueError("Choose a ZIP destination outside the saved result and media cache")
    if (
        source.is_symlink()
        or source.stat().st_size != expected["bytes"]
        or sha256_file(source) != expected["sha256"]
    ):
        raise ValueError("Prepared gallery changed since verification")
    scores = np.asarray([item["scores"][:3] for item in items], dtype=np.float64)
    if (
        scores.ndim != 2
        or not len(scores)
        or not np.isfinite(scores).all()
        or len(images) != len(scores)
        or any(image.isNull() for image in images)
    ):
        raise ValueError("Mesh images do not match saved scores")
    rotation = checked_rotation(rotation)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tempfile.TemporaryDirectory(prefix=".pca-view-", dir=target.parent) as temporary:
            temporary = Path(temporary)
            gallery = temporary / "PCA-Gallery"
            gallery.mkdir()
            for folder in ("figures", "thumbnails", "videos"):
                (gallery / folder).mkdir()
            with zipfile.ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Prepared gallery archive is corrupt")
                if sum(i.file_size for i in archive.infolist()) > 512 * 1024 * 1024:
                    raise ValueError("Gallery exceeds the presentation export budget")
                for item in archive.infolist():
                    relative = Path(item.filename)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("Unsafe gallery member")
                    relative = relative.relative_to("PCA-Gallery")
                    allowed = relative.as_posix() in {
                        "index.html",
                        "mesh-pca.html",
                        "mesh-pca.json",
                        "mesh-view.json",
                    }
                    allowed |= len(relative.parts) == 2 and (
                        (relative.parts[0] == "figures" and relative.suffix in {".png", ".pdf"})
                        or (relative.parts[0] == "thumbnails" and relative.suffix == ".png")
                        or (relative.parts[0] == "videos" and relative.suffix == ".mp4")
                    )
                    if not allowed:
                        raise ValueError("Unexpected file in prepared presentation gallery")
                    destination = gallery / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(item))
            page = (gallery / "mesh-pca.html").read_text(encoding="utf-8")
            match = re.search(r",ratios=(\[[^\]]*\]),canvas=", page)
            if match is None:
                raise ValueError("Saved gallery variance labels are missing")
            saved_ratios = np.asarray(json.loads(match[1]), dtype=np.float64)
            if (
                saved_ratios.ndim != 1
                or len(saved_ratios) < scores.shape[1]
                or not np.isfinite(saved_ratios).all()
                or (
                    ratios is not None
                    and not np.array_equal(np.asarray(ratios)[: len(saved_ratios)], saved_ratios)
                )
            ):
                raise ValueError("Gallery variance labels differ from the saved result")
            ratios = saved_ratios
            frames = []
            for index, image in enumerate(images, 1):
                data = QByteArray()
                buffer = QBuffer(data)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if not image.save(buffer, "PNG"):
                    raise ValueError("Mesh view image could not be encoded")
                buffer.close()
                content = bytes(data)
                (gallery / f"thumbnails/{index}.png").write_bytes(content)
                with Image.open(io.BytesIO(content)) as decoded:
                    frames.append(np.asarray(decoded.convert("RGBA")))
            figures = []
            for x, y in [(0, 1), (0, 2), (1, 2)]:
                if scores.shape[1] <= y:
                    continue
                figure = Figure(figsize=(14, 10), dpi=150)
                FigureCanvasAgg(figure)
                ax = figure.subplots()
                for column, setter in [(x, ax.set_xlim), (y, ax.set_ylim)]:
                    values = scores[:, column]
                    pad = max(float(np.ptp(values)), 1e-6) * 0.20
                    setter(float(values.min()) - pad, float(values.max()) + pad)
                for row, frame in zip(scores, frames, strict=True):
                    ax.add_artist(
                        AnnotationBbox(OffsetImage(frame, zoom=0.18), row[[x, y]], frameon=False)
                    )
                ax.set_xlabel(f"PC{x + 1} ({ratios[x]:.2%})")
                ax.set_ylabel(f"PC{y + 1} ({ratios[y]:.2%})")
                ax.set_title(f"Mesh PCA · PC{x + 1} / PC{y + 1}\nMesh view: {name}")
                ax.grid(alpha=0.15)
                stem = f"PCA-PC{x + 1}-PC{y + 1}"
                for extension in ("png", "pdf"):
                    figure.savefig(gallery / f"figures/{stem}.{extension}", bbox_inches="tight")
                figure.clear()
                figures.append((f"PC{x + 1} / PC{y + 1} · {name}", stem + ".png"))
            figures += [
                (p.stem.replace("-", " "), p.name)
                for p in sorted((gallery / "figures").glob("*.png"))
                if not p.name.startswith("PCA-PC")
            ]
            videos = [
                (p.stem.replace("-", " "), p.name)
                for p in sorted((gallery / "videos").glob("*.mp4"))
            ]
            _write_gallery(
                gallery,
                figures,
                videos,
                SimpleNamespace(scores=scores, explained_variance_ratio=ratios),
            )
            for filename in ("index.html", "mesh-pca.html"):
                path = gallery / filename
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text + f"<p>PCA mesh view: {html.escape(name)}</p>", encoding="utf-8"
                )
            (gallery / "mesh-view.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "camera_rotation": rotation.tolist(),
                        "scores_unchanged": True,
                        "other_media": "Axis panels and movies retain their labelled views.",
                    }
                ),
                encoding="utf-8",
            )
            _archive_gallery(gallery, stage)
            with zipfile.ZipFile(stage) as archive:
                exported = json.loads(archive.read("PCA-Gallery/mesh-pca.json"))
                if not np.array_equal([r["scores"] for r in exported], scores):
                    raise ValueError("Exported PCA positions differ")
            if sha256_file(source) != expected["sha256"]:
                raise ValueError("Prepared gallery changed during export")
            os.replace(stage, target)
        return target
    finally:
        stage.unlink(missing_ok=True)
