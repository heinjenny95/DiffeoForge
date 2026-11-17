"""Evidence that native preview callbacks only observe a bound accepted state."""

import ast
import hashlib
import json
import os
from pathlib import Path
from threading import Event, Thread
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from diffeoforge.pilot_preview_assets import SOURCE


@pytest.fixture
def runtime(tmp_path):
    module = ModuleType("preview_runtime_test")
    ast.parse(SOURCE.decode(), feature_version=(3, 8))
    exec(compile(SOURCE, "pilot_preview_runtime.py", "exec"), module.__dict__)
    engine = tmp_path / "engine"
    engine.mkdir()
    model = b"""<model><template>
        <object id="fixed"><deformable-object-type>Landmark</deformable-object-type></object>
        <object id="surface"><deformable-object-type>SurfaceMesh</deformable-object-type></object>
        </template></model>"""
    (engine / "model.xml").write_bytes(model)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "effective_config": {"model": {"object_id": "surface"}},
        "protected_artifacts": [{
            "path": "engine/model.xml", "sha256": hashlib.sha256(model).hexdigest(),
        }],
    }))
    publisher = module.Publisher(engine)
    return module, publisher


def _request(publisher, **overrides):
    publisher.directory.mkdir(exist_ok=True)
    request = dict(
        version="pilot-live-preview-v1",
        id="a" * 32,
        manifest_sha256=publisher.manifest,
        object_id="surface",
        vertex_count=6,
        indices=[4, 2, 0],
    )
    request.update(overrides)
    publisher.request_path.write_text(json.dumps(request))
    return request


class _Tensor:
    """Capture devices copied to the reader without requiring the native runtime."""

    def __init__(self, array, copies):
        self.array = array
        self.shape = array.shape
        self.ndim = array.ndim
        self.copies = copies

    def detach(self):
        return self

    def __getitem__(self, indices):
        return _Tensor(self.array[indices], self.copies)

    def cpu(self):
        self.copies.append(self.shape[0])
        return self

    def numpy(self):
        return self.array


def _estimator(vertices, controls):
    def obj(kind, count):
        return SimpleNamespace(type=kind, get_number_of_points=lambda: count)

    return SimpleNamespace(
        dataset=SimpleNamespace(subject_ids=["registered-subject"]),
        statistical_model=SimpleNamespace(
            name="DeterministicAtlas",
            number_of_processes=1,
            freeze_template=True,
            freeze_control_points=True,
            template=SimpleNamespace(object_list=[obj("landmark", 2), obj("surfacemesh", 6)]),
            exponential=SimpleNamespace(
                flow_is_modified=False,
                shoot_is_modified=False,
                get_template_points=lambda: {"landmark_points": vertices},
                control_points_t=[controls],
            ),
        ),
    )


def test_native_frame_samples_object_offset_and_caps_controls(runtime, monkeypatch):
    module, publisher = runtime
    request = _request(publisher)
    vertices = np.arange(24).reshape(8, 3).astype(np.float32)
    controls = np.arange(600).reshape(200, 3).astype(np.float64)
    copies, threads = [], []
    estimator = _estimator(_Tensor(vertices, copies), _Tensor(controls, copies))

    class Thread:
        def __init__(self, *, target, args, daemon, name):
            assert daemon
            self.target, self.args = target, args
            threads.append(self)

        def start(self):
            assert not copies

    monkeypatch.setattr(module, "threading", SimpleNamespace(Thread=Thread))
    publisher.offer(estimator, 15)
    publisher.offer(estimator, 16)
    assert len(threads) == 1 and publisher.busy
    assert not copies
    threads[0].target(*threads[0].args)
    with np.load(publisher.directory / "frame.npz", allow_pickle=False) as frame:
        assert set(frame.files) == {"id", "iteration", "points", "controls"}
        assert str(frame["id"]) == request["id"]
        assert int(frame["iteration"]) == 15
        np.testing.assert_array_equal(frame["points"], vertices[[6, 4, 2]])
        assert frame["controls"].shape == (128, 3)
        np.testing.assert_array_equal(frame["controls"][[0, -1]], controls[[0, -1]])
    assert copies == [3, 128]
    assert not publisher.busy


