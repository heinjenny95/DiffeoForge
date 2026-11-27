"""An inspected, unresolved method pair may inform another form without approval."""

from diffeoforge import reference_guided_pilot as guided


def provisional_comparison(snapshot, *, context=None):
    """Read scalar/history metadata only; this preview never prepares or runs a fit."""
    from diffeoforge.guided_strategy import _candidate, _context

    info = guided.record(snapshot)
    unavailable = dict(
        eligible=False,
        available=False,
        target=None,
        tested=[],
        explanation="Inspect both complete, technically valid method fits first.",
    )
    record = snapshot.attachment_comparison or {}
    methods = record.get("methods", {})
    candidates = snapshot.candidates
    if (
        not info
        or info.get("version") != guided.ADAPTIVE_VERSION
        or info.get("phase") != "screen"
        or info.get("goal")
        or record.get("regional_objective")
        or record.get("refinement")
        or len(candidates) != 2
        or snapshot.plan.pilot_subject_count != 1
        or {c.candidate_id for c in candidates} != set(methods)
        or set(methods.values()) != {"current", "varifold"}
    ):
        return unavailable
    values = [c.values for c in snapshot.current_stage.candidates]
    if len(values) != 2 or any(v != snapshot.plan.effective_values for v in values):
        return unavailable
    try:
        for candidate in candidates:
            _candidate(snapshot, candidate.candidate_id)
    except ValueError:
        return unavailable
    cases = context["cases"] if context is not None else _context(snapshot)[0]
    tested = {c["target"] for c in cases} | {info["target"]}
    order = info["pilot_order"]
    target = next((name for name in order if name not in tested), None)
    return dict(
        eligible=True,
        available=target is not None,
        target=target,
        tested=[name for name in order if name in tested],
        explanation=(
            "Compare coarse method behaviour on another selected diverse form. "
            "This does not approve either fit or add suitable coverage; the current "
            "fits and marks stay saved. Preparing starts no fit."
            if target
            else "All selected forms have already been screened. Choose an inspected "
            "starting method and refine the marked problems on this form, or inspect "
            "the saved alternatives. No additional comparison was prepared."
        ),
    )
