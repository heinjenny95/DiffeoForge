"""Choose a capable eligible starting basis before common checks, never mid-protocol."""
from copy import deepcopy


def rank(profiles):
    """Local residual counts prioritize a hard form, not a transferable ordinary basis."""
    eligible = [p for p in profiles if p["eligible_basis"]]
    return max(eligible, key=lambda p: p["controls"], default=None)


def prepare(snapshot, value):
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_basis import _physics
    from diffeoforge.pilot_form_progress import _protocol

    result = deepcopy(value)
    protocol = value["protocol"]
    base = verify_reference(protocol["reference"])
    base_candidate = next(c for c in base.candidates
                          if c.candidate_id == protocol["reference"]["candidate_id"])
    physics = _physics(load_config(base_candidate.config_path))
    controls = base.attachment_comparison["controls"]
    profiles = []
    for row in value["reviews"]:
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        parent = verify_reference(ref)
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        record = parent.attachment_comparison
        nested = record.get("refinement") or {}
        eligible = (not record.get("regional_objective")
            and nested.get("initialization") == "nested"
            and nested["source_controls"]["sha256"] == controls["sha256"]
            and ref["method"] == protocol["reference"]["method"]
            and _physics(load_config(candidate.config_path)) == physics)
        profiles.append(dict(row=row, parent=parent, controls=record["controls"]["count"],
                             eligible_basis=eligible,
                             regional=bool(record.get("regional_objective"))))
    chosen = rank(profiles)
    if chosen and chosen["controls"] > controls["count"]:
        result.update(origin_review=chosen["row"],
                      protocol=_protocol(chosen["parent"], chosen["row"]["candidate_id"]))
    selected_count = chosen["controls"] if chosen else controls["count"]
    return result, dict(controls=selected_count,
        reference=result["protocol"]["reference"],
        demand={p["row"]["filename"]: p["controls"] for p in profiles},
        reason="Start from the largest accepted transferable nested basis with unchanged "
               "fitting physics. Local residual counts prioritize difficult forms; they "
               "cannot be copied into an ordinary shared model.")
