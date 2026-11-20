"""The action deadline reaches fixed-field preparation without native dispatch."""

import pytest

from diffeoforge import regional_evaluation as evaluation
from diffeoforge.mesh_filter_worker import current_cancellation, mesh_filter_cancellation


@pytest.mark.parametrize("mode", ["surface", "points"])
def test_nested_preparation_stops_before_reading_a_field(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(evaluation, "field_inputs", lambda *_: pytest.fail("Read after stop"))
    with mesh_filter_cancellation(lambda: True), pytest.raises(InterruptedError):
        if mode == "surface":
            evaluation.evaluate(tmp_path / "source", tmp_path / "unused")
        else:
            evaluation.evaluate_points(tmp_path / "source", [[0, 0, 0]],
                                       tmp_path / "unused", count=37)
    assert not (tmp_path / "unused").exists()


def test_operation_callback_is_live_and_context_restores_afterwards():
    state = dict(stop=False)
    assert current_cancellation() is None
    with mesh_filter_cancellation(lambda: state["stop"]):
        callback = evaluation._cancellation(None)
        assert not callback()
        state["stop"] = True
        assert callback()
    assert current_cancellation() is None


def test_explicit_callback_keeps_its_existing_scope():
    with mesh_filter_cancellation(lambda: True):
        assert not evaluation._cancellation(lambda: False)()
    with pytest.raises(TypeError):
        evaluation._cancellation("not callable")
