from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from diffeoforge.desktop.app import build_parser

ROOT = Path(__file__).parents[1]


def test_desktop_parser_is_available_without_importing_qt() -> None:
    args = build_parser().parse_args([])

    assert args.smoke is False
    assert "PySide6" not in sys.modules


def test_desktop_module_reports_a_clear_optional_dependency_error() -> None:
    if importlib.util.find_spec("PySide6") is not None:
        pytest.skip("PySide6 is installed")

    completed = subprocess.run(
        [sys.executable, "-m", "diffeoforge.desktop", "--smoke"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "install diffeoforge[desktop]" in completed.stderr


def test_desktop_window_constructs_in_offscreen_smoke() -> None:
    pytest.importorskip("PySide6")
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [sys.executable, "-m", "diffeoforge.desktop", "--smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


def test_desktop_window_exposes_required_project_controls(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-desktop-test"])
    window = DiffeoForgeWindow()

    assert window.windowTitle() == "DiffeoForge Desktop"
    assert window.findChild(QLineEdit, "meshDirectoryEdit") is not None
    assert window.findChild(QLineEdit, "projectDirectoryEdit") is not None
    assert window.findChild(QComboBox, "engineCombo") is not None
    assert window.findChild(QComboBox, "unitsCombo") is not None
    assert window.create_button.isEnabled() is False
    assert "CPU/float64" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is True
    window.engine_combo.setCurrentIndex(1)
    application.processEvents()
    assert "Deformetrica-4.3" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_window_renders_parameter_review_as_second_step(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from diffeoforge.desktop.project_review import ProjectReviewResult, ReviewItem
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-desktop-review-test"])
    window = DiffeoForgeWindow()
    report = tmp_path / "workload.html"
    report.write_text("report\n", encoding="utf-8")
    review = ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name="Käfer Atlas",
        config_path=tmp_path / "modern-atlas.yaml",
        config_sha256="a" * 64,
        report_path=report,
        report_label="Modern-Workload-Report",
        subject_count=305,
        parameters=(ReviewItem("Kontrollpunkte", "9", "Effektiver Wert."),),
        workload=(
            ReviewItem(
                "Peak-RAM und Laufzeit",
                "unbekannt · Pilotmessung erforderlich",
                "Keine erfundene Prognose.",
            ),
        ),
        warnings=("Produktionsskalierung ist nicht validiert.",),
        scientific_boundary="Kein Atlas wurde gestartet.",
    )

    window._review_succeeded(review)
    application.processEvents()

    assert window.page_stack.currentIndex() == 1
    assert window.rail_steps[1].objectName() == "stepActive"
    assert "Käfer Atlas" in window.review_summary_label.text()
    assert "Kein Atlas" in window.review_boundary_label.text()
    parameter_rows = window.findChild(QWidget, "parameterReview")
    workload_rows = window.findChild(QWidget, "workloadReview")
    assert parameter_rows is not None
    assert workload_rows is not None
    assert "Kontrollpunkte" in parameter_rows.findChildren(QLabel)[0].text()
    assert "unbekannt" in workload_rows.findChildren(QLabel)[0].text()
    assert "Produktionsskalierung" in window.review_warnings_label.text()
    assert window.show_run_button.isEnabled() is True
    window._show_run_page()
    assert window.page_stack.currentIndex() == 2
    assert window.rail_steps[2].objectName() == "stepActive"
    assert "a" * 64 in window.run_summary_label.text()
    assert window.start_atlas_button.isEnabled() is True
    window._show_review_page()
    assert window.page_stack.currentIndex() == 1
    window._show_setup_page()
    assert window.page_stack.currentIndex() == 0
    window.close()
    application.processEvents()


def test_desktop_window_keeps_reference_compute_route_explicitly_unavailable(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-reference-test"])
    window = DiffeoForgeWindow()
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=tmp_path / "atlas.yaml",
        config_sha256="b" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="Reference boundary",
    )

    window._review_succeeded(review)
    window._show_run_page()

    assert window.page_stack.currentIndex() == 1
    assert window.show_run_button.isEnabled() is False
    assert "noch nicht verbunden" in window.show_run_button.text()
    window.close()
    application.processEvents()


def test_desktop_window_renders_exact_modern_progress_event(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent
    from diffeoforge.modern_progress import ModernOptimizerProgress, ModernProgressEvent

    application = QApplication.instance() or QApplication(["diffeoforge-progress-test"])
    window = DiffeoForgeWindow()
    progress = ModernProgressEvent(
        sequence=7,
        phase="optimization",
        status="decision",
        message="Momenta block accepted",
        completed_stages=4,
        optimizer=ModernOptimizerProgress(
            completed_decisions=1,
            maximum_decisions=6,
            cycle=1,
            max_cycles=2,
            block="momenta",
            status="accepted",
            objective=12.5,
            attachment=10.0,
            regularity=2.5,
            gradient_norm=0.25,
            accepted_step_size=0.01,
            line_search_evaluations=2,
        ),
    )
    event = DesktopWorkerEvent(
        request_id="desktop-test",
        sequence=2,
        kind="progress",
        payload={"modern_progress": progress.as_dict()},
    )

    window._atlas_event(event)

    assert window.run_progress_bar.value() == 4
    assert window.run_progress_bar.maximum() == 7
    assert "Momenta block accepted" in window.run_stage_label.text()
    assert "Entscheidung 1 von 6" in window.run_optimizer_label.text()
    assert "Objective 12.5" in window.run_optimizer_label.text()
    assert "#2 progress" in window.run_event_log.toPlainText()
    window.close()
    application.processEvents()


def test_atlas_qt_worker_queues_cancel_before_thread_run(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from diffeoforge.desktop.widgets import _AtlasWorker
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent

    event = DesktopWorkerEvent(
        request_id="desktop-test",
        sequence=0,
        kind="started",
        payload={
            "engine": "modern_cpu",
            "config_sha256": "c" * 64,
            "destination": str(Path.cwd() / "result"),
            "cancellation": "cooperative_safe_points",
        },
    )

    class FakeController:
        state = "idle"

        def __init__(self) -> None:
            self.cancel_calls = 0

        def request_cancel(self) -> bool:
            self.cancel_calls += 1
            return True

        def run(self, *, event_callback):
            self.state = "running"
            event_callback(event)
            self.state = "cancelled"
            return object()

    controller = FakeController()
    worker = _AtlasWorker(controller)  # type: ignore[arg-type]

    assert worker.request_cancel() is True
    assert worker.request_cancel() is False
    worker.run()

    assert controller.cancel_calls == 1


def test_desktop_window_starts_bound_worker_and_shows_only_reconciled_result(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _AtlasWorker
    from diffeoforge.desktop.worker_controller import DesktopWorkerControllerResult
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent, DesktopWorkerRequest

    application = QApplication.instance() or QApplication(["diffeoforge-run-test"])
    config = (tmp_path / "modern-atlas.yaml").resolve()
    config.write_text("reviewed\n", encoding="utf-8")
    destination = (tmp_path / "modern-result").resolve()
    request = DesktopWorkerRequest(
        request_id="desktop-bound",
        config_path=config,
        destination=destination,
        expected_config_sha256="d" * 64,
    )
    review = ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name="Bound run",
        config_path=config,
        config_sha256="d" * 64,
        report_path=tmp_path / "workload.html",
        report_label="Modern-Workload-Report",
        subject_count=5,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="boundary",
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.build_reviewed_worker_request",
        lambda review, request_id: request,
    )
    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._review_succeeded(review)
    window._show_run_page()

    window._start_atlas()

    assert len(queued) == 1
    assert isinstance(window._worker, _AtlasWorker)
    assert window.start_atlas_button.isEnabled() is False
    assert window.cancel_atlas_button.isEnabled() is True
    assert "desktop-bound" in window.run_summary_label.text()
    window._cancel_atlas()
    assert window.cancel_atlas_button.isEnabled() is False
    assert "nächsten sicheren Punkt" in window.run_state_label.text()
    assert window.close() is False
    assert window._close_after_worker is True
    assert "Fenster bleibt" in window.run_state_label.text()

    terminal = DesktopWorkerEvent(
        request_id="desktop-bound",
        sequence=1,
        kind="completed",
        payload={
            "destination": str(destination),
            "manifest_sha256": "e" * 64,
            "subject_count": 5,
            "bundle_path": "result-bundle/manifest.json",
        },
    )
    window._atlas_succeeded(
        DesktopWorkerControllerResult(
            request_id="desktop-bound",
            exit_code=0,
            terminal_event=terminal,
            events=(terminal,),
            stderr="",
        )
    )

    assert window.run_result_card.isHidden() is False
    assert "unabhängig verifiziert" in window.run_state_label.text()
    assert "Probanden: 5" in window.run_result_label.text()
    assert window.start_atlas_button.isEnabled() is False
    application.processEvents()
