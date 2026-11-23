"""Displacement of the same approved material in fixed green patches."""
from __future__ import annotations

import numpy as np

from diffeoforge.reconstruction_feedback import (
    ReconstructionMaterialUnavailable,
    material_mask,
    topology_sha256,
)
from diffeoforge.regional_preservation import vertex_ids

METRICS = ("fixed_material_p95", "fixed_material_max")
# Existing dense fixed-area guard in regional_fit, expressed as % original diagonal.
LIMIT_PERCENT = 0.01


def _material_grids(template, template_mesh, fitted, lineage):
    """Shared topology is meaningful only after the immutable template was bound."""
    if template is None or template_mesh is None:
        return {}
    base = topology_sha256(template_mesh.vertices, template_mesh.triangles)
    current = topology_sha256(fitted.vertices, fitted.triangles)
    if current == base:
        return {template.sha256: len(template_mesh.vertices)}
    if lineage is None:
        return {}
    # from_evaluation verifies every subdivision, including unchanged original vertex
    # order and each new midpoint. A coincidental topological match is insufficient.
    return lineage.shared_vertex_prefixes(template.sha256, current)


class FixedPatches:
    def __init__(self, approved, geometry, template_mesh, lineage, regions, original):
        self.reference = np.asarray(geometry.vertices, float)
        faces = np.asarray(geometry.triangles, int)
        self.diagonal = float(np.linalg.norm(np.ptp(np.asarray(original.vertices, float), axis=0)))
        self.stage = approved
        self.grids = _material_grids(approved.material_template, template_mesh, geometry, lineage)
        self.ids = {}
        for i, mark in enumerate(regions):
            if mark.get("purpose") != "fixed":
                continue
            if mark.get("reconstruction"):
                try:
                    selected = material_mask(self.reference, faces, [mark], lineage=lineage)
                    self.ids[i] = np.unique(faces[selected])
                except ReconstructionMaterialUnavailable:
                    self.ids[i] = np.array([], int)
            else:
                self.ids[i] = vertex_ids(self.reference, faces, [mark])

    def compare(self, stage, geometry, template_mesh, lineage):
        verified_count = 0
        if stage.key == "approved":
            verified_count = len(self.reference)
        elif (stage.material_template and self.stage.material_template
              and stage.material_template.sha256 == self.stage.material_template.sha256):
            grids = _material_grids(stage.material_template, template_mesh, geometry, lineage)
            verified_count = max((count for key, count in self.grids.items()
                                  if grids.get(key) == count), default=0)
        result = {}
        for index, ids in self.ids.items():
            p95 = maximum = None
            if len(ids) >= 3 and ids[-1] < verified_count and self.diagonal > 0:
                actual = np.asarray(geometry.vertices, float)[ids]
                distances = np.linalg.norm(actual - self.reference[ids], axis=1)
                if np.isfinite(distances).all():
                    p95 = float(np.quantile(distances, .95)) * 100 / self.diagonal
                    maximum = float(distances.max()) * 100 / self.diagonal
            for metric, value in zip(METRICS, (p95, maximum), strict=True):
                result[index, metric] = None if value is None else (value, value)
        return result
