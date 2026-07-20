"""Discovery and verification for the Windows Deformetrica reference runtime.

The desktop application treats the runtime as an implementation detail.  Public
installers target a uniquely named, DiffeoForge-managed WSL distribution.  During
same-owner alpha development an already installed Deformetrica 4.3 environment may
be reused without modifying it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

EXPECTED_DEFORMETRICA_VERSION = "4.3.0"
MANAGED_WSL_DISTRIBUTION = "DiffeoForge-Reference-4.3"
MANAGED_WSL_EXECUTABLE = "/opt/diffeoforge/reference/bin/deformetrica"
_VERSION_PATTERN = re.compile(r"(?<![0-9])4\.3\.0(?![0-9])")


@dataclass(frozen=True)
class ReferenceRuntimeProbe:
    """Read-only observation of one configured reference launcher."""

    launcher: Mapping[str, str]
    ready: bool
    version: str | None
    summary: str
    guidance: str | None = None
    managed: bool = False


def managed_wsl_launcher() -> dict[str, str]:
    """Return the stable launcher identity owned by the Windows installer."""

    return {
        "type": "wsl",
        "distribution": MANAGED_WSL_DISTRIBUTION,
        "executable": MANAGED_WSL_EXECUTABLE,
    }


def _decode_windows_output(payload: bytes) -> str:
    if not payload:
        return ""
    # `wsl --list --quiet` is UTF-16 on several supported Windows builds.
    if b"\x00" in payload[:256]:
        return payload.decode("utf-16-le", errors="replace").lstrip("\ufeff")
    return payload.decode("utf-8", errors="replace").lstrip("\ufeff")


def _run_wsl(arguments: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["wsl.exe", *arguments],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def installed_wsl_distributions() -> tuple[str, ...]:
    """List WSL distributions without starting or changing any distribution."""

    if os.name != "nt" or shutil.which("wsl.exe") is None:
        return ()
    try:
        completed = _run_wsl(["--list", "--quiet"])
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    names = (
        line.strip().strip("\x00")
        for line in _decode_windows_output(completed.stdout).splitlines()
    )
    return tuple(dict.fromkeys(name for name in names if name))


def probe_wsl_launcher(
    launcher: Mapping[str, str],
    *,
    expected_version: str = EXPECTED_DEFORMETRICA_VERSION,
) -> ReferenceRuntimeProbe:
    """Verify distribution, executable, and exact version without mutation."""

    normalized = {str(key): str(value) for key, value in launcher.items()}
    if normalized.get("type") != "wsl":
        raise ValueError("probe_wsl_launcher requires a WSL launcher")
    distribution = normalized.get("distribution", "")
    executable = normalized.get("executable", "")
    managed = (
        distribution == MANAGED_WSL_DISTRIBUTION
        and executable == MANAGED_WSL_EXECUTABLE
    )
    if os.name != "nt":
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            "WSL launchers are available only on Windows.",
            "Run the native Deformetrica launcher on this operating system.",
            managed,
        )
    if shutil.which("wsl.exe") is None:
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            "The Windows Subsystem for Linux command is unavailable.",
            "Repair the DiffeoForge reference-runtime installation.",
            managed,
        )
    distributions = installed_wsl_distributions()
    if distribution not in distributions:
        guidance = (
            "Repair DiffeoForge to restore its bundled Deformetrica runtime."
            if managed
            else f"The configured WSL distribution {distribution!r} is not installed."
        )
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            f"WSL distribution is missing: {distribution}",
            guidance,
            managed,
        )
    try:
        executable_check = _run_wsl(
            ["-d", distribution, "--", "/usr/bin/test", "-x", executable]
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            f"Could not inspect the Deformetrica executable: {error}",
            "Repair the DiffeoForge reference-runtime installation.",
            managed,
        )
    if executable_check.returncode != 0:
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            f"Deformetrica executable is missing or not executable: {executable}",
            "Repair the DiffeoForge reference-runtime installation.",
            managed,
        )
    try:
        version_check = _run_wsl(
            ["-d", distribution, "--", executable, "--help"], timeout=45
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return ReferenceRuntimeProbe(
            normalized,
            False,
            None,
            f"Deformetrica did not answer its version probe: {error}",
            "Repair the DiffeoForge reference-runtime installation.",
            managed,
        )
    output = "\n".join(
        part
        for part in (
            _decode_windows_output(version_check.stdout),
            _decode_windows_output(version_check.stderr),
        )
        if part
    )
    version = expected_version if _VERSION_PATTERN.search(output) else None
    if version_check.returncode != 0 or version != expected_version:
        first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
        return ReferenceRuntimeProbe(
            normalized,
            False,
            version,
            first_line or f"Deformetrica version {expected_version} was not verified.",
            f"DiffeoForge requires the verified Deformetrica {expected_version} runtime.",
            managed,
        )
    ownership = "managed" if managed else "existing read-only"
    return ReferenceRuntimeProbe(
        normalized,
        True,
        version,
        f"Deformetrica {version} in {distribution} ({ownership} runtime)",
        None,
        managed,
    )


def _default_home_deformetrica(distribution: str) -> str | None:
    """Find a legacy `/home/*/deformetrica` executable without a shell."""

    try:
        completed = _run_wsl(["-d", distribution, "--", "/bin/ls", "-1", "/home"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    for user in _decode_windows_output(completed.stdout).splitlines():
        user = user.strip()
        if not user or "/" in user or user in {".", ".."}:
            continue
        candidate = f"/home/{user}/deformetrica/bin/deformetrica"
        try:
            checked = _run_wsl(
                ["-d", distribution, "--", "/usr/bin/test", "-x", candidate]
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if checked.returncode == 0:
            return candidate
    return None


def select_preferred_reference_launcher() -> dict[str, str]:
    """Choose a verified runtime, falling back to the installer-owned identity.

    The legacy search exists only to migrate same-owner alpha installations.  It
    never installs, upgrades, or writes into an existing WSL distribution.
    """

    if os.name != "nt":
        return {"type": "native", "executable": shutil.which("deformetrica") or "deformetrica"}

    managed = managed_wsl_launcher()
    if probe_wsl_launcher(managed).ready:
        return managed

    for distribution in installed_wsl_distributions():
        candidate = _default_home_deformetrica(distribution)
        if candidate is None:
            continue
        launcher = {
            "type": "wsl",
            "distribution": distribution,
            "executable": candidate,
        }
        if probe_wsl_launcher(launcher).ready:
            return launcher
    return managed


def launcher_label(launcher: Mapping[str, str]) -> str:
    """Return an end-user label without exposing container-centric wording."""

    launcher_type = str(launcher.get("type", ""))
    if launcher_type == "wsl":
        distribution = str(launcher.get("distribution", ""))
        if distribution == MANAGED_WSL_DISTRIBUTION:
            return "Bundled DiffeoForge Deformetrica 4.3 runtime"
        return f"Detected Deformetrica 4.3 runtime ({distribution})"
    if launcher_type == "native":
        return f"Native Deformetrica runtime ({launcher.get('executable', '')})"
    if launcher_type == "container":
        return f"Developer container runtime ({launcher.get('image', '')})"
    return "Unknown Deformetrica runtime"


def launcher_identity(launcher: Mapping[str, str]) -> dict[str, str]:
    """Return only the stable schema fields for exact launcher binding."""

    launcher_type = str(launcher.get("type", ""))
    fields = {
        "container": ("type", "engine", "image"),
        "wsl": ("type", "distribution", "executable"),
        "native": ("type", "executable"),
    }.get(launcher_type)
    if fields is None:
        raise ValueError(f"Unsupported reference launcher type: {launcher_type!r}")
    identity = {field: str(launcher[field]) for field in fields}
    return identity
