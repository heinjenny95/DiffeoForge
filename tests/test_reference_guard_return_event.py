"""Truthful return-bound events from generated code, without a native runtime.

The real CLI/capped-model integration is qualified separately. These controls
execute the actual generated entry wrapper with explicit dependency doubles.
"""

import ast
import copy
import functools
import hashlib
import json
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.reference_guard_assets import RUNTIME_SOURCE


class Violation(RuntimeError):
    pass


def harness(tmp_path, *, failure=None):
    trace = []
    controls = np.array([[0.123456789, 0.2, 0.3], [0.4, 0.5, 0.6]], dtype=np.float64)

    class Context:
        initial_momenta = None
        initial_controls = Path("test-controls.txt")
        root = tmp_path
        fingerprint = "fixed-test-inputs"
        policy = {"initializer": "native_zero"}
        manifest = {"effective_config": {"optimization": {"max_iterations": 2}}}
        records = {}

        def __init__(self):
            self.content_checks = 0

        def current(self):
            return self.fingerprint

        def verify_content(self):
            self.content_checks += 1
            trace.append(("content", self.content_checks))
            if failure == "content" and self.content_checks == 2:
                raise ValueError("changed test input")
            return self.fingerprint

    class Guard:
        def __init__(self):
            self.accepted = None

        def fail(self, reason, **details):
            raise Violation(reason)

        def export_allowed(self, values):
            trace.append(("getter-bound", None))
            if failure == "binding":
                raise Violation("unbound getter")
            np.testing.assert_array_equal(values, estimator.statistical_model.values.ravel())

        def _event(self, kind, **details):
            trace.append(("event", {"kind": kind, **details}))

    def attach(estimator, directory, *, provenance, context_provider):
        assert context_provider() == provenance["objective_fingerprint"]
        estimator._private_finite_guard = Guard()
        return estimator._private_finite_guard

    model = SimpleNamespace(
        values=np.zeros((1, 2, 3), dtype=np.float64),
        freeze_template=True,
        freeze_control_points=True,
        get_control_points=lambda: controls.copy(),
    )
    estimator = SimpleNamespace(
        method="L-BFGS-B",
        current_iteration=1,
        parameters_order=["momenta"],
        x0=np.zeros(6, dtype=np.float64),
        max_iterations=2,
        statistical_model=model,
        _get_parameters=lambda: {"momenta": model.values.copy()},
        _vectorize_parameters=lambda values: values["momenta"].ravel(),
    )
    sentinel = object()

    def original_update(self):
        trace.append(("native-update", None))
        if failure == "exception":
            raise RuntimeError("test native failure")
        if failure == "uncaught-stop":
            raise StopIteration
        model.values = np.full((1, 2, 3), 0.01, dtype=np.float64)
        self.current_iteration = 4 if failure == "iteration" else 3
        if failure == "cap":
            self.max_iterations = 3
        self._private_finite_guard.accepted = {
            "key": "accepted-key",
            "evaluation": 7,
            "native_iteration": 3,
        }
        return sentinel

    namespace = dict(
        context=Context(),
        guard_module=SimpleNamespace(NumericalGuardViolation=Violation, attach_instance=attach),
        original_update=original_update,
        original_write=lambda self: None,
        dispatched=[False],
        np=np,
        types=types,
        functools=functools,
        hashlib=hashlib,
        read_2D_array=lambda _: controls.copy(),
        _canonical=lambda value: json.dumps(value, sort_keys=True).encode(),
    )
    generated_globals = {}
    exec(compile(RUNTIME_SOURCE, "generated-regional-guard-runtime.py", "exec"), generated_globals)
    namespace.update(
        {name: generated_globals[name] for name in ("NATIVE_SCIPY_SHA", "DECLARATION")}
    )
    tree = ast.parse(RUNTIME_SOURCE.decode("utf-8"))
    node = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "guarded_update"
    )
    isolated = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(node)], type_ignores=[]))
    exec(compile(isolated, "generated-regional-guard-entry.py", "exec"), namespace)
    return namespace["guarded_update"], estimator, trace, sentinel


def test_normal_native_return_is_preserved_and_event_follows_verified_binding(tmp_path):
    update, estimator, trace, sentinel = harness(tmp_path)
    assert update(estimator) is sentinel
    events = [(i, value) for i, (kind, value) in enumerate(trace) if kind == "event"]
    assert len(events) == 1
    position, event = events[0]
    assert event == {
        "kind": "native_update_returned_bound_to_accepted",
        "parameter_sha256": "accepted-key",
        "evaluation_reference": 7,
        "native_iteration": 3,
        "configured_max_iterations": 2,
        "original_update_returned_normally": True,
    }
    getter = next(i for i, row in enumerate(trace) if row[0] == "getter-bound")
    assert getter < position
    assert any(kind == "content" for kind, _ in trace[getter + 1 : position])
    assert sum(kind == "native-update" for kind, _ in trace) == 1
    assert all("OptimizeResult" not in value.get("kind", "") for _, value in events)


@pytest.mark.parametrize(
    "failure", ["exception", "uncaught-stop", "binding", "content", "cap", "iteration"]
)
def test_failed_or_unbound_native_return_never_claims_a_normal_bound_event(tmp_path, failure):
    update, estimator, trace, _ = harness(tmp_path, failure=failure)
    with pytest.raises(Violation):
        update(estimator)
    assert not any(kind == "event" for kind, _ in trace)
    assert sum(kind == "native-update" for kind, _ in trace) == 1


def test_return_bound_event_does_not_allow_a_second_update(tmp_path):
    update, estimator, trace, _ = harness(tmp_path)
    update(estimator)
    with pytest.raises(Violation, match="relaunch_forbidden"):
        update(estimator)
    assert sum(kind == "event" for kind, _ in trace) == 1
    assert sum(kind == "native-update" for kind, _ in trace) == 1


def test_runtime_and_rendered_adapter_parse_as_python38(tmp_path):
    from test_reference_finite_accepted_guard import config_fixture, render

    from diffeoforge.reference_finite_accepted_guard import mark_new_configuration

    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    generated = render(config)
    for name in ("regional_guard_runtime.py", "sitecustomize.py", "finite_accepted_guard.py"):
        ast.parse(generated[name].decode("utf-8"), filename=name, feature_version=(3, 8))
