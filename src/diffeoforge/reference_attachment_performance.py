"""Offline reference-runtime performance qualification; Python 3.8 compatible.

Nothing here is installed by the run generator.  The cache probe is deliberately
scoped to an isolated comparison: scientific GPU/end-to-end qualification is
required before production use.  No scientific mesh is reduced by this module.
"""

import copy
import math
import re
from contextlib import contextmanager

VERSION = "reference-attachment-performance-v1"
_CACHE_ATTRIBUTE = "_diffeoforge_target_normals_probe_v1"


def prepare_target_normals(normals, torch):
    """The native operations, in the native order; never detach a target graph."""
    areas = torch.norm(normals, 2, 1)
    return areas, normals / areas.unsqueeze(1)


def cached_target_normals(target, normals, torch):
    """Cache fixed target preparation, invalidating tensor edits and replacements.

    Native target-self norms and triangle centres/normals are already cached.
    This candidate only avoids repeating the remaining norm/normalisation pass.
    A graph-bearing target deliberately takes the unchanged uncached path.
    """
    if normals.requires_grad or normals.grad_fn is not None:
        return prepare_target_normals(normals, torch)
    signature = (normals._version, tuple(normals.shape), tuple(normals.stride()),
                 normals.dtype, normals.device)
    record = getattr(target, _CACHE_ATTRIBUTE, None)
    if record is not None and record[0] is normals and record[1] == signature:
        return record[2]
    result = prepare_target_normals(normals, torch)
    # Keep the tensor itself alive: storage-address reuse cannot validate a hit.
    setattr(target, _CACHE_ATTRIBUTE, (normals, signature, result))
    return result


def cached_varifold_distance(points, source, target, kernel):
    """Deformetrica 4.3 varifold formula with only target preparation reused."""
    import torch
    from deformetrica.core.model_tools.attachments.multi_object_attachment import (
        MultiObjectAttachment,
    )
    from deformetrica.support import utilities

    device, _ = utilities.get_best_device(kernel.gpu_mode)
    geometry = (
        MultiObjectAttachment._MultiObjectAttachment__get_source_and_target_centers_and_normals
    )
    c1, n1, c2, n2 = geometry(points, source, target, device=device)
    areaa = torch.norm(n1, 2, 1)
    areab, nbeta = cached_target_normals(target, n2, torch)
    nalpha = n1 / areaa.unsqueeze(1)

    def scalar_product(x, y, left_area, right_area, left_normal, right_normal):
        values = kernel.convolve((x, left_normal), (y, right_normal),
                                 right_area.view(-1, 1), mode="varifold")
        return torch.dot(left_area.view(-1), values.view(-1))

    if target.norm is None:
        target.norm = scalar_product(c2, c2, areab, areab, nbeta, nbeta)
    return (scalar_product(c1, c1, areaa, areaa, nalpha, nalpha) + target.norm
            - 2 * scalar_product(c1, c2, areaa, areab, nalpha, nbeta))


@contextmanager
def isolated_native_cache_probe():
    """Temporarily substitute the candidate in this isolated Python process.

    The caller owns an offline process, not a running desktop worker.  Restoration
    also happens on exceptions.  Nested probes are refused to avoid provenance
    ambiguity; this context manager is not imported by production dispatch.
    """
    from deformetrica.core.model_tools.attachments.multi_object_attachment import (
        MultiObjectAttachment,
    )

    original = MultiObjectAttachment.varifold_distance
    if original is cached_varifold_distance:
        raise RuntimeError("A native cache probe is already active")
    MultiObjectAttachment.varifold_distance = staticmethod(cached_varifold_distance)
    try:
        yield
    finally:
        MultiObjectAttachment.varifold_distance = staticmethod(original)


def prepare_resolution_comparison(*, source_hashes, starting_field_hashes,
                                  effective_settings, candidate_mesh_hashes):
    """Declare an explicit paired experiment, without starting/qualifying one.

    Both arms use the same initial controls/momenta and solver settings.  Only
    scientific working surface geometry may differ.  Full original endpoints
    must be evaluated in both arms; visual proxies are never scientific inputs.
    All hashes describe separately retained copies, never overwritten originals.
    """
    def hashes(value, required):
        if set(value) != set(required):
            raise ValueError("Every required evidence hash must be declared")
        if any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}", x)
               for x in value.values()):
            raise ValueError("Evidence needs lowercase SHA256 hashes")
        return dict(value)

    inputs = hashes(source_hashes, ("template", "target"))
    field = hashes(starting_field_hashes, ("controls", "momenta"))
    candidate = hashes(candidate_mesh_hashes, ("template", "target"))
    required = {
        "attachment", "attachment_width", "deformation_width", "noise_std",
        "timepoints", "precision", "max_iterations", "convergence_tolerance",
        "optimizer", "freeze_template", "freeze_controls",
    }
    if set(effective_settings) != required:
        raise ValueError("Declare the complete unchanged numerical contract")
    for name in ("attachment_width", "deformation_width", "noise_std",
                 "convergence_tolerance"):
        value = effective_settings[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not (
                math.isfinite(value) and value > 0):
            raise ValueError("Numerical contract needs finite positive scales/tolerance")
    for name, minimum in (("timepoints", 2), ("max_iterations", 1)):
        value = effective_settings[name]
        if type(value) is not int or value < minimum:
            raise ValueError("Numerical contract needs positive integer effort")
    if effective_settings["precision"] not in ("float32", "float64"):
        raise ValueError("Declare an explicit native precision")
    if effective_settings["freeze_template"] is not True:
        raise ValueError("This comparison requires a frozen template")
    if effective_settings["freeze_controls"] is not True:
        raise ValueError("This comparison requires frozen controls")
    if candidate == inputs:
        raise ValueError("A reduced candidate must identify different working geometry")
    return {
        "version": VERSION,
        "status": "prepared_unqualified",
        "production_enabled": False,
        "source_sha256": inputs,
        "starting_field_sha256": field,
        "effective_settings": copy.deepcopy(effective_settings),
        "arms": {
            "full_reference": {"working_mesh_sha256": inputs},
            "reduced_candidate": {"working_mesh_sha256": candidate},
        },
        "required_evidence": [
            "Independent complete full-resolution inputs and reduction audit",
            "Same initial field, native cap, tolerance, time grid and precision",
            "Wall time including reduction, fitting, full-material flow and all QC",
            "Native return/stop, full-resolution endpoint and field hashes for both arms",
            "Both distance directions on complete originals and marked fine structures",
            "Preservation, intersection and temporal/spatial checks for both arms",
            "Independent anatomical review of matched full-resolution overlays",
            "GPU/end-to-end qualification before any production enablement",
        ],
        "qualification": "No speed or anatomical equivalence claim from preparation",
    }
