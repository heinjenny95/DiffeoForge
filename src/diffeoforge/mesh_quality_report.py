"""Portable JSON and CSV evidence for deterministic mesh-quality assessments."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from diffeoforge.mesh import read_vtk_polydata
from diffeoforge.mesh_quality import (
    QUALITY_BOUNDARY,
    QUALITY_DEFINITIONS_VERSION,
    QUANTILE_METHOD,
    MeshQualitySettings,
    assess_triangle_mesh,
    compare_triangle_meshes,
    enforce_deformation_quality,
    enforce_mesh_quality,
)

REPORT_VERSION = "0.1"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"Mesh-quality path is outside the evidence root: {path}") from error


def build_mesh_quality_report(
    root: Path,
    descriptors: list[dict[str, str]],
    settings: MeshQualitySettings,
    *,
    reference_path: Path | None = None,
) -> dict[str, Any]:
    """Assess declared mesh files and optionally compare them with one reference."""

    if not descriptors:
        raise ValueError("Mesh-quality evidence requires at least one mesh descriptor")
    resolved_reference = None if reference_path is None else reference_path.resolve()
    reference = read_vtk_polydata(resolved_reference) if resolved_reference is not None else None
    reference_relative = None if reference_path is None else _relative(root, reference_path)
    mesh_cache = {} if resolved_reference is None else {resolved_reference: reference}
    metrics_cache = {}
    records: list[dict[str, Any]] = []
    for index, descriptor in enumerate(descriptors):
        label = descriptor.get("label")
        role = descriptor.get("role")
        stage = descriptor.get("stage")
        path_value = descriptor.get("path")
        if not all(isinstance(value, str) and value for value in (label, role, stage, path_value)):
            raise TypeError("Mesh-quality descriptors require label, role, stage, and path")
        path = Path(path_value).resolve()
        mesh = mesh_cache.get(path)
        if mesh is None:
            mesh = read_vtk_polydata(path)
            mesh_cache[path] = mesh
        metrics = metrics_cache.get(path)
        if metrics is None:
            metrics = assess_triangle_mesh(mesh.vertices, mesh.triangles)
            metrics_cache[path] = metrics
        evidence_label = f"{label} ({role}, {stage})"
        enforce_mesh_quality(evidence_label, metrics, settings)
        comparison = None
        if reference is not None and path != resolved_reference:
            comparison_result = compare_triangle_meshes(
                reference.vertices,
                reference.triangles,
                mesh.vertices,
                mesh.triangles,
            )
            enforce_deformation_quality(evidence_label, comparison_result, settings)
            comparison = comparison_result.as_manifest()
        records.append(
            {
                "index": index,
                "label": label,
                "role": role,
                "stage": stage,
                "path": _relative(root, path),
                "metrics": metrics.as_manifest(),
                "comparison_to_reference": comparison,
            }
        )
    return {
        "report_version": REPORT_VERSION,
        "definitions_version": QUALITY_DEFINITIONS_VERSION,
        "quantile_method": QUANTILE_METHOD,
        "settings": settings.as_manifest(),
        "reference_path": reference_relative,
        "meshes": records,
        "scientific_boundary": QUALITY_BOUNDARY,
    }


def _number(value: object) -> str:
    if value is None:
        return ""
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("Mesh-quality CSV values must be finite")
    return format(0.0 if normalized == 0.0 else normalized, ".17g")


def _summary_value(metrics: dict[str, Any], name: str, statistic: str) -> str:
    summary = metrics.get(name)
    return "" if summary is None else _number(summary[statistic])


def _csv_text(value: str) -> str:
    return f"'{value}" if value and value[0] in "=+-@\t\r" else value


def mesh_quality_csv_rows(report: dict[str, Any]) -> list[list[str]]:
    """Flatten a quality report into stable, spreadsheet-friendly rows."""

    header = [
        "index",
        "label",
        "role",
        "stage",
        "path",
        "points",
        "triangles",
        "unique_edges",
        "isolated_vertices",
        "duplicate_faces",
        "boundary_edges",
        "manifold_edges",
        "nonmanifold_edges",
        "face_connected_components",
        "euler_characteristic",
        "inconsistently_oriented_manifold_edges",
        "zero_area_faces",
        "zero_length_edge_faces",
        "bounding_box_diagonal",
        "total_surface_area",
        "minimum_area_over_bbox_diagonal_squared",
        "minimum_triangle_area",
        "median_triangle_area",
        "minimum_angle_degrees",
        "median_angle_degrees",
        "maximum_edge_ratio",
        "minimum_face_area_ratio",
        "median_face_area_ratio",
        "maximum_face_area_ratio",
    ]
    rows = [header]
    for record in report["meshes"]:
        metrics = record["metrics"]
        comparison = record["comparison_to_reference"]
        ratios = None if comparison is None else comparison["face_area_ratio"]
        rows.append(
            [
                str(record["index"]),
                _csv_text(record["label"]),
                _csv_text(record["role"]),
                _csv_text(record["stage"]),
                _csv_text(record["path"]),
                str(metrics["points"]),
                str(metrics["triangles"]),
                str(metrics["unique_edges"]),
                str(metrics["isolated_vertices"]),
                str(metrics["duplicate_faces"]),
                str(metrics["boundary_edges"]),
                str(metrics["manifold_edges"]),
                str(metrics["nonmanifold_edges"]),
                str(metrics["face_connected_components"]),
                str(metrics["euler_characteristic"]),
                str(metrics["inconsistently_oriented_manifold_edges"]),
                str(metrics["zero_area_faces"]),
                str(metrics["zero_length_edge_faces"]),
                _number(metrics["bounding_box_diagonal"]),
                _number(metrics["total_surface_area"]),
                _number(metrics["minimum_area_over_bbox_diagonal_squared"]),
                _summary_value(metrics, "triangle_area", "minimum"),
                _summary_value(metrics, "triangle_area", "median"),
                _summary_value(metrics, "minimum_angle_degrees", "minimum"),
                _summary_value(metrics, "minimum_angle_degrees", "median"),
                _summary_value(metrics, "edge_ratio", "maximum"),
                "" if ratios is None else _number(ratios["minimum"]),
                "" if ratios is None else _number(ratios["median"]),
                "" if ratios is None else _number(ratios["maximum"]),
            ]
        )
    return rows
