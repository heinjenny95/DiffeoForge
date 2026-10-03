"""Reusable, hash-bound display geometry for pilot review, never analysis inputs."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES, build_display_proxy
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview

_LOCK = threading.Lock()
_MODELS: OrderedDict[tuple[str, int], MeshPreviewModel] = OrderedDict()
_CACHE_VERSION = "pilot-display-v2"


def _payload_digest(data) -> str:
    return hashlib.sha256(
        b"".join(
            data[name].tobytes()
            for name in ("vertices", "triangles", "edges", "bounds", "source_faces")
        )
    ).hexdigest()


def _classic_ascii(raw: bytes):
    """Vectorize the common triangular legacy VTK; other encodings use the reader."""
    header = raw.split(b"\n", 4)[:4]
    if len(header) != 4 or header[2].strip() != b"ASCII":
        return None
    points = re.search(rb"(?m)^POINTS\s+(\d+)\s+(?:float|double)\s*\r?\n", raw)
    faces = re.search(rb"(?m)^POLYGONS\s+(\d+)\s+(\d+)\s*\r?\n", raw)
    if points is None or faces is None or faces.start() <= points.end():
        return None
    n, f, count = int(points[1]), int(faces[1]), int(faces[2])
    if count != f * 4 or raw[faces.end() :].lstrip().startswith(b"OFFSETS"):
        return None
    vertices = np.fromstring(raw[points.end() : faces.start()].decode("ascii"), sep=" ")
    cells = np.fromstring(raw[faces.end() :].decode("ascii"), dtype=np.int64, count=count, sep=" ")
    if len(vertices) != n * 3 or len(cells) != count or n < 1 or f < 1:
        raise ValueError("Incomplete VTK display geometry")
    vertices, cells = vertices.reshape(-1, 3), cells.reshape(-1, 4)
    triangles = cells[:, 1:]
    if (
        not np.isfinite(vertices).all()
        or not (cells[:, 0] == 3).all()
        or triangles.min() < 0
        or triangles.max() >= n
        or np.any(triangles[:, 0] == triangles[:, 1])
        or np.any(triangles[:, 1] == triangles[:, 2])
        or np.any(triangles[:, 2] == triangles[:, 0])
    ):
        raise ValueError("Invalid VTK display geometry")
    return vertices, triangles


def load_pilot_preview(
    path: Path, *, cache_directory: Path | None = None, triangle_budget: int = DEFAULT_DISPLAY_FACES
) -> MeshPreviewModel:
    """Hash current source bytes before cache lookup; reuse only bounded geometry.

    Cache identity includes the algorithm version and face budget. Corrupt disk
    caches are regenerated. Full resolution remains a separate explicit load.
    """
    source = path.resolve()
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    key = digest, triangle_budget
    with _LOCK:
        model = _MODELS.get(key)
        if model is not None:
            _MODELS.move_to_end(key)
            from dataclasses import replace

            return replace(model, path=source)
    target = (
        cache_directory / f"{_CACHE_VERSION}-{digest}-{triangle_budget}.npz"
        if cache_directory is not None
        else None
    )
    data = None
    if target is not None and target.is_file():
        try:
            with np.load(target, allow_pickle=False) as saved:
                data = {name: saved[name] for name in saved.files}
            points, faces, edges = data["vertices"], data["triangles"], data["edges"]
            bounds, source_faces = data["bounds"], data["source_faces"]
            if (
                str(data["digest"]) != digest
                or _payload_digest(data) != str(data["payload_digest"])
                or bounds.shape != (6,)
                or not np.isfinite(bounds).all()
                or source_faces.shape != ()
                or source_faces.dtype.kind not in "iu"
                or int(source_faces) < len(faces)
                or faces.dtype.kind not in "iu"
                or edges.dtype.kind not in "iu"
                or len(faces) > triangle_budget
                or points.ndim != 2
                or points.shape[1] != 3
                or faces.ndim != 2
                or faces.shape[1] != 3
                or edges.ndim != 2
                or edges.shape[1] != 2
                or not np.isfinite(points).all()
                or not len(faces)
                or faces.min() < 0
                or faces.max() >= len(points)
                or edges.min() < 0
                or edges.max() >= len(points)
            ):
                data = None
        except (OSError, ValueError, KeyError, EOFError):
            data = None
    if data is None:
        parsed = _classic_ascii(raw) if source.suffix.lower() == ".vtk" else None
        if parsed is None:
            model = load_mesh_preview(source, triangle_budget=triangle_budget)
            if model.sha256 != digest:
                raise ValueError("Mesh changed while preparing its preview")
            points, faces, edges = (
                np.asarray(model.vertices),
                np.asarray(model.triangles),
                np.asarray(model.edges),
            )
            bounds, source_faces = model.bounds, model.source_triangle_count
        else:
            vertices, triangles = parsed
            low, high = vertices.min(axis=0), vertices.max(axis=0)
            bounds = tuple(float(v) for v in np.column_stack((low, high)).ravel())
            if not max(high - low) > 0:
                raise ValueError("Mesh has no spatial extent")
            proxy = build_display_proxy(vertices, triangles, budget=triangle_budget)
            points, faces, edges, source_faces = (
                proxy.vertices,
                proxy.triangles,
                proxy.edges,
                len(triangles),
            )
        data = dict(
            vertices=points,
            triangles=faces,
            edges=edges,
            bounds=np.array(bounds),
            source_faces=np.array(source_faces),
            digest=np.array(digest),
        )
        data["payload_digest"] = np.array(_payload_digest(data))
        if target is not None:
            try:
                import os
                import tempfile

                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, suffix=".npz", delete=False
                ) as f:
                    temporary = Path(f.name)
                    np.savez_compressed(f, **data)
                os.replace(temporary, target)
            except OSError:
                pass  # A read-only/cache-full project can still display the verified source.
    model = MeshPreviewModel(
        path=source,
        sha256=digest,
        vertices=tuple(map(tuple, data["vertices"].tolist())),
        triangles=tuple(map(tuple, data["triangles"].tolist())),
        edges=tuple(map(tuple, data["edges"].tolist())),
        bounds=tuple(data["bounds"].tolist()),
        geometry_is_proxy=len(data["triangles"]) < int(data["source_faces"]),
        source_triangle_count=int(data["source_faces"]),
    )
    with _LOCK:
        _MODELS[key] = model
        while len(_MODELS) > 64:
            _MODELS.popitem(last=False)
    return model
