"""Choose a capable eligible starting basis before common checks, never mid-protocol."""
from copy import deepcopy


def rank(profiles):
    """Local residual counts prioritize a hard form, not a transferable ordinary basis."""
    eligible = [p for p in profiles if p["eligible_basis"]]
    return max(eligible, key=lambda p: p["controls"], default=None)


def prepare(snapshot, value):
    from diffeoforge.config import load_config
    from diffeoforge.guided_density import controls_for, refinement_for
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_common_basis import _physics
    from diffeoforge.pilot_form_progress import _protocol, configure

    result = deepcopy(value)
    protocol = value["protocol"]
    reference = protocol["reference"]
    base = verify_reference(reference)
    base_candidate = next(c for c in base.candidates
                          if c.candidate_id == reference["candidate_id"])
    config = load_config(base_candidate.config_path)
    configure(config, value, config["optimization"]["method"])
    physics = _physics(config)
    controls = controls_for(base.attachment_comparison, reference["candidate_id"])
    profiles = []
    for row in value["reviews"]:
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        parent = verify_reference(ref)
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        record = parent.attachment_comparison
        nested = refinement_for(record, ref["candidate_id"])
        capacity = (record.get("guided", {}).get("strategy") or {}).get("common_capacity_request")
        if capacity and nested.get("initialization") != "nested":
            source = capacity["protocol"]["reference"]
            previous = verify_reference(source)
            nested = dict(initialization="nested",
                          source_controls=controls_for(
                              previous.attachment_comparison, source["candidate_id"]))
        eligible = (not record.get("regional_objective")
            and nested.get("initialization") == "nested"
            and nested["source_controls"]["sha256"] == controls["sha256"]
            and ref["method"] == protocol["reference"]["method"]
            and _physics(load_config(candidate.config_path)) == physics)
        profiles.append(dict(row=row, parent=parent,
                             controls=controls_for(record, ref["candidate_id"])["count"],
                             eligible_basis=eligible,
                             regional=bool(record.get("regional_objective"))))
    chosen = rank(profiles)
    if chosen and chosen["controls"] > controls["count"]:
        result.update(origin_review=chosen["row"],
                      protocol=_protocol(chosen["parent"], chosen["row"]["candidate_id"]))
    selected_count = chosen["controls"] if chosen else controls["count"]
    from diffeoforge.pilot_common_capacity import demand

    counts = demand(value)
    return result, dict(controls=selected_count, required_controls=max(counts.values()),
        reference=result["protocol"]["reference"],
        demand=counts,
        reason="The shared basis must meet the largest accepted complete-field control "
               "demand, including local additions. A separate capacity candidate is prepared "
               "first if necessary; no smaller common basis is assumed sufficient.")
