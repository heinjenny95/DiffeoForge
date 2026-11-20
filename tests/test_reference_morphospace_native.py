"""Accepted-step and final-export checks against the native adapter protocol."""

import hashlib
import inspect
import json
import math
import pickle
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from diffeoforge import reference_morphospace_native as native
from diffeoforge.reference_checkpoint_schedule import SITECUSTOMIZE


class Exponential:
    def write_flow(self):
        self.flows += 1


class BaseEstimator:
    def update(self):
        self.invocations += 1


def _adapt(monkeypatch, mode, *, long_window=400):
    class Gradient(BaseEstimator):
        def __init__(self, folder, *, origin=0, maximum=325, pattern=None, subjects=3):
            self.output_dir = str(folder)
            self.state_file = str(folder / "deformetrica-state.p")
            self.current_iteration = origin
            self.max_iterations = maximum
            self.convergence_tolerance = 0.1
            self.current_parameters = {"iteration": origin}
            self.callback_ret = True
            self.callback = None
            self.invocations = 0
            self.line_search_failure = None
            self.bad_trial = None
            self.numerical_failure = None
            self.cancel_at = None
            self.printed = []
            self.exports = []
            self.dataset = SimpleNamespace(subject_ids=[f"specimen-{i}" for i in range(subjects)])
            self.base_momenta = np.zeros((subjects, 1, 3))
            self.base_momenta[:, 0, 0] = np.arange(subjects)
            exponential = Exponential()
            exponential.flows = 0
            self.statistical_model = SimpleNamespace(
                exponential=exponential,
                get_momenta=lambda: self.momenta,
                get_control_points=lambda: np.zeros((1, 3)),
            )
            self.pattern = pattern or (lambda momenta, iteration: momenta)
            self._set_parameters(self.current_parameters)

        def _set_parameters(self, parameters):
            self.momenta = self.pattern(self.base_momenta.copy(), parameters["iteration"])

        def _evaluate_model_fit(self, parameters, with_grad=False):
            self._set_parameters(parameters)
            iteration = parameters["iteration"]
            if iteration == self.cancel_at:
                raise KeyboardInterrupt
            objective = -40.0 if iteration == 0 else -10.0 + iteration * 0.005
            if with_grad:
                gradient = math.nan if iteration == self.numerical_failure else 0.01
                return objective, 0.0, {"momenta": np.array([gradient])}
            if iteration == self.bad_trial:
                objective = -math.inf
            return objective, 0.0

        def print(self):
            self.printed.append(self.current_iteration)

        def _dump_state_file(self):
            Path(self.state_file).write_bytes(pickle.dumps({
                "current_parameters": self.current_parameters,
                "current_iteration": self.current_iteration,
            }))

        def write(self):
            self.exports.append((self.current_iteration, self.momenta.copy()))
            for _ in self.dataset.subject_ids:
                self.statistical_model.exponential.write_flow()
            self._dump_state_file()

        def update(self):
            super().update()
            self.current_attachment, self.current_regularity, gradient = self._evaluate_model_fit(
                self.current_parameters, with_grad=True)
            self.current_log_likelihood = self.current_attachment + self.current_regularity
            self.print()
            initial_log_likelihood = self.current_log_likelihood
            last_log_likelihood = initial_log_likelihood
            while self.callback_ret and self.current_iteration < self.max_iterations:
                assert gradient["momenta"].shape == (1,)
                self.current_iteration += 1
                new_parameters = {"iteration": self.current_iteration}
                new_attachment, new_regularity = self._evaluate_model_fit(new_parameters)
                found_min = (self.current_iteration != self.line_search_failure
                             and new_attachment > -math.inf)
                if not found_min:
                    self._set_parameters(self.current_parameters)
                    break
                self.current_attachment = new_attachment
                self.current_regularity = new_regularity
                self.current_log_likelihood = new_attachment + new_regularity
                self.current_parameters = new_parameters
                self._set_parameters(self.current_parameters)
                delta_f_current = last_log_likelihood - self.current_log_likelihood
                delta_f_initial = initial_log_likelihood - self.current_log_likelihood
                if (math.fabs(delta_f_current)
                        < self.convergence_tolerance * math.fabs(delta_f_initial)):
                    break
                self.print()
                if self.current_iteration % 40 == 0:
                    self.write()
                if self.callback is not None:
                    self.callback_ret = self.callback()
                last_log_likelihood = self.current_log_likelihood
                if not self.current_iteration == self.max_iterations:
                    gradient = self._evaluate_model_fit(self.current_parameters, with_grad=True)[2]
                if self.current_iteration % 40 == 0:
                    self._dump_state_file()

    for name, cls, attribute in (
        ("deformetrica.core.estimators.gradient_ascent", Gradient, "GradientAscent"),
        ("deformetrica.core.model_tools.deformations.exponential", Exponential, "Exponential"),
    ):
        module = ModuleType(name)
        setattr(module, attribute, cls)
        monkeypatch.setitem(sys.modules, name, module)
    source = textwrap.dedent(inspect.getsource(Gradient.update))
    monkeypatch.setattr(native, "UPDATE_SHA256", hashlib.sha256(source.encode()).hexdigest())

    def install(subjects=3):
        from diffeoforge.reference_checkpoint_schedule import render_adapter

        config = {
            "project": {"atlas_stop": {"mode": mode, "check_interval": 25,
                                       "window_iterations": 200, "cohort_threshold_percent": 1.0,
                                       "specimen_threshold_percent": 2.0}},
            "output": {"checkpoint_mode": "compact_final_export"},
            "optimization": {"method": "gradient_ascent"},
            "model": {"deformation": {"kernel_width": 1.0}},
        }
        if long_window is not None:
            config["project"]["atlas_stop"]["long_window_iterations"] = long_window
        labels = tuple(f"specimen-{i}" for i in range(subjects))
        scope = {}
        # Make a failed hook raise during tests instead of exiting the Python process.
        source = render_adapter(morphospace_source=native.adapter_source(config, labels))
        exec(source.replace("os._exit(1)", "raise"), scope)
        return scope

    return Gradient, install


