"""Numerical headroom and exhausted hypotheses, separate from visual acceptance."""


def iteration_limited(candidate):
    """Require an explicit native cap stop, never infer it from a poor-looking fit."""
    metrics = candidate.metrics or {}
    cap, final = metrics.get("maximum_iterations"), metrics.get("final_iteration")
    return (
        candidate.status == "completed"
        and metrics.get("completed") is True
        and metrics.get("converged") is False
        and metrics.get("optimizer_stop_signal") == "maximum_iterations"
        and type(cap) is int and cap > 0
        and type(final) is int and final >= cap
    )


def next_hypothesis(cases, method, target, fallback):
    """Try another explanation after rejected detail tests, not endless width cuts."""
    relevant = [r for r in cases if r["method"] == method and r["target"] == target
                and not r.get("approval")]
    details = [r for r in relevant if r.get("goal") == "detail"]
    failed_detail = any(r.get("outcome") in {"same", "worse", "unsure", "rejected"}
                        for r in details)
    if len(details) < 2 and not failed_detail:
        return fallback, ""
    tested = {r.get("goal") for r in relevant}
    reason = (
        "Finer surface matching has already been tried without a suitable fit. "
        "Test a different explanation while keeping the saved reference. "
    )
    if "weight" not in tested:
        return "weight", reason
    if "local_motion" not in tested:
        return "local_motion", reason
    if "density" not in tested:
        return "density", (
            "The previous parameter changes did not resolve the missing detail. "
            "Control-point density has not been tested on this form. "
        )
    return None, (
        "These guided hypotheses have not produced a suitable fit. Review the saved "
        "attempts and the original template alignment below before choosing another test. "
        "A completed test does not establish that its parameter cannot help."
    )
