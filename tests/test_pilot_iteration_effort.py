"""New local preparation gets headroom without altering old renders or physics."""

import copy
import xml.etree.ElementTree as ET

import pytest

from diffeoforge.pilot_iteration_effort import regional_allowance


def test_single_and_separate_areas_and_capture_keep_operator_headroom():
    recipe = dict(focus_width=0.1, residual=False)
    marks = [dict(symptom="detail")]
    before = copy.deepcopy((recipe, marks))
    simple = regional_allowance(recipe, marks)
    multiple = regional_allowance(recipe, [*marks, dict(symptom="curvature")])
    captured = regional_allowance(
        dict(recipe, capture_evidence=dict(original_to_fit_p95=0.3)), marks
    )
    inherited = regional_allowance(recipe, marks, 1400)
    assert 200 < simple["maximum_iterations"] < multiple["maximum_iterations"]
    assert captured["maximum_iterations"] >= multiple["maximum_iterations"]
    assert inherited["maximum_iterations"] == 1400
    assert before == (recipe, marks)
    assert all(
        not r["anatomical_approval"]
        and not r["convergence_claim"]
        and r["cumulative_iteration_limit"] is None
        for r in (simple, multiple, captured, inherited)
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True])
def test_untrusted_capture_does_not_invent_an_allowance(bad):
    with pytest.raises(ValueError, match="capture distance"):
        regional_allowance(
            dict(focus_width=0.1, capture_evidence=dict(original_to_fit_p95=bad)), []
        )


@pytest.mark.parametrize("symptom", ["detail", "curvature"])
def test_actual_guided_transition_and_generated_native_cap(tmp_path, monkeypatch, symptom):
    from test_regional_fit import (
        test_real_pilot_transition_stages_regional_assets_without_launching,
    )

    from diffeoforge import runs
    from diffeoforge.config import load_config

    prepare = runs.prepare_run
    generated = []

    def capture(config_path, *args, **kwargs):
        config = load_config(config_path)
        root = prepare(config_path, *args, **kwargs)
        xml = ET.parse(root / "engine/optimization_parameters.xml")
        cap = int(xml.find("max-iterations").text)
        assert cap == config["optimization"]["max_iterations"]
        assert cap >= 400
        assert config["optimization"]["method"] == "lbfgs"
        generated.append(cap)
        return root

    monkeypatch.setattr(runs, "prepare_run", capture)
    test_real_pilot_transition_stages_regional_assets_without_launching(
        tmp_path, monkeypatch, symptom
    )
    assert len(generated) == 1


def test_no_marks_keeps_unavailable_preview_readable_and_does_not_approve():
    row = regional_allowance(dict(focus_width=0.1), [])
    assert row["anatomical_approval"] is False


@pytest.mark.parametrize("runtime,method,expected", [
    (530., "gradient_ascent", True),
    (230., "gradient_ascent", False),
    (530., "lbfgs", False),
])
def test_slow_legacy_seed_has_one_review_checkpoint(monkeypatch, runtime, method, expected):
    from types import SimpleNamespace

    from diffeoforge import config
    from diffeoforge.pilot_iteration_effort import legacy_checkpoint

    monkeypatch.setattr(config, "load_config", lambda _: {"optimization": {"method": method}})
    prior = SimpleNamespace(config_path="seed.yaml", metrics={
        "runtime_seconds": runtime, "final_iteration": 120,
    })
    recipe = dict(phase="initial_warm", focus_width=.1, residual=False)
    marks = [dict(symptom="detail"), dict(symptom="missing")]
    checkpoint = legacy_checkpoint(recipe, 600, prior)
    assert bool(checkpoint) is expected
    if checkpoint:
        row = regional_allowance(dict(recipe, review_checkpoint=checkpoint), marks)
        assert row["maximum_iterations"] == 120
        assert row["cumulative_iteration_limit"] == 600
        with pytest.raises(ValueError, match="allowance"):
            invalid = dict(recipe, review_checkpoint=dict(checkpoint, total_iterations=601))
            regional_allowance(invalid, marks)
    assert regional_allowance(recipe, marks)["maximum_iterations"] == 600


