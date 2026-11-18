"""Material-bound reconstruction marks; geometric support is not homology."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np


def topology_sha256(vertices, faces):
    """Bind ordered material triangles and vertex count, independently of position."""
    f = np.asarray(faces, dtype="<i8")
    h = hashlib.sha256(np.asarray([len(vertices), *f.shape], dtype="<i8").tobytes())
    h.update(f.tobytes())
    return h.hexdigest()


def validate_evidence(value):
    if (not isinstance(value, dict)
            or set(value) != {"sha256", "topology_sha256", "face_ids"}
            or any(not isinstance(value[k], str) or not re.fullmatch(r"[0-9a-f]{64}", value[k])
                   for k in ("sha256", "topology_sha256"))
            or not isinstance(value["face_ids"], list) or not value["face_ids"]
            or any(type(i) is not int or i < 0 for i in value["face_ids"])
            or value["face_ids"] != sorted(set(value["face_ids"]))):
        raise ValueError("Invalid inspected reconstruction material binding")


def material_mask(vertices, faces, rows, *, lineage=None):
    """Follow explicitly selected material; never identify target anatomy by proximity."""
    f = np.asarray(faces, int)
    selected = np.zeros(len(f), bool)
    digest = None
    for row in rows:
        evidence = row.get("reconstruction")
        if evidence is None:
            continue
        validate_evidence(evidence)
        if digest is None:
            digest = topology_sha256(vertices, f)
        if evidence["topology_sha256"] == digest and evidence["face_ids"][-1] < len(f):
            selected[evidence["face_ids"]] = True
        elif lineage is not None:
            # Qualification may conformingly subdivide the original material
            # grid. Only its verified exact ancestry can transport these IDs;
            # a nearby surface or a display proxy is never a substitute.
            descendants = np.asarray(lineage.material_mask(vertices, f, evidence))
            if descendants.dtype != np.bool_ or descendants.shape != selected.shape:
                raise ValueError("Invalid marked reconstruction material lineage mask")
            selected |= descendants
        else:
            raise ValueError("The marked reconstruction material connectivity changed")
    return selected


def bind(row, model):
    """Record exact inspected bytes plus the exact faces inside the user's brush."""
    from diffeoforge.regional_fit import mask

    faces = np.asarray(model.triangles, int)
    chosen = np.flatnonzero(mask(np.asarray(model.vertices)[faces].mean(1), [row]))
    if not len(chosen):
        raise ValueError("The marked brush contains no reconstruction face centres; enlarge it")
    return dict(sha256=model.sha256,
                topology_sha256=topology_sha256(model.vertices, faces),
                face_ids=chosen.tolist())


def verify_review_regions(snapshot, candidate, regions, *, previous_regions=None):
    """New marks must name the exact inspected output; unchanged journals persist."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_evaluation import endpoint
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    pending = {}
    for name, rows in regions.items():
        previous = snapshot.problem_regions.get(candidate.candidate_id, {}).get(name, [])
        previous = [*previous, *(previous_regions or {}).get(name, [])]
        if snapshot.attachment_comparison.get("guided"):
            from diffeoforge.guided_feedback import region_state

            inherited, _ = region_state(snapshot, candidate.candidate_id, name)
            previous = [*previous, *inherited]
        new = [r for r in rows if r.get("reconstruction") and r not in previous]
        if new:
            pending[name] = new
    if not pending:
        return
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    for name, rows in pending.items():
        evaluated = endpoint(candidate, subject=name)
        if evaluated:
            path, digest = Path(evaluated["path"]), evaluated["sha256"]
        else:
            found = [r for r in report.inventory
                     if ("__Reconstruction__" + object_id + "__subject_") in r["path"]
                     and r["path"].endswith("__subject_" + name + ".vtk")]
            if len(found) != 1:
                raise ValueError("The inspected reconstruction is missing or ambiguous")
            path = study._safe_study_path(run / "output", found[0]["path"])
            digest = found[0]["sha256"]
        if sha256_file(path) != digest:
            raise ValueError("The inspected reconstruction bytes changed")
        loaded = load_surface_mesh(path)
        if loaded.metadata.sha256 != digest:
            raise ValueError("The inspected reconstruction changed during verification")
        for row in rows:
            if row["reconstruction"]["sha256"] != digest:
                raise ValueError("A new correction must identify the exact "
                                 "inspected reconstruction")
            material_mask(loaded.geometry.vertices, loaded.geometry.triangles, [row])
            from diffeoforge.regional_fit import mask

            faces = np.asarray(loaded.geometry.triangles)
            expected = np.flatnonzero(mask(np.asarray(loaded.geometry.vertices)[faces].mean(1),
                                           [row])).tolist()
            if row["reconstruction"]["face_ids"] != expected:
                raise ValueError("The inspected reconstruction faces differ from the marked brush")


def target_support(source_vertices, source_faces, target_vertices, target_faces, regions):
    """Select target support for a reconstruction mark, explicitly without pairing.

    A brush can lie in empty original space. Its selected source material is
    then compared with a connected nearby original patch of comparable area.
    This is a fitting hypothesis, not an anatomical correspondence or a request
    to change topology. The chosen target faces are retained in the plan.
    """
    from diffeoforge.regional_fit import mask
    from diffeoforge.regional_material_patch import select

    sv, sf = np.asarray(source_vertices), np.asarray(source_faces)
    tv, tf = np.asarray(target_vertices), np.asarray(target_faces)
    selected = np.zeros(len(tf), bool)
    proposals = []
    for index, row in enumerate(regions):
        chosen = mask(tv[tf].mean(1), [row])
        if not chosen.any() and row.get("reconstruction"):
            # Swap roles only to propose connected original support. Removing
            # the marker binding avoids interpreting target face IDs as source IDs.
            spatial = {k: v for k, v in row.items() if k != "reconstruction"}
            material = material_mask(sv, sf, [row])
            chosen, _ = select(tv, tf, sv, sf[material], [spatial], infer=True,
                               target_masks=[np.ones(int(material.sum()), bool)])
            proposals.append(dict(region=index, target_faces=np.flatnonzero(chosen).tolist(),
                method="nearby-connected-original-support-v1",
                biological_correspondence_claim=False, topology_change_claim=False))
        if not chosen.any():
            raise ValueError("The marked original area contains no face centres; enlarge it")
        selected |= chosen
    return selected, proposals
