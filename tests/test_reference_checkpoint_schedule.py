"""Output suppression must preserve native checkpoint/final-export behavior."""

import pickle
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from diffeoforge.reference_checkpoint_schedule import SITECUSTOMIZE, new_run_config, render_adapter


def _adapter(monkeypatch, tmp_path):
    class Exponential:
        def write_flow(self):
            self.flows += 1

    class Gradient:
        def __init__(self):
            self.state_file = str(tmp_path / "state.p")
            self.current_parameters = {"field": [1, 2, 3]}
            self.current_iteration = 0
            self.dataset = SimpleNamespace(subject_ids=["a", "b"])
            self.statistical_model = SimpleNamespace(exponential=Exponential())
            self.statistical_model.exponential.flows = 0
            self.failed_dump = False

        def _dump_state_file(self):
            with open(self.state_file, "wb") as f:
                if self.failed_dump:
                    f.write(b"partial")
                    raise OSError("simulated disk failure")
                pickle.dump((self.current_iteration, self.current_parameters), f)

        def update(self):
            for iteration in range(1, 4):
                self.current_iteration = iteration
                self.write()

        def write(self):
            for _ in self.dataset.subject_ids:
                self.statistical_model.exponential.write_flow()
            self._dump_state_file()

    class Scipy(Gradient):
        update = Gradient.update

        def _get_parameters(self):
            return self.current_parameters

        def _vectorize_parameters(self, params):
            return params["field"]

        def _dump_state_file(self, parameters):
            with open(self.state_file, "wb") as f:
                pickle.dump((self.current_iteration, parameters), f)

        def write(self):
            for _ in self.dataset.subject_ids:
                self.statistical_model.exponential.write_flow()
            self._dump_state_file(self._vectorize_parameters(self._get_parameters()))

    for name, cls, attribute in (
        ("deformetrica.core.estimators.gradient_ascent", Gradient, "GradientAscent"),
        ("deformetrica.core.estimators.scipy_optimize", Scipy, "ScipyOptimize"),
        ("deformetrica.core.model_tools.deformations.exponential", Exponential, "Exponential"),
    ):
        module = ModuleType(name)
        setattr(module, attribute, cls)
        monkeypatch.setitem(sys.modules, name, module)
    exec(SITECUSTOMIZE, {})
    return Gradient, Scipy


def test_periodic_saves_have_no_flows_and_final_write_exports_every_subject(
    monkeypatch, tmp_path
):
    estimator = _adapter(monkeypatch, tmp_path)[0]()
    estimator.update()
    assert estimator.statistical_model.exponential.flows == 0
    saved = pickle.loads(Path(estimator.state_file).read_bytes())
    assert saved[0] == 3
    assert saved[1] == {"field": [1, 2, 3]}
    estimator.write()
    assert estimator.statistical_model.exponential.flows == 2
    assert not list(tmp_path.glob(".df-checkpoint-*"))


def test_interrupted_checkpoint_replacement_retains_previous_complete_state(monkeypatch, tmp_path):
    estimator = _adapter(monkeypatch, tmp_path)[0]()
    estimator._dump_state_file()
    previous = Path(estimator.state_file).read_bytes()
    estimator.failed_dump = True
    with pytest.raises(OSError, match="disk failure"):
        estimator._dump_state_file()
    assert Path(estimator.state_file).read_bytes() == previous
    assert not list(tmp_path.glob(".df-checkpoint-*"))


def test_new_run_policy_keeps_source_and_explicit_legacy_policy():
    source = {"output": {"retain_flow_meshes": True}}
    assert new_run_config(source)["output"]["checkpoint_mode"] == "compact_final_export"
    assert "checkpoint_mode" not in source["output"]
    source["output"]["checkpoint_mode"] = "native_full_outputs"
    assert new_run_config(source) == source
    compile(render_adapter(), "sitecustomize.py", "exec")


def test_failed_final_export_still_has_latest_readable_checkpoint(monkeypatch, tmp_path):
    estimator = _adapter(monkeypatch, tmp_path)[0]()
    estimator.update()

    def fail():
        raise OSError("final export failure")

    monkeypatch.setattr(estimator.statistical_model.exponential, "write_flow", fail)
    with pytest.raises(OSError, match="final export failure"):
        estimator.write()
    assert pickle.loads(Path(estimator.state_file).read_bytes())[0] == 3
