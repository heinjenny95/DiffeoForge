"""The reference-oriented GUI must not require the optional local Torch engine."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_desktop_starts_with_torch_explicitly_unavailable() -> None:
    pytest.importorskip("PySide6")
    code = """
import importlib.abc
import sys

class RejectTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise ModuleNotFoundError('Torch deliberately unavailable', name='torch')

sys.meta_path.insert(0, RejectTorch())
from diffeoforge.desktop.app import main
assert main(['--smoke']) == 0
assert 'torch' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_remote_controller_import_keeps_numerical_dependencies_optional() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import diffeoforge.desktop.remote_atlas_controller; "
                "assert 'torch' not in sys.modules; assert 'PySide6' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_reference_cli_with_analysis_extra_does_not_import_torch() -> None:
    pytest.importorskip("numpy")
    code = """
import importlib.abc
import sys

class RejectTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise ModuleNotFoundError('Torch deliberately unavailable', name='torch')

sys.meta_path.insert(0, RejectTorch())
from diffeoforge.cli import build_parser
build_parser()
assert 'torch' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
