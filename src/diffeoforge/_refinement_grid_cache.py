"""Bounded, immutable original-grid reuse within one augmentation operation."""

from __future__ import annotations

import hashlib
import os
import stat
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.mesh import TriangleMesh

# Reject junctions/symlinks, offline files and recall-on-access cloud placeholders.
_UNSAFE_ATTRIBUTES = 0x00441400
_MAXIMUM_ENTRIES = 2
_MAXIMUM_BYTES = 256 * 1024**2


def _identity(value):
    # On Windows, stat/fstat report the actual volume/file index, not a path hash.
    if not value.st_ino:
        raise ValueError("Original grid has no verifiable file identity")
    # Windows path-stat and fstat expose different legacy ctime meanings. The
    # actual file ID, size, mtime and complete SHA are comparable on both paths.
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _path_identity(path):
    leaf = path.lstat()
    if (not stat.S_ISREG(leaf.st_mode)
            or getattr(leaf, "st_file_attributes", 0) & _UNSAFE_ATTRIBUTES):
        raise ValueError("Original grid must be an ordinary, locally available file")
    parents = []
    for parent in path.parents:
        value = parent.lstat()
        if (not stat.S_ISDIR(value.st_mode)
                or getattr(value, "st_file_attributes", 0) & _UNSAFE_ATTRIBUTES):
            raise ValueError("Original grid has an unsafe parent directory")
        if not value.st_ino:
            raise ValueError("Original grid parent has no verifiable file identity")
        # Directory timestamps may change when unrelated output children are written.
        parents.append((value.st_dev, value.st_ino))
    return _identity(leaf), tuple(parents)


@dataclass(frozen=True)
class _Seal:
    identity: tuple
    parents: tuple
    sha256: str


def _seal(path):
    before, parents = _path_identity(path)
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        if _identity(os.fstat(stream.fileno())) != before:
            raise ValueError("Original grid changed before opening")
        while block := stream.read(1024 * 1024):
            digest.update(block)
        if _identity(os.fstat(stream.fileno())) != before:
            raise ValueError("Original grid changed while hashing")
    if _path_identity(path) != (before, parents):
        raise ValueError("Original grid path changed while hashing")
    return _Seal(before, parents, digest.hexdigest())


def _immutable(values, dtype):
    array = np.asarray(values, dtype=dtype)
    # A bytes owner prevents consumers from re-enabling ndarray writes.
    return np.frombuffer(array.tobytes(order="C"), dtype=dtype).reshape(array.shape)


class _OriginalGridCache:
    """At most two parsed grids; every lookup still checks live identity and SHA."""

    def __init__(self, loader, *, maximum_bytes=_MAXIMUM_BYTES):
        if maximum_bytes < 0:
            raise ValueError("Original-grid cache byte limit cannot be negative")
        self._loader = loader
        self._maximum_bytes = maximum_bytes
        self._entries = OrderedDict()
        self._bindings = {}
        self.retained_bytes = 0
        self.active = False
        self._used = False

    def __enter__(self):
        if self._used:
            raise RuntimeError("Original-grid cache belongs to one operation")
        self._used = self.active = True
        return self

    def __exit__(self, *args):
        try:
            if args[0] is None:
                for path, expected in self._bindings.items():
                    if _seal(Path(path)) != expected:
                        raise ValueError("Original grid changed before augmentation completed")
        finally:
            self._entries.clear()
            self._bindings.clear()
            self.retained_bytes = 0
            self.active = False

    def get(self, path):
        if not self.active:
            raise RuntimeError("Original-grid cache is outside its operation")
        # Keep the original path spelling until after ancestor checks: resolve()
        # would conceal a junction or symlink in the caller's source path.
        path = Path(os.path.abspath(Path(path).expanduser()))
        key = os.path.normcase(str(path))
        seal = _seal(path)
        previous = self._bindings.setdefault(key, seal)
        if previous != seal:
            raise ValueError("Original grid changed or was replaced during augmentation")
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key][0]

        loaded = self._loader(path)
        if loaded.metadata.sha256 != seal.sha256 or _seal(path) != seal:
            raise ValueError("Original grid changed during parsing")
        geometry = TriangleMesh(
            vertices=_immutable(loaded.geometry.vertices, np.float64),
            triangles=_immutable(loaded.geometry.triangles, np.int64),
        )
        size = geometry.vertices.nbytes + geometry.triangles.nbytes
        if size > self._maximum_bytes:
            return geometry  # Oversized grids remain verified but are not retained.
        while self._entries and (len(self._entries) >= _MAXIMUM_ENTRIES
                                 or self.retained_bytes + size > self._maximum_bytes):
            _, (_, removed_bytes) = self._entries.popitem(last=False)
            self.retained_bytes -= removed_bytes
        self._entries[key] = geometry, size
        self.retained_bytes += size
        return geometry
