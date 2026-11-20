"""Read-only pilot hints from content/rule-bound existing mesh inspections.

No surface parse, revalidation, repair, fitting, or approval.
Cached Euler/edge counts are triage, never a closed-manifold/genus certificate.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

VERSION = "pilot-input-topology-triage-v1"
_SHA = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class Evidence:
    sha256: str
    definitions_version: str
    points: int
    triangles: int
    unique_edges: int
    isolated_vertices: int
    euler_characteristic: int
    face_components: int
    boundary_edges: int
    manifold_edges: int
    nonmanifold_edges: int
    inconsistent_winding_edges: int
    duplicate_faces: int
    zero_area_faces: int
    connectivity_sha256: str

    def __post_init__(self):
        if not _SHA.fullmatch(self.sha256) or not _SHA.fullmatch(
            self.connectivity_sha256
        ):
            raise ValueError("Invalid content/connectivity binding")
        for key, value in asdict(self).items():
            if key not in {"sha256", "definitions_version", "connectivity_sha256"}:
                if type(value) is not int or (
                    key != "euler_characteristic" and value < 0
                ):
                    raise ValueError("Topology counts must be finite integers")
        if (
            self.points < 3
            or self.triangles < 1
            or self.face_components < 1
            or self.face_components > self.triangles
            or self.isolated_vertices > self.points
            or self.euler_characteristic
            != self.points - self.unique_edges + self.triangles
            or self.unique_edges
            != self.boundary_edges + self.manifold_edges + self.nonmanifold_edges
            or self.inconsistent_winding_edges > self.manifold_edges
        ):
            raise ValueError("Inconsistent cached topology counts")

    @property
    def used_euler(self):
        # Existing mesh_quality Euler includes stored, isolated vertices.
        return self.euler_characteristic - self.isolated_vertices


def _digest_file(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def _identity(path):
    info = path.stat(follow_symlinks=False)
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("Selected mesh cannot be a symbolic link")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def load_cached(path, expected_sha256, cache_roots):
    """Fresh hash of ONE selected file, then existing typed cache only; miss stays unknown."""
    from diffeoforge.mesh_inspection_cache import read, vtk_check
    from diffeoforge.mesh_quality import QUALITY_DEFINITIONS_VERSION

    path = Path(path)
    if not _SHA.fullmatch(expected_sha256):
        raise ValueError("A verified selected input SHA256 is required")
    before = _identity(path)
    if _digest_file(path) != expected_sha256:
        raise ValueError("Selected input content changed")
    row = (vtk_check if path.suffix.lower() == ".vtk" else read)(
        path, expected_sha256, cache_roots
    )
    if _identity(path) != before:
        raise ValueError("Selected input identity changed during cache lookup")
    if row is None:
        return None
    meta, quality = row[:2]
    if meta.sha256 != expected_sha256 or meta.bytes != before[2]:
        raise ValueError("Inspection content binding changed")
    try:
        return Evidence(
            expected_sha256,
            QUALITY_DEFINITIONS_VERSION,
            quality.points,
            quality.triangles,
            quality.unique_edges,
            quality.isolated_vertices,
            quality.euler_characteristic,
            quality.face_connected_components,
            quality.boundary_edges,
            quality.manifold_edges,
            quality.nonmanifold_edges,
            quality.inconsistently_oriented_manifold_edges,
            quality.duplicate_faces,
            quality.zero_area_faces,
            quality.connectivity_sha256,
        )
    except (TypeError, ValueError):
        # Disposable cached counts are not scientific authority. Invalid cached
        # scalars mean unknown; never parse/revalidate a mesh to replace them.
        return None


def triage(template, subject):
    """Presentation evidence only; never modifies availability/approval/parameters."""
    result = dict(
        version=VERSION,
        status="unknown",
        confidence="cached_counts_only",
        reasons=[],
        template=None if template is None else asdict(template),
        subject=None if subject is None else asdict(subject),
        confirmed_component_genera=None,
        block_all_geometry_trials=False,
        external_geometry_trials_remain_available=True,
        automatic_approval=False,
        local_region_irreducibility_inferred=False,
    )
    if template is None or subject is None:
        result.update(
            title="Input openings and connections: comparison unavailable",
            message="Matching cached inspection evidence is unavailable for this selected pair. "
            "No new mesh validation has been started. You can inspect the original and starting "
            "template; a separate check can clarify their openings and connections.",
        )
        return result
    if template.definitions_version != subject.definitions_version:
        result.update(
            title="Input openings and connections: comparison unavailable",
            message="The cached inspections use different checking rules. Their structural "
            "compatibility is unknown; no new validation or fit has been started.",
        )
        return result
    if template.used_euler != subject.used_euler:
        result["reasons"].append("different_used_vertex_euler_counts")
    if template.face_components != subject.face_components:
        result["reasons"].append("different_connected_surface_part_counts")
    if (template.boundary_edges == 0) != (subject.boundary_edges == 0):
        result["reasons"].append("one_surface_has_open_boundaries")
    issues = [
        label
        for label, values in (
            (
                "isolated_vertices",
                (template.isolated_vertices, subject.isolated_vertices),
            ),
            (
                "nonmanifold_edges",
                (template.nonmanifold_edges, subject.nonmanifold_edges),
            ),
            (
                "inconsistent_winding",
                (
                    template.inconsistent_winding_edges,
                    subject.inconsistent_winding_edges,
                ),
            ),
            ("duplicate_faces", (template.duplicate_faces, subject.duplicate_faces)),
            ("zero_area_faces", (template.zero_area_faces, subject.zero_area_faces)),
        )
        if any(values)
    ]
    result["input_review_issues"] = issues
    unsafe = any(issue != "isolated_vertices" for issue in issues)
    if unsafe:
        # Raw winding/edge/face-quality flags are not topology invariants. Unsafe
        # evidence cannot promote differing or matching counts to a structure claim.
        result.update(
            status="unknown",
            confidence="unsafe_cached_input_quality",
            input_review_recommended=True,
            title="Review input surfaces before comparing their structure",
            message="The cached inspection has surface-quality limitations. Whether their openings "
            "or connections match is unknown. Inspect the original and starting template before "
            "attributing this problem to fitting parameters. Outer contours and details remain "
            "separate geometric questions.",
        )
        return result
    if result["reasons"]:
        result["status"] = "potential_structure_mismatch"
    elif issues:
        result["status"] = "input_review_needed"
    elif template.boundary_edges or subject.boundary_edges:
        result["status"] = "open_surface_comparison_limited"
    else:
        result["status"] = "no_difference_detected_in_cached_counts"
    warning = result["status"] == "potential_structure_mismatch"
    result["input_review_recommended"] = (
        warning
        or bool(issues)
        or bool(template.boundary_edges or subject.boundary_edges)
    )
    if warning:
        result["title"] = "Inputs may have different openings or connections"
        result["message"] = (
            "Deformation cannot create or remove a true through-opening or connection between "
            "parts. Inspect the original and starting template for the affected area before trying "
            "more parameter changes there. Outer contours and surface details can still be "
            "improved separately. This hint does not identify which marked area is responsible "
            "and does not approve a fit."
        )
    elif issues or template.boundary_edges or subject.boundary_edges:
        result["title"] = "Review input openings and connections"
        result["message"] = (
            "The cached inspection has input-quality or open-boundary limitations. These counts "
            "cannot certify matching openings or connections. Inspect the original and template "
            "before explaining the problem as a fitting parameter alone; other geometric "
            "improvements remain available."
        )
    else:
        result["title"] = "Input openings and connections"
        result["message"] = (
            "The available counts do not reveal a structural difference. They do not prove that "
            "the surfaces match anatomically or that the fit is suitable."
        )
    return result


def selected_pair(template_path, subject_path, template_sha, subject_sha, cache_roots):
    """Fresh selected input hashes and existing inspections only; no fallback work."""
    template = load_cached(template_path, template_sha, cache_roots)
    subject = load_cached(subject_path, subject_sha, cache_roots)
    return triage(template, subject)


def prepare_for_snapshot(snapshot, verified_manifest, *, cache_roots=None):
    """One background hint for this selected singleton, never a lineage/cohort scan.

    The existing presentation operation supplies its already-bound manifest.
    Hash/identity changes remain errors. Missing or corrupt disposable inspection
    evidence is an unknown hint and never starts validation or parses a surface.
    """
    if getattr(getattr(snapshot, "plan", None), "pilot_subject_count", None) != 1:
        return triage(None, None)
    inputs = verified_manifest["inputs"]
    if len(inputs["subjects"]) != 1:
        return triage(None, None)
    root = Path(snapshot.study_directory).resolve(strict=True)
    original, template = inputs["subjects"][0], inputs["template"]
    rows = (template, original)
    paths = [(root / row["copy"]).resolve(strict=True) for row in rows]
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError("Selected singleton input escapes its protected study")
    if cache_roots is None:
        from diffeoforge.desktop.recent_projects import default_store_path

        shared = default_store_path().parent / "cache" / "mesh-inspections"
        # Only explicit roots already named by this study; no recent-project or
        # ancestor scan. Missing existing evidence remains unknown.
        source = verified_manifest.get("source_config", {}).get("original_path")
        cache_roots = (root, Path(source).parent if source else None, shared)
    return selected_pair(
        paths[0], paths[1], template["sha256"], original["sha256"], cache_roots
    )
