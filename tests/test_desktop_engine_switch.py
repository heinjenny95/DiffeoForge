"""The pilot action must not reuse a project prepared for another engine."""

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.widgets import (
    DiffeoForgeWindow,
    _ProjectWorker,
    _ReferenceReadinessWorker,
    _ReviewWorker,
)


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(["engine-switch-test"])
    instance = DiffeoForgeWindow()
    yield instance
    instance._worker = None
    instance.close()
    application.processEvents()


@pytest.mark.parametrize("original", list(DesktopEngine))
def test_engine_change_invalidates_only_engine_bound_state(window, monkeypatch, tmp_path, original):
    other = next(engine for engine in DesktopEngine if engine != original)
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(original))
    config = tmp_path / "existing.yaml"
    config.write_bytes(b"existing configuration and evidence\n")
    landmarks = tmp_path / "landmarks.csv"
    landmarks.write_bytes(b"saved landmark coordinates\n")
    window.landmarks_edit.setText(str(landmarks))
    window.project_edit.setText(str(tmp_path))
    preview, visual, plan = object(), object(), object()
    monkeypatch.setattr(window, "_update_procrustes_controls", lambda: None)
    monkeypatch.setattr(window, "_approved_procrustes_fingerprint", lambda: "approved-gpa")
    monkeypatch.setattr(window, "_reference_calibration_plan_matches_current_inputs", lambda: False)
    window._procrustes_preview = preview
    window._procrustes_visual = visual
    window._procrustes_visual_reviewed_fingerprint = "approved-gpa"
    window._reference_calibration_plan = plan
    window._result = SimpleNamespace(engine=original, config_path=config)
    window._review = SimpleNamespace(engine=original, config_path=config)
    for name in (
        "_template_preview",
        "_reference_readiness",
        "_reference_preparation_status",
        "_run_readiness",
        "_reference_run_request",
        "_run_result",
        "_result_review",
    ):
        setattr(window, name, object())
    window._reference_calibrated_config_path = config
    window._reference_calibration_study_directory = tmp_path
    window._guided_reference_calibration_requested = True
    window.result_card.show()
    window.run_result_card.show()

    window.engine_combo.setCurrentIndex(window.engine_combo.findData(other))

    for name in (
        "_result",
        "_review",
        "_template_preview",
        "_reference_readiness",
        "_reference_preparation_status",
        "_run_readiness",
        "_reference_run_request",
        "_run_result",
        "_result_review",
        "_reference_calibrated_config_path",
        "_reference_calibration_study_directory",
    ):
        assert getattr(window, name) is None, name
    assert not window._guided_reference_calibration_requested
    assert window.result_card.isHidden()
    assert window.run_result_card.isHidden()
    assert not window._step_is_unlocked(2)
    assert not window._step_is_unlocked(3)
    assert window._procrustes_preview is preview
    assert window._procrustes_visual is visual
    assert window._procrustes_visual_reviewed_fingerprint == "approved-gpa"
    assert window._reference_calibration_plan is plan
    assert window.landmarks_edit.text() == str(landmarks)
    assert window.project_edit.text() == str(tmp_path)
    assert config.read_bytes() == b"existing configuration and evidence\n"
    assert landmarks.read_bytes() == b"saved landmark coordinates\n"


@pytest.mark.parametrize("stale_field", ["_result", "_review", "both"])
def test_pilot_repairs_stale_modern_state_and_queues_only_one_reference_project(
    window,
    monkeypatch,
    tmp_path,
    stale_field,
):
    reference = DesktopEngine.DEFORMETRICA_REFERENCE
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(reference))
    monkeypatch.setattr(window, "_reference_calibration_plan_matches_current_inputs", lambda: True)
    # Keep the execution-card check independent of a large real mesh analysis.
    window._reference_calibration_plan = SimpleNamespace(pilot_subject_count=3, stages=())
    for name in ("_result", "_review"):
        if stale_field in (name, "both"):
            setattr(window, name, SimpleNamespace(engine=DesktopEngine.MODERN_CPU))
    window._reference_readiness = SimpleNamespace(ready=True)
    window._reference_calibrated_config_path = tmp_path  # would otherwise look completed below
    completed_file = tmp_path / "stale-selected.yaml"
    completed_file.write_text("preserve me", encoding="utf-8")
    window._reference_calibrated_config_path = completed_file
    queued = []
    window._thread_pool = SimpleNamespace(start=queued.append)
    request = SimpleNamespace(engine=reference, approved_procrustes_fingerprint=None)
    monkeypatch.setattr(window, "_request", lambda: request)
    monkeypatch.setattr(window, "_configuration_path", lambda _request: tmp_path / "atlas.yaml")

    for _ in range(20):
        window._prepare_or_open_reference_calibration()

    assert len(queued) == 1
    assert isinstance(queued[0], _ProjectWorker)
    assert window._worker is queued[0]
    assert window._guided_reference_calibration_requested
    assert window._result is None and window._review is None
    assert not window.open_reference_calibration_button.isEnabled()
    assert not window.engine_combo.isEnabled()
    assert "Creating and validating" in window.reference_calibration_execution_status.text()
    assert "Checking" not in window.reference_calibration_execution_status.text()
    assert completed_file.read_text(encoding="utf-8") == "preserve me"


