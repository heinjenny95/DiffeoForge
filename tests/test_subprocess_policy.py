from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import subprocess_policy

ROOT = Path(__file__).resolve().parents[1]


class _StartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = -1


def test_hidden_windows_process_kwargs_combine_flags_and_hide_window(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_policy, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        subprocess_policy.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
    )
    monkeypatch.setattr(
        subprocess_policy.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False
    )
    monkeypatch.setattr(subprocess_policy.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(
        subprocess_policy.subprocess, "STARTUPINFO", _StartupInfo, raising=False
    )

    options = subprocess_policy.hidden_windows_process_kwargs(creationflags=0x00000200)

    assert options["creationflags"] == 0x08000200
    assert options["startupinfo"].dwFlags & 0x00000001
    assert options["startupinfo"].wShowWindow == 0


def test_hidden_windows_process_kwargs_are_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_policy, "os", SimpleNamespace(name="posix"))

    assert subprocess_policy.hidden_windows_process_kwargs(creationflags=123) == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows console-allocation evidence")
def test_hidden_windows_process_kwargs_prevent_child_console_allocation() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import ctypes; print(int(ctypes.windll.kernel32.GetConsoleWindow()))",
        ],
        capture_output=True,
        text=True,
        check=False,
        **subprocess_policy.hidden_windows_process_kwargs(),
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "0"


def test_every_production_subprocess_call_uses_hidden_windows_policy() -> None:
    violations: list[str] = []
    source_root = ROOT / "src" / "diffeoforge"
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        def is_launcher(value):
            return (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "subprocess"
                and value.attr in {"run", "Popen"}
            )

        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                positional = [*args.posonlyargs, *args.args]
                defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
                for arg, default in zip(
                    [*positional, *args.kwonlyargs], [*defaults, *args.kw_defaults], strict=True
                ):
                    if is_launcher(default):
                        aliases.add(arg.arg)
            elif isinstance(node, ast.Assign) and is_launcher(node.value):
                aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                aliases.update(n.asname or n.name for n in node.names
                               if n.name in {"run", "Popen"})
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (is_launcher(node.func)
                    or isinstance(node.func, ast.Name) and node.func.id in aliases):
                continue
            guarded = any(
                keyword.arg is None
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id == "hidden_windows_process_kwargs"
                for keyword in node.keywords
            )
            if not guarded:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert violations == []
