"""Dependency-free readers for supported triangular surface-mesh inputs.

VTK remains the canonical downstream format. PLY, OBJ, and STL are accepted as
immutable source formats for inspection, landmark placement, and reviewed
Procrustes preprocessing.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, NamedTuple

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import TriangleMesh, inspect_vtk, read_vtk_polydata

SUPPORTED_SURFACE_EXTENSIONS = (".vtk", ".ply", ".obj", ".stl")
SurfaceFormat = Literal["legacy_vtk", "ply", "obj", "stl"]


@dataclass(frozen=True)
class SurfaceMeshMetadata:
    """Format-independent source identity and observable triangle geometry."""

    path: str
    bytes: int
    sha256: str
    source_format: SurfaceFormat
    encoding: str
    points: int
    triangles: int
    bounds: tuple[float, float, float, float, float, float]
    bounding_box_extents: tuple[float, float, float]
    bounding_box_diagonal: float
    topology_note: str

    def as_manifest(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        value = asdict(self)
        value["bounds"] = list(self.bounds)
        value["bounding_box_extents"] = list(self.bounding_box_extents)
        return value


@dataclass(frozen=True)
class LoadedSurfaceMesh:
    """One parsed source mesh and metadata derived from the same source bytes."""

    metadata: SurfaceMeshMetadata
    geometry: TriangleMesh


def is_supported_surface_path(path: Path | str) -> bool:
    """Return whether *path* has one explicitly supported mesh extension."""

    return Path(path).suffix.casefold() in SUPPORTED_SURFACE_EXTENSIONS


def canonical_vtk_filename(path: Path | str) -> str:
    """Return the transparent canonical VTK filename for one source mesh."""

    source = Path(path)
    if not is_supported_surface_path(source):
        raise ConfigurationError(
            f"Unsupported surface format {source.suffix or '<none>'!r}: {source}"
        )
    return f"{source.stem}.vtk"


def _bounds(
    vertices: tuple[tuple[float, float, float], ...],
    path: Path,
) -> tuple[
    tuple[float, float, float, float, float, float],
    tuple[float, float, float],
    float,
]:
    if not vertices:
        raise ConfigurationError(f"Surface mesh contains no vertices: {path}")
    minima = [math.inf, math.inf, math.inf]
    maxima = [-math.inf, -math.inf, -math.inf]
    for vertex in vertices:
        if len(vertex) != 3 or not all(math.isfinite(value) for value in vertex):
            raise ConfigurationError(
                f"Surface mesh contains incomplete or non-finite coordinates: {path}"
            )
        for axis, value in enumerate(vertex):
            minima[axis] = min(minima[axis], value)
            maxima[axis] = max(maxima[axis], value)
    bounds = (
        minima[0],
        maxima[0],
        minima[1],
        maxima[1],
        minima[2],
        maxima[2],
    )
    extents = (
        maxima[0] - minima[0],
        maxima[1] - minima[1],
        maxima[2] - minima[2],
    )
    diagonal = math.sqrt(sum(value * value for value in extents))
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise ConfigurationError(f"Surface mesh has a degenerate bounding box: {path}")
    return bounds, extents, diagonal


def _validated_geometry(
    vertices: list[tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    path: Path,
) -> TriangleMesh:
    normalized_vertices = tuple(vertices)
    normalized_triangles = tuple(triangles)
    _bounds(normalized_vertices, path)
    if not normalized_triangles:
        raise ConfigurationError(f"Surface mesh contains no triangular faces: {path}")
    for triangle in normalized_triangles:
        if len(triangle) != 3:
            raise ConfigurationError(
                f"Surface mesh contains a non-triangular face: {path}"
            )
        if min(triangle) < 0 or max(triangle) >= len(normalized_vertices):
            raise ConfigurationError(f"Surface triangle index is out of range: {path}")
        if len(set(triangle)) != 3:
            raise ConfigurationError(
                f"Surface triangle contains a repeated vertex index: {path}"
            )
    return TriangleMesh(
        vertices=normalized_vertices,
        triangles=normalized_triangles,
    )


def _read_obj(raw: bytes, path: Path) -> tuple[TriangleMesh, str, str]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"OBJ mesh is not readable UTF-8 text: {path}") from error
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for line_number, source_line in enumerate(text.splitlines(), start=1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if fields[0] == "v":
            if len(fields) < 4:
                raise ConfigurationError(
                    f"OBJ vertex on line {line_number} has fewer than three coordinates: {path}"
                )
            try:
                vertex = tuple(float(value) for value in fields[1:4])
            except ValueError as error:
                raise ConfigurationError(
                    f"OBJ vertex on line {line_number} is not numeric: {path}"
                ) from error
            vertices.append(vertex)
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ConfigurationError(
                    "OBJ input must contain exclusively triangular faces; "
                    f"line {line_number} has {len(fields) - 1} vertices: {path}"
                )
            indices: list[int] = []
            for token in fields[1:]:
                vertex_token = token.split("/", 1)[0]
                try:
                    declared = int(vertex_token)
                except ValueError as error:
                    raise ConfigurationError(
                        f"OBJ face contains an invalid vertex reference {token!r}: {path}"
                    ) from error
                if declared == 0:
                    raise ConfigurationError(f"OBJ vertex indices cannot be zero: {path}")
                index = declared - 1 if declared > 0 else len(vertices) + declared
                indices.append(index)
            triangles.append(tuple(indices))
    if not vertices:
        raise ConfigurationError(f"OBJ mesh contains no vertices: {path}")
    return (
        _validated_geometry(vertices, triangles, path),
        "text/utf-8",
        "indexed OBJ vertices and triangular faces; non-geometric attributes ignored",
    )


_PLY_SCALARS: dict[str, tuple[str, int, bool]] = {
    "char": ("b", 1, True),
    "int8": ("b", 1, True),
    "uchar": ("B", 1, True),
    "uint8": ("B", 1, True),
    "short": ("h", 2, True),
    "int16": ("h", 2, True),
    "ushort": ("H", 2, True),
    "uint16": ("H", 2, True),
    "int": ("i", 4, True),
    "int32": ("i", 4, True),
    "uint": ("I", 4, True),
    "uint32": ("I", 4, True),
    "float": ("f", 4, False),
    "float32": ("f", 4, False),
    "double": ("d", 8, False),
    "float64": ("d", 8, False),
}


class _PlyProperty(NamedTuple):
    name: str
    scalar_type: str | None
    count_type: str | None
    item_type: str | None


class _PlyElement(NamedTuple):
    name: str
    count: int
    properties: tuple[_PlyProperty, ...]


def _ply_header(raw: bytes, path: Path) -> tuple[str, tuple[_PlyElement, ...], int]:
    offset = 0
    lines: list[str] = []
    for payload in raw.splitlines(keepends=True):
        offset += len(payload)
        try:
            line = payload.rstrip(b"\r\n").decode("ascii")
        except UnicodeDecodeError as error:
            raise ConfigurationError(f"PLY header is not ASCII: {path}") from error
        lines.append(line)
        if line.strip() == "end_header":
            break
    else:
        raise ConfigurationError(f"PLY end_header marker is missing: {path}")
    if not lines or lines[0].strip() != "ply":
        raise ConfigurationError(f"PLY header must start with 'ply': {path}")

    encoding: str | None = None
    elements: list[tuple[str, int, list[_PlyProperty]]] = []
    current: list[_PlyProperty] | None = None
    for line in lines[1:]:
        fields = line.split()
        if not fields or fields[0] in {"comment", "obj_info", "end_header"}:
            continue
        if fields[0] == "format":
            if len(fields) < 3 or fields[2] != "1.0":
                raise ConfigurationError(f"PLY format version 1.0 is required: {path}")
            encoding = fields[1]
            if encoding not in {"ascii", "binary_little_endian", "binary_big_endian"}:
                raise ConfigurationError(f"Unsupported PLY encoding {encoding!r}: {path}")
        elif fields[0] == "element":
            if len(fields) != 3:
                raise ConfigurationError(f"Malformed PLY element declaration: {path}")
            try:
                count = int(fields[2])
            except ValueError as error:
                raise ConfigurationError(f"Invalid PLY element count: {path}") from error
            if count < 0:
                raise ConfigurationError(f"PLY element count cannot be negative: {path}")
            current = []
            elements.append((fields[1], count, current))
        elif fields[0] == "property":
            if current is None:
                raise ConfigurationError(
                    f"PLY property appears before an element declaration: {path}"
                )
            if len(fields) == 3:
                scalar_type = fields[1].casefold()
                if scalar_type not in _PLY_SCALARS:
                    raise ConfigurationError(
                        f"Unsupported PLY scalar type {fields[1]!r}: {path}"
                    )
                current.append(_PlyProperty(fields[2], scalar_type, None, None))
            elif len(fields) == 5 and fields[1] == "list":
                count_type = fields[2].casefold()
                item_type = fields[3].casefold()
                if count_type not in _PLY_SCALARS or item_type not in _PLY_SCALARS:
                    raise ConfigurationError(f"Unsupported PLY list type: {path}")
                if not _PLY_SCALARS[count_type][2]:
                    raise ConfigurationError(
                        f"PLY list count type must be an integer: {path}"
                    )
                current.append(
                    _PlyProperty(fields[4], None, count_type, item_type)
                )
            else:
                raise ConfigurationError(f"Malformed PLY property declaration: {path}")
    if encoding is None:
        raise ConfigurationError(f"PLY format declaration is missing: {path}")
    return (
        encoding,
        tuple(
            _PlyElement(name, count, tuple(properties))
            for name, count, properties in elements
        ),
        offset,
    )


def _ply_scalar_text(token: str, type_name: str, path: Path) -> int | float:
    try:
        return int(token) if _PLY_SCALARS[type_name][2] else float(token)
    except ValueError as error:
        raise ConfigurationError(
            f"PLY payload contains a non-numeric {type_name} value: {path}"
        ) from error


def _read_ply_ascii(
    payload: bytes,
    elements: tuple[_PlyElement, ...],
    path: Path,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    try:
        lines = iter(payload.decode("ascii").splitlines())
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"ASCII PLY payload is not ASCII text: {path}") from error
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for element in elements:
        for _ in range(element.count):
            try:
                tokens = next(lines).split()
            except StopIteration as error:
                raise ConfigurationError(f"ASCII PLY payload is truncated: {path}") from error
            cursor = 0
            values: dict[str, int | float | list[int | float]] = {}
            for prop in element.properties:
                if prop.scalar_type is not None:
                    if cursor >= len(tokens):
                        raise ConfigurationError(f"ASCII PLY record is truncated: {path}")
                    values[prop.name] = _ply_scalar_text(
                        tokens[cursor], prop.scalar_type, path
                    )
                    cursor += 1
                else:
                    assert prop.count_type is not None
                    assert prop.item_type is not None
                    if cursor >= len(tokens):
                        raise ConfigurationError(f"ASCII PLY list is truncated: {path}")
                    count_value = _ply_scalar_text(
                        tokens[cursor], prop.count_type, path
                    )
                    cursor += 1
                    if not isinstance(count_value, int) or count_value < 0:
                        raise ConfigurationError(f"Invalid ASCII PLY list count: {path}")
                    end = cursor + count_value
                    if end > len(tokens):
                        raise ConfigurationError(f"ASCII PLY list is truncated: {path}")
                    values[prop.name] = [
                        _ply_scalar_text(token, prop.item_type, path)
                        for token in tokens[cursor:end]
                    ]
                    cursor = end
            if cursor != len(tokens):
                raise ConfigurationError(
                    f"ASCII PLY record contains undeclared values: {path}"
                )
            _capture_ply_record(element.name, values, vertices, triangles, path)
    if any(line.strip() for line in lines):
        raise ConfigurationError(f"ASCII PLY contains undeclared trailing records: {path}")
    return vertices, triangles


def _unpack_ply_scalar(
    payload: bytes,
    offset: int,
    type_name: str,
    endian: str,
    path: Path,
) -> tuple[int | float, int]:
    code, width, integral = _PLY_SCALARS[type_name]
    end = offset + width
    if end > len(payload):
        raise ConfigurationError(f"Binary PLY payload is truncated: {path}")
    value = struct.unpack_from(endian + code, payload, offset)[0]
    return (int(value) if integral else float(value)), end


def _read_ply_binary(
    payload: bytes,
    elements: tuple[_PlyElement, ...],
    path: Path,
    *,
    endian: str,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    offset = 0
    for element in elements:
        for _ in range(element.count):
            values: dict[str, int | float | list[int | float]] = {}
            for prop in element.properties:
                if prop.scalar_type is not None:
                    value, offset = _unpack_ply_scalar(
                        payload, offset, prop.scalar_type, endian, path
                    )
                    values[prop.name] = value
                else:
                    assert prop.count_type is not None
                    assert prop.item_type is not None
                    count_value, offset = _unpack_ply_scalar(
                        payload, offset, prop.count_type, endian, path
                    )
                    if not isinstance(count_value, int) or count_value < 0:
                        raise ConfigurationError(f"Invalid binary PLY list count: {path}")
                    items: list[int | float] = []
                    for _ in range(count_value):
                        item, offset = _unpack_ply_scalar(
                            payload, offset, prop.item_type, endian, path
                        )
                        items.append(item)
                    values[prop.name] = items
            _capture_ply_record(element.name, values, vertices, triangles, path)
    if offset != len(payload):
        raise ConfigurationError(f"Binary PLY contains undeclared trailing bytes: {path}")
    return vertices, triangles


def _capture_ply_record(
    element_name: str,
    values: dict[str, int | float | list[int | float]],
    vertices: list[tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    path: Path,
) -> None:
    if element_name == "vertex":
        try:
            coordinates = (float(values["x"]), float(values["y"]), float(values["z"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ConfigurationError(
                f"PLY vertex element must define scalar x, y, and z properties: {path}"
            ) from error
        vertices.append(coordinates)
    elif element_name == "face":
        indices_value = values.get("vertex_indices", values.get("vertex_index"))
        if not isinstance(indices_value, list):
            raise ConfigurationError(
                f"PLY face element must define a vertex_indices list: {path}"
            )
        if len(indices_value) != 3:
            raise ConfigurationError(
                "PLY input must contain exclusively triangular faces; "
                f"found a face with {len(indices_value)} vertices: {path}"
            )
        if any(not isinstance(value, int) for value in indices_value):
            raise ConfigurationError(f"PLY face indices must be integers: {path}")
        triangles.append(tuple(indices_value))


def _read_ply(raw: bytes, path: Path) -> tuple[TriangleMesh, str, str]:
    encoding, elements, payload_offset = _ply_header(raw, path)
    if not any(element.name == "vertex" for element in elements):
        raise ConfigurationError(f"PLY vertex element is missing: {path}")
    if not any(element.name == "face" for element in elements):
        raise ConfigurationError(f"PLY face element is missing: {path}")
    payload = raw[payload_offset:]
    if encoding == "ascii":
        vertices, triangles = _read_ply_ascii(payload, elements, path)
    else:
        vertices, triangles = _read_ply_binary(
            payload,
            elements,
            path,
            endian="<" if encoding == "binary_little_endian" else ">",
        )
    return (
        _validated_geometry(vertices, triangles, path),
        encoding,
        "indexed PLY vertices and triangular faces; non-geometric properties ignored",
    )


_ASCII_STL_VERTEX_RE = re.compile(
    r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)


def _indexed_stl_geometry(
    facet_vertices: list[tuple[float, float, float]],
    path: Path,
) -> TriangleMesh:
    if not facet_vertices or len(facet_vertices) % 3:
        raise ConfigurationError(f"STL contains an incomplete triangle facet: {path}")
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    indices: dict[tuple[float, float, float], int] = {}
    for start in range(0, len(facet_vertices), 3):
        triangle: list[int] = []
        for raw_vertex in facet_vertices[start : start + 3]:
            vertex = tuple(0.0 if value == 0.0 else value for value in raw_vertex)
            index = indices.get(vertex)
            if index is None:
                index = len(vertices)
                indices[vertex] = index
                vertices.append(vertex)
            triangle.append(index)
        triangles.append(tuple(triangle))
    return _validated_geometry(vertices, triangles, path)


def _read_stl(raw: bytes, path: Path) -> tuple[TriangleMesh, str, str]:
    is_binary = False
    triangle_count = 0
    if len(raw) >= 84:
        triangle_count = struct.unpack_from("<I", raw, 80)[0]
        is_binary = 84 + triangle_count * 50 == len(raw)
    facet_vertices: list[tuple[float, float, float]] = []
    if is_binary:
        for index in range(triangle_count):
            offset = 84 + index * 50
            values = struct.unpack_from("<12fH", raw, offset)
            facet_vertices.extend(
                (
                    (float(values[3]), float(values[4]), float(values[5])),
                    (float(values[6]), float(values[7]), float(values[8])),
                    (float(values[9]), float(values[10]), float(values[11])),
                )
            )
        encoding = "binary_little_endian"
    else:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as error:
            raise ConfigurationError(
                f"STL is neither a complete binary STL nor ASCII text: {path}"
            ) from error
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _ASCII_STL_VERTEX_RE.match(line)
            if match is None:
                continue
            try:
                facet_vertices.append(tuple(float(value) for value in match.groups()))
            except ValueError as error:
                raise ConfigurationError(
                    f"ASCII STL vertex on line {line_number} is not numeric: {path}"
                ) from error
        encoding = "ascii"
    return (
        _indexed_stl_geometry(facet_vertices, path),
        encoding,
        "STL facet coordinates deduplicated exactly into indexed triangle vertices",
    )


def load_surface_mesh(path: Path | str) -> LoadedSurfaceMesh:
    """Read one supported triangle surface and derive format-bound metadata."""

    source = Path(path).expanduser().resolve()
    suffix = source.suffix.casefold()
    if suffix not in SUPPORTED_SURFACE_EXTENSIONS:
        raise ConfigurationError(
            f"Unsupported surface format {source.suffix or '<none>'!r}: {source}. "
            "Supported inputs are VTK, PLY, OBJ, and STL."
        )
    try:
        raw = source.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read surface mesh {source}: {error}") from error
    if not raw:
        raise ConfigurationError(f"Surface mesh is empty: {source}")

    if suffix == ".vtk":
        vtk_metadata = inspect_vtk(source)
        geometry = read_vtk_polydata(source)
        source_format: SurfaceFormat = "legacy_vtk"
        encoding = vtk_metadata.encoding.casefold()
        topology_note = "legacy VTK PolyData vertices and triangular polygons"
    elif suffix == ".obj":
        geometry, encoding, topology_note = _read_obj(raw, source)
        source_format = "obj"
    elif suffix == ".ply":
        geometry, encoding, topology_note = _read_ply(raw, source)
        source_format = "ply"
    else:
        geometry, encoding, topology_note = _read_stl(raw, source)
        source_format = "stl"

    bounds, extents, diagonal = _bounds(geometry.vertices, source)
    metadata = SurfaceMeshMetadata(
        path=str(source),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        source_format=source_format,
        encoding=encoding,
        points=len(geometry.vertices),
        triangles=len(geometry.triangles),
        bounds=bounds,
        bounding_box_extents=extents,
        bounding_box_diagonal=diagonal,
        topology_note=topology_note,
    )
    return LoadedSurfaceMesh(metadata=metadata, geometry=geometry)


def inspect_surface_mesh(path: Path | str) -> SurfaceMeshMetadata:
    """Return format-independent source metadata for one supported mesh."""

    return load_surface_mesh(path).metadata


def read_surface_mesh(path: Path | str) -> TriangleMesh:
    """Return triangle geometry from VTK, PLY, OBJ, or STL."""

    return load_surface_mesh(path).geometry
