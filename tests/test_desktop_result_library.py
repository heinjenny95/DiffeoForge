"""Result navigation must find deep atlases without changing scientific evidence."""

from __future__ import annotations

import json
import os
import subprocess
import threading

import pytest

from diffeoforge.desktop.result_library import (
    entry_name,
    load_library_preferences,
    save_library_preference,
    scan_result_library,
)


def _run(
    path, *, name="Study atlas", count=56, ended="2026-10-19T11:30:00Z", status="completed", code=0
):
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "backend": {"id": "deformetrica_reference"},
                "project": {"name": name},
                "input_count": {"subjects": count},
            }
        )
    )
    (path / "result.json").write_text(
        json.dumps(
            {
                "status": status,
                "return_code": code,
                "ended_at": ended,
            }
        )
    )
    return path


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_finds_full_atlas_under_selected_calibration_and_multiple_versions(tmp_path):
    new = _run(tmp_path / "v7/calibration/search/joint-95/selected/runs/opaque-id")
    old = _run(tmp_path / "v6/runs/older", ended="2026-10-18T11:00:00Z")
    pilot = _run(
        tmp_path / "v7/calibration/fit/runs/pilot-attempt-01",
        name="Study atlas calibration fit-specimen",
        count=1,
    )
    _run(tmp_path / "v7/runs/in-progress", status="running", code=None)
    _run(tmp_path / "v7/runs/failed", status="failed", code=1)
    before = _snapshot(tmp_path)
    scan = scan_result_library((tmp_path, tmp_path / "v7", new))
    assert {e.result.run_directory for e in scan.entries} == {new, old, pilot}
    assert scan.entries[-1].result.run_directory == old
    main = next(e for e in scan.entries if e.result.run_directory == new)
    assert not main.pilot and main.subjects == 56 and main.project_name == "Study atlas"
    assert next(e for e in scan.entries if e.result.run_directory == pilot).pilot
    assert not scan.incomplete and not scan.unavailable
    assert _snapshot(tmp_path) == before


def test_does_not_walk_geometry_output_or_completed_run_children(tmp_path):
    good = _run(tmp_path / "runs/done")
    _run(tmp_path / "output/nested/false-copy")
    _run(good / "analysis/false-copy")
    _run(tmp_path / "inputs/nested/false-copy")
    assert [e.result.run_directory for e in scan_result_library((tmp_path,)).entries] == [good]


@pytest.mark.parametrize("kind", ["depth", "directories", "cancelled"])
def test_bounded_search_reports_partial_results_instead_of_false_empty(tmp_path, kind):
    _run(tmp_path / "project/version/runs/done")
    cancel = threading.Event()
    options = {}
    if kind == "depth":
        options["maximum_depth"] = 1
    elif kind == "directories":
        options["maximum_directories"] = 2
    else:
        cancel.set()
    scan = scan_result_library((tmp_path,), cancel, **options)
    assert scan.incomplete
    assert scan.visited <= options.get("maximum_directories", 6000)


def test_missing_corrupt_and_oversized_records_do_not_hide_other_projects(tmp_path, monkeypatch):
    from diffeoforge.desktop import result_library as library

    good = _run(tmp_path / "good")
    corrupt = _run(tmp_path / "corrupt")
    (corrupt / "manifest.json").write_text("{")
    large = _run(tmp_path / "large")
    (large / "manifest.json").write_text(" " * 2048)
    monkeypatch.setattr(library, "MAX_RECORD_BYTES", 1024)
    scan = scan_result_library((tmp_path, tmp_path / "moved"))
    assert [e.result.run_directory for e in scan.entries] == [good]
    assert str(tmp_path / "moved") in scan.unavailable


def test_does_not_follow_symbolic_root_or_child(tmp_path):
    real = tmp_path / "outside"
    _run(real / "done")
    root = tmp_path / "chosen"
    root.mkdir()
    link = root / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links unavailable for this account")
    assert not scan_result_library((root, link)).entries


@pytest.mark.skipif(os.name != "nt", reason="Windows junction guard")
def test_does_not_follow_windows_junction(tmp_path):
    outside = tmp_path / "outside"
    _run(outside / "done")
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    link = chosen / "junction"
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
    )
    assert created.returncode == 0
    assert not scan_result_library((chosen, link)).entries


