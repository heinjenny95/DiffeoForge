"""The desktop comparison dispatches the exact chosen existing-run contrast."""

import sys
import threading
import time
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.group_atlas_comparison_dialog import GroupAtlasComparisonDialog


def _wait(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition()


def _selected_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    metadata = tmp_path / "cohort.csv"
    metadata.write_text("mesh,genotype\ns1,WT\ns2,WT\ns3,KO\ns4,KO\n", encoding="utf-8")
    dialog = GroupAtlasComparisonDialog(first)
    dialog.show()
    dialog._select_metadata(metadata)
    _wait(app, lambda: dialog.ids.count() == 2)
    dialog.ids.setCurrentText("mesh")
    dialog.groups.setCurrentText("genotype")
    dialog.reference.setCurrentText("WT")
    dialog.comparison.setCurrentText("KO")
    return app, dialog, first, second, metadata


def test_choose_exact_contrast_and_create_one_private_report(tmp_path, monkeypatch):
    app, dialog, first, second, metadata = _selected_dialog(tmp_path, monkeypatch)
    calls = []

    def write_group_comparison(a, b, csv, output, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        calls.append((a, b, csv, kwargs))
        output.mkdir()
        report = output / "group-comparison.html"
        report.write_text("<h1>Comparison</h1>", encoding="utf-8")
        return report

    monkeypatch.setitem(sys.modules, "diffeoforge.biological_atlas_comparison",
                        SimpleNamespace(write_group_comparison=write_group_comparison))
    try:
        assert not dialog.create.isEnabled()
        dialog._select_second(first)
        assert not dialog.create.isEnabled()
        dialog._select_second(second)
        assert dialog.create.isEnabled()
        dialog.comparison.setCurrentText("WT")
        assert not dialog.create.isEnabled()
        dialog.comparison.setCurrentText("KO")
        dialog.create.click()
        assert not dialog.create.isEnabled()
        _wait(app, dialog.open_report.isEnabled)
        assert calls == [(first, second, metadata, dict(
            id_column="mesh", group_column="genotype", reference_level="WT", comparison_level="KO",
        ))]
        assert dialog._report.is_relative_to(tmp_path) and dialog._report.is_file()
        assert list(first.iterdir()) == list(second.iterdir()) == []
        assert dialog.open_report.isVisible()
        dialog.reference.setCurrentText("KO")
        assert not dialog.open_report.isVisible()
        assert not dialog.create.isEnabled()
    finally:
        dialog.close()


def test_changed_metadata_requires_reselect_before_comparison(tmp_path, monkeypatch):
    app, dialog, _first, second, metadata = _selected_dialog(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setitem(sys.modules, "diffeoforge.biological_atlas_comparison",
                        SimpleNamespace(write_group_comparison=lambda *_a, **_kw: calls.append(1)))
    try:
        dialog._select_second(second)
        metadata.write_text("mesh,genotype\ns1,NEW\n", encoding="utf-8")
        dialog.create.click()
        _wait(app, dialog.create.isEnabled)
        assert "CSV changed" in dialog.status.text()
        assert not calls and not dialog.open_report.isVisible()
    finally:
        dialog.close()
