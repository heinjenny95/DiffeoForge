"""Explicit rejected annotations stay goals even if the old accepted fit also missed them."""

from copy import deepcopy
from types import SimpleNamespace

from diffeoforge import pilot_common_diagnosis as diagnosis


def evidence(global_gap, marked_gap):
    def surface(value):
        return dict(
            diagonal=10.0,
            repeats=[
                dict(mean=value, p95=value, p99=value, regional_tail=value, regions={})
                for _ in range(2)
            ],
            warnings=[],
        )

    def patch(value, purpose="problem"):
        return dict(
            region=dict(purpose=purpose),
            repeats=[
                dict(
                    original_to_fit_p95=value,
                    original_to_fit_p99=value,
                    fit_to_original_p95=value,
                    fit_to_original_p99=value,
                )
                for _ in range(2)
            ],
        )

    return dict(
        accepted=surface(0.5),
        current=surface(global_gap),
        agreement=surface(global_gap),
        accepted_local=False,
        accepted_controls=200,
        current_controls=200,
        objective_tail=[-100.0, -99.0, -98.0],
        marked_accepted=[patch(0.5)],
        marked_current=[patch(marked_gap)],
    )


def assessed(monkeypatch, current, previous=None, *, rejected=True):
    from diffeoforge import guided_feedback

    accepted_ref = dict(directory="accepted", candidate_id="fit", target="public.vtk")
    current_ref = dict(accepted_ref, directory="current")
    previous_ref = dict(accepted_ref, directory="previous") if previous else None
    accepted = SimpleNamespace(attachment_comparison=dict(guided=dict(screen_trials_spent=1)))
    saved = SimpleNamespace(visual_reviews={"fit": False} if rejected else {})
    monkeypatch.setattr(
        guided_feedback,
        "verify_reference",
        lambda r: accepted if r["directory"] == "accepted" else saved,
    )
    monkeypatch.setattr(guided_feedback, "reference", lambda *a: accepted_ref)
    monkeypatch.setattr(
        guided_feedback,
        "region_state",
        lambda *a: ([r["region"] for r in current["marked_current"]], False),
    )

    def compared(_a, b, **kwargs):
        return dict(
            deepcopy(previous if b["directory"] == "previous" else current),
            original_sha256="bound-original",
            template_sha256="bound-template",
        )

    monkeypatch.setattr(diagnosis, "_compare", compared)
    value = dict(reviews=[dict(directory="accepted", candidate_id="fit", filename="public.vtk")])
    return diagnosis.diagnose(None, value, current_ref, previous_ref)


def test_active_problem_plateau_vetoes_iterations_despite_improving_toward_poor_accepted_fit(
    monkeypatch,
):
    current, previous = evidence(0.2, 0.4), evidence(0.4, 0.4)
    result = assessed(monkeypatch, current, previous)
    assert result["gap"] and result["marked_progress"] is False
    assert diagnosis.recommend(result, capped=True)["kind"] != "iterations"


def test_active_problem_needs_an_actual_local_progress_comparison(monkeypatch):
    result = assessed(monkeypatch, evidence(0.2, 0.4))
    assert result["gap"] and result["marked_progress"] is False
    assert diagnosis.recommend(result, capped=True)["kind"] == "capacity"


def test_measured_progress_at_every_active_problem_allows_the_existing_bounded_test(monkeypatch):
    result = assessed(monkeypatch, evidence(0.2, 0.2), evidence(0.4, 0.4))
    assert result["gap"] and result["marked_progress"] is True
    assert diagnosis.recommend(result, capped=True)["kind"] == "iterations"


def test_preserved_areas_do_not_have_to_keep_improving(monkeypatch):
    current, previous = evidence(0.2, 0.4), evidence(0.4, 0.4)
    for measured in (current, previous):
        measured["marked_current"][0]["region"]["purpose"] = "fixed"
        measured["marked_accepted"][0]["region"]["purpose"] = "fixed"
    result = assessed(monkeypatch, current, previous)
    assert not result["gap"] and result["marked_progress"] is None


def test_a_forward_gain_cannot_hide_a_reverse_regression_in_an_active_problem(monkeypatch):
    current, previous = evidence(0.2, 0.2), evidence(0.4, 0.4)
    for repeat in current["marked_current"][0]["repeats"]:
        repeat["fit_to_original_p99"] = 0.6
    result = assessed(monkeypatch, current, previous)
    assert result["marked_progress"] is False
    assert diagnosis.recommend(result, capped=True)["kind"] != "iterations"


def test_unreviewed_legacy_comparison_does_not_invent_a_rejected_problem_goal(monkeypatch):
    result = assessed(monkeypatch, evidence(0.2, 0.4), evidence(0.4, 0.4), rejected=False)
    assert not result["gap"] and result["marked_progress"] is None
