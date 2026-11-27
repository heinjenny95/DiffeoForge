"""Matched control-point trials after an unsuitable high-disparity single fit."""

import math
from pathlib import Path

from diffeoforge.config import load_config
from diffeoforge.guided_density import controls_for
from diffeoforge.pilot_control_capacity import MAX_CONTROLS

VERSION = "guided-early-density-v1"
REFERENCE_ID = "density-reference"
ITERATIONS = 40


def preview(snapshot, identifier, context):
    """Offer a bounded comparison once per form before more expensive refinements."""
    from diffeoforge.guided_feedback import reference, verify_reference
    from diffeoforge.pilot_form_progress import is_common_check
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    if (not info or not info["target"] or snapshot.plan.pilot_subject_count != 1
            or info["phase"] == "joint" or is_common_check(info)
            or snapshot.visual_reviews.get(identifier) is not False
            or any(snapshot.visual_reviews.values()) or not context["allowed"].get(identifier)
            or snapshot.attachment_comparison.get("early_density_comparison")
            or any(row["target"] == info["target"] and (row.get("early_density_comparison")
                       or row.get("approval")) for row in context["cases"])):
        return None
    inspected = (context["feedback"].get(identifier) or {}).get("selected")
    seed = inspected or reference(snapshot, identifier)
    parent = verify_reference(seed) if inspected else snapshot
    if (parent.plan.pilot_subject_count != 1
            or parent.attachment_comparison.get("regional_objective")):
        return None
    if seed["target"] != info["target"]:
        return None
    saved = next(c for c in parent.candidates if c.candidate_id == seed["candidate_id"])
    config = load_config(saved.config_path)
    recommendation = config["project"]["parameter_provenance"]["recommendation"]
    if (recommendation.get("expected_shape_disparity") not in {"high", "extreme"}
            or not all(config["optimization"][key]
                       for key in ("freeze_control_points", "freeze_template"))):
        return None
    count = controls_for(parent.attachment_comparison, seed["candidate_id"])["count"]
    denser = math.ceil(1.5 * count)
    if denser > MAX_CONTROLS:
        return None
    return dict(available=True, reference=seed, initial_control_count=count,
                denser_control_count=denser)


def verify(root, manifest, record):
    """Keep the two-arm exception to ordinary study layouts precisely bound."""
    pair = record.get("early_density_comparison")
    if pair is None:
        return
    from diffeoforge.guided_feedback import verify_reference

    seed = record["refinement"]["reference"]
    parent = verify_reference(seed)
    candidate = next(c for c in parent.candidates if c.candidate_id == seed["candidate_id"])
    before = load_config(candidate.config_path)
    after = load_config(root / manifest["source_config"]["copy"])
    initial = controls_for(parent.attachment_comparison, seed["candidate_id"])["count"]
    denser_id = "guided-" + seed["method"]
    base_values = seed["values"]
    dense_values = dict(base_values, initial_control_point_spacing=(
        base_values["initial_control_point_spacing"] * .8))
    stage = manifest["plan"]["stages"][0]
    source_model = before["model"]["deformation"]
    model = after["model"]["deformation"]
    if (
        pair != dict(version=VERSION, reference_candidate_id=REFERENCE_ID,
                     denser_candidate_id=denser_id, initial_control_count=initial)
        or record["guided"]["phase"] != "refine"
        or record["guided"]["goal"] != "density"
        or record["methods"] != {REFERENCE_ID: seed["method"], denser_id: seed["method"]}
        or {r["candidate_id"]: r["parameter_values"] for r in stage["candidates"]}
        != {REFERENCE_ID: base_values, denser_id: dense_values}
        or record["refinement"]["initialization"] != "nested"
        or record["iterations"] != ITERATIONS or manifest["pilot_max_iterations"] != ITERATIONS
        or record["controls"]["count"] != math.ceil(1.5 * initial)
        or parent.attachment_comparison.get("regional_objective")
        or Path(parent.attachment_comparison["guided"]["origin"]).resolve()
        != Path(record["guided"]["origin"]).resolve()
        or after["optimization"] != dict(before["optimization"], max_iterations=ITERATIONS)
        or any(model[k] != source_model[k] for k in ("timepoints", "use_rk2"))
        or after["runtime"] != before["runtime"]
        or record["guided"]["strategy"].get("anchor") != seed
    ):
        raise ValueError("Matched control-point comparison settings or saved start changed")


def outcome(snapshot):
    """Compare both completed arms on the same original and markings."""
    from diffeoforge.pilot_regions import comparison

    record = snapshot.attachment_comparison
    pair = record.get("early_density_comparison")
    if not pair or any(c.status != "completed" for c in snapshot.candidates):
        return None
    target = record["guided"]["target"]
    subjects = {}
    for candidate in snapshot.candidates:
        metrics = candidate.metrics or {}
        row = metrics.get("attachment_comparison", {}).get("subjects", {}).get(target)
        if not row or metrics.get("invalid_face_count") != 0:
            return "unavailable"
        subjects[candidate.candidate_id] = row
    before = subjects[pair["reference_candidate_id"]]
    after = subjects[pair["denser_candidate_id"]]
    regions = record["guided"]["feedback"]["regions"]
    old = before.get("marked_regions", {}).get("measurements", [])
    new = after.get("marked_regions", {}).get("measurements", [])
    if len(regions) != len(old) or len(regions) != len(new):
        return "unavailable"
    return comparison(old, new, before, after)