@pytest.mark.parametrize("change,expected", [
    ("none", 480), ("no-gain", 0), ("reverse-worse", 0), ("missing-qc", 0),
    ("missing-measurement", 0), ("already-continued", 0), ("not-capped", 0),
])
def test_checkpoint_remainder_uses_bidirectional_gain_in_every_red_area(change, expected):
    from diffeoforge.pilot_adaptive_fit import HARD_QUALITY_FLAGS
    from diffeoforge.pilot_iteration_effort import checkpoint_remainder

    marks = [dict(symptom="detail"), dict(symptom="missing"),
             dict(symptom="position", purpose="fixed")]
    checkpoint = dict(version="regional-review-checkpoint-v1", first_iterations=120,
                      total_iterations=600)
    strategy = dict(regional_recipe=dict(review_checkpoint=checkpoint))

    def measured(region, forward, reverse):
        return dict(region=region,
                    repeats=[dict(original_to_fit_p95=forward, fit_to_original_p95=reverse)] * 2)

    info = dict(strategy=strategy, feedback=dict(
        regions=marks, baseline=[measured(row, .8, .7) for row in marks[:2]]))
    metrics = dict(maximum_iterations=120, final_iteration=120)
    quality = dict.fromkeys(HARD_QUALITY_FLAGS, True) | dict(marked_regions=marks)
    after = [measured(row, .5, .6) for row in marks[:2]]
    subject = dict(regional_quality=quality, marked_regions=dict(measurements=after))
    if change == "none":
        pass
    elif change == "no-gain":
        after[1] = measured(marks[1], .8, .7)
    elif change == "reverse-worse":
        after[1] = measured(marks[1], .5, .81)
    elif change == "missing-qc":
        del quality["spatial_resolution_sufficient"]
    elif change == "missing-measurement":
        after.pop()
    elif change == "already-continued":
        strategy["optimization"] = {"iterations": 480}
    elif change == "not-capped":
        metrics["final_iteration"] -= 1
    assert checkpoint_remainder(info, metrics, subject) == expected


def test_guarded_proposal_offers_only_the_remaining_checkpoint_budget(monkeypatch):
    from types import SimpleNamespace

    from diffeoforge import config, reference_calibration_study, reference_guided_pilot
    from diffeoforge.pilot_adaptive_fit import HARD_QUALITY_FLAGS
    from diffeoforge.regional_continuation import GUARD, _proposal

    markings = [{"symptom": "detail", "purpose": "problem"}]
    chosen = dict(target="shape.vtk", candidate_id="c", method="varifold", values={})

    def measurement(score):
        return [{"region": markings[0], "repeats": [
            dict(original_to_fit_p95=score, fit_to_original_p95=score),
        ] * 2}]

    info = dict(
        pilot_order=["shape.vtk"],
        feedback=dict(regions=markings, baseline=measurement(.8)),
        strategy=dict(regional_recipe=dict(review_checkpoint=dict(
            version="regional-review-checkpoint-v1", first_iterations=120, total_iterations=600
        ))),
    )
    subject = dict(regional_quality=dict.fromkeys(HARD_QUALITY_FLAGS, True)
                   | dict(marked_regions=markings),
                   marked_regions=dict(measurements=measurement(.55), outcome="improved"))
    metrics = dict(
        maximum_iterations=120, final_iteration=120, completed=True, converged=False,
        optimizer_stop_signal="maximum_iterations",
        attachment_comparison={"subjects": {"shape.vtk": subject}},
    )
    current = SimpleNamespace(status="completed", metrics=metrics, config_path="fit.yaml")
    snapshot = SimpleNamespace(plan=SimpleNamespace(pilot_subject_count=1), visual_reviews={})
    data = dict(current=current, current_reference=chosen, anchor=chosen, regions=markings,
                context=dict(feedback={"c": {"feedback": {"outcome": "better"}}}))
    frozen = dict(config={"optimization": {"max_iterations": 120}},
                  last_logged_native_iteration=120, accepted_native_iteration=120,
                  accepted_objective_progress=True, accepted_gradient_nonzero=True,
                  objective_sha256="objective", seals={}, accepted_parameter_sha256="accepted",
                  guard_objective_fingerprint="guard")
    monkeypatch.setattr(reference_guided_pilot, "record", lambda _: info)
    monkeypatch.setattr(reference_calibration_study, "calibration_candidate_run_directory",
                        lambda _: "run")
    provenance = {"finite_accepted_guard": GUARD}
    monkeypatch.setattr(config, "load_config",
                        lambda _: {"project": {"parameter_provenance": provenance}})
    monkeypatch.setattr("diffeoforge.regional_continuation.bundle", lambda _: frozen)
    result = _proposal(snapshot, "c", data)
    assert result["optimization_iterations"] == 480
    assert result["initialization_reference"] == chosen
    assert result["regional_continuation"]["marks"] == markings

    subject["regional_quality"]["no_new_intersection_flags"] = False
    assert _proposal(snapshot, "c", data) is None
    subject["regional_quality"]["no_new_intersection_flags"] = True

    info["strategy"]["optimization"] = {"iterations": 480}
    assert _proposal(snapshot, "c", data) is None
