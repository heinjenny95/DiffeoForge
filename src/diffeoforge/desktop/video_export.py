"""Verified side-by-side MP4 export on a shared frame clock."""

import os
import uuid
from pathlib import Path

from diffeoforge.mesh import sha256_file


def export_video_comparison(target, entries, *, protected=()):
    import imageio.v2 as imageio
    import numpy as np
    from PIL import Image, ImageDraw

    target = Path(target).expanduser()
    if target.is_symlink():
        raise ValueError("Choose a regular MP4 destination")
    target = target.resolve()
    if (
        target.suffix.lower() != ".mp4"
        or not 1 <= len(entries) <= 10
        or any(target.is_relative_to(Path(p).resolve()) for p in protected if p is not None)
    ):
        raise ValueError("Choose an MP4 destination outside the saved result/media")

    def check():
        for path, record in entries:
            if (
                path.is_symlink()
                or path.stat().st_size != record["bytes"]
                or sha256_file(path) != record["sha256"]
            ):
                raise ValueError("A saved video changed since verification")

    check()
    readers = []
    stage = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.mp4")
    try:
        readers = [imageio.get_reader(path) for path, _ in entries]
        counts = [reader.count_frames() for reader in readers]
        rates = [reader.get_meta_data()["fps"] for reader in readers]
        if len(set(counts)) != 1 or any(abs(rate - rates[0]) > 1e-6 for rate in rates):
            raise ValueError("Videos do not share a frame clock")
        columns = min(3, len(readers))
        width, height = 640, 456
        rows = (len(readers) + columns - 1) // columns
        with imageio.get_writer(
            stage,
            fps=rates[0],
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=1,
            ffmpeg_params=["-crf", "21", "-threads", "2"],
        ) as writer:
            for frame in range(counts[0]):
                plate = Image.new("RGB", (width * columns, height * rows), "white")
                draw = ImageDraw.Draw(plate)
                for i, reader in enumerate(readers):
                    image = Image.fromarray(reader.get_data(frame))
                    image.thumbnail((width, height - 28))
                    x, y = (i % columns) * width, (i // columns) * height
                    draw.text((x + 12, y + 8), entries[i][0].stem, fill="black")
                    plate.paste(image, (x + (width - image.width) // 2, y + 28))
                writer.append_data(np.asarray(plate))
        check()
        with imageio.get_reader(stage) as reader:
            if reader.count_frames() != counts[0]:
                raise ValueError("Combined video frame count differs")
        os.replace(stage, target)
        return target
    finally:
        for reader in readers:
            reader.close()
        stage.unlink(missing_ok=True)
