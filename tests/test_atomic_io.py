from __future__ import annotations

import os
from pathlib import Path

import pytest

from diffeoforge import atomic_io


def test_atomic_replace_retries_transient_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "prepared.tmp"
    destination = tmp_path / "state.json"
    source.write_bytes(b"new state\n")
    destination.write_bytes(b"old state\n")
    actual_replace = os.replace
    attempts = 0

    def transient_replace(current_source, current_destination) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated transient scanner handle")
        actual_replace(current_source, current_destination)

    monkeypatch.setattr(atomic_io.os, "replace", transient_replace)

    atomic_io.replace_atomically(source, destination)

    assert attempts == 2
    assert destination.read_bytes() == b"new state\n"
    assert not source.exists()


def test_atomic_replace_surfaces_persistent_permission_error_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "prepared.tmp"
    destination = tmp_path / "state.json"
    source.write_bytes(b"new state\n")
    destination.write_bytes(b"old state\n")
    attempts = 0

    def denied_replace(*_args) -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("simulated persistent denial")

    monkeypatch.setattr(atomic_io.os, "replace", denied_replace)

    with pytest.raises(PermissionError, match="persistent denial"):
        atomic_io.replace_atomically(source, destination)

    assert attempts == atomic_io._REPLACE_ATTEMPTS
    assert destination.read_bytes() == b"old state\n"
    assert source.read_bytes() == b"new state\n"
