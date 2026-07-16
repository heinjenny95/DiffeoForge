"""Dependency-free preflight inspection for legacy VTK surface meshes."""

from __future__ import annotations

import hashlib
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from numbers import Integral, Real
from pathlib import Path

from diffeoforge.config import ConfigurationError, InputSummary

_HEADER_RE = re.compile(rb"\A# vtk DataFile Version\s+([^\r\n]+)", re.IGNORECASE)
_ENCODING_RE = re.compile(rb"(?:\A|\r?\n)(ASCII|BINARY)\r?\n", re.IGNORECASE)
_DATASET_RE = re.compile(rb"(?:\A|\r?\n)DATASET\s+(\S+)\r?\n", re.IGNORECASE)
_POINTS_RE = re.compile(
    rb"(?:\A|\r?\n)POINTS\s+(\d+)\s+(float|double)[ \t]*\r?\n",
    re.IGNORECASE,
)
_POLYGONS_RE = re.compile(
    rb"(?:\A|\r?\n)POLYGONS\s+(\d+)\s+(\d+)(?:\r?\n|\s)",
    re.IGNORECASE,
)
_OFFSETS_RE = re.compile(
    rb"OFFSETS\s+(vtktypeint32|vtktypeint64|int|long)[ \t]*\r?\n",
    re.IGNORECASE,
)
_CONNECTIVITY_RE = re.compile(
    rb"\r?\nCONNECTIVITY\s+(vtktypeint32|vtktypeint64|int|long)[ \t]*\r?\n",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MeshMetadata:
    """Observable geometry and integrity metadata for one VTK mesh."""

    path: str
    bytes: int
    sha256: str
    vtk_version: str
    encoding: str
    dataset_type: str
    points: int
    cells: int
    triangular: bool
    bounds: tuple[float, float, float, float, float, float]
    bounding_box_extents: tuple[float, float, float]
    bounding_box_diagonal: float

    def as_manifest(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        value = asdict(self)
        value["bounds"] = list(self.bounds)
        value["bounding_box_extents"] = list(self.bounding_box_extents)
        return value


@dataclass(frozen=True)
class TriangleMesh:
    """Complete dependency-free geometry from one supported VTK surface."""

    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounds_from_values(values: list[float], path: Path) -> tuple[float, ...]:
    if not values or len(values) % 3:
        raise ConfigurationError(f"VTK point coordinates are incomplete: {path}")

    minima = [math.inf, math.inf, math.inf]
    maxima = [-math.inf, -math.inf, -math.inf]
    for index, value in enumerate(values):
        if not math.isfinite(value):
            raise ConfigurationError(f"VTK mesh contains non-finite coordinates: {path}")
        axis = index % 3
        minima[axis] = min(minima[axis], value)
        maxima[axis] = max(maxima[axis], value)
    return (
        minima[0],
        maxima[0],
        minima[1],
        maxima[1],
        minima[2],
        maxima[2],
    )


def _read_point_values(
    raw: bytes,
    points_match: re.Match[bytes],
    point_count: int,
    scalar_type: str,
    encoding: str,
    path: Path,
) -> list[float]:
    start = points_match.end()
    value_count = point_count * 3
    if encoding == "BINARY":
        width = 4 if scalar_type == "float" else 8
        end = start + value_count * width
        payload = raw[start:end]
        if len(payload) != value_count * width:
            raise ConfigurationError(f"Binary VTK point payload is truncated: {path}")
        format_code = ">f" if scalar_type == "float" else ">d"
        return [value[0] for value in struct.iter_unpack(format_code, payload)]

    polygons_match = _POLYGONS_RE.search(raw, start)
    point_text_end = polygons_match.start() if polygons_match else len(raw)
    try:
        tokens = raw[start:point_text_end].decode("ascii").split()
        values = [float(token) for token in tokens[:value_count]]
    except (UnicodeDecodeError, ValueError) as error:
        raise ConfigurationError(f"Could not parse ASCII VTK points: {path}") from error
    if len(values) != value_count:
        raise ConfigurationError(f"ASCII VTK point payload is truncated: {path}")
    return values


def _integer_width(type_name: bytes, path: Path) -> int:
    normalized = type_name.decode("ascii").lower()
    if normalized in {"vtktypeint32", "int"}:
        return 4
    if normalized in {"vtktypeint64", "long"}:
        return 8
    raise ConfigurationError(f"Unsupported VTK integer type {normalized!r}: {path}")


def _read_vtk51_offsets(
    raw: bytes,
    polygons_match: re.Match[bytes],
    offset_count: int,
    connectivity_count: int,
    encoding: str,
    path: Path,
) -> tuple[int, bool] | None:
    """Read VTK 5.1 split-cell arrays, or return None for classic POLYGONS."""

    offsets_match = _OFFSETS_RE.match(raw, polygons_match.end())
    if offsets_match is None:
        return None
    if offset_count < 2:
        raise ConfigurationError(f"VTK 5.1 POLYGONS contain no cells: {path}")

    if encoding == "BINARY":
        width = _integer_width(offsets_match.group(1), path)
        payload_start = offsets_match.end()
        payload_end = payload_start + offset_count * width
        payload = raw[payload_start:payload_end]
        if len(payload) != offset_count * width:
            raise ConfigurationError(f"Binary VTK OFFSETS payload is truncated: {path}")
        format_code = ">i" if width == 4 else ">q"
        offsets = [value[0] for value in struct.iter_unpack(format_code, payload)]
        connectivity_match = _CONNECTIVITY_RE.match(raw, payload_end)
    else:
        connectivity_match = _CONNECTIVITY_RE.search(raw, offsets_match.end())
        if connectivity_match is None:
            raise ConfigurationError(f"VTK 5.1 CONNECTIVITY section is missing: {path}")
        try:
            offsets = [
                int(token)
                for token in raw[offsets_match.end() : connectivity_match.start()]
                .decode("ascii")
                .split()
            ]
        except (UnicodeDecodeError, ValueError) as error:
            raise ConfigurationError(f"Could not parse ASCII VTK OFFSETS: {path}") from error

    if connectivity_match is None:
        raise ConfigurationError(f"VTK 5.1 CONNECTIVITY section is missing: {path}")
    if len(offsets) != offset_count:
        raise ConfigurationError(
            f"VTK 5.1 expected {offset_count} offsets, found {len(offsets)}: {path}"
        )
    if offsets[0] != 0 or offsets[-1] != connectivity_count:
        raise ConfigurationError(
            f"VTK 5.1 offsets do not span the declared connectivity array: {path}"
        )

    cell_sizes = [end - start for start, end in zip(offsets[:-1], offsets[1:], strict=True)]
    if any(size <= 0 for size in cell_sizes):
        raise ConfigurationError(f"VTK 5.1 contains invalid polygon offsets: {path}")
    return len(cell_sizes), all(size == 3 for size in cell_sizes)


def inspect_vtk(path: Path | str) -> MeshMetadata:
    """Validate and inventory one legacy VTK triangular PolyData mesh.

    Legacy binary VTK coordinates are big-endian by specification. Reading the
    coordinates directly keeps the core preflight independent from heavyweight
    visualization packages while still checking real geometry rather than only
    the filename or header.
    """

    mesh_path = Path(path).resolve()
    try:
        raw = mesh_path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read VTK mesh {mesh_path}: {error}") from error

    header = _HEADER_RE.search(raw)
    encoding_match = _ENCODING_RE.search(raw[:1024])
    dataset_match = _DATASET_RE.search(raw[:2048])
    points_match = _POINTS_RE.search(raw)
    polygons_match = _POLYGONS_RE.search(raw)
    if not all((header, encoding_match, dataset_match, points_match, polygons_match)):
        raise ConfigurationError(
            f"VTK mesh must be legacy PolyData with POINTS and POLYGONS sections: {mesh_path}"
        )

    assert header is not None
    assert encoding_match is not None
    assert dataset_match is not None
    assert points_match is not None
    assert polygons_match is not None

    dataset_type = dataset_match.group(1).decode("ascii").upper()
    if dataset_type != "POLYDATA":
        raise ConfigurationError(f"VTK dataset must be POLYDATA, got {dataset_type}: {mesh_path}")

    encoding = encoding_match.group(1).decode("ascii").upper()
    point_count = int(points_match.group(1))
    polygon_header_count = int(polygons_match.group(1))
    connectivity_size = int(polygons_match.group(2))
    if point_count <= 0 or polygon_header_count <= 0:
        raise ConfigurationError(f"VTK mesh contains no points or polygons: {mesh_path}")

    scalar_type = points_match.group(2).decode("ascii").lower()
    values = _read_point_values(
        raw,
        points_match,
        point_count,
        scalar_type,
        encoding,
        mesh_path,
    )
    bounds = _bounds_from_values(values, mesh_path)
    extents = (
        bounds[1] - bounds[0],
        bounds[3] - bounds[2],
        bounds[5] - bounds[4],
    )
    diagonal = math.sqrt(sum(value * value for value in extents))
    if diagonal <= 0:
        raise ConfigurationError(f"VTK mesh has a degenerate bounding box: {mesh_path}")

    vtk51_cells = _read_vtk51_offsets(
        raw,
        polygons_match,
        polygon_header_count,
        connectivity_size,
        encoding,
        mesh_path,
    )
    if vtk51_cells is None:
        cell_count = polygon_header_count
        triangular = connectivity_size == cell_count * 4
    else:
        cell_count, triangular = vtk51_cells
    if not triangular:
        raise ConfigurationError(
            "VTK POLYGONS are not exclusively triangular "
            f"({cell_count} cells, connectivity size {connectivity_size}): {mesh_path}"
        )

    return MeshMetadata(
        path=str(mesh_path),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        vtk_version=header.group(1).decode("ascii").strip(),
        encoding=encoding,
        dataset_type=dataset_type,
        points=point_count,
        cells=cell_count,
        triangular=triangular,
        bounds=tuple(float(value) for value in bounds),
        bounding_box_extents=tuple(float(value) for value in extents),
        bounding_box_diagonal=float(diagonal),
    )


def read_vtk_points(path: Path | str) -> tuple[tuple[float, float, float], ...]:
    """Return point coordinates from a supported legacy VTK PolyData mesh."""

    mesh_path = Path(path).resolve()
    try:
        raw = mesh_path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read VTK mesh {mesh_path}: {error}") from error

    encoding_match = _ENCODING_RE.search(raw[:1024])
    points_match = _POINTS_RE.search(raw)
    if encoding_match is None or points_match is None:
        raise ConfigurationError(f"VTK mesh has no readable POINTS section: {mesh_path}")

    encoding = encoding_match.group(1).decode("ascii").upper()
    point_count = int(points_match.group(1))
    scalar_type = points_match.group(2).decode("ascii").lower()
    values = _read_point_values(
        raw,
        points_match,
        point_count,
        scalar_type,
        encoding,
        mesh_path,
    )
    _bounds_from_values(values, mesh_path)
    return tuple(
        (values[index], values[index + 1], values[index + 2]) for index in range(0, len(values), 3)
    )


def _read_integer_payload(
    raw: bytes,
    *,
    start: int,
    count: int,
    width: int,
    encoding: str,
    path: Path,
    label: str,
) -> tuple[list[int], int]:
    if encoding == "BINARY":
        end = start + count * width
        payload = raw[start:end]
        if len(payload) != count * width:
            raise ConfigurationError(f"Binary VTK {label} payload is truncated: {path}")
        format_code = ">i" if width == 4 else ">q"
        return [value[0] for value in struct.iter_unpack(format_code, payload)], end
    try:
        tokens = raw[start:].decode("ascii").split()
        values = [int(token) for token in tokens[:count]]
    except (UnicodeDecodeError, ValueError) as error:
        raise ConfigurationError(f"Could not parse ASCII VTK {label}: {path}") from error
    if len(values) != count:
        raise ConfigurationError(f"ASCII VTK {label} payload is truncated: {path}")
    return values, len(raw)


def _read_vtk_triangles(
    raw: bytes,
    polygons_match: re.Match[bytes],
    point_count: int,
    encoding: str,
    path: Path,
) -> tuple[tuple[int, int, int], ...]:
    header_count = int(polygons_match.group(1))
    connectivity_count = int(polygons_match.group(2))
    offsets_match = _OFFSETS_RE.match(raw, polygons_match.end())
    triangles: list[tuple[int, int, int]] = []

    if offsets_match is None:
        values, _ = _read_integer_payload(
            raw,
            start=polygons_match.end(),
            count=connectivity_count,
            width=4,
            encoding=encoding,
            path=path,
            label="POLYGONS",
        )
        cursor = 0
        for _ in range(header_count):
            if cursor >= len(values) or values[cursor] != 3:
                raise ConfigurationError(f"VTK POLYGONS are not exclusively triangular: {path}")
            if cursor + 4 > len(values):
                raise ConfigurationError(f"VTK POLYGONS payload is truncated: {path}")
            triangles.append(tuple(values[cursor + 1 : cursor + 4]))
            cursor += 4
        if cursor != connectivity_count:
            raise ConfigurationError(f"VTK POLYGONS size does not match the declared cells: {path}")
    else:
        offset_width = _integer_width(offsets_match.group(1), path)
        if encoding == "BINARY":
            offsets, offsets_end = _read_integer_payload(
                raw,
                start=offsets_match.end(),
                count=header_count,
                width=offset_width,
                encoding=encoding,
                path=path,
                label="OFFSETS",
            )
            connectivity_match = _CONNECTIVITY_RE.match(raw, offsets_end)
        else:
            connectivity_match = _CONNECTIVITY_RE.search(raw, offsets_match.end())
            if connectivity_match is None:
                raise ConfigurationError(f"VTK 5.1 CONNECTIVITY section is missing: {path}")
            try:
                offsets = [
                    int(token)
                    for token in raw[offsets_match.end() : connectivity_match.start()]
                    .decode("ascii")
                    .split()
                ]
            except (UnicodeDecodeError, ValueError) as error:
                raise ConfigurationError(f"Could not parse ASCII VTK OFFSETS: {path}") from error
        if connectivity_match is None:
            raise ConfigurationError(f"VTK 5.1 CONNECTIVITY section is missing: {path}")
        if len(offsets) != header_count:
            raise ConfigurationError(
                f"VTK 5.1 expected {header_count} offsets, found {len(offsets)}: {path}"
            )
        if len(offsets) < 2 or offsets[0] != 0 or offsets[-1] != connectivity_count:
            raise ConfigurationError(
                f"VTK 5.1 offsets do not span the declared connectivity array: {path}"
            )
        connectivity_width = _integer_width(connectivity_match.group(1), path)
        connectivity, _ = _read_integer_payload(
            raw,
            start=connectivity_match.end(),
            count=connectivity_count,
            width=connectivity_width,
            encoding=encoding,
            path=path,
            label="CONNECTIVITY",
        )
        for start, end in zip(offsets[:-1], offsets[1:], strict=True):
            if end - start != 3:
                raise ConfigurationError(f"VTK POLYGONS are not exclusively triangular: {path}")
            triangles.append(tuple(connectivity[start:end]))

    for triangle in triangles:
        if min(triangle) < 0 or max(triangle) >= point_count:
            raise ConfigurationError(f"VTK triangle index is out of range: {path}")
        if len(set(triangle)) != 3:
            raise ConfigurationError(f"VTK triangle contains a repeated vertex index: {path}")
    if not triangles:
        raise ConfigurationError(f"VTK mesh contains no triangles: {path}")
    return tuple(triangles)


def read_vtk_polydata(path: Path | str) -> TriangleMesh:
    """Return vertices and triangle connectivity from supported legacy VTK PolyData."""

    mesh_path = Path(path).resolve()
    metadata = inspect_vtk(mesh_path)
    try:
        raw = mesh_path.read_bytes()
    except OSError as error:
        raise ConfigurationError(f"Could not read VTK mesh {mesh_path}: {error}") from error
    encoding_match = _ENCODING_RE.search(raw[:1024])
    polygons_match = _POLYGONS_RE.search(raw)
    if encoding_match is None or polygons_match is None:
        raise ConfigurationError(f"VTK mesh has no readable POLYGONS section: {mesh_path}")
    triangles = _read_vtk_triangles(
        raw,
        polygons_match,
        metadata.points,
        encoding_match.group(1).decode("ascii").upper(),
        mesh_path,
    )
    if len(triangles) != metadata.cells:
        raise ConfigurationError(
            f"VTK triangle count changed between inspection and parsing: {mesh_path}"
        )
    return TriangleMesh(vertices=read_vtk_points(mesh_path), triangles=triangles)


def write_vtk_polydata(
    path: Path | str,
    vertices: Sequence[Sequence[Real]],
    triangles: Sequence[Sequence[Integral]],
    *,
    title: str = "DiffeoForge surface",
) -> Path:
    """Write deterministic, exclusive ASCII legacy VTK triangular PolyData."""

    destination = Path(path).resolve()
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("title must be a non-empty single line")
    try:
        title.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("title must contain only ASCII characters") from error
    try:
        normalized_vertices = tuple(
            tuple(float(coordinate) for coordinate in vertex) for vertex in vertices
        )
    except (TypeError, ValueError) as error:
        raise TypeError("vertices must be a sequence of numeric rows") from error
    if not normalized_vertices or any(len(vertex) != 3 for vertex in normalized_vertices):
        raise ValueError("vertices must have shape (n, 3)")
    if not all(math.isfinite(value) for vertex in normalized_vertices for value in vertex):
        raise ValueError("vertices must contain only finite values")

    normalized_triangles: list[tuple[int, int, int]] = []
    try:
        for triangle in triangles:
            if len(triangle) != 3:
                raise ValueError("triangles must have shape (n, 3)")
            if any(
                isinstance(index, bool) or not isinstance(index, Integral) for index in triangle
            ):
                raise TypeError("triangle indices must be integers")
            normalized_triangles.append(tuple(int(index) for index in triangle))
    except TypeError as error:
        if "triangle indices" in str(error):
            raise
        raise TypeError("triangles must be a sequence of integer rows") from error
    if not normalized_triangles:
        raise ValueError("triangles must contain at least one face")
    maximum_index = len(normalized_vertices) - 1
    for triangle in normalized_triangles:
        if min(triangle) < 0 or max(triangle) > maximum_index:
            raise ValueError("triangles contain an out-of-range vertex index")
        if len(set(triangle)) != 3:
            raise ValueError("triangles contain a repeated vertex index")

    def coordinate(value: float) -> str:
        return format(0.0 if value == 0.0 else value, ".17g")

    lines = [
        "# vtk DataFile Version 3.0",
        title.strip(),
        "ASCII",
        "DATASET POLYDATA",
        f"POINTS {len(normalized_vertices)} double",
        *(" ".join(coordinate(value) for value in vertex) for vertex in normalized_vertices),
        f"POLYGONS {len(normalized_triangles)} {len(normalized_triangles) * 4}",
        *(f"3 {a} {b} {c}" for a, b, c in normalized_triangles),
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="ascii", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return destination


def inspect_inputs(summary: InputSummary) -> tuple[MeshMetadata, tuple[MeshMetadata, ...]]:
    """Inspect the template and every selected subject in stable order."""

    template = inspect_vtk(summary.template)
    subjects = tuple(inspect_vtk(path) for path in summary.subjects)
    return template, subjects
