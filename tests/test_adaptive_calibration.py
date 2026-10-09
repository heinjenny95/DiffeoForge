from dataclasses import replace

import pytest

from diffeoforge.adaptive_calibration import (
    FIT_PARAMETERS,
    AdaptiveSearchPolicy,
    FitObservation,
    adaptive_fit_decision,
)

VALUES = dict.fromkeys(FIT_PARAMETERS, 1.0)
BOUNDS = dict.fromkeys(FIT_PARAMETERS, (0.125, 8.0))


def row(name, scores, **kwargs):
    return FitObservation(name, VALUES, dict(zip(("one", "two"), scores, strict=True)), **kwargs)


def decide(rows, **kwargs):
    args = dict(
        expected_subjects=["one", "two"],
        policy=AdaptiveSearchPolicy(),
        bounds=BOUNDS,
        round_index=0,
        new_runs_used=0,
    )
    args.update(kwargs)
    return adaptive_fit_decision(rows, **args)


def test_fit_not_speed_or_small_average_selects_search_center():
    result = decide([row("bad-tail", [0.001, 0.9]), row("closer", [0.3, 0.3])])
    assert result.center_id == "closer"
    assert result.trials
    assert all(t.values["noise_std"] > 0 for t in result.trials)


def test_human_anatomy_acceptance_outranks_proxy_and_rejection_excludes_center():
    approved = row("anatomy-preserved", [.3, .4], review_approved=True, converged=False)
    rejected = row("bad-anatomy", [.01, .01], review_approved=False)
    numerical = row("unreviewed", [.02, .02])
    result = decide([approved, rejected, numerical], previous_center_id="bad-anatomy")
    assert result.center_id == "anatomy-preserved"
    assert result.trials
    assert decide([rejected]).stop_reason == "no_valid_fit_evidence"


def test_plateau_does_not_launch_another_blind_batch():
    result = decide(
        [row("base", [0.02, 0.5]), row("same", [0.02, 0.5])],
        previous_center_id="base",
        round_index=1,
        new_runs_used=7,
    )
    assert not result.trials
    assert result.stop_reason == "fit_plateau"


def test_improved_worst_subject_cannot_hide_damage_to_good_subject():
    result = decide(
        [row("base", [0.02, 0.5]), row("tradeoff", [0.03, 0.1])],
        previous_center_id="base",
        round_index=1,
        new_runs_used=7,
    )
    assert result.center_id == "base"
    assert result.regressions["tradeoff"] == ("one",)
    assert result.stop_reason == "specimen_tradeoff"


def test_dominating_fit_recenters_and_respects_remaining_budget():
    result = decide(
        [row("base", [0.02, 0.5]), row("better", [0.019, 0.1])],
        previous_center_id="base",
        round_index=1,
        new_runs_used=10,
    )
    assert result.center_id == "better"
    assert len(result.trials) == 2
    assert result.trials[1].values["noise_std"] == pytest.approx(2**-0.5)


def test_parameter_interactions_are_tested_and_spatial_changes_restart_field():
    result = decide([row("base", [0.02, 0.5])])
    trials = {t.label: t for t in result.trials}
    joint = trials["detail-and-fit"]
    assert joint.values["noise_std"] == joint.values["attachment_kernel_width"] == 0.5
    assert joint.initialization == "warm"
    assert trials["global-deformation"].initialization == "zero"
    assert trials["denser-controls"].initialization == "zero"


def test_finite_cap_limited_result_can_seed_more_optimization_without_approval():
    result = decide([row("base", [0.02, 0.5], converged=False)])
    assert result.trials[0].label == "continue"
    assert result.trials[0].values == VALUES
    assert result.trials[0].iterations == 300


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True])
def test_invalid_subject_evidence_does_not_seed_search(bad):
    assert decide([row("bad", [0.1, bad])]).stop_reason == "no_valid_fit_evidence"


def test_missing_subject_and_invalid_geometry_are_rejected():
    partial = FitObservation("partial", VALUES, {"one": 0.1})
    assert decide([partial, row("bad", [0.1, 0.2], invalid_faces=1)]).trials == ()


def test_bounds_and_deduplication_cannot_be_silently_bypassed():
    narrow = dict.fromkeys(FIT_PARAMETERS, (0.9, 1.1))
    first = decide([row("base", [0.1, 0.3])], bounds=narrow)
    assert len(first.trials) == 1  # Only continuation changes no spatial setting.
    second = decide(
        [row("base", [0.1, 0.3])], bounds=narrow, tested_trial_keys=[first.trials[0].trial_id]
    )
    assert second.trials == ()
    assert second.stop_reason == "no_new_trial_within_bounds"


def test_stop_budget_does_not_create_approval_or_new_work():
    result = decide([row("base", [0.1, 0.3])], new_runs_used=12)
    assert result.stop_reason == "budget_reached"
    assert not result.trials


def test_relative_strategy_scales_with_dataset_units():
    first = row("base", [0.01, 0.2])
    scaled = replace(first, values={k: v * 1000 for k, v in VALUES.items()})
    a = decide([first])
    b = decide([scaled], bounds={k: (lo * 1000, hi * 1000) for k, (lo, hi) in BOUNDS.items()})
    assert [t.label for t in a.trials] == [t.label for t in b.trials]
    for ta, tb in zip(a.trials, b.trials, strict=True):
        for name in FIT_PARAMETERS:
            assert tb.values[name] == pytest.approx(1000 * ta.values[name])


def test_missing_previous_center_never_silently_restarts_search():
    with pytest.raises(ValueError, match="previous search center"):
        decide([row("other", [0.1, 0.2])], previous_center_id="missing", round_index=1)
