"""Local presentation recording: compressed segments, truthful timing and atomic export."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

FPS = 30
SPEEDS = {"active": 10, "waiting": 1000}
SEGMENT_FRAMES = 900


def _hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _save(path, data):
    stage = path.with_suffix(".tmp")
    stage.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # Windows scanners can briefly hold a just-written manifest without delete
    # sharing. Bound retries happen only in the encoder, never on the GUI thread.
    for attempt in range(8):
        try:
            stage.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


class RecordingLock:
    """An OS-released lock; recovery never trusts a PID or interrupts a writer."""

    def __init__(self, directory):
        self.stream = (directory / "session.lock").open("a+b")
        try:
            if self.stream.tell() == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if __import__("os").name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()


def _verify_segments(directory, data):
    if data.get("kind") != "diffeoforge_process_recording" or data.get("version") != 1:
        raise ValueError("This is not a supported DiffeoForge recording")
    size = data.get("size", ())
    if (
        len(size) != 2
        or any(type(v) is not int or v < 2 or v > 8192 or v % 2 for v in size)
        or data.get("fps") != FPS
    ):
        raise ValueError("Invalid recording dimensions or playback rate")
    seen = set()
    for item in data["segments"]:
        name = item["path"]
        if not re.fullmatch(r"segment-\d{5}\.mp4", name) or name in seen:
            raise ValueError("Unsafe or duplicate recording segment")
        seen.add(name)
        path = directory / name
        if (
            path.is_symlink()
            or path.stat().st_size != item["bytes"]
            or _hash(path) != item["sha256"]
        ):
            raise ValueError("A sealed recording segment changed")
        if not isinstance(item["frames"], int) or item["frames"] < 1:
            raise ValueError("Invalid recording frame count")
    if not seen:
        raise ValueError("No completed recording segments are available")


def _export(directory, data, project, *, recovered=False):
    import imageio_ffmpeg

    _verify_segments(directory, data)
    concat = directory / "concat.txt"
    concat.write_text("".join(f"file '{r['path']}'\n" for r in data["segments"]), encoding="utf-8")
    stage = directory / "export.part.mp4"
    encoder = imageio_ffmpeg.get_ffmpeg_exe()
    options = {"creationflags": 0x08000000} if __import__("os").name == "nt" else {}
    result = subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(stage),
        ],
        capture_output=True,
        timeout=120,
        **options,
    )
    if result.returncode:
        raise RuntimeError("MP4 assembly failed: " + result.stderr.decode(errors="replace")[-1000:])
    # Demux the whole MP4 and count its copied video packets without decoding a
    # potentially hour-long recording on the GUI thread.
    check = subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-i",
            str(stage),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
        ],
        capture_output=True,
        timeout=120,
        **options,
    )
    counts = re.findall(rb"(?m)^frame=\s*(\d+)", check.stdout)
    expected_frames = sum(r["frames"] for r in data["segments"])
    if check.returncode or not counts or int(counts[-1]) != expected_frames:
        raise RuntimeError("Assembled MP4 frame count does not match sealed segments")
    frames = imageio_ffmpeg.read_frames(str(stage))
    try:
        meta = next(frames)
        next(frames)  # At least one actual frame must decode.
    finally:
        frames.close()
    if tuple(meta["size"]) != tuple(data["size"]) or abs(meta["fps"] - FPS) > 0.01:
        raise RuntimeError("Exported recording size or playback rate differs")
    if project and not Path(project).is_dir():
        raise FileNotFoundError("The bound recording project is no longer available")
    target_root = Path(project).resolve() / "recordings" if project else directory
    if target_root.is_symlink():
        raise ValueError("Recording destination must not be a symbolic link")
    target_root.mkdir(parents=True, exist_ok=True)
    name = directory.name + ("-recovered" if recovered else "") + ".mp4"
    target = target_root / name
    companion = target.with_suffix(".json")
    if companion.exists():
        raise FileExistsError("Recording timing companion already exists")
    if target.exists():
        raise FileExistsError("Recording export already exists; it will not be replaced")
    copying = target.with_suffix(".copying")
    if copying.exists():
        raise FileExistsError("An unfinished export copy already exists")
    digest = _hash(stage)
    try:
        shutil.copyfile(stage, copying)
        if _hash(copying) != digest:
            raise RuntimeError("Recording export copy differs from verified MP4")
        # Unique session UUID plus exclusive destination reservation avoids replacing
        # any existing user video, including after a concurrent recovery request.
        with target.open("xb"):
            pass
        for attempt in range(8):
            if target.stat().st_size != 0:
                raise FileExistsError("Reserved recording destination changed during export")
            try:
                copying.replace(target)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        copying.unlink(missing_ok=True)
    data.update(
        status="recovered_partial" if recovered else "complete",
        output={
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": digest,
            "frames": expected_frames,
            "seconds": expected_frames / FPS,
        },
        recovered_partial=recovered,
    )
    _save(directory / "session.json", data)
    _save(companion, data)
    # Delete only this session's enumerated temporary files after verified delivery.
    # Never recurse into a supplied project or follow a segment symlink.
    for item in data["segments"]:
        (directory / item["path"]).unlink()
    concat.unlink(missing_ok=True)
    stage.unlink(missing_ok=True)
    return target


class ProcessRecording:
    def __init__(self, root, size=(1920, 1080), *, segment_frames=SEGMENT_FRAMES):
        if len(size) != 2 or any(type(v) is not int or v < 2 or v > 8192 or v % 2 for v in size):
            raise ValueError("Recording dimensions must be even and between 2 and 8192")
        if type(segment_frames) is not int or segment_frames < 1:
            raise ValueError("Invalid recording segment length")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        name = datetime.now(UTC).strftime("process-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
        self.directory = self.root / name
        self.directory.mkdir()
        self.lock = RecordingLock(self.directory)
        self.segment_frames = segment_frames
        self.data = {
            "kind": "diffeoforge_process_recording",
            "version": 1,
            "status": "recording",
            "created_at": datetime.now(UTC).isoformat(),
            "size": list(size),
            "fps": FPS,
            "speeds": SPEEDS,
            "mode_policy": "Busy workflow tasks 1000x; human review and decisions 10x",
            "segments": [],
            "timeline": [],
            "capture_gaps": [],
            "capture_gap_count": 0,
            "capture_samples": 0,
            "pauses": [],
            "boundary": "Local UI presentation; not scientific run evidence",
        }
        self._writer = None
        self._segment_count = 0
        self._total_frames = 0
        self._output_time = 0.0
        self._last = None
        self._last_t = 0.0
        self._mode = "active"
        self._save()

    def _save(self):
        _save(self.directory / "session.json", self.data)

    def _seal(self):
        if self._writer is None:
            return
        self._writer.close()
        self._writer = None
        path = self.directory / f"segment-{len(self.data['segments']) + 1:05}.mp4"
        self.data["segments"].append(
            {
                "path": path.name,
                "frames": self._segment_count,
                "bytes": path.stat().st_size,
                "sha256": _hash(path),
            }
        )
        self._segment_count = 0
        self._save()

    def _append(self, pixels, count):
        import imageio_ffmpeg

        for _ in range(count):
            if self._writer is None:
                if shutil.disk_usage(self.root).free < 512 * 1024**2:
                    raise OSError("Recording stopped: less than 512 MiB free for video staging")
                path = self.directory / f"segment-{len(self.data['segments']) + 1:05}.mp4"
                self._writer = imageio_ffmpeg.write_frames(
                    str(path),
                    tuple(self.data["size"]),
                    fps=FPS,
                    codec="libx264",
                    quality=None,
                    macro_block_size=2,
                    ffmpeg_log_level="error",
                    ffmpeg_timeout=15,
                    output_params=["-preset", "veryfast", "-crf", "20", "-threads", "1"],
                )
                self._writer.send(None)
            self._writer.send(pixels)
            self._segment_count += 1
            self._total_frames += 1
            if self._segment_count >= self.segment_frames:
                self._seal()

    def add(self, pixels, elapsed, mode, *, pauses=()):
        if mode not in SPEEDS or not math.isfinite(elapsed) or elapsed < self._last_t:
            raise ValueError("Invalid recording time or mode")
        w, h = self.data["size"]
        if pixels.shape != (h, w, 3) or pixels.dtype != np.uint8:
            raise ValueError("Recording frame dimensions or pixel type differ")
        self._advance(elapsed, pauses=pauses)
        self._last = np.ascontiguousarray(pixels).copy()
        if not self.data["timeline"] or self._mode != mode:
            self.data["timeline"].append(
                {
                    "source_start": elapsed,
                    "mode": mode,
                    "speed": SPEEDS[mode],
                    "output_start": self._output_time,
                }
            )
        self._mode = mode
        self.data["capture_samples"] += 1

    def _advance(self, elapsed, *, pauses=()):
        previous_end, omitted = self._last_t, 0.0
        for pause in pauses:
            start, end = pause["source_start"], pause["source_end"]
            if (not math.isfinite(start) or not math.isfinite(end)
                    or start < previous_end or end <= start or end > elapsed
                    or pause["reason"] != "interface_unresponsive"):
                raise ValueError("Invalid recording pause interval")
            previous_end = end
            omitted += end - start
        self.data["pauses"].extend(dict(p) for p in pauses)
        if self._last is not None:
            delta = elapsed - self._last_t - omitted
            self._output_time += delta / SPEEDS[self._mode]
            count = max(0, round(self._output_time * FPS) - self._total_frames)
            # A delayed GUI/encoder sample is recorded rather than presented as
            # captured motion. Delays in intentionally sparse waiting mode are normal.
            if self._mode == "active" and delta > 1.0:
                self.data["capture_gap_count"] += 1
                if len(self.data["capture_gaps"]) < 1000:
                    self.data["capture_gaps"].append(
                        {"source_start": self._last_t, "seconds": delta}
                    )
                from PIL import Image, ImageDraw, ImageFont

                image = Image.fromarray(self._last)
                draw = ImageDraw.Draw(image)
                font = ImageFont.load_default(size=max(12, image.width // 65))
                draw.rectangle((0, 0, image.width, max(30, image.width // 22)), fill="#9b302b")
                draw.text(
                    (8, 5), f"Capture delayed: {delta:.1f}s (held frame)", font=font, fill="white"
                )
                self._append(np.asarray(image), count)
            else:
                self._append(self._last, count)
        self._last_t = elapsed

    def finish(self, elapsed, project=None, reason="session", *, pauses=()):
        try:
            if not math.isfinite(elapsed) or elapsed < self._last_t:
                raise ValueError("Invalid recording finish time")
            if self._last is None:
                raise ValueError("No application frames were captured")
            self._advance(elapsed, pauses=pauses)
            # Keep the actual final UI visible for one playback second. This is
            # an explicitly declared end hold, not extra elapsed session time.
            self._append(self._last, FPS)
            self._seal()
            self.data.update(
                source_seconds=elapsed,
                final_hold_frames=FPS,
                finish_reason=reason,
                status="exporting",
            )
            self._save()
            return _export(self.directory, self.data, project)
        except Exception as error:
            self.data.update(status="failed", error=str(error))
            self._save()
            raise
        finally:
            self.lock.close()

    def fail(self, error):
        try:
            if self._writer is not None:
                self._writer.close()
                self._writer = None
        finally:
            self.data.update(status="failed", error=str(error))
            self._save()
            self.lock.close()


def recover_recording(directory, root, project=None):
    directory, root = Path(directory).resolve(), Path(root).resolve()
    if directory.parent != root or not re.fullmatch(
        r"process-\d{8}T\d{6}Z-[a-f0-9]{12}", directory.name
    ):
        raise ValueError("Recovery must use this application's recording staging folder")
    lock = RecordingLock(directory)
    try:
        data = json.loads((directory / "session.json").read_text(encoding="utf-8"))
        if data.get("status") in {"complete", "recovered_partial"}:
            raise ValueError("This recording has already been exported")
        return _export(directory, data, project, recovered=True)
    finally:
        lock.close()
