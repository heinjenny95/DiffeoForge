"""Small fail-closed helper for exact, non-overwriting evidence files."""

from __future__ import annotations

import os
from pathlib import Path

from diffeoforge.config import ConfigurationError


def write_new_exact_file(
    payload: bytes,
    output_path: Path | str,
    *,
    artifact_label: str,
) -> Path:
    """Write bytes once in an existing real directory and verify the open file."""

    if not isinstance(payload, bytes):
        raise TypeError("Exact file payload must be bytes")
    destination = Path(output_path).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ConfigurationError(
            f"{artifact_label} already exists and will not be overwritten: {destination}"
        )
    parent = destination.parent
    if not parent.exists() or parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError(
            f"{artifact_label} parent must be an existing real directory: {parent}"
        )

    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError as error:
        raise ConfigurationError(
            f"{artifact_label} already exists and will not be overwritten: {destination}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Could not create {artifact_label.lower()} {destination}: {error}"
        ) from error

    try:
        with os.fdopen(descriptor, "w+b") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            observed = handle.read()
    except OSError as error:
        raise ConfigurationError(
            f"Could not complete {artifact_label.lower()} {destination}: {error}"
        ) from error
    if observed != payload:
        raise ConfigurationError(
            f"{artifact_label} did not preserve exact bytes: {destination}"
        )
    return destination
