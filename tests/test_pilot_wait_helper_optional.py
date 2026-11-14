"""Headless scientific fixtures must not eagerly require the Qt GUI extra."""

import subprocess
import sys
from pathlib import Path


def test_pilot_wait_helper_can_be_imported_with_qt_blocked(tmp_path):
    helpers = Path(__file__).resolve().parent
    code = """
import importlib.abc
import sys
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            raise ModuleNotFoundError('Qt intentionally unavailable')
sys.meta_path.insert(0, BlockQt())
sys.path.insert(0, sys.argv[1])
import pilot_view_helpers
assert 'PySide6' not in sys.modules
assert callable(pilot_view_helpers.wait_pilot_view)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(helpers)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_closed_qt_fixture_windows_are_deleted_before_application_teardown(monkeypatch):
    import pytest

    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from conftest import _delete_closed_test_windows
    from PySide6.QtWidgets import QApplication, QWidget
    from shiboken6 import isValid

    app = QApplication.instance() or QApplication([])
    existing = {id(w) for w in app.topLevelWidgets()}
    window = QWidget()
    window.close()
    assert isValid(window)
    _delete_closed_test_windows(existing)
    assert not isValid(window)