def test_preferences_are_separate_recoverable_and_names_do_not_rename_runs(tmp_path):
    run = _run(tmp_path / "project/runs/opaque")
    before = _snapshot(run)
    store = tmp_path / "state/library.json"
    assert save_library_preference(root=run.parent.parent, opened=run, path=store)
    assert save_library_preference(rename=(run, "Final atlas — chosen name"), path=store)
    entry = scan_result_library((run,)).entries[0]
    prefs = load_library_preferences(store)
    assert entry_name(entry, prefs) == "Final atlas — chosen name"
    assert save_library_preference(opened=run, path=store)
    assert load_library_preferences(store)["opened"] == [str(run)]
    assert _snapshot(run) == before
    assert save_library_preference(rename=(run, ""), path=store)
    assert entry_name(entry, load_library_preferences(store)) == "Study atlas"
    store.write_text("broken")
    assert load_library_preferences(store) == {"roots": [], "opened": [], "names": {}}
    assert store.read_text() == "broken"


def test_bad_metadata_and_boolean_return_code_are_not_convergence_claims(tmp_path):
    good = _run(tmp_path / "good", count="invalid", ended="yesterday")
    _run(tmp_path / "boolean", code=False)
    (entry,) = scan_result_library((tmp_path,)).entries
    assert entry.result.run_directory == good and entry.subjects is None
    assert entry.completed_at == "" and entry.date_label


@pytest.fixture
def application(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    return QApplication.instance() or QApplication(["result-library-test"])


def _wait(application, predicate):
    from PySide6.QtTest import QTest

    for _ in range(500):
        application.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    pytest.fail("Result library did not finish")


def test_dialog_background_scan_filter_names_and_explicit_selection(
    application, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    from diffeoforge.desktop.result_library_dialog import ResultLibraryDialog

    run = _run(tmp_path / "study/deep/selected/runs/done")
    _run(tmp_path / "study/deep/runs/pilot-01", name="Study calibration fit", count=1)
    dialog = ResultLibraryDialog(tmp_path / "study")
    dialog.show()
    _wait(application, lambda: dialog.table.rowCount() == 1 and dialog._worker is None)
    assert dialog.selected_result is None
    assert dialog.table.item(0, 1).text() == "56"
    assert not dialog.location_details.panel.isVisible()
    dialog.show_pilots.setChecked(True)
    assert dialog.table.rowCount() == 2
    dialog.search.setText("done 2026")
    assert dialog.table.rowCount() == 1
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Final anatomy", True))
    dialog._rename()
    dialog.search.setText("Final anatomy")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "Final anatomy"
    dialog._open()
    assert dialog.selected_result.run_directory == run
    assert not dialog.isVisible()


def test_dialog_scan_is_off_gui_thread_and_close_cancels(application, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    import diffeoforge.desktop.result_library_dialog as module

    entered, release, cancelled = threading.Event(), threading.Event(), []
    threads, ticks = [], []

    def slow(roots, cancel):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        cancelled.append(cancel.is_set())
        return module.ResultLibraryScan((), 0, True, ())

    monkeypatch.setattr(module, "scan_result_library", slow)
    dialog = module.ResultLibraryDialog(tmp_path)
    dialog.show()
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(5)
    try:
        _wait(application, lambda: entered.is_set() and len(ticks) >= 3)
        assert threads == [threads[0]] and threads[0] != threading.get_ident()
        dialog.reject()
        assert dialog._worker.cancelled.is_set()
    finally:
        release.set()
        _wait(application, lambda: bool(cancelled))
        timer.stop()
    assert cancelled == [True]


def test_add_folder_is_remembered_and_cancel_never_opens_result(application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from diffeoforge.desktop.result_library_dialog import ResultLibraryDialog

    root = tmp_path / "new-project"
    _run(root / "version/selected/runs/done")
    dialog = ResultLibraryDialog()
    dialog.show()
    _wait(application, lambda: dialog._worker is None and dialog.status.text() != "")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(root))
    dialog._add_folder()
    _wait(application, lambda: dialog.table.rowCount() == 1 and dialog._worker is None)
    dialog.reject()
    assert dialog.selected_result is None
    reopened = ResultLibraryDialog()
    reopened.show()
    _wait(application, lambda: reopened.table.rowCount() == 1 and reopened._worker is None)
    reopened.reject()
