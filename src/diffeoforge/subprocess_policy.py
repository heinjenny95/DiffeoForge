"""Cross-platform subprocess options for desktop-safe child processes."""

from __future__ import annotations

import os
import subprocess
from typing import Any

_CREATE_NO_WINDOW = 0x08000000


def hidden_windows_process_kwargs(*, creationflags: int = 0) -> dict[str, Any]:
    """Return subprocess kwargs that cannot create a visible Windows console.

    The options are deliberately harmless on non-Windows hosts. On Windows,
    ``CREATE_NO_WINDOW`` prevents console allocation while ``SW_HIDE`` also
    covers launchers such as ``wsl.exe`` on builds that honor ``STARTUPINFO``.
    """

    if os.name != "nt":
        return {}

    options: dict[str, Any] = {
        "creationflags": creationflags
        | int(getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW))
    }
    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 1))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        options["startupinfo"] = startupinfo
    return options
