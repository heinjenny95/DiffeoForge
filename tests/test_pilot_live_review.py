"""Accepted-state timing, stale-decision and preview-scope regressions."""

import ast
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_reference_finite_accepted_guard import config_fixture, render

from diffeoforge.pilot_live_review import preview_models, read_review, request_review_action
from diffeoforge.pilot_review_assets import DECLARATION, SOURCE
from diffeoforge.reference_finite_accepted_guard import mark_new_configuration
from diffeoforge.runs import prepare_run


def prepared(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepare_run(path, run_id="review-test")
    return run, json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def runtime_fixture(tmp_path, monkeypatch, *, action="continue", cached=False):
    import xml.etree.ElementTree as ET

    run, manifest = prepared(tmp_path)
    module = {}
    exec(compile(SOURCE, "pilot_review_runtime.py", "exec"), module)
    clock = [0.0]
    xml = ET.parse(run / "engine/model.xml").getroot()
    objects, points = [], []
    for row in xml.find("template"):
        p = (run / "engine" / row.find("filename").text).resolve()
        from diffeoforge.mesh import read_vtk_points

        vertices = read_vtk_points(p)
        count = len(vertices)
        objects.append(
            SimpleNamespace(
                type=row.find("deformable-object-type").text, get_number_of_points=lambda n=count: n
            )
        )
        points.extend(vertices)
    array = np.array(points, dtype=np.float32)
    tensor = SimpleNamespace()
    tensor.detach = lambda: tensor
    tensor.cpu = lambda: tensor
    tensor.numpy = lambda: array
    values = np.full(6, 0.25, dtype=np.float64)
    key = hashlib.sha256(
        str(values.shape).encode() + values.dtype.str.encode() + values.tobytes()
    ).hexdigest()
    state = dict(x=values, key=key, evaluation=3 if cached else 4, f=7.25)
    guard = SimpleNamespace(
        evaluations=4,
        accepted_count=2,
        accepted=state,
        require_bound_vector=lambda actual, expected, reason: np.testing.assert_array_equal(
            actual, expected["x"]
        ),
        _active=lambda: None,
    )
    estimator = SimpleNamespace(
        current_iteration=2,
        max_iterations=600,
        _vectorize_parameters=lambda x: x,
        _get_parameters=lambda: values,
        statistical_model=SimpleNamespace(
            template=SimpleNamespace(object_list=objects),
            exponential=SimpleNamespace(get_template_points=lambda: dict(landmark_points=tensor)),
        ),
    )
    context = SimpleNamespace(
        root=run, engine=run / "engine", manifest=manifest, verify_content=lambda: None
    )
    review = module["Review"](context, estimator, guard, clock=lambda: clock[0])
    clock[0] = 601.0
    seen = []

    def sleep(_):
        clock[0] += 123.0
        bound = read_review(run)
        assert bound is not None
        seen.append(bound)
        request_review_action(bound, action)

    monkeypatch.setattr(module["time"], "sleep", sleep)
    return review, state, clock, seen, run


def test_only_new_configurations_enable_review_and_native_sources_remain_python38(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    assert config["project"]["parameter_provenance"]["pilot_review"] == DECLARATION
    new = render(config)
    assert new["pilot_review_runtime.py"] == SOURCE
    ast.parse(SOURCE.decode(), feature_version=(3, 8))
    config["project"]["parameter_provenance"].pop("pilot_review")
    legacy = render(config)
    assert "pilot_review_runtime.py" not in legacy
    assert "_df_review_install" not in legacy["sitecustomize.py"].decode()
    assert new["model.xml"] == legacy["model.xml"]
    assert new["optimization_parameters.xml"] == legacy["optimization_parameters.xml"]


def test_intermediate_review_cannot_silently_opt_into_an_unguarded_run(tmp_path):
    from diffeoforge.config import ConfigurationError, validate_schema

    config = config_fixture(tmp_path)
    config["project"]["parameter_provenance"]["pilot_review"] = dict(DECLARATION)
    with pytest.raises(ConfigurationError):
        validate_schema(config)
    with pytest.raises(ConfigurationError, match="finite accepted guard"):
        render(config)


def test_review_finish_is_distinct_from_a_native_cap_and_does_not_mask_line_search_failure():
    from diffeoforge.analysis.reference_convergence_visualization import (
        detect_reference_stop_evidence,
    )

    text = ">> STOP: PILOT REVIEW REQUEST (accepted state; not convergence)\n"
    native_callback_message = ">> STOP: TOTAL NO. of ITERATIONS EXCEEDS LIMIT"
    observed = detect_reference_stop_evidence(
        text + native_callback_message, final_iteration=17, maximum_iterations=600
    )
    assert observed.signal == "pilot_review_request"
    assert "convergence" in observed.summary
    failure = detect_reference_stop_evidence(
        text + "Number of line search loops exceeded", final_iteration=17, maximum_iterations=600
    )
    assert failure.signal == "line_search_exhausted"


def test_continue_excludes_review_wait_and_preserves_parameters_and_model(tmp_path, monkeypatch):
    review, state, clock, seen, run = runtime_fixture(tmp_path, monkeypatch)
    before = state["x"].copy()
    review.after_accept(state)
    assert len(seen) == 1 and review.waited == 123.0
    assert read_review(run) is None
    np.testing.assert_array_equal(before, state["x"])
    assert review.estimator.max_iterations == 600
    assert not (run / "output/pilot-review/finish.json").exists()
    assert not review.due()
    clock[0] += 599.0
    assert not review.due()
    clock[0] += 1.0
    assert review.due()
    original, fit = preview_models_for_waiting_snapshot(seen[0])
    assert original.point_count > 0 and fit.point_count > 0


def preview_models_for_waiting_snapshot(bound):
    # Test-only restore of the control pointer. No scientific process exists.
    path = bound["run"] / "output/pilot-review/live.json"
    path.write_text(json.dumps(bound["live"]), encoding="utf-8")
    return preview_models(bound)


def test_finish_requests_native_finalization_without_claiming_convergence(tmp_path, monkeypatch):
    review, state, _, seen, run = runtime_fixture(tmp_path, monkeypatch, action="finish")
    with pytest.raises(StopIteration):
        review.after_accept(state)
    finish = json.loads((run / "output/pilot-review/finish.json").read_text())
    assert finish["action"] == "finish" and finish["numerical_convergence"] is False
    assert finish["parameter_sha256"] == state["key"]
    assert len(seen) == 1
    from diffeoforge.pilot_live_review import verified_finish

    with pytest.raises(FileNotFoundError):
        verified_finish(run)  # A decision alone cannot fabricate a normal guard return.


@pytest.mark.parametrize("case", ["initial", "cap", "cached", "before_budget"])
def test_no_review_of_initial_terminal_or_mismatched_cached_geometry(tmp_path, monkeypatch, case):
    review, state, clock, seen, _ = runtime_fixture(tmp_path, monkeypatch, cached=case == "cached")
    if case == "cap":
        review.estimator.current_iteration = 601
    if case == "before_budget":
        clock[0] = 599.0
    review.after_accept(state, initial=case == "initial")
    assert seen == [] and review.generation == 0


def test_stale_and_changed_preview_cannot_receive_a_decision(tmp_path, monkeypatch):
    review, state, _, seen, run = runtime_fixture(tmp_path, monkeypatch)
    review.after_accept(state)
    with pytest.raises(ValueError, match="no longer waiting"):
        request_review_action(seen[0], "continue")
    path = run / "output/pilot-review/live.json"
    path.write_text(json.dumps(seen[0]["live"]), encoding="utf-8")
    (seen[0]["folder"] / "points.npy").write_bytes(b"bad")
    with pytest.raises(ValueError, match="array changed"):
        read_review(run)


def test_live_panel_loads_optional_detail_and_sends_one_generation_bound_decision(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.pilot_live_review import PilotLiveReviewPanel

    application = QApplication.instance() or QApplication([])
    review, state, _, seen, run = runtime_fixture(tmp_path, monkeypatch)
    review.after_accept(state)
    monkeypatch.undo()  # Restore the real clock/sleep before the Qt event loop.
    bound = seen[0]
    (bound["folder"] / "command.json").unlink()
    (run / "output/pilot-review/live.json").write_text(json.dumps(bound["live"]), encoding="utf-8")
    import time

    panel = PilotLiveReviewPanel()
    panel.resize(1000, 680)
    panel.set_run(run)
    panel.poll()
    deadline = time.monotonic() + 15
    while not panel.finish_button.isEnabled() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert panel.bound is not None and panel.canvas.reconstruction_model.point_count > 0
    assert "projections captured" in panel.note.text()
    panel.canvas.original_detail.setChecked(True)
    while not panel.finish_button.isEnabled() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert not panel.canvas.reconstruction_model.geometry_is_proxy
    assert not panel.canvas.original_model.geometry_is_proxy
    panel.finish_button.click()
    command = json.loads((bound["folder"] / "command.json").read_text())
    assert command["action"] == "finish" and command["nonce"] == bound["live"]["nonce"]
    assert not panel.continue_button.isEnabled() and not panel.finish_button.isEnabled()
    panel.active = lambda: False
    panel.poll()
    assert panel.bound is None and panel.run is None and panel.isHidden()
    panel.timer.stop()
    panel.close()
