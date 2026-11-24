"""Verified face ancestry for reconstruction marks on refined material grids.

Only exact conforming subdivision is supported. The original inspected mark
remains unchanged; its selected material faces are followed through recorded
parent maps, never recovered from endpoint proximity or a display proxy.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file

VERSION = "reconstruction-material-lineage-v1"
_FILE_KEYS = {"path", "sha256", "bytes"}
_GRID_KEYS = _FILE_KEYS | {"topology_sha256", "vertices", "faces"}


def _not_cancelled():
    return False


def _poll(cancelled):
    if cancelled():
        raise InterruptedError("Material ancestry checks cancelled; saved fit and marks retained")


def _file(path):
    path = Path(path).resolve(strict=True)
    return dict(path=str(path), sha256=sha256_file(path), bytes=path.stat().st_size)


def _grid(path, geometry=None):
    from diffeoforge.reconstruction_feedback import topology_sha256
    from diffeoforge.surface_io import load_surface_mesh

    row = _file(path)
    if geometry is None:
        mesh = load_surface_mesh(path).geometry
        geometry = mesh.vertices, mesh.triangles
    vertices, faces = map(np.asarray, geometry)
    return dict(row, topology_sha256=topology_sha256(vertices, faces),
                vertices=len(vertices), faces=len(faces))


def _checked_file(row, *, grid=False):
    keys = _GRID_KEYS if grid else _FILE_KEYS
    if (not isinstance(row, dict) or set(row) != keys
            or not isinstance(row["path"], str) or not Path(row["path"]).is_absolute()
            or not isinstance(row["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            or type(row["bytes"]) is not int or row["bytes"] <= 0):
        raise ValueError("Invalid reconstruction material lineage file binding")
    path = Path(row["path"])
    if (not path.is_file() or path.stat().st_size != row["bytes"]
            or sha256_file(path) != row["sha256"]):
        raise ValueError("Reconstruction material lineage evidence changed")
    return path


def _checked_grid(row):
    from diffeoforge.reconstruction_feedback import topology_sha256
    from diffeoforge.surface_io import load_surface_mesh

    path = _checked_file(row, grid=True)
    if (any(type(row[key]) is not int or row[key] <= 0 for key in ("vertices", "faces"))
            or not isinstance(row["topology_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["topology_sha256"])):
        raise ValueError("Invalid reconstruction material grid binding")
    mesh = load_surface_mesh(path)
    vertices = np.asarray(mesh.geometry.vertices, float)
    faces = np.asarray(mesh.geometry.triangles, np.int64)
    if (mesh.metadata.sha256 != row["sha256"] or len(vertices) != row["vertices"]
            or len(faces) != row["faces"]
            or topology_sha256(vertices, faces) != row["topology_sha256"]):
        raise ValueError("Reconstruction material grid identity changed")
    return vertices, faces


def _checked_array(row, *, ndim):
    path = _checked_file(row)
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise ValueError("Invalid reconstruction material ancestry array") from error
    if (not isinstance(value, np.ndarray) or value.ndim != ndim
            or value.dtype.kind not in "iu"):
        raise ValueError("Invalid reconstruction material ancestry array")
    # Recheck after loading, including when another process replaces this file.
    _checked_file(row)
    return value


def _verify_stage(old, new, parents, edges):
    """Reproduce exact subdivision, including midpoint order and child winding."""
    from diffeoforge._conforming_children import children

    ov, of = old
    nv, nf = new
    if (parents.shape != (len(nf),) or edges.ndim != 2 or edges.shape[1] != 2
            or not len(edges) or len(nv) != len(ov) + len(edges)
            or not np.array_equal(nv[:len(ov)], ov)
            or parents.min() < 0 or parents.max() >= len(of)
            or edges.min() < 0 or edges.max() >= len(ov)
            or not np.array_equal(edges, np.unique(np.sort(edges, axis=1), axis=0))
            or np.any(edges[:, 0] == edges[:, 1])):
        raise ValueError("Invalid or incomplete reconstruction material ancestry")
    original_edges = np.unique(np.sort(np.concatenate(
        (of[:, [0, 1]], of[:, [1, 2]], of[:, [2, 0]])), axis=1), axis=0)
    # Integer edge identities, not vertex coordinates, prove material ownership.
    keys = edges[:, 0] * len(ov) + edges[:, 1]
    available = original_edges[:, 0] * len(ov) + original_edges[:, 1]
    if not np.isin(keys, available).all():
        raise ValueError("A reconstruction material split edge is not in its parent grid")
    if not np.array_equal(nv[len(ov):], ov[edges].mean(axis=1)):
        raise ValueError("Refinement changed original material vertices or edge midpoints")
    expected_faces, expected_parents = children(of, edges, len(ov))
    if (not np.array_equal(nf, expected_faces)
            or not np.array_equal(parents, expected_parents)):
        raise ValueError("Reconstruction material children do not match their recorded parents")


@dataclass(frozen=True)
class MaterialLineage:
    """An operation-local, verified chain; it is not an anatomical correspondence."""

    _grids: tuple
    _parents: tuple
    _files: tuple
    _cancelled: Callable[[], bool] = field(default=_not_cancelled, repr=False, compare=False)

    def shared_vertex_prefixes(self, root_sha256, endpoint_topology):
        """Return exact prefixes shared by retained material on this verified subdivision."""
        if (self._grids[0]["sha256"] != root_sha256
                or self._grids[-1]["topology_sha256"] != endpoint_topology):
            return {}
        for row in self._files:
            _poll(self._cancelled)
            _checked_file(row, grid="topology_sha256" in row)
        return {row["sha256"]: row["vertices"] for row in self._grids}

    def material_mask(self, vertices, faces, evidence):
        from diffeoforge.reconstruction_feedback import topology_sha256, validate_evidence

        validate_evidence(evidence)
        for row in self._files:
            _poll(self._cancelled)
            _checked_file(row, grid="topology_sha256" in row)
        _poll(self._cancelled)
        current = self._grids[-1]
        if topology_sha256(vertices, faces) != current["topology_sha256"]:
            raise ValueError("Reconstruction material lineage does not name this current grid")
        matches = [i for i, row in enumerate(self._grids)
                   if row["topology_sha256"] == evidence["topology_sha256"]]
        if len(matches) != 1:
            from diffeoforge.reconstruction_feedback import ReconstructionMaterialUnavailable

            raise ReconstructionMaterialUnavailable(
                "The marked reconstruction has no verified material ancestor")
        start = matches[0]
        if evidence["face_ids"][-1] >= self._grids[start]["faces"]:
            raise ValueError("The marked reconstruction ancestor face is out of range")
        chosen = np.zeros(self._grids[start]["faces"], dtype=bool)
        chosen[evidence["face_ids"]] = True
        for parents in self._parents[start:]:
            _poll(self._cancelled)
            chosen = chosen[parents]
        _poll(self._cancelled)
        return chosen


def from_evaluation(receipt, *, cancelled=_not_cancelled, event_callback=None):
    """Verify a declared chain once; old evaluations without a declaration return None."""
    _poll(cancelled)
    data = receipt.get("material_lineage")
    if data is None:
        return None
    if (not isinstance(data, dict) or set(data) != {"version", "root", "current", "stages"}
            or data["version"] != VERSION or not isinstance(data["stages"], list)
            or not 1 <= len(data["stages"]) <= 64):
        raise ValueError("Invalid reconstruction material lineage declaration")
    first = data["root"]
    if event_callback:
        event_callback(dict(event="qualification_phase", message=
            "Checking the original reconstruction material grid; no new fitting."))
    _poll(cancelled)
    previous = _checked_grid(first)
    _poll(cancelled)
    grids, maps, files = [first], [], [first]
    for index, stage in enumerate(data["stages"]):
        _poll(cancelled)
        if (not isinstance(stage, dict)
                or set(stage) != {"old_grid", "new_grid", "parent_faces", "split_edges"}
                or stage["old_grid"] != grids[-1]):
            raise ValueError("Reconstruction material lineage has a missing or changed stage")
        if event_callback:
            event_callback(dict(event="qualification_phase", message=
                f"Checking exact material ancestry, stage {index + 1} of "
                f"{len(data['stages'])}; no new fitting."))
        _poll(cancelled)
        current = _checked_grid(stage["new_grid"])
        _poll(cancelled)
        parents = _checked_array(stage["parent_faces"], ndim=1)
        _poll(cancelled)
        edges = _checked_array(stage["split_edges"], ndim=2)
        _poll(cancelled)
        _verify_stage(previous, current, parents, edges)
        _poll(cancelled)
        parents = np.asarray(parents, np.int64)
        parents.setflags(write=False)
        grids.append(stage["new_grid"])
        maps.append(parents)
        files.extend((stage["new_grid"], stage["parent_faces"], stage["split_edges"]))
        previous = current
    reference = receipt.get("reference_source") or {}
    if (data["current"] != grids[-1]
            or reference.get("sha256") != grids[-1]["sha256"]
            or Path(reference.get("path", "")).resolve() != Path(grids[-1]["path"]).resolve()):
        raise ValueError("Reconstruction material lineage does not bind the evaluated source")
    _poll(cancelled)
    return MaterialLineage(tuple(deepcopy(grids)), tuple(maps), tuple(deepcopy(files)), cancelled)


def starting_evidence(grid, *evaluations):
    """Find saved ancestry for the exact original-material grid used for the next fit."""
    matching = [entry for entry in evaluations if entry and entry.get("material_lineage")
                and entry["reference_source"]["sha256"] == grid["sha256"]]
    if not matching:
        return None
    entry = max(matching, key=lambda row: len(row["material_lineage"]["stages"]))
    return {key: entry[key] for key in ("reference_source", "material_lineage")}


def _attach(receipt, data, source):
    if receipt["reference_source"] != source:
        raise ValueError("Composed fields do not share the refined original material grid")
    updated = dict(receipt, material_lineage=deepcopy(data))
    if receipt.get("prefix"):
        updated["prefix"] = _attach(receipt["prefix"], data, source)
    return updated


def on_staged_grid(receipt, data):
    """Keep exact ancestors when a successor evaluates a byte-identical staged grid."""
    if not data:
        return receipt
    source = receipt["reference_source"]
    current = data["current"]
    if source["sha256"] != current["sha256"] or data["stages"][-1]["new_grid"] != current:
        raise ValueError("Saved reconstruction ancestry does not bind the staged material grid")
    path = str(Path(source["path"]).resolve())
    if path != current["path"]:
        _checked_file(current, grid=True)
        current = dict(current, path=path)
        stages = [*data["stages"][:-1], dict(data["stages"][-1], new_grid=current)]
        data = dict(data, stages=stages, current=current)
    _checked_file(current, grid=True)
    return _attach(receipt, data, source)


def append_stage(before, after, parent_faces, split_edges, *, old_geometry=None, new_geometry=None):
    """Attach newly saved refinement evidence without changing any old receipt or mark."""
    old = _grid(before["reference_source"]["path"], old_geometry)
    new = _grid(after["reference_source"]["path"], new_geometry)
    if (old["sha256"] != before["reference_source"]["sha256"]
            or new["sha256"] != after["reference_source"]["sha256"]):
        raise ValueError("Original material source changed during lineage recording")
    existing = before.get("material_lineage")
    if existing is None:
        data = dict(version=VERSION, root=old, current=old, stages=[])
    else:
        data = deepcopy(existing)
        if data.get("version") != VERSION or data.get("current") != old:
            raise ValueError("Refinement did not continue its declared original material grid")
    data["stages"].append(dict(old_grid=old, new_grid=new,
                               parent_faces=_file(parent_faces), split_edges=_file(split_edges)))
    data["current"] = new

    return _attach(after, data, after["reference_source"])
