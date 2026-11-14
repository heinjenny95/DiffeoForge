"""Restricted native checkpoint evidence; no untrusted code or native restore."""

import builtins
import hashlib
import pickle

import numpy as np
import pytest

from diffeoforge.reference_guarded_checkpoint import read_guarded_checkpoint


def payload():
    return dict(
        parameters=np.array([-0.0, 0.1234567890123456, 0.25, -0.5, 0.75, 1.0], dtype=np.float64),
        current_iteration=4,
        parameters_shape=dict(momenta=(1, 2, 3)),
        parameters_order=["momenta"],
    )


def read(tmp_path, data, *, iteration=4, values=6):
    path = tmp_path / "state.p"
    path.write_bytes(pickle.dumps(data, protocol=4))
    return read_guarded_checkpoint(
        path,
        values=values,
        iteration=iteration,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_pinned_checkpoint_preserves_bits_and_is_immutable(tmp_path):
    source = payload()
    loaded = read(tmp_path, source)
    assert loaded.current_iteration == 4
    assert np.array_equal(loaded.parameters.view(np.uint64), source["parameters"].view(np.uint64))
    with pytest.raises(ValueError):
        loaded.parameters.flags.writeable = True


def test_wrong_schema_iteration_order_nonfinite_dtype_and_checksum_fail(tmp_path):
    variants = [
        dict(current_iteration=True),
        dict(current_iteration=5),
        dict(parameters_shape=dict(momenta=(1, 3, 2))),
        dict(parameters_order=["template"]),
        dict(extra="not native"),
        dict(parameters=np.ones(6, dtype=np.float32)),
        dict(parameters=np.full(6, np.nan)),
    ]
    for variant in variants:
        with pytest.raises((ValueError, TypeError)):
            read(tmp_path, payload() | variant)
    path = tmp_path / "state.p"
    with pytest.raises(ValueError, match="checksum"):
        read_guarded_checkpoint(path, values=6, iteration=4, expected_sha256="0" * 64)


def test_oversized_array_shape_rejected_before_any_numpy_allocation(tmp_path, monkeypatch):
    reconstruct = np.ndarray([0]).__reduce__()[0]

    class LargeShape:
        def __reduce__(self):
            return (
                reconstruct,
                (np.ndarray, (0,), b"b"),
                (1, (10**12,), np.dtype("float64"), False, b""),
            )

    monkeypatch.setattr(
        np, "frombuffer", lambda *_a, **_k: pytest.fail("Allocated malformed checkpoint")
    )
    with pytest.raises(ValueError, match="before allocation"):
        read(tmp_path, payload() | dict(parameters=LargeShape()))


def test_arbitrary_global_and_extension_opcodes_are_rejected(tmp_path):
    class Callable:
        def __reduce__(self):
            return builtins.eval, ("1+1",)

    with pytest.raises(ValueError, match="global is not permitted"):
        read(tmp_path, Callable())
    path = tmp_path / "ext.p"
    path.write_bytes(b"\x80\x04\x82\x01.")
    with pytest.raises(ValueError, match="opcode"):
        read_guarded_checkpoint(
            path,
            values=6,
            iteration=4,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
