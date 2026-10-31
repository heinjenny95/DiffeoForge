"""Disposable per-content inspection evidence; project approvals are never shared."""

import hashlib
import logging
import math
from dataclasses import replace

from diffeoforge.analysis.mesh_scaling import MeshScaleMetrics
from diffeoforge.mesh_quality import MeshQualityResult
from diffeoforge.project_checkpoint import CheckpointUnavailable, load_checkpoint, save_checkpoint
from diffeoforge.surface_io import SurfaceMeshMetadata

INSPECTION_VERSION = "surface-1"
LOG = logging.getLogger(__name__)


def key(path, digest):
    from diffeoforge.mesh_quality import QUALITY_DEFINITIONS_VERSION

    return (
        INSPECTION_VERSION
        + "-"
        + hashlib.sha256(
            f"{digest}:{path.suffix.lower()}:{QUALITY_DEFINITIONS_VERSION}".encode()
        ).hexdigest()
    )


def read(path, digest, roots):
    """Fresh caller hash plus typed, finite evidence; names/paths grant no trust."""
    for root in roots:
        if root is None:
            continue
        try:
            row = load_checkpoint(root, key(path, digest))
            if (
                not isinstance(row, tuple)
                or len(row) != 3
                or not isinstance(row[0], SurfaceMeshMetadata)
                or not isinstance(row[1], MeshQualityResult)
                or not isinstance(row[2], MeshScaleMetrics)
            ):
                continue
            meta, quality, scale = row
            if (
                meta.sha256 != digest
                or meta.bytes != path.stat().st_size
                or meta.points != quality.points
                or meta.triangles != quality.triangles
                or meta.points < 3
                or meta.triangles < 1
                or not math.isfinite(meta.bounding_box_diagonal)
                or meta.bounding_box_diagonal <= 0
                or len(meta.bounds) != 6
                or not all(math.isfinite(v) for v in meta.bounds)
            ):
                continue
            LOG.info("Mesh inspection reused: %s · content %s", path, digest)
            return replace(meta, path=str(path)), quality, scale
        except (CheckpointUnavailable, OSError, ValueError, TypeError):
            continue
    LOG.info("Mesh inspection cache miss: %s · content %s · rules %s", path, digest,
             INSPECTION_VERSION)
    return None


def write(path, digest, row, roots):
    for root in roots:
        if root is None:
            continue
        try:
            save_checkpoint(root, key(path, digest), row)
        except (OSError, ValueError):
            pass  # Unwritable cache never changes the source inspection result.


def vtk_check(path, digest, roots):
    """Read the existing VTK metadata/quality format without parsing geometry."""
    from diffeoforge.mesh import MeshMetadata
    from diffeoforge.mesh_quality import QUALITY_DEFINITIONS_VERSION

    name = "vtk-1-" + hashlib.sha256(f"{digest}:{QUALITY_DEFINITIONS_VERSION}".encode()).hexdigest()
    for root in roots:
        if root is None:
            continue
        try:
            row = load_checkpoint(root, name)
            if (
                isinstance(row, tuple)
                and len(row) == 2
                and isinstance(row[0], MeshMetadata)
                and isinstance(row[1], MeshQualityResult)
                and row[0].sha256 == digest
                and row[0].bytes == path.stat().st_size
                and row[0].triangular
                and row[0].points == row[1].points
                and row[0].cells == row[1].triangles
            ):
                return replace(row[0], path=str(path)), row[1]
        except (CheckpointUnavailable, OSError, ValueError, TypeError):
            continue
    return None


def prime_vtk(paths, roots):
    """Prime the bounded scalar metadata cache from fresh content-bound evidence."""
    from diffeoforge import mesh

    for path in paths:
        digest = mesh.sha256_file(path)
        row = vtk_check(path, digest, roots)
        if row is None:
            continue
        with mesh._METADATA_LOCK:
            mesh._METADATA_CACHE[digest] = row[0]
            while len(mesh._METADATA_CACHE) > 256:
                mesh._METADATA_CACHE.popitem(last=False)


def desktop_locations():
    """Bounded migration from existing user-selected projects, without opening runs."""
    from diffeoforge.desktop.recent_projects import default_store_path, load_recent_projects

    shared = default_store_path().parent / "cache" / "mesh-inspections"
    return shared, tuple(r.project_directory for r in load_recent_projects())
