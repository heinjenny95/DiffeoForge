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
    """Revisit hypotheses at larger contrasts; no one-test-per-family dead end."""
    relevant = [r for r in cases if r["method"] == method and r["target"] == target
                and not r.get("approval")]
    if not relevant:
        return fallback, ""
    families = ("detail", "weight", "local_motion", "density")
    counts = {g: sum(r.get("goal") == g for r in relevant) for g in families}
    last = relevant[-1]
    family, outcome = last.get("goal"), last.get("outcome")
    if (outcome == "same" and family in families and counts[family] < 2
            and len({r.get("goal") for r in relevant} & set(families)) == 1):
        return family, "Test a larger contrast from the retained fit. "
    if outcome == "better":
        return fallback, ""
    alternatives = [g for g in families if g != family or outcome != "worse"]
    return min(alternatives, key=lambda g: counts[g]), (
        "Try another explanation from the retained fit. Previous tests remain available; "
        "each parameter can be revisited at a different scale. "
    )
