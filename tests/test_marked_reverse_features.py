"""Public regression fixtures for sparse reverse features; no optimizer runs."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import guided_feedback, guided_response, pilot_common_diagnosis, pilot_regions


def test_a_tiny_marked_reconstructed_patch_gets_direct_reverse_samples():
    body = [(10.0, 0.0, 0.0), (110.0, 0.0, 0.0), (10.0, 100.0, 0.0)]
    patch = [(0.0, 0.0, 0.0), (0.002, 0.0, 0.0), (0.0, 0.002, 0.0)]
    extra = [(0.0, 0.0, 0.01), (0.002, 0.0, 0.01), (0.0, 0.002, 0.01)]
    original = SimpleNamespace(
        vertices=np.array(body + patch), triangles=np.array([[0, 1, 2], [3, 4, 5]])
    )
    fit = SimpleNamespace(
        vertices=np.array(body + patch + extra),
        triangles=np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]]),
    )
    region = dict(center=[0.0007, 0.0007, 0.005], radius=0.02, purpose="problem")
    row = pilot_regions.measure(original, fit, [region])[0]
    assert all(r["original_to_fit_p95"] < 1e-6 for r in row["repeats"])
    assert all(
        r["reverse_count"] >= 2048 and r["fit_to_original_p95"] > 0.009 for r in row["repeats"]
    )


def surface(value):
    return dict(
        diagonal=10.0,
        repeats=[
            dict(mean=value, p95=value, p99=value, regional_tail=value, regions={})
            for _ in range(2)
        ],
        warnings=[],
    )


@pytest.mark.parametrize("tail_key", ["fit_to_original_p99", "original_to_fit_p99"])
def test_marked_p99_regression_vetoes_more_unchanged_iterations(tail_key):
    def evidence(value, reverse99):
        patch = dict(
            region=dict(purpose="problem"),
            repeats=[
                dict(
                    original_to_fit_p95=0.01,
                    original_to_fit_p99=0.01,
                    fit_to_original_p95=0.01,
                    fit_to_original_p99=reverse99,
                )
            ]
            * 2,
        )
        patch["repeats"][0][tail_key] = reverse99
        accepted = deepcopy(patch)
        accepted["repeats"][0][tail_key] = 0.01
        return dict(
            accepted=surface(0.01),
            current=surface(value),
            agreement=surface(value),
            accepted_local=True,
            accepted_controls=200,
            current_controls=200,
            objective_tail=[-100.0, -99.0, -98.0],
            marked_accepted=[accepted],
            marked_current=[patch],
        )

    measured = pilot_common_diagnosis.assess(evidence(0.2, 0.8), evidence(0.4, 0.2))
    assert measured["trend"] == "worse"
    assert any(x["region"].endswith(tail_key) for x in measured["local_losses"])
    assert pilot_common_diagnosis.recommend(measured, capped=True)["kind"] != "iterations"


def response(mean=1.0, reverse95=1.0, reverse99=1.0):
    repeat = dict(
        original_to_fit_mean=mean,
        original_to_fit_p95=2.0,
        original_to_fit_p99=2.0,
        fit_to_original_p95=reverse95,
        fit_to_original_p99=reverse99,
    )
    return dict(
        baseline=[dict(region=dict(purpose="problem"), diagonal=10.0, repeats=[repeat] * 2)],
        global_baseline=dict(repeats=[dict(mean=1.0, p95=2.0, p99=3.0)] * 2, warnings=[]),
    )


def test_reverse_p99_loss_is_a_tradeoff_even_when_forward_mean_improves():
    assert guided_response.compare(response(), response(0.7, reverse99=4.0))["status"] == "tradeoff"


def test_removing_an_extra_reverse_projection_counts_as_measured_improvement():
    assert (
        guided_response.compare(response(), response(reverse95=0.5, reverse99=0.5))["status"]
        == "improved"
    )


def test_reverse_gain_cannot_hide_lost_original_surface():
    assert (
        guided_response.compare(response(), response(1.2, reverse95=0.5, reverse99=0.5))["status"]
        == "tradeoff"
    )


def test_direct_reverse_p99_detects_a_projection_that_local_p95_still_misses():
    body = [(10.0, 0.0, 0.0), (110.0, 0.0, 0.0), (10.0, 100.0, 0.0)]
    patch = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    extra = [(0.1, 0.1, 0.05), (0.2, 0.1, 0.05), (0.1, 0.3, 0.05)]
    original = SimpleNamespace(
        vertices=np.array(body + patch), triangles=np.array([[0, 1, 2], [3, 4, 5]])
    )
    fit = SimpleNamespace(
        vertices=np.array(body + patch + extra),
        triangles=np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]]),
    )
    region = dict(center=[0.33, 0.33, 0.0], radius=1.0, purpose="problem")
    row = pilot_regions.measure(original, fit, [region])[0]
    assert all(
        r["fit_to_original_p95"] < 1e-6 and r["fit_to_original_p99"] > 0.049 for r in row["repeats"]
    )


def test_legacy_global_reverse_measurements_are_remeasured_without_changing_receipts(monkeypatch):
    from diffeoforge import pilot_recovery

    marks = [dict(center=[0, 0, 0], radius=1)]
    legacy = response()["baseline"]
    legacy[0]["region"] = marks[0]
    for repeat in legacy[0]["repeats"]:
        repeat.pop("fit_to_original_p99", None)
    saved = deepcopy(legacy)
    subject = dict(marked_regions=dict(measurements=legacy), repeats=[])
    parent = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                candidate_id="probe",
                metrics=dict(attachment_comparison=dict(subjects={"public": subject})),
            )
        ]
    )
    monkeypatch.setattr(guided_feedback, "verify_reference", lambda _: parent)
    calls = []
    monkeypatch.setattr(
        pilot_recovery, "capture", lambda *a, **k: calls.append(k) or dict(baseline=["fresh"])
    )
    value = guided_response.measured(
        dict(directory="thin-reverse-regression", candidate_id="probe", target="public"), marks
    )
    assert value["baseline"] == ["fresh"] and calls
    assert legacy == saved
