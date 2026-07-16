"""Deterministic quality evidence for triangular surface meshes."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from numbers import Integral, Real

QUALITY_DEFINITIONS_VERSION = "0.1"
QUANTILE_METHOD = "linear interpolation at sorted index (n - 1) * q"
QUALITY_BOUNDARY = (
    "Edge topology and triangle-shape diagnostics only. This assessment does not "
    "detect triangle-triangle self-intersections, non-manifold vertices whose incident "
    "edges are individually manifold, global embedding validity, anatomical plausibility, "
    "registration quality, or Deformetrica equivalence."
)


class MeshQualityError(ValueError):
    """Raised when a declared mesh-quality gate fails."""


@dataclass(frozen=True)
class MetricSummary:
    """Six deterministic descriptive statistics for one finite metric."""

    minimum: float
    q05: float
    median: float
    mean: float
    q95: float
    maximum: float

    def as_manifest(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class MeshQualitySettings:
    """Explicit structural and geometric gates for modern-workflow meshes."""

    require_no_duplicate_faces: bool = True
    require_no_isolated_vertices: bool = True
    require_edge_manifold: bool = True
    require_consistent_orientation: bool = True
    require_single_component: bool = False
    require_closed_surface: bool = False
    reject_zero_area_faces: bool = True
    minimum_triangle_angle_degrees: float | None = None
    maximum_triangle_edge_ratio: float | None = None
    minimum_face_area_ratio: float | None = None
    maximum_face_area_ratio: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "require_no_duplicate_faces",
            "require_no_isolated_vertices",
            "require_edge_manifold",
            "require_consistent_orientation",
            "require_single_component",
            "require_closed_surface",
            "reject_zero_area_faces",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        minimum_angle = _optional_finite(
            "minimum_triangle_angle_degrees",
            self.minimum_triangle_angle_degrees,
            minimum=0.0,
            inclusive=False,
        )
        if minimum_angle is not None and minimum_angle > 60.0:
            raise ValueError("minimum_triangle_angle_degrees cannot exceed 60")
        maximum_edge_ratio = _optional_finite(
            "maximum_triangle_edge_ratio",
            self.maximum_triangle_edge_ratio,
            minimum=1.0,
            inclusive=True,
        )
        minimum_area_ratio = _optional_finite(
            "minimum_face_area_ratio",
            self.minimum_face_area_ratio,
            minimum=0.0,
            inclusive=False,
        )
        maximum_area_ratio = _optional_finite(
            "maximum_face_area_ratio",
            self.maximum_face_area_ratio,
            minimum=0.0,
            inclusive=False,
        )
        if (
            minimum_area_ratio is not None
            and maximum_area_ratio is not None
            and minimum_area_ratio > maximum_area_ratio
        ):
            raise ValueError(
                "minimum_face_area_ratio cannot exceed maximum_face_area_ratio"
            )
        object.__setattr__(self, "minimum_triangle_angle_degrees", minimum_angle)
        object.__setattr__(self, "maximum_triangle_edge_ratio", maximum_edge_ratio)
        object.__setattr__(self, "minimum_face_area_ratio", minimum_area_ratio)
        object.__setattr__(self, "maximum_face_area_ratio", maximum_area_ratio)

    def as_manifest(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: object) -> MeshQualitySettings:
        if not isinstance(value, Mapping):
            raise TypeError("quality_control must be a mapping")
        return cls(**dict(value))


@dataclass(frozen=True)
class MeshQualityResult:
    """Topology counts and geometry distributions for one triangular mesh."""

    points: int
    triangles: int
    unique_edges: int
    connectivity_sha256: str
    isolated_vertices: int
    duplicate_faces: int
    boundary_edges: int
    manifold_edges: int
    nonmanifold_edges: int
    face_connected_components: int
    euler_characteristic: int
    inconsistently_oriented_manifold_edges: int
    zero_area_faces: int
    zero_length_edge_faces: int
    undefined_angle_faces: int
    bounding_box_diagonal: float
    total_surface_area: float
    minimum_area_over_bbox_diagonal_squared: float
    triangle_area: MetricSummary
    minimum_angle_degrees: MetricSummary | None
    edge_ratio: MetricSummary | None

    def as_manifest(self) -> dict[str, object]:
        value = asdict(self)
        value["definitions_version"] = QUALITY_DEFINITIONS_VERSION
        value["quantile_method"] = QUANTILE_METHOD
        value["scientific_boundary"] = QUALITY_BOUNDARY
        return value


@dataclass(frozen=True)
class MeshDeformationQuality:
    """Local triangle-area change relative to a mesh with identical connectivity."""

    connectivity_identical: bool
    zero_reference_area_faces: int
    face_area_ratio: MetricSummary | None

    def as_manifest(self) -> dict[str, object]:
        return asdict(self)


def _optional_finite(
    name: str,
    value: float | None,
    *,
    minimum: float,
    inclusive: bool,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar or None")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    invalid = normalized < minimum if inclusive else normalized <= minimum
    if invalid:
        operator = "at least" if inclusive else "greater than"
        raise ValueError(f"{name} must be {operator} {minimum}")
    return normalized


def _normalized_geometry(
    vertices: Sequence[Sequence[Real]],
    triangles: Sequence[Sequence[Integral]],
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int], ...]]:
    if not isinstance(vertices, Sequence) or isinstance(vertices, (str, bytes)):
        raise TypeError("vertices must be a sequence")
    if not isinstance(triangles, Sequence) or isinstance(triangles, (str, bytes)):
        raise TypeError("triangles must be a sequence")
    normalized_vertices: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if not isinstance(vertex, Sequence) or len(vertex) != 3:
            raise ValueError("vertices must have shape (points, 3)")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in vertex):
            raise TypeError("vertex coordinates must be real scalars")
        point = tuple(float(value) for value in vertex)
        if not all(math.isfinite(value) for value in point):
            raise ValueError("vertex coordinates must be finite")
        normalized_vertices.append(point)  # type: ignore[arg-type]
    if not normalized_vertices:
        raise ValueError("vertices must contain at least one point")

    normalized_triangles: list[tuple[int, int, int]] = []
    for triangle in triangles:
        if not isinstance(triangle, Sequence) or len(triangle) != 3:
            raise ValueError("triangles must have shape (faces, 3)")
        if any(isinstance(index, bool) or not isinstance(index, Integral) for index in triangle):
            raise TypeError("triangle indices must be integers")
        face = tuple(int(index) for index in triangle)
        if len(set(face)) != 3:
            raise ValueError("triangles must not repeat a vertex index")
        if min(face) < 0 or max(face) >= len(normalized_vertices):
            raise ValueError("triangles contain an out-of-range vertex index")
        normalized_triangles.append(face)  # type: ignore[arg-type]
    if not normalized_triangles:
        raise ValueError("triangles must contain at least one face")
    return tuple(normalized_vertices), tuple(normalized_triangles)


def _quantile(sorted_values: list[float], q: float) -> float:
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _summary(values: list[float]) -> MetricSummary | None:
    if not values:
        return None
    if not all(math.isfinite(value) for value in values):
        raise ValueError("metric values must be finite")
    ordered = sorted(values)
    return MetricSummary(
        minimum=ordered[0],
        q05=_quantile(ordered, 0.05),
        median=_quantile(ordered, 0.5),
        mean=math.fsum(ordered) / len(ordered),
        q95=_quantile(ordered, 0.95),
        maximum=ordered[-1],
    )


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _subtract(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(value: tuple[float, ...]) -> float:
    return math.sqrt(math.fsum(coordinate * coordinate for coordinate in value))


def _triangle_area(
    vertices: tuple[tuple[float, float, float], ...],
    triangle: tuple[int, int, int],
) -> float:
    a, b, c = (vertices[index] for index in triangle)
    return 0.5 * _norm(_cross(_subtract(b, a), _subtract(c, a)))


def _minimum_angle(
    vertices: tuple[tuple[float, float, float], ...],
    triangle: tuple[int, int, int],
) -> float | None:
    points = [vertices[index] for index in triangle]
    angles: list[float] = []
    for index in range(3):
        center = points[index]
        first = _subtract(points[(index + 1) % 3], center)
        second = _subtract(points[(index + 2) % 3], center)
        denominator = _norm(first) * _norm(second)
        if denominator == 0.0:
            return None
        cosine = math.fsum(a * b for a, b in zip(first, second, strict=True)) / denominator
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return min(angles)


def _connectivity_sha256(triangles: tuple[tuple[int, int, int], ...]) -> str:
    digest = hashlib.sha256()
    for a, b, c in triangles:
        digest.update(f"{a},{b},{c};".encode("ascii"))
    return digest.hexdigest()


def assess_triangle_mesh(
    vertices: Sequence[Sequence[Real]],
    triangles: Sequence[Sequence[Integral]],
) -> MeshQualityResult:
    """Compute exact topology counts and deterministic triangle-quality summaries."""

    points, faces = _normalized_geometry(vertices, triangles)
    edge_faces: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    referenced_vertices: set[int] = set()
    canonical_faces: Counter[tuple[int, int, int]] = Counter()
    areas: list[float] = []
    minimum_angles: list[float] = []
    edge_ratios: list[float] = []
    zero_area_faces = 0
    zero_length_edge_faces = 0
    undefined_angle_faces = 0
    for face_index, face in enumerate(faces):
        referenced_vertices.update(face)
        canonical_faces[tuple(sorted(face))] += 1
        for start, end in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (min(start, end), max(start, end))
            direction = 1 if (start, end) == key else -1
            edge_faces[key].append((face_index, direction))
        area = _triangle_area(points, face)
        areas.append(area)
        if area == 0.0:
            zero_area_faces += 1
        lengths = [
            math.dist(points[face[0]], points[face[1]]),
            math.dist(points[face[1]], points[face[2]]),
            math.dist(points[face[2]], points[face[0]]),
        ]
        shortest = min(lengths)
        if shortest == 0.0:
            zero_length_edge_faces += 1
        else:
            edge_ratios.append(max(lengths) / shortest)
        minimum_angle = _minimum_angle(points, face)
        if minimum_angle is None:
            undefined_angle_faces += 1
        else:
            minimum_angles.append(minimum_angle)

    adjacency: list[set[int]] = [set() for _ in faces]
    boundary_edges = manifold_edges = nonmanifold_edges = 0
    inconsistent_edges = 0
    for incidences in edge_faces.values():
        if len(incidences) == 1:
            boundary_edges += 1
        elif len(incidences) == 2:
            manifold_edges += 1
            if incidences[0][1] == incidences[1][1]:
                inconsistent_edges += 1
        else:
            nonmanifold_edges += 1
        incident_faces = [face_index for face_index, _ in incidences]
        for position, face_index in enumerate(incident_faces):
            adjacency[face_index].update(incident_faces[:position])
            adjacency[face_index].update(incident_faces[position + 1 :])

    remaining = set(range(len(faces)))
    components = 0
    while remaining:
        components += 1
        queue = deque([remaining.pop()])
        while queue:
            current = queue.popleft()
            connected = adjacency[current] & remaining
            remaining.difference_update(connected)
            queue.extend(connected)

    minima = [min(point[axis] for point in points) for axis in range(3)]
    maxima = [max(point[axis] for point in points) for axis in range(3)]
    diagonal = math.sqrt(
        math.fsum(
            (high - low) ** 2 for low, high in zip(minima, maxima, strict=True)
        )
    )
    area_summary = _summary(areas)
    assert area_summary is not None
    return MeshQualityResult(
        points=len(points),
        triangles=len(faces),
        unique_edges=len(edge_faces),
        connectivity_sha256=_connectivity_sha256(faces),
        isolated_vertices=len(points) - len(referenced_vertices),
        duplicate_faces=sum(count - 1 for count in canonical_faces.values()),
        boundary_edges=boundary_edges,
        manifold_edges=manifold_edges,
        nonmanifold_edges=nonmanifold_edges,
        face_connected_components=components,
        euler_characteristic=len(points) - len(edge_faces) + len(faces),
        inconsistently_oriented_manifold_edges=inconsistent_edges,
        zero_area_faces=zero_area_faces,
        zero_length_edge_faces=zero_length_edge_faces,
        undefined_angle_faces=undefined_angle_faces,
        bounding_box_diagonal=diagonal,
        total_surface_area=math.fsum(areas),
        minimum_area_over_bbox_diagonal_squared=(
            0.0 if diagonal == 0.0 else area_summary.minimum / diagonal**2
        ),
        triangle_area=area_summary,
        minimum_angle_degrees=_summary(minimum_angles),
        edge_ratio=_summary(edge_ratios),
    )


def mesh_quality_failures(
    result: MeshQualityResult,
    settings: MeshQualitySettings,
) -> tuple[str, ...]:
    """Return every failed declared gate in stable order."""

    failures: list[str] = []
    checks = (
        (settings.require_no_duplicate_faces and result.duplicate_faces > 0, "duplicate faces"),
        (
            settings.require_no_isolated_vertices and result.isolated_vertices > 0,
            "isolated vertices",
        ),
        (settings.require_edge_manifold and result.nonmanifold_edges > 0, "non-manifold edges"),
        (
            settings.require_consistent_orientation
            and result.inconsistently_oriented_manifold_edges > 0,
            "inconsistently oriented manifold edges",
        ),
        (
            settings.require_single_component and result.face_connected_components != 1,
            "multiple face-connected components",
        ),
        (settings.require_closed_surface and result.boundary_edges > 0, "boundary edges"),
        (settings.reject_zero_area_faces and result.zero_area_faces > 0, "zero-area faces"),
    )
    failures.extend(message for failed, message in checks if failed)
    if settings.minimum_triangle_angle_degrees is not None:
        if result.minimum_angle_degrees is None:
            failures.append("undefined triangle angles")
        elif result.minimum_angle_degrees.minimum < settings.minimum_triangle_angle_degrees:
            failures.append(
                "minimum triangle angle "
                f"{result.minimum_angle_degrees.minimum:.17g} is below "
                f"{settings.minimum_triangle_angle_degrees:.17g} degrees"
            )
    if settings.maximum_triangle_edge_ratio is not None:
        if result.zero_length_edge_faces > 0 or result.edge_ratio is None:
            failures.append("undefined triangle edge ratio")
        elif result.edge_ratio.maximum > settings.maximum_triangle_edge_ratio:
            failures.append(
                "maximum triangle edge ratio "
                f"{result.edge_ratio.maximum:.17g} exceeds "
                f"{settings.maximum_triangle_edge_ratio:.17g}"
            )
    return tuple(failures)


def enforce_mesh_quality(
    label: str,
    result: MeshQualityResult,
    settings: MeshQualitySettings,
) -> None:
    failures = mesh_quality_failures(result, settings)
    if failures:
        raise MeshQualityError(f"Mesh quality gate failed for {label}: {', '.join(failures)}")


def compare_triangle_meshes(
    reference_vertices: Sequence[Sequence[Real]],
    reference_triangles: Sequence[Sequence[Integral]],
    vertices: Sequence[Sequence[Real]],
    triangles: Sequence[Sequence[Integral]],
) -> MeshDeformationQuality:
    """Summarize per-face area ratios when ordered connectivity is identical."""

    reference_points, reference_faces = _normalized_geometry(
        reference_vertices, reference_triangles
    )
    points, faces = _normalized_geometry(vertices, triangles)
    identical = reference_faces == faces and len(reference_points) == len(points)
    if not identical:
        raise ValueError("mesh comparison requires identical ordered connectivity")
    ratios: list[float] = []
    zero_reference_area_faces = 0
    for reference_face, face in zip(reference_faces, faces, strict=True):
        reference_area = _triangle_area(reference_points, reference_face)
        if reference_area == 0.0:
            zero_reference_area_faces += 1
            continue
        ratios.append(_triangle_area(points, face) / reference_area)
    return MeshDeformationQuality(
        connectivity_identical=True,
        zero_reference_area_faces=zero_reference_area_faces,
        face_area_ratio=_summary(ratios),
    )


def deformation_quality_failures(
    result: MeshDeformationQuality,
    settings: MeshQualitySettings,
) -> tuple[str, ...]:
    failures: list[str] = []
    if not result.connectivity_identical:
        failures.append("connectivity differs from the reference")
    if settings.minimum_face_area_ratio is not None:
        if result.zero_reference_area_faces or result.face_area_ratio is None:
            failures.append("undefined local face-area ratios")
        elif result.face_area_ratio.minimum < settings.minimum_face_area_ratio:
            failures.append(
                "minimum local face-area ratio "
                f"{result.face_area_ratio.minimum:.17g} is below "
                f"{settings.minimum_face_area_ratio:.17g}"
            )
    if settings.maximum_face_area_ratio is not None:
        if result.zero_reference_area_faces or result.face_area_ratio is None:
            failures.append("undefined local face-area ratios")
        elif result.face_area_ratio.maximum > settings.maximum_face_area_ratio:
            failures.append(
                "maximum local face-area ratio "
                f"{result.face_area_ratio.maximum:.17g} exceeds "
                f"{settings.maximum_face_area_ratio:.17g}"
            )
    return tuple(failures)


def enforce_deformation_quality(
    label: str,
    result: MeshDeformationQuality,
    settings: MeshQualitySettings,
) -> None:
    failures = deformation_quality_failures(result, settings)
    if failures:
        raise MeshQualityError(
            f"Mesh deformation quality gate failed for {label}: {', '.join(failures)}"
        )
