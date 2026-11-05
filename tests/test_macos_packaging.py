"""Mac package entrypoints retain their production worker dispatch contracts."""
import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "distribution/macos"


@pytest.mark.parametrize("entry,module,method", [
    ("diffeoforge_desktop.py", "diffeoforge.desktop.app", "main"),
    ("diffeoforge_worker.py", "diffeoforge.desktop.worker", "_process_main"),
    ("diffeoforge_reference_worker.py", "diffeoforge.desktop.reference_worker_harness", "main"),
    ("diffeoforge_reference_preparation_worker.py",
     "diffeoforge.desktop.reference_preparation_worker_harness", "main"),
    ("diffeoforge_reference_execution_worker.py",
     "diffeoforge.desktop.reference_execution_worker", "_process_main"),
])
def test_frozen_mac_entrypoints_configure_then_use_the_correct_parent_protocol(
    monkeypatch, entry, module, method,
):
    calls = []
    bootstrap, target = ModuleType("macos_bootstrap"), ModuleType(module)
    bootstrap.configure_runtime_path = lambda: calls.append("configure")
    setattr(target, method, lambda: calls.append("main"))
    monkeypatch.setitem(sys.modules, "macos_bootstrap", bootstrap)
    monkeypatch.setitem(sys.modules, module, target)
    monkeypatch.setattr(sys, "argv", [entry])
    try:
        runpy.run_path(str(ROOT / entry), run_name="__main__")
    except SystemExit as exit_event:
        assert exit_event.code is None
    assert calls == ["configure", "main"]


def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "mac_package_bootstrap", ROOT / "macos_bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_moved_mac_application_discovers_its_own_reference_environment(tmp_path, monkeypatch):
    contents = tmp_path / "Applications Käfer/DiffeoForge.app/Contents"
    executable = contents / "MacOS/DiffeoForge"
    executable.parent.mkdir(parents=True)
    executable.touch()
    native = contents / "Resources/ReferenceRuntime/bin"
    native.mkdir(parents=True)
    (native / "deformetrica").touch()
    module = bootstrap()
    module.sys = SimpleNamespace(platform="darwin", frozen=True, executable=str(executable))
    monkeypatch.setenv("PATH", "/original")
    module.configure_runtime_path()
    assert module.os.environ["PATH"].split(module.os.pathsep) == [str(native), "/original"]


@pytest.mark.parametrize("platform,frozen", [("win32", True), ("darwin", False)])
def test_mac_packaging_does_not_change_other_launch_environments(monkeypatch, platform, frozen):
    module = bootstrap()
    module.sys = SimpleNamespace(platform=platform, frozen=frozen)
    monkeypatch.setenv("PATH", "/original")
    module.configure_runtime_path()
    assert module.os.environ["PATH"] == "/original"
