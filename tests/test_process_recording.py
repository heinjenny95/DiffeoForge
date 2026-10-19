from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("imageio_ffmpeg")

import numpy as np

from diffeoforge.process_recording import ProcessRecording, recover_recording


def pixels(value=100):
    return np.full((96, 160, 3), value, dtype=np.uint8)


def decode(path):
    import imageio_ffmpeg

    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        meta = next(reader)
        frames = [np.frombuffer(frame, np.uint8).reshape(96, 160, 3) for frame in reader]
        return meta, frames
    finally:
        reader.close()


def test_native_encoder_preserves_timing_final_state_and_project_delivery(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rec = ProcessRecording(tmp_path / "staging", (160, 96), segment_frames=25)
    # Three captures per second at 10x => thirty playback frames per second.
    for i in range(31):
        rec.add(pixels(20 + i * 3), i / 3, "active")
    rec.add(pixels(150), 10, "waiting")
    rec.add(pixels(190), 310, "active")
    rec.add(pixels(230), 320, "active")
    path = rec.finish(320, project, "computation_finished")
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert path.parent == project / "recordings"
    assert data["status"] == "complete"
    assert data["source_seconds"] == 320
    assert data["final_hold_frames"] == 30
    # 10s / 10 + 300s / 1000 + 10s / 10 + one-second declared end hold.
    assert data["output"]["frames"] == 99
    assert data["output"]["seconds"] == 3.3
    assert [item["speed"] for item in data["timeline"]] == [10, 1000, 10]
    assert data["capture_gap_count"] == 1
    assert data["output"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(rec.directory.glob("segment-*.mp4"))
    meta, frames = decode(path)
    assert meta["fps"] == 30 and len(frames) == 99
    assert abs(float(frames[-1].mean()) - 230) < 5
    # The deliberately delayed active capture is visibly labelled, not silent motion.
    assert frames[45][10, 150, 0] > frames[45][10, 150, 1] + 50


def test_live_lock_then_partial_recovery_without_replacing_existing_outputs(tmp_path):
    root = tmp_path / "staging"
    rec = ProcessRecording(root, (160, 96), segment_frames=2)
    for i in range(7):
        rec.add(pixels(i * 20), i / 3, "active")
    with pytest.raises(OSError):
        recover_recording(rec.directory, root)
    rec.fail(RuntimeError("public engineering interruption"))
    path = recover_recording(rec.directory, root)
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["status"] == "recovered_partial"
    assert data["recovered_partial"] is True
    assert data["output"]["frames"] == 6
    assert len(decode(path)[1]) == 6
    with pytest.raises(ValueError, match="already been exported"):
        recover_recording(rec.directory, root)


def test_unresponsive_intervals_are_cut_but_normal_waiting_and_final_state_remain(tmp_path):
    rec = ProcessRecording(tmp_path, (160, 96))
    rec.add(pixels(40), 0, "active")
    rec.add(pixels(80), 1, "active")
    rec.add(pixels(120), 601, "waiting", pauses=({
        "source_start": 1, "source_end": 601, "reason": "interface_unresponsive",
    },))
    rec.add(pixels(220), 901, "active")  # Healthy five-minute backend wait stays.
    path = rec.finish(901, reason="manual_finish")
    data = json.loads(path.with_suffix(".json").read_text())
    assert data["source_seconds"] == 901
    assert data["capture_gap_count"] == 0
    assert data["pauses"][0]["source_end"] == 601
    # One active second /10 + 300 responsive waiting seconds /1000 + final hold.
    meta, frames = decode(path)
    assert meta["fps"] == 30 and len(frames) == 42
    assert abs(float(frames[-1].mean()) - 220) < 5


@pytest.mark.parametrize("pauses", [
    ({"source_start": -1, "source_end": 2, "reason": "interface_unresponsive"},),
    ({"source_start": 1, "source_end": 5, "reason": "interface_unresponsive"},),
    ({"source_start": 2, "source_end": 1, "reason": "interface_unresponsive"},),
])
def test_invalid_pause_cannot_remove_unrelated_video_time(tmp_path, pauses):
    rec = ProcessRecording(tmp_path, (160, 96))
    rec.add(pixels(), 0, "active")
    try:
        with pytest.raises(ValueError, match="pause interval"):
            rec.add(pixels(), 3, "active", pauses=pauses)
        assert rec.data["pauses"] == []
    finally:
        rec.fail(RuntimeError("fixture cleanup"))


@pytest.mark.parametrize("corruption", ["bytes", "path", "size", "fps"])
def test_recovery_rejects_changed_or_unsafe_fragments(tmp_path, corruption):
    root = tmp_path / "staging"
    rec = ProcessRecording(root, (160, 96), segment_frames=1)
    rec.add(pixels(), 0, "active")
    rec.add(pixels(), 1 / 3, "active")
    rec.fail(RuntimeError("interrupted"))
    manifest = rec.directory / "session.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if corruption == "bytes":
        (rec.directory / data["segments"][0]["path"]).write_bytes(b"changed")
    elif corruption == "path":
        data["segments"][0]["path"] = "../outside.mp4"
    elif corruption == "size":
        data["size"] = [3, 7]
    else:
        data["fps"] = 100
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        recover_recording(rec.directory, root)
    assert not list(root.rglob("process-*.mp4"))
    with pytest.raises(ValueError, match="staging folder"):
        recover_recording(rec.directory, tmp_path / "other")


def test_invalid_time_and_unavailable_project_fail_without_deleting_segments(tmp_path):
    rec = ProcessRecording(tmp_path, (160, 96), segment_frames=100)
    rec.add(pixels(), 0, "active")
    with pytest.raises(ValueError):
        rec.add(pixels(), -1, "active")
    rec.add(pixels(), 1 / 3, "active")
    with pytest.raises(FileNotFoundError):
        rec.finish(1 / 3, tmp_path / "missing")
    assert list(rec.directory.glob("segment-*.mp4"))
    assert json.loads((rec.directory / "session.json").read_text())["status"] == "failed"


def test_export_retries_transient_windows_destination_lock(tmp_path, monkeypatch):
    original = Path.replace
    calls = []

    def locked_twice(source, target):
        if source.suffix == ".copying":
            calls.append(target)
            if len(calls) <= 2:
                raise PermissionError("Fixture Windows sharing lock")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", locked_twice)
    rec = ProcessRecording(tmp_path, (160, 96))
    rec.add(pixels(), 0, "active")
    path = rec.finish(1)
    assert len(calls) == 3 and path.stat().st_size > 0
    assert len(decode(path)[1]) == 33


def test_abrupt_public_writer_exit_releases_lock_and_recovers_only_sealed_video(tmp_path):
    code = """
import os, sys
import numpy as np
from diffeoforge.process_recording import ProcessRecording
r = ProcessRecording(sys.argv[1], (160,96), segment_frames=2)
for i in range(7):
    r.add(np.full((96,160,3), 100, np.uint8), i/3, 'active')
os._exit(0)  # Deliberate presentation-only fixture crash; no scientific worker.
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, timeout=30)
    directory = next(tmp_path.glob("process-*"))
    path = recover_recording(directory, tmp_path)
    assert len(decode(path)[1]) == 6
    assert json.loads(path.with_suffix(".json").read_text())["recovered_partial"] is True
