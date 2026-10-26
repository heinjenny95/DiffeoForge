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
