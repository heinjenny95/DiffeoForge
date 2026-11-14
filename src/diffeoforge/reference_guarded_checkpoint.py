"""Bound, non-executable reader for the pinned native momenta-only checkpoint.

This reads parameter evidence; it never restores a native optimizer. NumPy dtype
and array BUILD states are validated by inert proxies BEFORE array allocation.
"""

import hashlib
import io
import os
import pickle
import pickletools
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAX_VALUES = 3_000_000
_ARRAY_TYPE = object()


class _Dtype:
    def __init__(self, *args):
        if args != ("f8", False, True):
            raise ValueError("Checkpoint dtype construction is not pinned Float64")
        self.ready = False

    def __setstate__(self, state):
        if self.ready or state != (3, "<", None, None, None, -1, -1, 0):
            raise ValueError("Checkpoint dtype state differs from little-endian Float64")
        self.ready = True


class _Array:
    def __init__(self, values):
        self.values = values
        self.array = None

    def __setstate__(self, state):
        if (
            self.array is not None
            or type(state) is not tuple
            or len(state) != 5
            or state[0] != 1
            or state[1] != (self.values,)
            or not isinstance(state[2], _Dtype)
            or not state[2].ready
            or state[3] is not False
            or type(state[4]) is not bytes
            or len(state[4]) != self.values * 8
        ):
            raise ValueError("Checkpoint array shape/dtype/order/bytes differ before allocation")
        self.array = np.frombuffer(state[4], dtype=np.dtype("<f8"))
        if not np.isfinite(self.array).all():
            raise ValueError("Checkpoint parameter array is not finite")


class _Reader(pickle.Unpickler):
    def __init__(self, stream, values):
        super().__init__(stream)
        self.values = values
        self.arrays = 0

    def _reconstruct(self, subtype, shape, dtype):
        if subtype is not _ARRAY_TYPE or shape != (0,) or dtype != b"b" or self.arrays:
            raise ValueError("Checkpoint array reconstruction differs from one flat native vector")
        self.arrays += 1
        return _Array(self.values)

    def find_class(self, module, name):
        if module in {"numpy.core.multiarray", "numpy._core.multiarray"} and name == "_reconstruct":
            return self._reconstruct
        if module == "numpy" and name == "ndarray":
            return _ARRAY_TYPE  # Inert token; cannot be called to allocate a malicious shape.
        if module == "numpy" and name == "dtype":
            return _Dtype
        raise ValueError("Checkpoint global is not permitted: " + module + "." + name)

    def persistent_load(self, _pid):
        raise ValueError("Checkpoint persistent references are not permitted")


@dataclass(frozen=True)
class GuardedCheckpoint:
    parameters: np.ndarray
    current_iteration: int


def read_guarded_checkpoint(path, *, values, iteration, expected_sha256):
    """Read only the exact bounded protocol-4 native single-momenta schema."""
    if (
        type(values) is not int
        or not 0 < values <= MAX_VALUES
        or values % 3
        or type(iteration) is not int
        or iteration < 0
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
    ):
        raise ValueError("Invalid expected native checkpoint scope")
    path = Path(path)
    limit = values * 8 + 1_048_576

    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if before.st_size > limit:
            raise ValueError("Checkpoint exceeds bounded parameter evidence size")
        raw = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if (
        len(raw) > limit
        or identity(before) != identity(after)
        or identity(after) != identity(path.stat())
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("Checkpoint file identity or checksum changed")
    count = 0
    for op, arg, _ in pickletools.genops(raw):
        count += 1
        if (
            count > 256
            or (count == 1 and (op.name != "PROTO" or arg != 4))
            or op.name
            in {"EXT1", "EXT2", "EXT4", "PERSID", "BINPERSID", "INST", "OBJ", "NEWOBJ", "NEWOBJ_EX"}
        ):
            raise ValueError("Checkpoint pickle protocol/opcode is outside pinned native scope")
    if not count:
        raise ValueError("Empty native checkpoint")
    stream = io.BytesIO(raw)
    data = _Reader(stream, values).load()
    if (
        stream.tell() != len(raw)
        or type(data) is not dict
        or set(data) != {"parameters", "current_iteration", "parameters_shape", "parameters_order"}
        or type(data["current_iteration"]) is not int
        or data["current_iteration"] != iteration
        or data["parameters_shape"] != {"momenta": (1, values // 3, 3)}
        or data["parameters_order"] != ["momenta"]
        or not isinstance(data["parameters"], _Array)
        or data["parameters"].array is None
    ):
        raise ValueError("Checkpoint schema/iteration/single-momenta basis differs")
    return GuardedCheckpoint(data["parameters"].array, iteration)
