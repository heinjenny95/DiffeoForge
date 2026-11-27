"""Reusable, hash-bound display geometry for pilot review, never analysis inputs."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from zipfile import BadZipFile

import numpy as np

from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES, build_display_proxy
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview

PILOT_DISPLAY_FACES = 4_000
_LOCK = threading.Lock()
_MODELS: OrderedDict[tuple[str, int], MeshPreviewModel] = OrderedDict()
_LOADING: dict[tuple[str, int], Future[MeshPreviewModel]] = {}
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
    path: Path, *, cache_directory: Path | None = None, triangle_budget: int = PILOT_DISPLAY_FACES,
    legacy_cache: Path | None = None,
) -> MeshPreviewModel:
    """Hash current source bytes before cache lookup; reuse only bounded geometry.

    Cache identity includes the algorithm version and face budget. Corrupt disk
    caches are regenerated. Full resolution remains a separate explicit load.
    """
    source = path.resolve()
    from diffeoforge.mesh import sha256_file

    if type(triangle_budget) is not int or triangle_budget < 1:
        raise ValueError("Display face budget must be a positive integer")
    digest = sha256_file(source)
    key = digest, triangle_budget
    with _LOCK:
        model = _MODELS.get(key)
        if model is not None:
            _MODELS.move_to_end(key)
            return replace(model, path=source)
        pending = _LOADING.get(key)
        if pending is None:
            _LOADING[key] = Future()
    if pending is not None:
        return replace(pending.result(), path=source)

    try:
        model = _prepare(source, digest, cache_directory, triangle_budget, legacy_cache)
    except BaseException as error:
        with _LOCK:
            _LOADING.pop(key).set_exception(error)
        raise
    with _LOCK:
        _MODELS[key] = model
        while len(_MODELS) > 64:
            _MODELS.popitem(last=False)
        _LOADING.pop(key).set_result(model)
    return model


def load_study_preview(path: Path, study_cache: Path) -> MeshPreviewModel:
    """Reuse the exact same source proxy across attempts in one calibration workspace."""
    if study_cache.name != "display-cache":
        return load_pilot_preview(path, cache_directory=study_cache)
    shared = study_cache.parent.parent / "pilot-display-cache"
    return load_pilot_preview(path, cache_directory=shared, legacy_cache=study_cache)


def _cache_path(directory, digest, budget):
    return directory / f"{_CACHE_VERSION}-{digest}-{budget}.npz"


def _previous_cache_paths(legacy_cache, directory, digest):
    for older in dict.fromkeys((legacy_cache, directory)):
        if older is not None:
            yield _cache_path(older, digest, DEFAULT_DISPLAY_FACES)
    if legacy_cache is not None and directory is not None and directory.parent.is_dir():
        filename = _cache_path(directory, digest, DEFAULT_DISPLAY_FACES).name
        # Earlier versions persisted a reused original only in the attempt that
        # first opened it. Look for that exact digest in this workspace's cache folders.
        yield from directory.parent.glob(f"guided-pilot-*/display-cache/{filename}")


def _read_payload(path, digest, budget):
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as saved:
            data = {name: saved[name] for name in saved.files}
        points, faces, edges = data["vertices"], data["triangles"], data["edges"]
        bounds, source_faces = data["bounds"], data["source_faces"]
        if (
            str(data["digest"]) == digest
            and _payload_digest(data) == str(data["payload_digest"])
            and bounds.shape == (6,)
            and np.isfinite(bounds).all()
            and source_faces.shape == ()
            and source_faces.dtype.kind in "iu"
            and int(source_faces) >= len(faces)
            and faces.dtype.kind in "iu"
            and edges.dtype.kind in "iu"
            and 0 < len(faces) <= budget
            and points.ndim == 2 and points.shape[1] == 3
            and faces.ndim == 2 and faces.shape[1] == 3
            and edges.ndim == 2 and edges.shape[1] == 2 and len(edges)
            and np.isfinite(points).all()
            and faces.min() >= 0 and faces.max() < len(points)
            and edges.min() >= 0 and edges.max() < len(points)
        ):
            return data
    except (OSError, ValueError, KeyError, EOFError, TypeError, BadZipFile):
        return None
    return None


def _prepare(source, digest, directory, triangle_budget, legacy_cache):
    target = _cache_path(directory, digest, triangle_budget) if directory is not None else None
    data = _read_payload(target, digest, triangle_budget) if target is not None else None
    if data is not None:
        return _model(source, digest, data)

    # Existing 8k previews are already verified display-only surfaces. Reducing one
    # takes a fraction of the time of running a second full-mesh decimator.
    if triangle_budget == PILOT_DISPLAY_FACES:
        for old_path in _previous_cache_paths(legacy_cache, directory, digest):
            older = _read_payload(old_path, digest, DEFAULT_DISPLAY_FACES)
            if older is None:
                continue
            try:
                proxy = build_display_proxy(older["vertices"], older["triangles"],
                                            budget=triangle_budget)
            except ValueError:
                continue  # Try the original if a previously reduced surface collapses.
            data = dict(older, vertices=proxy.vertices, triangles=proxy.triangles,
                        edges=proxy.edges)
            break
    if data is None:
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Mesh changed while preparing its preview")
        parsed = None
        if source.suffix.lower() == ".vtk":
            from diffeoforge.desktop.pilot_binary_vtk import binary_triangles

            parsed = binary_triangles(raw)
            if parsed is None:
                parsed = _classic_ascii(raw)
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
    if target is not None:
        import os
        import tempfile

        data["payload_digest"] = np.array(_payload_digest(data))
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".npz", delete=False) as f:
                temporary = Path(f.name)
                np.savez_compressed(f, **data)
            os.replace(temporary, target)
        except OSError:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Cache I/O is optional for the verified geometry.
    return _model(source, digest, data)


def _model(source, digest, data):
    return MeshPreviewModel(
        path=source,
        sha256=digest,
        vertices=tuple(map(tuple, data["vertices"].tolist())),
        triangles=tuple(map(tuple, data["triangles"].tolist())),
        edges=tuple(map(tuple, data["edges"].tolist())),
        bounds=tuple(data["bounds"].tolist()),
        geometry_is_proxy=len(data["triangles"]) < int(data["source_faces"]),
        source_triangle_count=int(data["source_faces"]),
    )
