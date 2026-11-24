"""Host requests and reads sampled native endpoints for the pilot's live display."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_STORED, BadZipFile, ZipFile

import numpy as np

from diffeoforge.desktop.display_proxy import DisplayProxy
from diffeoforge.desktop.mesh_preview import MeshPreviewModel

VERSION = "pilot-live-preview-v2"
LEGACY_VERSION = "pilot-live-preview-v1"
FACE_BUDGETS = (1_600, 6_000, 16_000)
FACE_BUDGET = 6_000
POINT_LIMIT = 48_000
CONTROL_LIMIT = 128
_FRAME_LIMIT = 2 * 1024 * 1024
_REQUEST_LIMIT = 1024 * 1024
_LEGACY_FRAME_LIMIT = 128 * 1024
_LEGACY_REQUEST_LIMIT = 64 * 1024
_LEGACY_POINT_LIMIT = 4_096
_MESH_LIMIT = 128 * 1024 * 1024
_RENEW_INTERVAL = 5


@dataclass(frozen=True, eq=False)
class Binding:
    folder: Path
    identifier: str
    target: MeshPreviewModel
    indices: np.ndarray
    faces: np.ndarray
    edges: np.ndarray
    source_faces: int
    face_budget: int = FACE_BUDGET
    requested_face_budget: int = FACE_BUDGET
    legacy_runtime: bool = False
    protocol_version: str = VERSION
    point_limit: int = FACE_BUDGET * 3
    frame_limit: int = _FRAME_LIMIT
    region_scope: dict | None = None


@dataclass(frozen=True, eq=False)
class Frame:
    iteration: int
    target: MeshPreviewModel
    fit: MeshPreviewModel
    controls: np.ndarray


def _bounded_file(path, limit):
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError("Invalid pilot preview file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Oversized pilot preview file")
    return data


def _protected_file(run, relative, protected, limit):
    path = run / relative
    if not path.resolve().is_relative_to(run):
        raise ValueError("Pilot preview input leaves its run")
    raw = _bounded_file(path, limit)
    if hashlib.sha256(raw).hexdigest() != protected.get(relative):
        raise ValueError("Protected pilot preview input changed")
    return raw


def _geometry(path, raw):
    from diffeoforge.desktop.pilot_binary_vtk import binary_triangles
    from diffeoforge.desktop.pilot_preview import _classic_ascii
    from diffeoforge.surface_io import load_surface_mesh

    if path.suffix.lower() == ".vtk":
        try:
            parsed = binary_triangles(raw)
            if parsed is None:
                lines = raw.split(b"\n", 4)
                if len(lines) == 5 and lines[3].split() == [b"DATASET", b"POLYDATA"]:
                    parsed = _classic_ascii(raw)
            if parsed is not None:
                return parsed
        except (ValueError, UnicodeError):
            pass  # Fall back for other supported VTK surface encodings.
    loaded = load_surface_mesh(path)
    if loaded.metadata.sha256 != hashlib.sha256(raw).hexdigest():
        raise ValueError("Pilot preview source changed while loading")
    return loaded.geometry.vertices, loaded.geometry.triangles


def _reduced_geometry(vertices, faces, *, face_budget=FACE_BUDGET, point_limit=None):
    """Reduce once, retaining verified original vertex indices across all frames."""
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkFiltersCore import vtkQuadricClustering

    points = np.ascontiguousarray(vertices, dtype=np.float64)
    topology = np.ascontiguousarray(faces, dtype=np.int64)
    point_limit = face_budget * 3 if point_limit is None else point_limit
    if len(topology) <= face_budget and len(np.unique(topology)) <= point_limit:
        mapped = topology
    else:
        surface = vtkPolyData()
        verts = vtkPoints()
        verts.SetData(numpy_to_vtk(points))
        surface.SetPoints(verts)
        cells = vtkCellArray()
        offsets = np.arange(0, 3 * len(topology) + 1, 3, dtype=np.int64)
        cells.SetData(numpy_to_vtkIdTypeArray(offsets), numpy_to_vtkIdTypeArray(topology.ravel()))
        surface.SetPolys(cells)
        source_ids = np.arange(len(points), dtype=np.int64)
        ids = numpy_to_vtkIdTypeArray(source_ids)
        ids.SetName("pilot_source_index")
        surface.GetPointData().AddArray(ids)
        reducer = vtkQuadricClustering()
        reducer.SetInputData(surface)
        reducer.UseInputPointsOn()
        reducer.AutoAdjustNumberOfDivisionsOff()
        longest = np.ptp(points, axis=0)
        span = longest.max()
        if not np.isfinite(span) or span <= 0:
            raise ValueError("The live preview source has no finite spatial extent")
        longest /= span
        for bins in (128, 112, 96, 84, 72, 64, 56, 48, 40, 32, 24, 16, 10, 6, 4):
            reducer.SetNumberOfDivisions(*np.maximum(1, np.ceil(longest * bins)).astype(int))
            reducer.Update()
            output = reducer.GetOutput()
            count = output.GetNumberOfPolys()
            if 0 < count <= face_budget and output.GetNumberOfPoints() <= point_limit:
                break
        else:
            raise ValueError("The source surface cannot make a bounded pilot preview")
        kept_ids = output.GetPointData().GetArray("pilot_source_index")
        if kept_ids is None:
            raise ValueError("The live display reduction lost original vertex identities")
        kept = vtk_to_numpy(kept_ids)
        output_points = vtk_to_numpy(output.GetPoints().GetData())
        if (not len(kept) or kept.min() < 0 or kept.max() >= len(points)
                or not np.array_equal(points[kept].astype(output_points.dtype), output_points)):
            raise ValueError("The live display reduction changed the sampled source vertices")
        polys = output.GetPolys()
        if not np.all(np.diff(vtk_to_numpy(polys.GetOffsetsArray())) == 3):
            raise ValueError("The live display reduction produced non-triangular geometry")
        mapped = kept[vtk_to_numpy(polys.GetConnectivityArray()).reshape(-1, 3)]
    canonical = np.sort(mapped, axis=1)
    valid = (canonical[:, 0] != canonical[:, 1]) & (canonical[:, 1] != canonical[:, 2])
    _, first = np.unique(canonical[valid], axis=0, return_index=True)
    indices, remap = np.unique(mapped[valid][np.sort(first)], return_inverse=True)
    if not 0 < len(indices) <= point_limit or not len(remap):
        raise ValueError("Invalid sampled pilot display mesh")
    triangles = remap.reshape(-1, 3)
    edges = _edges(triangles)
    for array in (indices, triangles, edges):
        array.setflags(write=False)
    return indices, triangles, edges


def _edges(faces):
    pairs = np.concatenate((faces[:, :2], faces[:, 1:], faces[:, (2, 0)]))
    return np.unique(np.sort(pairs, axis=1), axis=0)


def _model(path, sha256, points, faces, edges, source_faces, face_budget=FACE_BUDGET):
    low, high = points.min(0), points.max(0)
    proxy = DisplayProxy(points, faces, edges, source_faces, face_budget,
                         "sampled native surface; display only")
    return MeshPreviewModel(
        path=path, sha256=sha256,
        vertices=tuple(map(tuple, points.tolist())),
        triangles=tuple(map(tuple, faces.tolist())),
        edges=tuple(map(tuple, edges.tolist())),
        bounds=tuple(np.column_stack((low, high)).ravel()),
        display_proxy=proxy, geometry_is_proxy=True, source_triangle_count=source_faces,
    )


def _region_scope(run, provenance, protected, target_hash):
    from diffeoforge.pilot_region_scope import label, summary
    from diffeoforge.regional_fit import instruction_regions

    declaration = provenance.get("regional_fit")
    if not declaration:
        return None
    try:
        path = "input/regional/plan.json"
        if protected.get(path) != declaration["sha256"]:
            raise ValueError("Regional plan identity changed")
        plan = json.loads(_protected_file(run, path, protected, _MESH_LIMIT))
        if plan["target_sha256"] != target_hash:
            raise ValueError("Regional plan belongs to another target")
        scope = summary(plan)
        if not scope:
            return None
        markers = {}
        for index, region in enumerate(instruction_regions(plan)):
            if region.get("source_sha256") != target_hash:
                raise ValueError("Mark belongs to another specimen")
            # A reconstruction brush binds material on an earlier field. Its saved
            # centre is not a location on this frame's target or moving surface.
            if not region.get("reconstruction"):
                center = np.asarray(region["center"], dtype=float)
                if center.shape != (3,) or not np.isfinite(center).all():
                    raise ValueError("Invalid mark centre")
                markers[label(index)] = tuple(center)
        if len(markers) != len(instruction_regions(plan)):
            scope["text"] += " Marks on an earlier reconstruction are listed here by role only."
        return dict(scope, markers=markers)
    except (OSError, KeyError, ValueError, TypeError):
        return dict(text="Mark positions unavailable for this preview.", markers={})


def prepare(run: Path, request_id: str, *, face_budget=FACE_BUDGET) -> Binding | None:
    """Prepare one small request for an eligible, freshly staged pilot run."""
    if type(face_budget) is not int or face_budget not in FACE_BUDGETS:
        raise ValueError("Choose a supported live preview resolution")
    requested_face_budget = face_budget
    run = run.resolve()
    if not (run / "engine/pilot_preview_runtime.py").is_file():
        return None
    manifest_raw = _bounded_file(run / "manifest.json", 16 * 1024 * 1024)
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    checksum = _bounded_file(run / "manifest.sha256", 256).decode("ascii").split()
    if checksum != [manifest_sha256, "manifest.json"]:
        raise ValueError("Prepared pilot preview manifest checksum changed")
    manifest = json.loads(manifest_raw)
    provenance = manifest["effective_config"]["project"]["parameter_provenance"]
    declaration = provenance.get("pilot_live_preview")
    if declaration not in ({"version": VERSION}, {"version": LEGACY_VERSION}):
        return None
    legacy_runtime = declaration == {"version": LEGACY_VERSION}
    version = LEGACY_VERSION if legacy_runtime else VERSION
    if legacy_runtime:
        face_budget = FACE_BUDGETS[0]
    point_limit = _LEGACY_POINT_LIMIT if legacy_runtime else face_budget * 3
    protected = {row["path"]: row["sha256"] for row in manifest["protected_artifacts"]}
    runtime = _protected_file(run, "engine/pilot_preview_runtime.py", protected, 1024 * 1024)
    if not legacy_runtime and b"VERSION = 'pilot-live-preview-v2'" not in runtime:
        raise ValueError("The staged publisher lacks the declared live preview capability")
    model = ET.fromstring(_protected_file(run, "engine/model.xml", protected, 1024 * 1024))
    object_id = manifest["effective_config"]["model"]["object_id"]
    sources = [obj for obj in model.findall("template/object") if obj.get("id") == object_id]
    if len(sources) != 1 or sources[0].findtext("deformable-object-type") != "SurfaceMesh":
        raise ValueError("Pilot preview needs one exact native source surface")
    filename = sources[0].findtext("filename")
    if not filename:
        raise ValueError("Pilot preview surface has no native source")
    source = (run / "engine" / filename).resolve()
    if not source.is_relative_to(run):
        raise ValueError("Pilot preview surface escapes its run")
    relative = source.relative_to(run).as_posix()
    raw = _protected_file(run, relative, protected, _MESH_LIMIT)
    vertices, faces = _geometry(source, raw)
    indices, triangles, edges = _reduced_geometry(
        vertices, faces, face_budget=face_budget, point_limit=point_limit)
    vertex_count, source_faces = len(vertices), len(faces)
    del raw, vertices, faces
    subjects = [row for row in manifest["inputs"] if row["role"] == "subject"]
    if len(subjects) != 1:
        raise ValueError("Pilot preview needs one target surface")
    relative = subjects[0]["staged_path"]
    target_path = run / relative
    raw = _protected_file(run, relative, protected, _MESH_LIMIT)
    vertices, faces = _geometry(target_path, raw)
    target_indices, target_faces, target_edges = _reduced_geometry(
        vertices, faces, face_budget=face_budget, point_limit=point_limit)
    target_points = np.asarray(vertices)[target_indices]
    target_points.setflags(write=False)
    target = _model(target_path, protected[relative], target_points,
                    target_faces, target_edges, len(faces), face_budget)
    scope = _region_scope(run, provenance, protected, protected[relative])
    folder = run / "pilot-preview"
    folder.mkdir(exist_ok=True)
    if folder.resolve() != folder or folder.is_symlink():
        raise ValueError("Invalid live preview directory")
    identifier = request_id if re.fullmatch(r"[a-f0-9]{32}", request_id) else uuid4().hex
    request = dict(
        version=version, id=identifier, object_id=object_id, vertex_count=vertex_count,
        manifest_sha256=manifest_sha256, indices=indices.tolist(),
    )
    if not legacy_runtime:
        request["face_budget"] = face_budget
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > (_LEGACY_REQUEST_LIMIT if legacy_runtime else _REQUEST_LIMIT):
        raise ValueError("Oversized live preview request")
    temporary = folder / (".request-" + uuid4().hex)
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
        os.replace(temporary, folder / "request.json")
    finally:
        temporary.unlink(missing_ok=True)
    return Binding(folder, identifier, target, indices, triangles, edges, source_faces,
                   face_budget, requested_face_budget, legacy_runtime, version, point_limit,
                   _LEGACY_FRAME_LIMIT if legacy_runtime else _FRAME_LIMIT, scope)


def release(binding: Binding) -> None:
    """Retire this demand without removing a newer request in the same run."""
    try:
        if binding.folder.resolve() == binding.folder:
            (binding.folder / ("stop-" + binding.identifier)).touch(exist_ok=False)
    except OSError:
        pass  # Requests expire without a viewer's renewal, including after a crash.


def _renew(binding):
    request = binding.folder / "request.json"
    if time.time() - request.stat().st_mtime >= _RENEW_INTERVAL:
        data = json.loads(_bounded_file(request, _REQUEST_LIMIT))
        if (data.get("id") == binding.identifier
                and data.get("version") == binding.protocol_version):
            os.utime(request, None)


def _array(archive, name, expected):
    member = archive.getinfo(name + ".npy")
    if member.compress_type != ZIP_STORED or member.file_size > _FRAME_LIMIT:
        raise ValueError("Invalid live frame array member")
    with io.BytesIO(archive.read(member)) as stream:
        if np.lib.format.read_magic(stream) != (1, 0):
            raise ValueError("Invalid live frame array format")
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=512)
        if fortran or not expected(shape, dtype):
            raise ValueError("Live frame array does not match its declared scope")
        raw = stream.read()
    if len(raw) != int(np.prod(shape)) * dtype.itemsize:
        raise ValueError("Live frame array contains inconsistent bytes")
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def read_frame(binding: Binding, after_iteration: int) -> Frame | None:
    """Renew one viewer's demand and consume a complete, newer frame of its own run."""
    path = binding.folder / "frame.npz"
    try:
        if (binding.folder / ("stop-" + binding.identifier)).exists():
            return None
        _renew(binding)
        payload = _bounded_file(path, binding.frame_limit)
        with ZipFile(io.BytesIO(payload)) as archive:
            expected = ["controls.npy", "id.npy", "iteration.npy", "points.npy"]
            if not binding.legacy_runtime:
                expected += ["face_budget.npy", "version.npy"]
            if sorted(archive.namelist()) != sorted(expected):
                return None
            if not binding.legacy_runtime:
                version = _array(archive, "version", lambda s, d: not s and d == np.dtype("U32"))
                budget = _array(archive, "face_budget", lambda s, d: not s and d == np.int64)
                if (version.item() != binding.protocol_version
                        or budget.item() != binding.face_budget):
                    return None
            identifier = _array(archive, "id", lambda s, d: not s and d == np.dtype("U32"))
            if identifier.item() != binding.identifier:
                return None
            iteration = _array(archive, "iteration", lambda s, d: not s and d == np.int64).item()
            if iteration < 1 or iteration <= after_iteration:
                return None
            points = _array(archive, "points", lambda s, d: (
                s == (len(binding.indices), 3) and d in (np.float32, np.float64)))
            controls = _array(archive, "controls", lambda s, d: (
                len(s) == 2 and s[1] == 3 and s[0] <= CONTROL_LIMIT
                and d in (np.float32, np.float64)))
        if not np.isfinite(points).all() or not np.isfinite(controls).all():
            return None
    except (OSError, ValueError, KeyError, EOFError, BadZipFile):
        return None
    fit = _model(path, hashlib.sha256(payload).hexdigest(), points,
                 binding.faces, binding.edges, binding.source_faces, binding.face_budget)
    return Frame(iteration, binding.target, fit, controls)
