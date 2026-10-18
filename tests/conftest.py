"""Engineering tests must never read or change the user's recording preference."""

import importlib.util

import pytest


@pytest.fixture(autouse=True)
def isolated_recording_preferences(monkeypatch, tmp_path):
    if importlib.util.find_spec("PySide6") is None:
        return
    from PySide6.QtCore import QSettings

    import diffeoforge.desktop.process_recorder as recording

    monkeypatch.setattr(
        recording,
        "_default_settings",
        lambda: QSettings(str(tmp_path / "recording-preferences.ini"), QSettings.Format.IniFormat),
    )
