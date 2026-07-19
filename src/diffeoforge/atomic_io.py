"""Small, auditable helpers for exclusive creation and atomic text replacement."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_safely(
    destination: Path,
    content: str,
    *,
    overwrite: bool,
    encoding: str = "utf-8",
) -> None:
    """Create a text file exclusively or replace it atomically.

    Replacement content is completely rendered and flushed to a sibling temporary file
    before ``os.replace`` publishes it. A failed write therefore leaves an existing
    destination untouched. Ownership checks remain the caller's responsibility.
    """

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        with destination.open("x", encoding=encoding, newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
