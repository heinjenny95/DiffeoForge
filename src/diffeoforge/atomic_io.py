"""Small, auditable helpers for exclusive creation and atomic text replacement."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_REPLACE_ATTEMPTS = 4
_REPLACE_RETRY_SECONDS = 0.01


def replace_atomically(source: Path, destination: Path) -> None:
    """Publish one prepared path, tolerating bounded transient access denial.

    Windows indexers and security scanners can briefly hold a just-written file
    open even after DiffeoForge closed its own handle. Only ``PermissionError``
    is retried, the source bytes are never rewritten between attempts, and the
    final failure remains visible to the caller.
    """

    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_SECONDS * (2**attempt))


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
        replace_atomically(temporary, destination)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
