"""Read only the bundled presentation fixture; no project/result/controller state."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path

from diffeoforge.desktop.mesh_preview import MeshPreviewModel


def load_demo_fixture() -> dict:
    root = files("diffeoforge.desktop").joinpath("demo_data")
    payload = root.joinpath("presentation.json").read_bytes()
    expected = root.joinpath("presentation.sha256").read_text(encoding="ascii").strip()
    if len(payload) > 500_000 or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("Bundled demo fixture failed its size/hash check")
    value = json.loads(payload)
    if value["format"] != "diffeoforge-presentation-fixture-1" or len(value["subjects"]) != 5:
        raise ValueError("Unsupported demo fixture")
    return value


def demo_mesh(geometry: dict, label: str) -> MeshPreviewModel:
    vertices = tuple(tuple(float(v) for v in point) for point in geometry["vertices"])
    triangles = tuple(tuple(int(v) for v in face) for face in geometry["triangles"])
    if not vertices or any(len(p) != 3 or not all(map(math.isfinite, p)) for p in vertices):
        raise ValueError("Invalid demo vertices")
    if any(len(face) != 3 or min(face) < 0 or max(face) >= len(vertices) for face in triangles):
        raise ValueError("Invalid demo triangles")
    edges = tuple(
        sorted({tuple(sorted(edge)) for a, b, c in triangles for edge in ((a, b), (b, c), (c, a))})
    )
    bounds = tuple(
        v
        for axis in range(3)
        for v in (min(p[axis] for p in vertices), max(p[axis] for p in vertices))
    )
    # An in-memory display identity, never an existing project path or loadable run.
    return MeshPreviewModel(
        Path(f"DEMO-{label}"), "demo-in-memory", vertices, triangles, edges, bounds
    )