def test_pilot_continues_same_engine_review_and_readiness(window, monkeypatch, tmp_path):
    reference = DesktopEngine.DEFORMETRICA_REFERENCE
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(reference))
    monkeypatch.setattr(window, "_reference_calibration_plan_matches_current_inputs", lambda: True)
    monkeypatch.setattr(window, "_reference_calibration_context", lambda: None)
    window._reference_calibration_plan = SimpleNamespace(pilot_subject_count=3, stages=())
    window._result = SimpleNamespace(engine=reference, config_path=tmp_path / "atlas.yaml")
    calls = []
    monkeypatch.setattr(window, "_review_project", lambda: calls.append("review"))
    monkeypatch.setattr(
        window, "_create_project", lambda: pytest.fail("Existing project recreated")
    )
    window._prepare_or_open_reference_calibration()
    assert calls == ["review"]
    assert "Reviewing" in window.reference_calibration_execution_status.text()

    window._review = SimpleNamespace(engine=reference)
    queued = []
    window._thread_pool = SimpleNamespace(start=queued.append)
    window._prepare_or_open_reference_calibration()
    assert len(queued) == 1
    assert isinstance(queued[0], _ReferenceReadinessWorker)
    assert "Checking" in window.reference_calibration_execution_status.text()
    assert not window.open_reference_calibration_button.isEnabled()


def test_pilot_opens_ready_existing_context_without_recreating(window, monkeypatch, tmp_path):
    reference = DesktopEngine.DEFORMETRICA_REFERENCE
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(reference))
    monkeypatch.setattr(window, "_reference_calibration_plan_matches_current_inputs", lambda: True)
    monkeypatch.setattr(window, "_reference_calibration_context", lambda: (object(), tmp_path))
    window._result = SimpleNamespace(engine=reference)
    window._review = SimpleNamespace(engine=reference)
    window._reference_readiness = SimpleNamespace(ready=True)
    calls = []
    monkeypatch.setattr(window, "_open_reference_calibration", lambda: calls.append("open"))
    monkeypatch.setattr(
        window, "_create_project", lambda: pytest.fail("Existing project recreated")
    )
    window._prepare_or_open_reference_calibration()
    assert calls == ["open"]


def test_running_worker_keeps_engine_and_project_bound(window):
    original = window.engine_combo.currentData()
    other = next(engine for engine in DesktopEngine if engine != original)
    result = SimpleNamespace(engine=original)
    worker = _ReviewWorker(result)
    window._worker = worker
    window._sync_ready_state()
    assert not window.engine_combo.isEnabled()
    window._result = result
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(other))
    assert window.engine_combo.currentData() == original
    assert window._result is result
    assert window._worker is worker
    window._result = None
    window._worker = None
    window._sync_ready_state()
    assert window.engine_combo.isEnabled()


@pytest.mark.parametrize("review", [None, SimpleNamespace(engine=DesktopEngine.MODERN_CPU)])
def test_readiness_without_reference_review_explains_required_action(window, review):
    window._review = review
    window._guided_reference_calibration_requested = True
    window._check_reference_readiness()
    assert window._worker is None
    assert not window._guided_reference_calibration_requested
    assert "Create and review a Deformetrica project" in window.status_label.text()
    assert "Checking" not in window.reference_calibration_execution_status.text()


def test_hidden_reference_action_does_nothing_for_modern_engine(window, monkeypatch):
    window.engine_combo.setCurrentIndex(window.engine_combo.findData(DesktopEngine.MODERN_CPU))
    monkeypatch.setattr(window, "_create_project", lambda: pytest.fail("Hidden action ran"))
    window._prepare_or_open_reference_calibration()
    assert window._worker is None
    assert not window._guided_reference_calibration_requested
