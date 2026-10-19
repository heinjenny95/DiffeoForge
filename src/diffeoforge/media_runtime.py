"""Small image/video runtime check, also executed inside the frozen desktop."""

from __future__ import annotations

import importlib.metadata
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def verify_media_runtime() -> None:
    """Exercise image/vector/video output without a project or native job."""
    for distribution in ("imageio", "imageio-ffmpeg"):
        try:
            importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(
                f"Media support is missing package metadata for {distribution}. "
                "Install a repaired DiffeoForge build, then retry Visualization."
            ) from error

    import imageio.v2 as imageio
    import numpy as np

    with tempfile.TemporaryDirectory(prefix="diffeoforge-media-check-") as temporary:
        _verify_figure_formats(Path(temporary))
        path = Path(temporary) / "video.mp4"
        values = (32, 96, 160, 224)
        with imageio.get_writer(
            path,
            fps=12,
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=1,
            ffmpeg_params=["-crf", "21", "-threads", "2", "-movflags", "+faststart"],
        ) as writer:
            for value in values:
                writer.append_data(np.full((64, 64, 3), value, dtype=np.uint8))
        with imageio.get_reader(path) as reader:
            if reader.count_frames() != len(values):
                raise RuntimeError("Media check decoded an incorrect video frame count")
            for index, value in enumerate(values):
                frame = reader.get_data(index)
                if frame.shape != (64, 64, 3) or abs(float(frame.mean()) - value) > 5:
                    raise RuntimeError("Media check decoded incorrect video content")


def _verify_figure_formats(directory: Path) -> None:
    # Use a local Agg canvas rather than switching the live GUI's backend.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from PIL import Image

    figure = Figure(figsize=(2, 2), dpi=64)
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.plot([0, 1, 2], [0, 2, 1])
    axes.set_title("PCA media check")
    try:
        for suffix in ("png", "jpg", "pdf", "svg"):
            path = directory / f"figure.{suffix}"
            try:
                figure.savefig(path, format=suffix)
            except Exception as error:
                raise RuntimeError(f"Media {suffix.upper()} export failed: {error}") from error
            if suffix in {"png", "jpg"}:
                with Image.open(path) as image:
                    image.load()
                    if image.size != (128, 128) or image.convert("RGB").getextrema()[0][0] == 255:
                        raise RuntimeError(f"Media {suffix.upper()} check decoded an empty image")
            elif suffix == "pdf":
                contents = path.read_bytes()
                if not contents.startswith(b"%PDF-") or not contents.rstrip().endswith(b"%%EOF"):
                    raise RuntimeError("Media PDF check produced an incomplete document")
            elif ET.parse(path).getroot().tag != "{http://www.w3.org/2000/svg}svg":
                raise RuntimeError("Media SVG check produced an invalid document")
    finally:
        figure.clear()
