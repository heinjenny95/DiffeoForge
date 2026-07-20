from __future__ import annotations

import subprocess

from diffeoforge import reference_runtime


def _completed(argv: list[str], returncode: int = 0, output: bytes = b""):
    return subprocess.CompletedProcess(argv, returncode, stdout=output, stderr=b"")


def test_probe_wsl_launcher_verifies_exact_deformetrica_version(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "DiffeoForge-Reference-4.3",
        "executable": "/opt/diffeoforge/reference/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        reference_runtime,
        "installed_wsl_distributions",
        lambda: ("DiffeoForge-Reference-4.3",),
    )

    def fake_run(arguments: list[str], *, timeout: int = 30):
        if arguments[-1] == "--help":
            return _completed(arguments, output=b"Deformetrica 4.3.0\n")
        return _completed(arguments)

    monkeypatch.setattr(reference_runtime, "_run_wsl", fake_run)

    probe = reference_runtime.probe_wsl_launcher(launcher)

    assert probe.ready is True
    assert probe.version == "4.3.0"
    assert probe.managed is True


def test_probe_wsl_launcher_rejects_wrong_version(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        reference_runtime, "installed_wsl_distributions", lambda: ("Ubuntu",)
    )

    def fake_run(arguments: list[str], *, timeout: int = 30):
        if arguments[-1] == "--help":
            return _completed(arguments, output=b"Deformetrica 4.2.0\n")
        return _completed(arguments)

    monkeypatch.setattr(reference_runtime, "_run_wsl", fake_run)

    probe = reference_runtime.probe_wsl_launcher(launcher)

    assert probe.ready is False
    assert "4.3.0" in (probe.guidance or "")


def test_preferred_launcher_reuses_verified_same_owner_alpha_runtime(monkeypatch) -> None:
    managed = reference_runtime.managed_wsl_launcher()
    legacy = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(
        reference_runtime, "installed_wsl_distributions", lambda: ("Ubuntu",)
    )
    monkeypatch.setattr(
        reference_runtime,
        "_default_home_deformetrica",
        lambda distribution: legacy["executable"],
    )

    def fake_probe(launcher, *, expected_version="4.3.0"):
        ready = dict(launcher) == legacy
        return reference_runtime.ReferenceRuntimeProbe(
            dict(launcher), ready, "4.3.0" if ready else None, "test"
        )

    monkeypatch.setattr(reference_runtime, "probe_wsl_launcher", fake_probe)

    assert reference_runtime.select_preferred_reference_launcher() == legacy
    assert reference_runtime.select_preferred_reference_launcher() != managed


def test_preferred_launcher_falls_back_to_installer_owned_identity(monkeypatch) -> None:
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime, "installed_wsl_distributions", lambda: ())
    monkeypatch.setattr(
        reference_runtime,
        "probe_wsl_launcher",
        lambda launcher, **_kwargs: reference_runtime.ReferenceRuntimeProbe(
            dict(launcher), False, None, "missing"
        ),
    )

    assert (
        reference_runtime.select_preferred_reference_launcher()
        == reference_runtime.managed_wsl_launcher()
    )