def _report(folder):
    return json.loads((folder / native.REPORT_NAME).read_text(encoding="utf-8"))


def test_tolerance_terminal_includes_last_accepted_step_not_printed(monkeypatch, tmp_path):
    gradient, install = _adapt(monkeypatch, "optimizer_convergence")
    install()
    estimator = gradient(tmp_path)
    estimator.update()
    assert estimator.printed == [0, 1]
    assert estimator.invocations == 1
    assert estimator.exports == []
    estimator.write()
    report = _report(tmp_path)
    assert report["terminal"]["reason"] == "native_tolerance"
    assert report["terminal"]["iteration"] == 2
    assert report["terminal"]["export"] == "complete"
    row = report["observations"][-1]
    assert row["window_iterations"] == 2
    assert row["cohort_percent"] == 0.0
    assert not row["stable"]
    assert row["objective"] > report["observations"][0]["objective"]


@pytest.mark.parametrize("maximum", [200, 325])
def test_auto_exports_exact_accepted_checkpoint_in_one_invocation(monkeypatch, tmp_path, maximum):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install()
    estimator = gradient(tmp_path, maximum=maximum)
    estimator.update()
    assert estimator.invocations == 1
    assert estimator.current_iteration == 200
    assert estimator.exports == []
    estimator.write()
    report = _report(tmp_path)
    row = report["observations"][-1]
    assert row["previous_iteration"] == 0
    assert row["window_iterations"] == 200
    assert row["stable"]
    assert row["long_window"]["window_iterations"] == 200
    assert not row["long_window"]["stable"]
    assert estimator.exports[0][0] == report["terminal"]["iteration"] == row["iteration"]
    assert report["terminal"]["reason"] == "morphospace_stable"
    assert report["terminal"]["checkpoint_sha256"] == hashlib.sha256(
        Path(estimator.state_file).read_bytes()).hexdigest()
    with np.load(tmp_path / row["checkpoint"]["path"], allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["momenta"], estimator.exports[0][1])


@pytest.mark.parametrize("case", ["one_subject", "cohort"])
def test_auto_both_thresholds_required_and_terminal_shorter_window(monkeypatch, tmp_path, case):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install(subjects=100)

    def pattern(momenta, iteration):
        if case == "one_subject":
            momenta[-1, 0, 0] += 1.8 * iteration / 200
        else:
            momenta *= 1.0 + 0.015 * iteration / 200
        return momenta

    estimator = gradient(tmp_path, maximum=222, pattern=pattern, subjects=100)
    estimator.update()
    report = _report(tmp_path)
    before_cap, terminal = report["observations"][-2:]
    assert not before_cap["stable"]
    assert before_cap["iteration"] == 200
    if case == "one_subject":
        assert before_cap["cohort_percent"] < 1.0
        assert before_cap["max_subject_percent"] >= 2.0
        assert before_cap["worst_subjects"] == ["specimen-99"]
    else:
        assert before_cap["cohort_percent"] > 1.0
        assert before_cap["max_subject_percent"] < 2.0
    assert report["terminal"]["reason"] == "iteration_limit"
    assert terminal["iteration"] == 222
    assert terminal["window_iterations"] == 197


