"""A capped resume retains the native tolerance denominator and local line search."""

import hashlib
import inspect
import math
import pickle
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from diffeoforge.reference_checkpoint_schedule import SITECUSTOMIZE, render_adapter
from diffeoforge.reference_convergence_context import (
    ADAPTER_SOURCE,
    CHECKPOINT_KEY,
    validate_context,
)


class Base:
    def update(self):
        self.base_called = True


class Gradient(Base):
    def update(self):
        super().update()
        self.current_log_likelihood = self.values[self.current_iteration]
        initial_log_likelihood = self.current_log_likelihood
        last_log_likelihood = initial_log_likelihood
        while self.current_iteration < self.max_iterations:
            self.current_iteration += 1
            current_log_likelihood = self.values[self.current_iteration]
            q = current_log_likelihood - last_log_likelihood
            if q <= 0:
                self.stop = "line_search_exhausted"
                break
            self.current_parameters = current_log_likelihood
            delta_f_current = last_log_likelihood - current_log_likelihood
            delta_f_initial = initial_log_likelihood - current_log_likelihood
            if math.fabs(delta_f_current) < self.convergence_tolerance * math.fabs(delta_f_initial):
                self.stop = "tolerance_threshold"
                break
            last_log_likelihood = current_log_likelihood
        self._dump_state_file()

    def _dump_state_file(self):
        with open(self.state_file, "wb") as stream:
            pickle.dump({"current_iteration": self.current_iteration,
                         "current_parameters": self.current_parameters}, stream)

    def write(self):
        self._dump_state_file()


def context():
    return dict(version=1, initial_log_likelihood=-100.0, origin_iteration=0,
                origin_checkpoint_sha256="a" * 64, convergence_tolerance=1e-6)


def namespace(monkeypatch):
    module = ModuleType("deformetrica.core.estimators.gradient_ascent")
    module.GradientAscent = Gradient
    monkeypatch.setitem(sys.modules, module.__name__, module)
    result = {}
    exec(ADAPTER_SOURCE, result)
    return result


def estimator(tmp_path, values, start=0, maximum=None):
    obj = Gradient()
    obj.state_file = str(tmp_path / "state.p")
    obj.values = values
    obj.current_iteration = start
    obj.current_parameters = values[start]
    obj.max_iterations = len(values) - 1 if maximum is None else maximum
    obj.convergence_tolerance = 1e-6
    obj._dump_state_file()
    return obj


def install(ns, monkeypatch, *, require_saved=False):
    original = Gradient.update
    digest = hashlib.sha256(textwrap.dedent(inspect.getsource(original)).encode()).hexdigest()
    # Keep pytest's restoration record for both native methods.
    monkeypatch.setattr(Gradient, "update", original)
    monkeypatch.setattr(Gradient, "_dump_state_file", Gradient._dump_state_file)
    ns["_df_install_reference"](context(), digest, require_saved)


def test_preserved_reference_matches_uninterrupted_stop_and_keeps_super(monkeypatch, tmp_path):
    values = [-100.0, -90.0, -80.0, -79.99999]
    uninterrupted = estimator(tmp_path, values)
    uninterrupted.update()
    assert uninterrupted.stop == "tolerance_threshold"
    reset = estimator(tmp_path, values, start=2)
    reset.update()
    assert not hasattr(reset, "stop")  # Reset denominator misses the same native threshold.
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, values, start=2)
    install(ns, monkeypatch)
    resumed.update()
    assert resumed.base_called
    assert resumed.stop == uninterrupted.stop
    saved = pickle.loads(Path(resumed.state_file).read_bytes())
    assert saved[CHECKPOINT_KEY] == context()
    assert saved["current_iteration"] == 3
    assert saved["current_parameters"] == values[3]


def test_first_resumed_line_search_rejects_worsening_step(monkeypatch, tmp_path):
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, [-100.0, -80.0, -81.0], start=1)
    install(ns, monkeypatch)
    resumed.update()
    assert resumed.stop == "line_search_exhausted"
    assert resumed.current_parameters == -80.0


@pytest.mark.parametrize("change", [
    {"initial_log_likelihood": float("nan")}, {"convergence_tolerance": 1e-5},
    {"origin_iteration": 99}, {"version": True}, {"origin_checkpoint_sha256": "wrong"},
])
def test_invalid_checkpoint_context_fails_closed(monkeypatch, tmp_path, change):
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, [-100.0, -90.0])
    saved = pickle.loads(Path(resumed.state_file).read_bytes())
    saved[CHECKPOINT_KEY] = {**context(), **change}
    Path(resumed.state_file).write_bytes(pickle.dumps(saved))
    install(ns, monkeypatch)
    with pytest.raises(RuntimeError):
        resumed.update()
    assert resumed.current_iteration == 0


def test_missing_required_context_and_conflicting_baseline_rejected(monkeypatch, tmp_path):
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, [-100.0, -90.0])
    install(ns, monkeypatch, require_saved=True)
    with pytest.raises(RuntimeError, match="lost its convergence reference"):
        resumed.update()
    saved = pickle.loads(Path(resumed.state_file).read_bytes())
    saved[CHECKPOINT_KEY] = {**context(), "initial_log_likelihood": -101.0}
    Path(resumed.state_file).write_bytes(pickle.dumps(saved))
    with pytest.raises(RuntimeError, match="disagree"):
        resumed.update()


def test_unsupported_native_source_rejected_without_patching(monkeypatch):
    ns = namespace(monkeypatch)
    original = Gradient.update
    with pytest.raises(RuntimeError, match="Unsupported native"):
        ns["_df_install_reference"](context(), "b" * 64, False)
    assert Gradient.update is original


def test_following_resume_accepts_matching_checkpoint_context(monkeypatch, tmp_path):
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, [-100.0, -90.0, -80.0, -79.99999], start=2)
    saved = pickle.loads(Path(resumed.state_file).read_bytes())
    saved[CHECKPOINT_KEY] = context()
    Path(resumed.state_file).write_bytes(pickle.dumps(saved))
    install(ns, monkeypatch, require_saved=True)
    resumed.update()
    assert resumed.stop == "tolerance_threshold"
    assert pickle.loads(Path(resumed.state_file).read_bytes())[CHECKPOINT_KEY] == context()


def test_atomic_context_bundle_failure_preserves_previous_checkpoint(monkeypatch, tmp_path):
    ns = namespace(monkeypatch)
    resumed = estimator(tmp_path, [-100.0, -90.0])
    install(ns, monkeypatch)
    exp_module = ModuleType("deformetrica.core.model_tools.deformations.exponential")
    exp_module.Exponential = type("Exponential", (), {"write_flow": lambda self: None})
    monkeypatch.setitem(sys.modules, exp_module.__name__, exp_module)
    exec(SITECUSTOMIZE, {})
    resumed.update()
    previous = Path(resumed.state_file).read_bytes()
    resumed._df_convergence_reference = {**context(), "version": 9}
    with pytest.raises(RuntimeError):
        resumed._dump_state_file()
    assert Path(resumed.state_file).read_bytes() == previous
    assert not list(tmp_path.glob(".df-checkpoint-*"))


@pytest.mark.parametrize("change", [
    {"initial_log_likelihood": float("inf")}, {"origin_iteration": True},
    {"convergence_tolerance": 0}, {"extra": 1},
])
def test_public_context_validation_rejects_invalid_values(change):
    with pytest.raises(ValueError):
        validate_context({**context(), **change}, 1e-6)


def test_reference_adapter_requires_convergence_output_mode():
    with pytest.raises(ValueError, match="convergence-only"):
        render_adapter(convergence_reference=context())
