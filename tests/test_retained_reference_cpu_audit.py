"""Integrity and bounded claims for retained, public CPU diagnostic evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1] / "reference/reference-cpu-audit-v1"


def test_public_audit_checksums_and_native_static_probe_relationships():
    inventory = json.loads((ROOT / "checksums.json").read_text())
    assert len(inventory) == 13
    expected = {entry["path"] for entry in inventory}
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name not in {"README.md", "checksums.json"}
    }
    assert expected == actual
    for entry in inventory:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]

    def probe(directory, mode):
        paths = list((ROOT / directory).rglob(f"probe-{mode}.json"))
        assert len(paths) == 1
        return json.loads(paths[0].read_text())

    amd = probe("ci-amd-34829353422", "AUTO")
    intel = probe("ci-intel-34831998568", "AUTO")
    compatible = probe("ci-intel-34831998568", "COMPATIBLE")
    assert "AMD EPYC 7763" in amd["cpu_model"]
    assert "Intel" in intel["cpu_model"] and "8370C" in intel["cpu_model"]
    assert intel["threads"] == compatible["threads"] == 4
    assert compatible["subjects"] == amd["subjects"]
    changed = 0
    for left, right in zip(amd["subjects"], intel["subjects"], strict=True):
        assert left["subject"] == right["subject"]
        assert left["gradient_sha256"] == right["gradient_sha256"]
        for a, b in zip(left["terms"], right["terms"], strict=True):
            assert a["term"] == b["term"]
            assert a["left_sha256"] == b["left_sha256"]
            assert a["right_sha256"] == b["right_sha256"]
            changed += a["dot_float32"] != b["dot_float32"]
            assert abs(a["dot_float32"] - b["dot_float32"]) <= 4.76837158203125e-7
            assert abs(a["dot_float64"] - b["dot_float64"]) <= 8.881784197001252e-16
    assert changed == 5
