"""Saved comparison preparation remains usable on error, cancel and close."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

from diffeoforge import guided_feedback, reference_calibration_study, reference_guided_pilot
from diffeoforge.desktop import guided_fit_direction as comparison
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader, _Worker
from diffeoforge.desktop.reference_calibration_dialog import (
    CalibrationQcPair,
    ReferenceCalibrationDialog,
)


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["guided-comparison-lifecycle"])


def _wait(application, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(5)
    assert predicate()


class Window(QWidget):
    def __init__(self, root):
        super().__init__()
        self.study_directory = root
        self._worker = None
        self._mark_error_action = None
        self._view_loading = self._view_closed = self._review_saving = False
        self.status = QLabel("Reviewed fit saved; choose the next step.", self)
        self._viewer_preparation = PreviewMeshLoader(self)
        self._viewer_preparation.loaded.connect(
            lambda key, value: ReferenceCalibrationDialog._candidate_prepared(self, key, value))
        self._viewer_preparation.failed.connect(
            lambda key, error: ReferenceCalibrationDialog._candidate_prepare_failed(
                self, key, error))
        self._viewer_preparation.cancelled.connect(
            lambda: ReferenceCalibrationDialog._candidate_preparation_cancelled(self))
        self.working_choices = []

    def _open_guided_working_fit(self, *args, **kwargs):
        self.working_choices.append((args, kwargs))


@pytest.fixture
def setup(application, tmp_path, monkeypatch):
    window = Window(tmp_path)
    direction = dict(target="public.vtk", identifier="guided-varifold",
                     current={"candidate_id": "guided-varifold"},
                     alternative={"candidate_id": "guided-current"})
    shown, deleted = [], []

    class Dialog:
        working_view = None

        def __init__(self, owner, origin, selected, prepared):
            assert origin == window.study_directory
            shown.append((selected, prepared, owner))

        def exec(self):
            assert window.status.text() != comparison._PREPARING
            return QDialog.DialogCode.Rejected

        def deleteLater(self):
            deleted.append(True)

    monkeypatch.setattr(comparison, "_ComparisonDialog", Dialog)
    yield window, direction, shown, deleted, Dialog
    window._view_closed = True
    window._viewer_preparation.cancel()
    _wait(application, lambda: window._viewer_preparation._active is None)
    window.close()


@pytest.mark.parametrize("exception", [StopIteration(), ValueError("")])
def test_empty_exception_is_failure_instead_of_loaded_none(application, exception):
    records = []

    def fail():
        raise exception

    worker = _Worker(1, "public", fail)
    worker.signals.finished.connect(lambda *args: records.append(args))
    worker.run()
    assert len(records) == 1
    assert records[0][:3] == (1, "public", None)
    assert type(exception).__name__ in records[0][3]


def test_duplicate_clicks_prepare_once_and_close_restores_previous_status(
    application, setup, monkeypatch,
):
    window, direction, shown, deleted, _ = setup
    release, entered = threading.Event(), threading.Event()
    operations = []

    def prepare(*_args):
        operations.append(True)
        entered.set()
        assert release.wait(3)
        return "verified overlays"

    monkeypatch.setattr(comparison, "_prepare", prepare)
    previous = window.status.text()
    try:
        comparison.open_comparison(window, direction)
        assert entered.wait(2)
        comparison.open_comparison(window, direction.copy())
        assert window._viewer_preparation._pending is None
        assert operations == [True]
        application.processEvents()  # The parent event loop remains responsive.
    finally:
        release.set()
    _wait(application, lambda: bool(deleted))
    assert len(shown) == len(deleted) == 1
    assert window.status.text() == previous
    assert window._guided_comparison_request is None
    assert window._viewer_preparation._active is None


@pytest.mark.parametrize("exception", [StopIteration(), ValueError(""), ValueError("bad export")])
def test_async_failure_is_visible_clears_preparing_and_allows_retry(
    application, setup, monkeypatch, exception,
):
    window, direction, shown, _, _ = setup

    def fail(*_args):
        raise exception

    monkeypatch.setattr(comparison, "_prepare", fail)
    comparison.open_comparison(window, direction)
    _wait(application, lambda: window._guided_comparison_request is None)
    assert "Comparison unavailable:" in window.status.text()
    assert "bad export" in window.status.text() or type(exception).__name__ in window.status.text()
    assert shown == []
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "retry overlays")
    comparison.open_comparison(window, direction)
    _wait(application, lambda: len(shown) == 1)
    assert window._guided_comparison_request is None


def test_dialog_construction_error_is_visible_in_parent(application, setup, monkeypatch):
    window, direction, shown, _, _ = setup
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: None)

    def fail(*_args):
        raise ValueError("comparison display unavailable")

    monkeypatch.setattr(comparison, "_ComparisonDialog", fail)
    comparison.open_comparison(window, direction)
    _wait(application, lambda: window._guided_comparison_request is None)
    assert window.status.text() == "Comparison unavailable: comparison display unavailable"
    assert shown == []


def test_dialog_execution_error_releases_request_and_deletes_dialog(
    application, setup, monkeypatch,
):
    window, direction, _, deleted, dialog = setup
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "overlays")

    def fail(_dialog):
        raise ValueError("viewer could not open")

    monkeypatch.setattr(dialog, "exec", fail)
    comparison.open_comparison(window, direction)
    _wait(application, lambda: window._guided_comparison_request is None)
    assert window.status.text() == "Comparison unavailable: viewer could not open"
    assert deleted == [True]


def test_legacy_preparing_status_is_not_restored_after_close(application, setup, monkeypatch):
    window, direction, shown, _, _ = setup
    window.status.setText(comparison._PREPARING)
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "overlays")
    comparison.open_comparison(window, direction)
    _wait(application, lambda: bool(shown))
    assert window.status.text() not in {comparison._PREPARING, comparison._OPEN}


@pytest.mark.parametrize("fails", [False, True])
def test_changed_origin_discards_ready_or_failed_callback(
    application, setup, monkeypatch, tmp_path, fails,
):
    window, direction, shown, _, _ = setup
    release, entered = threading.Event(), threading.Event()

    def prepare(*_args):
        entered.set()
        assert release.wait(3)
        if fails:
            raise ValueError("old pilot error")
        return "old pilot overlays"

    monkeypatch.setattr(comparison, "_prepare", prepare)
    try:
        comparison.open_comparison(window, direction)
        assert entered.wait(2)
        window.study_directory = tmp_path / "other-pilot"
        window.status.setText("New pilot ready.")
    finally:
        release.set()
    _wait(application, lambda: window._viewer_preparation._active is None)
    assert shown == []
    assert window.status.text() == "New pilot ready."
    assert window._guided_comparison_request is None


@pytest.mark.parametrize("flag", ["_view_closed", "_review_saving", "_worker"])
def test_computation_review_or_close_supersedes_pending_comparison(
    application, setup, monkeypatch, flag,
):
    window, direction, shown, _, _ = setup
    release, entered = threading.Event(), threading.Event()

    def prepare(*_args):
        entered.set()
        assert release.wait(3)
        return "overlays"

    monkeypatch.setattr(comparison, "_prepare", prepare)
    try:
        comparison.open_comparison(window, direction)
        assert entered.wait(2)
        setattr(window, flag, True)
        window.status.setText("The newer action owns this status.")
    finally:
        release.set()
    _wait(application, lambda: window._viewer_preparation._active is None)
    assert shown == []
    assert window.status.text() == "The newer action owns this status."
    assert window._guided_comparison_request is None


def test_cancel_clears_pending_request_and_late_work_cannot_open_modal(
    application, setup, monkeypatch,
):
    window, direction, shown, _, _ = setup
    release, entered = threading.Event(), threading.Event()

    def prepare(*_args):
        entered.set()
        assert release.wait(3)
        return "cancelled overlays"

    monkeypatch.setattr(comparison, "_prepare", prepare)
    previous = window.status.text()
    try:
        comparison.open_comparison(window, direction)
        assert entered.wait(2)
        start = time.monotonic()
        window._viewer_preparation.cancel()
        assert time.monotonic() - start < 0.1
        assert window._guided_comparison_request is None
        assert window.status.text() == previous
        # Cancellation invalidates delivery; it does not pretend the reader exited.
        assert window._viewer_preparation._active is not None
    finally:
        release.set()
    _wait(application, lambda: window._viewer_preparation._active is None)
    assert shown == []
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "fresh overlays")
    comparison.open_comparison(window, direction)
    _wait(application, lambda: bool(shown))


def test_stale_generic_failure_does_not_overwrite_current_pilot_status(application, setup):
    window, _, _, _, _ = setup
    old = window.study_directory / "old-study"
    previous = window.status.text()
    ReferenceCalibrationDialog._candidate_prepare_failed(
        window, ("guided-working", old, {}), "old failure")
    assert window.status.text() == previous


@pytest.mark.parametrize("fails", [False, True])
def test_replaced_preparation_discards_old_comparison_and_keeps_new_action(
    application, setup, monkeypatch, fails,
):
    from diffeoforge.desktop import guided_working_fit

    window, direction, shown, _, _ = setup
    release, entered = threading.Event(), threading.Event()

    def prepare(*_args):
        entered.set()
        assert release.wait(3)
        return "old overlays"

    monkeypatch.setattr(comparison, "_prepare", prepare)
    newer = []

    def show(_window, key, value):
        newer.append((key, value))
        window.status.setText("New saved review ready.")

    monkeypatch.setattr(guided_working_fit, "show", show)

    def latest():
        if fails:
            raise ValueError("new saved review unavailable")
        return "new saved review"

    try:
        comparison.open_comparison(window, direction)
        assert entered.wait(2)
        window.status.setText("New saved review loading.")
        window._viewer_preparation.request_operation(
            ("guided-working", window.study_directory, {}), latest)
    finally:
        release.set()
    _wait(application, lambda: window._viewer_preparation._active is None)
    assert shown == []
    assert window._guided_comparison_request is None
    if fails:
        assert window.status.text() == "Comparison unavailable: new saved review unavailable"
    else:
        assert newer[0][1] == "new saved review"
        assert window.status.text() == "New saved review ready."


def test_loader_returns_own_token_when_activity_listener_queues_replacement(application):
    loader = PreviewMeshLoader()
    queued = []
    received = []

    def replace(busy):
        if busy and not queued:
            queued.append(True)
            loader.request_operation("latest", lambda: "latest")

    loader.activity_changed.connect(replace)
    loader.loaded.connect(lambda key, value: received.append((key, value)))
    token = loader.request_operation("original", lambda: "original")
    assert not loader.is_current_request(token)
    _wait(application, lambda: bool(received))
    assert received == [("latest", "latest")]


def test_explicit_saved_fit_choice_preserves_reference_and_view_hint(
    application, setup, monkeypatch,
):
    window, direction, _, _, dialog = setup
    chosen = dict(reference=direction["alternative"], markers=("unchanged marks",))
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "overlays")
    monkeypatch.setattr(dialog, "working_view", chosen)
    monkeypatch.setattr(dialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    comparison.open_comparison(window, direction)
    _wait(application, lambda: bool(window.working_choices))
    args, kwargs = window.working_choices[0]
    assert args == (direction["identifier"], direction["alternative"])
    assert kwargs == {"view_hint": chosen}
    assert window._guided_comparison_request is None


def test_replaced_request_during_modal_cannot_apply_old_working_choice(
    application, setup, monkeypatch,
):
    from diffeoforge.desktop import guided_working_fit

    window, direction, _, _, dialog = setup
    monkeypatch.setattr(comparison, "_prepare", lambda *_args: "overlays")
    monkeypatch.setattr(dialog, "working_view", dict(reference=direction["alternative"]))
    replacements = []
    monkeypatch.setattr(guided_working_fit, "show", lambda *args: replacements.append(args))

    def choose_after_replacement(_dialog):
        window.status.setText("New saved review loading.")
        window._viewer_preparation.request_operation(
            ("guided-working", window.study_directory, {}), lambda: "replacement")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialog, "exec", choose_after_replacement)
    comparison.open_comparison(window, direction)
    _wait(application, lambda: bool(replacements))
    assert window.working_choices == []
    assert window.status.text() == "New saved review loading."
    assert window._guided_comparison_request is None


@pytest.mark.parametrize("missing", ["subject", "candidate", "pair"])
def test_missing_saved_binding_reports_actionable_error(tmp_path, monkeypatch, missing):
    current, alternative = tmp_path / "current", tmp_path / "alternative"
    target = "public.vtk"
    snapshots, manifests = {}, {}
    direction = dict(target=target, current_cp=270, alternative_cp=270)
    for name, root in (("current", current), ("alternative", alternative)):
        identifier = "guided-" + name
        direction[name] = dict(directory=str(root), target=target,
                               candidate_id=identifier, method=name)
        snapshots[root] = SimpleNamespace(
            study_directory=root, candidates=[SimpleNamespace(candidate_id=identifier)],
            plan=SimpleNamespace(pilot_subject_count=1),
            attachment_comparison={"controls": {"count": 270}},
            info=dict(origin=str(tmp_path), target=target, screen_trials_spent=1,
                      history=[{"directory": str(alternative)}]),
        )
        manifests[root] = dict(inputs=dict(template={"sha256": "template"},
                                           subjects=[dict(filename=target, sha256="original")]))
    monkeypatch.setattr(reference_calibration_study, "load_reference_calibration_study",
                        snapshots.__getitem__)
    monkeypatch.setattr(reference_calibration_study, "_verify_manifest", manifests.__getitem__)
    monkeypatch.setattr(reference_guided_pilot, "record", lambda value: value.info)
    monkeypatch.setattr(guided_feedback, "verify_reference",
                        lambda ref: snapshots[Path(ref["directory"])])
    monkeypatch.setattr(comparison, "collect_calibration_qc_pairs", lambda *_args: (
        CalibrationQcPair("subject", target, current / target, current / "reco.vtk",
                          True, "original", "reconstruction"),))
    if missing == "subject":
        manifests[current]["inputs"]["subjects"] = []
        expected = "current pilot inputs do not contain public.vtk"
    elif missing == "candidate":
        snapshots[current].candidates = []
        expected = "Saved current fit guided-current is missing for public.vtk"
    else:
        monkeypatch.setattr(comparison, "collect_calibration_qc_pairs", lambda *_args: ())
        expected = "no original/reconstruction pair for public.vtk"
    with pytest.raises(ValueError, match=expected):
        comparison._prepare(current, direction)
