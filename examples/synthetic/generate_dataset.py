#!/usr/bin/env python3
"""Generate the deterministic, openly licensed DiffeoForge example dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

GENERATOR_VERSION = "1.0"
SUBDIVISION_LEVEL = 2


@dataclass(frozen=True)
class SurfaceParameters:
    """Named smooth deformation applied to the shared unit icosphere."""

    filename: str
    role: str
    scale: tuple[float, float, float]
    bend: float
    twist_radians: float
    polar_bulge: float
    translation: tuple[float, float, float]


SURFACES = (
    SurfaceParameters(
        "template.vtk",
        "template",
        (1.00, 0.78, 0.62),
        0.04,
        0.08,
        0.05,
        (0.00, 0.00, 0.00),
    ),
    SurfaceParameters(
        "subject-01.vtk",
        "subject",
        (0.96, 0.82, 0.60),
        0.02,
        -0.06,
        0.03,
        (-0.03, 0.02, 0.00),
    ),
    SurfaceParameters(
        "subject-02.vtk",
        "subject",
        (1.05, 0.74, 0.65),
        0.06,
        0.12,
        0.08,
        (0.02, -0.02, 0.01),
    ),
    SurfaceParameters(
        "subject-03.vtk",
        "subject",
        (1.00, 0.80, 0.58),
        -0.03,
        0.18,
        0.02,
        (0.01, 0.03, -0.02),
    ),
    SurfaceParameters(
        "subject-04.vtk",
        "subject",
        (0.92, 0.76, 0.70),
        0.08,
        -0.12,
        0.10,
        (-0.02, -0.01, 0.03),
    ),
    SurfaceParameters(
        "subject-05.vtk",
        "subject",
        (1.08, 0.83, 0.56),
        -0.01,
        0.05,
        -0.02,
        (0.03, 0.00, -0.01),
    ),
)


def _normalize(vertex: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vertex))
    return tuple(value / length for value in vertex)


def _icosahedron() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    vertices = [
        (-1.0, phi, 0.0),
        (1.0, phi, 0.0),
        (-1.0, -phi, 0.0),
        (1.0, -phi, 0.0),
        (0.0, -1.0, phi),
        (0.0, 1.0, phi),
        (0.0, -1.0, -phi),
        (0.0, 1.0, -phi),
        (phi, 0.0, -1.0),
        (phi, 0.0, 1.0),
        (-phi, 0.0, -1.0),
        (-phi, 0.0, 1.0),
    ]
    faces = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (4, 9, 5),
        (2, 4, 11),
        (6, 2, 10),
        (8, 6, 7),
        (9, 8, 1),
    ]
    return [_normalize(vertex) for vertex in vertices], faces


def _icosphere(
    subdivision_level: int,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices, faces = _icosahedron()
    for _ in range(subdivision_level):
        midpoint_indexes: dict[tuple[int, int], int] = {}
        refined_faces: list[tuple[int, int, int]] = []
        for first, second, third in faces:
            first_second = _midpoint_index(vertices, midpoint_indexes, first, second)
            second_third = _midpoint_index(vertices, midpoint_indexes, second, third)
            third_first = _midpoint_index(vertices, midpoint_indexes, third, first)
            refined_faces.extend(
                (
                    (first, first_second, third_first),
                    (second, second_third, first_second),
                    (third, third_first, second_third),
                    (first_second, second_third, third_first),
                )
            )
        faces = refined_faces
    return vertices, faces


def _midpoint_index(
    vertices: list[tuple[float, float, float]],
    midpoint_indexes: dict[tuple[int, int], int],
    left: int,
    right: int,
) -> int:
    edge = tuple(sorted((left, right)))
    if edge not in midpoint_indexes:
        point = _normalize(
            tuple(
                (vertices[left][axis] + vertices[right][axis]) / 2.0
                for axis in range(3)
            )
        )
        midpoint_indexes[edge] = len(vertices)
        vertices.append(point)
    return midpoint_indexes[edge]


def _validate_closed_topology(
    vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]
) -> int:
    edges: Counter[tuple[int, int]] = Counter()
    for face in faces:
        if len(set(face)) != 3 or any(index < 0 or index >= len(vertices) for index in face):
            raise ValueError(f"Invalid triangular face: {face}")
        first, second, third = face
        edges.update(
            (
                tuple(sorted((first, second))),
                tuple(sorted((second, third))),
                tuple(sorted((third, first))),
            )
        )
    if any(incidence != 2 for incidence in edges.values()):
        raise ValueError("Generated mesh is not a closed two-manifold.")
    if len(vertices) - len(edges) + len(faces) != 2:
        raise ValueError("Generated mesh does not have genus-zero Euler topology.")
    return len(edges)


def _deform(
    vertices: list[tuple[float, float, float]],
    parameters: SurfaceParameters,
) -> list[tuple[float, float, float]]:
    scale_x, scale_y, scale_z = parameters.scale
    translate_x, translate_y, translate_z = parameters.translation
    transformed = []
    for x_value, y_value, z_value in vertices:
        angle = parameters.twist_radians * z_value
        rotated_x = x_value * math.cos(angle) - y_value * math.sin(angle)
        rotated_y = x_value * math.sin(angle) + y_value * math.cos(angle)
        bent_x = rotated_x + parameters.bend * (z_value * z_value - (1.0 / 3.0))
        bulged_z = z_value * (1.0 + parameters.polar_bulge * (1.0 - z_value * z_value))
        transformed.append(
            (
                scale_x * bent_x + translate_x,
                scale_y * rotated_y + translate_y,
                scale_z * bulged_z + translate_z,
            )
        )
    return transformed


def _format_coordinate(value: float) -> str:
    if abs(value) < 0.5e-9:
        value = 0.0
    return f"{value:.9f}"


def _render_vtk(
    title: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> bytes:
    lines = [
        "# vtk DataFile Version 3.0",
        title,
        "ASCII",
        "DATASET POLYDATA",
        f"POINTS {len(vertices)} float",
    ]
    lines.extend(" ".join(_format_coordinate(value) for value in vertex) for vertex in vertices)
    lines.append(f"POLYGONS {len(faces)} {len(faces) * 4}")
    lines.extend(f"3 {first} {second} {third}" for first, second, third in faces)
    return ("\n".join(lines) + "\n").encode("ascii")


def build_dataset() -> dict[str, bytes]:
    """Return every generated file as deterministic bytes keyed by filename."""

    base_vertices, faces = _icosphere(SUBDIVISION_LEVEL)
    edge_count = _validate_closed_topology(base_vertices, faces)
    generated: dict[str, bytes] = {}
    records = []
    for parameters in SURFACES:
        payload = _render_vtk(
            f"DiffeoForge synthetic {parameters.role}",
            _deform(base_vertices, parameters),
            faces,
        )
        generated[parameters.filename] = payload
        record = asdict(parameters)
        record.update(
            {
                "points": len(base_vertices),
                "triangles": len(faces),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        records.append(record)

    manifest = {
        "dataset": "DiffeoForge synthetic ellipsoid cohort",
        "dataset_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "license": "CC0-1.0",
        "coordinate_units": "unitless",
        "construction": {
            "base_mesh": "unit icosphere",
            "subdivision_level": SUBDIVISION_LEVEL,
            "deterministic": True,
            "randomness": None,
            "shared_connectivity": True,
            "topology": "closed triangular genus-zero two-manifold",
            "points": len(base_vertices),
            "edges": edge_count,
            "triangles": len(faces),
            "euler_characteristic": len(base_vertices) - edge_count + len(faces),
        },
        "surfaces": records,
    }
    generated["dataset-manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return generated


def _write_dataset(output_directory: Path) -> int:
    output_directory.mkdir(parents=True, exist_ok=True)
    generated = build_dataset()
    for filename, payload in generated.items():
        (output_directory / filename).write_bytes(payload)
    print(f"Wrote {len(generated) - 1} meshes and dataset-manifest.json to {output_directory}")
    return 0


def _check_dataset(output_directory: Path) -> int:
    mismatches = []
    for filename, expected in build_dataset().items():
        path = output_directory / filename
        if not path.is_file():
            mismatches.append(f"missing: {path}")
        elif path.read_bytes() != expected:
            mismatches.append(f"does not match generator: {path}")
    if mismatches:
        for mismatch in mismatches:
            print(mismatch)
        return 1
    print(f"Synthetic dataset matches generator version {GENERATOR_VERSION}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "meshes",
        help="Directory receiving the generated meshes and manifest.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare committed files with deterministic generator output.",
    )
    args = parser.parse_args()
    if args.check:
        return _check_dataset(args.output.resolve())
    return _write_dataset(args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
