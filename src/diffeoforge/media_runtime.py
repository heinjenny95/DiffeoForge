"""Small image/video runtime check, also executed inside the frozen desktop."""

from __future__ import annotations

import importlib.metadata
import tempfile
from pathlib import Path


def verify_media_runtime() -> None:
    """Encode and decode synthetic frames without opening a project or native job."""
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