def test_accepted_callback_does_not_wait_for_request_validation(runtime, monkeypatch):
    module, publisher = runtime
    _request(publisher)
    copied = []
    vertices = _Tensor(np.arange(24).reshape(8, 3).astype(np.float32), copied)
    estimator = _estimator(vertices, vertices)
    entered, release, returned = Event(), Event(), Event()
    native_read = publisher._request
    writers = []

    class Writer(Thread):
        def start(self):
            writers.append(self)
            super().start()

    def wait_and_read(expected=None):
        entered.set()
        release.wait()
        return native_read(expected)

    def accept():
        publisher.offer(estimator, 15)
        returned.set()

    monkeypatch.setattr(module, "threading", SimpleNamespace(Thread=Writer))
    monkeypatch.setattr(publisher, "_request", wait_and_read)
    callback = Thread(target=accept, daemon=True)
    callback.start()
    try:
        assert entered.wait(5)
        assert returned.wait(5)
        assert not copied
        assert not (publisher.directory / "frame.npz").exists()
    finally:
        release.set()
        callback.join(5)
        for writer in writers:
            writer.join(5)
    assert (publisher.directory / "frame.npz").is_file()


@pytest.mark.parametrize("reason", ["stopped", "expired", "duplicate", "wrong_manifest"])
def test_native_request_requires_current_workspace_bound_rows(runtime, reason):
    _, publisher = runtime
    request = _request(publisher)
    if reason == "stopped":
        (publisher.directory / f"stop-{request['id']}").touch()
    elif reason == "expired":
        os.utime(publisher.request_path, (1, 1))
    elif reason == "duplicate":
        _request(publisher, indices=[0, 2, 2])
    else:
        _request(publisher, manifest_sha256="b" * 64)
    assert publisher._request() is None


def test_guarded_observer_watches_only_latest_successful_accept(runtime, monkeypatch):
    module, publisher = runtime
    accepted, offers = [], []
    guard = SimpleNamespace(
        evaluations=3,
        commit=lambda state, iteration, initial=False: accepted.append((iteration, initial)),
    )
    guard_module = SimpleNamespace(attach_instance=lambda estimator: guard)
    estimator = SimpleNamespace(parameters_order=["momenta"])
    monkeypatch.setattr(publisher, "offer", lambda _estimator, iteration: offers.append(iteration))
    module._attach_guarded(publisher, guard_module)
    assert guard_module.attach_instance(estimator) is guard
    guard.commit({"evaluation": 3}, 1, initial=True)
    guard.commit({"evaluation": 2}, 10)
    guard.commit({"evaluation": 3}, 11)
    estimator.parameters_order = ["control_points", "momenta"]
    guard.commit({"evaluation": 3}, 12)
    assert accepted == [(1, True), (10, False), (11, False), (12, False)]
    assert offers == [11]


def test_gradient_ascent_preview_keeps_progress_and_skips_invalid_state(runtime, monkeypatch):
    module, publisher = runtime
    offers = []

    class SyntheticGradientAscent:
        current_parameters = {"momenta": object()}
        current_log_likelihood = -1.5
        current_iteration = 8

        def print(self):
            return "native output"

    mock_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    monkeypatch.setattr(module, "_GA_SHA256", mock_digest)
    monkeypatch.setattr(publisher, "offer", lambda _estimator, iteration: offers.append(iteration))
    module._attach_gradient_ascent(publisher, SyntheticGradientAscent)
    instance = SyntheticGradientAscent()
    assert instance.print() == "native output"
    instance.current_iteration = 0
    assert instance.print() == "native output"
    instance.current_iteration = 8
    instance.current_log_likelihood = float("nan")
    assert instance.print() == "native output"
    instance.current_log_likelihood = -1.0
    instance.current_parameters = {"template": object(), "momenta": object()}
    assert instance.print() == "native output"
    assert offers == [8]