@pytest.mark.parametrize("degenerate_origin", [False, True])
def test_long_window_blocks_stop_when_primary_passes(monkeypatch, tmp_path, degenerate_origin):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install()

    def pattern(momenta, iteration):
        if iteration == 0 and degenerate_origin:
            return np.zeros_like(momenta)
        return momenta * (1.04 if iteration >= 200 else 1.0)

    estimator = gradient(tmp_path, maximum=700, pattern=pattern)
    estimator.update()
    estimator.write()
    report = _report(tmp_path)
    at_400 = next(row for row in report["observations"] if row["iteration"] == 400)
    assert at_400["stable"]
    assert at_400["long_window"]["previous_iteration"] == 0
    assert at_400["long_window"]["window_iterations"] == 400
    assert not at_400["long_window"]["stable"]
    if degenerate_origin:
        assert at_400["long_window"]["status"] == "unavailable"
    else:
        assert at_400["long_window"]["cohort_percent"] == pytest.approx(4.0)
    last = report["observations"][-1]
    assert last["stable"] and last["long_window"]["stable"]
    assert last["long_window"]["previous_iteration"] == 200
    assert report["terminal"]["reason"] == "morphospace_stable"
    assert report["terminal"]["iteration"] == 600
    assert estimator.invocations == 1
    assert estimator.exports[0][0] == 600


def test_cap_at_400_with_long_window_open_is_budget_stop(monkeypatch, tmp_path):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install()

    def pattern(momenta, iteration):
        return momenta * (1.04 if iteration >= 200 else 1.0)

    estimator = gradient(tmp_path, maximum=400, pattern=pattern)
    estimator.update()
    report = _report(tmp_path)
    assert report["observations"][-1]["stable"]
    assert not report["observations"][-1]["long_window"]["stable"]
    assert report["terminal"]["reason"] == "iteration_limit"


def test_already_prepared_policy_keeps_legacy_observations(monkeypatch, tmp_path):
    gradient, install = _adapt(monkeypatch, "morphospace_stability", long_window=None)
    install()
    gradient(tmp_path).update()
    report = _report(tmp_path)
    assert not any("long_window" in row for row in report["observations"])
    assert report["terminal"]["iteration"] == 200


@pytest.mark.parametrize("mode", ["optimizer_convergence", "morphospace_stability"])
def test_prior_iterations_and_individual_fits_do_not_count(monkeypatch, tmp_path, mode):
    gradient, install = _adapt(monkeypatch, mode)
    install()
    individual = gradient(tmp_path, subjects=1)
    individual._df_individual_initialization = True
    individual.update()
    assert individual.current_iteration == 2
    assert not (tmp_path / native.REPORT_NAME).exists()
    estimator = gradient(tmp_path, origin=100, maximum=301)
    estimator.update()
    report = _report(tmp_path)
    assert report["joint_origin_iteration"] == 100
    assert report["observations"][0]["iteration"] == 100
    if mode == "morphospace_stability":
        assert report["terminal"]["iteration"] == 300
    else:
        assert report["terminal"]["iteration"] == 111


@pytest.mark.parametrize(("failure", "reason", "accepted"), [
    ("line_search_failure", "line_search_exhausted", 50),
    ("bad_trial", "numerical_failure", 50),
    ("numerical_failure", "numerical_failure", 51),
    ("cancel_at", "cancelled", 50),
])
def test_failure_and_cancellation_keep_true_accepted_iteration(
    monkeypatch, tmp_path, failure, reason, accepted,
):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install()
    estimator = gradient(tmp_path)
    setattr(estimator, failure, 51)
    if failure == "cancel_at":
        with pytest.raises(KeyboardInterrupt):
            estimator.update()
    elif reason == "numerical_failure":
        with pytest.raises(RuntimeError, match="Nonfinite atlas gradient|No finite atlas"):
            estimator.update()
    else:
        estimator.update()
    report = _report(tmp_path)
    assert report["terminal"]["reason"] == reason
    assert report["terminal"]["iteration"] == accepted
    assert pickle.loads(Path(estimator.state_file).read_bytes())["current_iteration"] == accepted


def test_cancel_during_flow_export_is_distinct_from_stable_fit(monkeypatch, tmp_path):
    gradient, install = _adapt(monkeypatch, "morphospace_stability")
    install()
    estimator = gradient(tmp_path)
    estimator.update()

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(estimator.statistical_model.exponential, "write_flow", interrupt)
    with pytest.raises(KeyboardInterrupt):
        estimator.write()
    report = _report(tmp_path)
    assert report["observations"][-1]["stable"]
    assert report["terminal"]["reason"] == "cancelled"
    assert report["terminal"]["export"] == "failed"


def test_legacy_schedule_does_not_include_optional_instrumentation():
    from diffeoforge.reference_checkpoint_schedule import render_adapter

    assert native.adapter_source({}, ()) == ""
    assert "_df_ms_" not in render_adapter()
    assert all(line in render_adapter() for line in SITECUSTOMIZE.splitlines())
