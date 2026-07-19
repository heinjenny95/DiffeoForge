from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from diffeoforge.desktop.app import build_parser

ROOT = Path(__file__).parents[1]


def test_desktop_ui_source_has_no_german_copy() -> None:
    ui_sources = tuple((ROOT / "src" / "diffeoforge" / "desktop").glob("*.py"))
    forbidden = re.compile(
        r"\b(?:schritt|neues|wähle|daten|prüfen|projekt|auswählen|"
        r"koordinateneinheit|noch|ergebnisse|berechnen|abbrechen|öffnen|"
        r"verworfen|unbekannt|probanden|kanten|punkte|dreiecke|vollständig|"
        r"nichts|keine|nicht|bereit)\b",
        re.IGNORECASE,
    )

    violations: list[str] = []
    for source in ui_sources:
        text = source.read_text(encoding="utf-8")
        if match := forbidden.search(text):
            violations.append(f"{source.name}: {match.group(0)!r}")
        if match := re.search(r"[äöüÄÖÜß]", text):
            violations.append(f"{source.name}: {match.group(0)!r}")

    assert violations == []


def _reference_preparation_status_fixture(
    *,
    config: Path,
    config_sha256: str,
    approval: Path,
    approval_sha256: str,
    destination: Path,
    status: str,
    destination_status: str,
    destination_reason: str,
    manifest_sha256: str | None,
    engine_execution_started: bool | None,
):
    from diffeoforge.desktop.reference_preparation_status import (
        DesktopReferencePreparationStatus,
    )
    from diffeoforge.reference_preparation_reconciliation import (
        CHECKS,
        serialize_reference_preparation_reconciliation,
    )

    plan_fingerprint = "e" * 64
    scientific_boundary = "Read-only engineering status only."
    report = {
        "schema_version": "0.1",
        "status": status,
        "action_required": status == "attention_required",
        "mutation_performed": False,
        "approval_request": {
            "path": str(approval.resolve()),
            "bytes": 3,
            "sha256": approval_sha256,
            "expected_sha256": approval_sha256,
        },
        "approved_plan": {
            "canonical_fingerprint": plan_fingerprint,
            "run_id": "reference-001",
            "destination": str(destination.resolve()),
            "subjects": 8,
            "protected_files": 8,
        },
        "current_plan": {
            "config_path": str(config.resolve()),
            "config_sha256": config_sha256,
            "canonical_fingerprint": plan_fingerprint,
            "exactly_matches_approved": True,
        },
        "destination": {
            "path": str(destination.resolve()),
            "status": destination_status,
            "reason": destination_reason,
            "manifest_sha256": manifest_sha256,
            "engine_execution_started": engine_execution_started,
        },
        "private_stages": [],
        "state_stable_across_observations": True,
        "checks": list(CHECKS),
        "scientific_boundary": scientific_boundary,
    }
    report_bytes = serialize_reference_preparation_reconciliation(report)
    return DesktopReferencePreparationStatus(
        config_path=config.resolve(),
        config_sha256=config_sha256,
        approval_path=approval.resolve(),
        approval_sha256=approval_sha256,
        plan_fingerprint=plan_fingerprint,
        run_id="reference-001",
        status=status,
        action_required=status == "attention_required",
        destination_path=destination.resolve(),
        destination_status=destination_status,
        destination_reason=destination_reason,
        manifest_sha256=manifest_sha256,
        engine_execution_started=engine_execution_started,
        private_stages=(),
        state_stable_across_observations=True,
        mutation_performed=False,
        scientific_boundary=scientific_boundary,
        report_schema_version="0.1",
        report_bytes=report_bytes,
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
    )


def _saved_reference_status_verification_fixture(*, report: Path, digest: str):
    from diffeoforge.desktop.reference_preparation_status_verification import (
        DesktopSavedReferencePreparationStatusVerification,
    )
    from diffeoforge.reference_preparation_reconciliation_verification import (
        CHECKS,
        serialize_reference_preparation_reconciliation_verification,
    )

    scientific_boundary = (
        "Saved artifact only; reads no current project, config, approval, run, "
        "container, or engine state."
    )
    evidence = {
        "schema_version": "0.1",
        "status": "verified_saved_reference_preparation_reconciliation",
        "verifier": {"diffeoforge": "0.0.0.dev0"},
        "report": {
            "path": str(report.resolve()),
            "bytes": 2649,
            "sha256": digest,
            "expected_sha256": digest,
            "schema_version": "0.1",
            "status": "published_prepared_not_executed_verified",
            "action_required": False,
            "mutation_performed": False,
            "state_stable_across_observations": True,
            "matches_deterministic_serialization": True,
        },
        "recorded_observation": {
            "run_id": "saved-desktop-001",
            "approval_sha256": "a" * 64,
            "plan_fingerprint": "b" * 64,
            "destination_status": "verified_prepared_not_executed",
            "manifest_sha256": "c" * 64,
            "engine_execution_started": False,
            "private_stage_count": 0,
        },
        "checks": list(CHECKS),
        "scientific_boundary": scientific_boundary,
    }
    evidence_bytes = serialize_reference_preparation_reconciliation_verification(
        evidence
    )
    return DesktopSavedReferencePreparationStatusVerification(
        report_path=report.resolve(),
        report_byte_count=2649,
        report_sha256=digest,
        expected_report_sha256=digest,
        report_schema_version="0.1",
        report_status="published_prepared_not_executed_verified",
        action_required=False,
        mutation_performed=False,
        state_stable_across_observations=True,
        matches_deterministic_serialization=True,
        run_id="saved-desktop-001",
        approval_sha256="a" * 64,
        plan_fingerprint="b" * 64,
        destination_status="verified_prepared_not_executed",
        manifest_sha256="c" * 64,
        engine_execution_started=False,
        private_stage_count=0,
        verification_schema_version="0.1",
        verification_status="verified_saved_reference_preparation_reconciliation",
        verifier_version="0.0.0.dev0",
        checks=CHECKS,
        scientific_boundary=scientific_boundary,
        evidence_bytes=evidence_bytes,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
    )


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


def test_native_mesh_preview_canvas_renders_non_background_pixels(
    monkeypatch, tmp_path: Path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.mesh_preview import load_mesh_preview
    from diffeoforge.desktop.mesh_preview_widget import MeshPreviewCanvas
    from diffeoforge.mesh import write_vtk_polydata

    source = write_vtk_polydata(
        tmp_path / "template.vtk",
        (
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 3.0),
        ),
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    )
    application = QApplication.instance() or QApplication(["mesh-preview-canvas-test"])
    canvas = MeshPreviewCanvas()
    canvas.resize(420, 300)
    canvas.set_model(load_mesh_preview(source))
    canvas.set_plane("xz")
    image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    canvas.render(image)

    background = QColor("#f7f9f9").rgba()
    non_background = sum(
        image.pixel(x, y) != background
        for y in range(image.height())
        for x in range(image.width())
    )
    assert non_background > 100
    application.processEvents()


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
    assert window.findChild(QComboBox, "pairwiseEvaluationCombo") is not None
    assert window.create_button.isEnabled() is False
    assert "CPU/float64" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is True
    assert window.pairwise_combo.isEnabled() is True
    assert "small pilot" in window.pairwise_combo.currentText()
    window.pairwise_combo.setCurrentIndex(1)
    assert "bounds one pairwise allocation" in window.pairwise_hint.text()
    blockwise_request = window._request()
    assert blockwise_request.pairwise_mode == "blockwise"
    assert blockwise_request.query_tile_size == 256
    assert blockwise_request.source_tile_size == 256
    window.engine_combo.setCurrentIndex(1)
    application.processEvents()
    assert "Deformetrica 4.3" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is False
    assert window.pairwise_combo.isEnabled() is False
    assert window._request().pairwise_mode == "dense"
    window.close()
    application.processEvents()


def test_desktop_project_overwrite_requires_explicit_confirmation(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _ProjectWorker

    application = QApplication.instance() or QApplication(
        ["diffeoforge-overwrite-confirmation-test"]
    )
    project_directory = tmp_path / "existing project"
    project_directory.mkdir()
    config = project_directory / "modern-atlas.yaml"
    original = b"existing generated configuration\n"
    config.write_bytes(original)
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.mesh_edit.setText(str(ROOT / "examples" / "synthetic" / "meshes"))
    window.project_edit.setText(str(project_directory))
    window.units_combo.setCurrentIndex(window.units_combo.findData("unitless"))
    application.processEvents()

    monkeypatch.setattr(window, "_confirm_configuration_overwrite", lambda _path: False)
    window._create_project()

    assert queued == []
    assert window._worker is None
    assert config.read_bytes() == original
    assert "cancelled" in window.status_label.text()
    assert "unchanged" in window.status_label.text()

    monkeypatch.setattr(window, "_confirm_configuration_overwrite", lambda _path: True)
    window._create_project()

    assert len(queued) == 1
    assert isinstance(queued[0], _ProjectWorker)
    assert queued[0].request.overwrite_existing_configuration is True
    assert config.read_bytes() == original
    window.close()
    application.processEvents()


def test_desktop_window_renders_parameter_review_as_second_step(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from diffeoforge.desktop.project_review import ProjectReviewResult, ReviewItem
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reviewed_run import DesktopReviewedRunReadiness
    from diffeoforge.desktop.widgets import DiffeoForgeWindow
    from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest
    from diffeoforge.private_runs import PrivateRunDiscovery

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
    destination = (tmp_path / "modern-result").resolve()
    request = DesktopWorkerRequest(
        request_id="desktop-review",
        config_path=review.config_path,
        destination=destination,
        expected_config_sha256=review.config_sha256,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.check_reviewed_run_readiness",
        lambda *_args, **_kwargs: DesktopReviewedRunReadiness(
            request=request,
            discovery=PrivateRunDiscovery(destination, False, ()),
        ),
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
    assert "not connected yet" in window.show_run_button.text()
    assert window.reference_readiness_card.isHidden() is False
    assert window.reference_preparation_status_card.isHidden() is False
    assert window.refresh_reference_readiness_button.isEnabled() is True
    assert window.refresh_reference_preparation_status_button.isEnabled() is False
    assert window.export_reference_preparation_status_button.isEnabled() is False
    assert "has not been checked" in window.reference_readiness_status_label.text()
    window.close()
    application.processEvents()


def test_desktop_verifies_saved_reference_status_without_a_project(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from diffeoforge.desktop.widgets import (
        DiffeoForgeWindow,
        _SavedReferencePreparationStatusVerificationWorker,
    )

    application = QApplication.instance() or QApplication(
        ["diffeoforge-saved-reference-status-test"]
    )
    report = (tmp_path / "saved-status-Käfer.json").resolve()
    report.write_text("{}\n", encoding="utf-8")
    digest = "d" * 64
    result = _saved_reference_status_verification_fixture(
        report=report,
        digest=digest,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.review_saved_reference_preparation_status",
        lambda path, expected: (
            result
            if Path(path).resolve() == report and expected == digest
            else pytest.fail("wrong saved status verification inputs")
        ),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(report), "JSON-Dateien (*.json)"),
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]

    assert window.page_stack.currentIndex() == 0
    assert window._review is None
    assert window.verify_saved_reference_status_button.isEnabled() is False
    assert (
        window.export_saved_reference_status_verification_button.isEnabled() is False
    )
    window._choose_saved_reference_status_report()
    window.saved_reference_status_hash_edit.setText(digest)
    application.processEvents()

    assert window.verify_saved_reference_status_button.isEnabled() is True
    window.verify_saved_reference_status_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], _SavedReferencePreparationStatusVerificationWorker)
    assert window.verify_saved_reference_status_button.isEnabled() is False
    assert "checked read-only" in (
        window.saved_reference_status_verification_label.text()
    )

    queued[0].run()
    application.processEvents()

    detail = window.saved_reference_status_verification_detail_label.text().replace(
        "\u200b", ""
    )
    assert window._saved_reference_preparation_status_verification is result
    assert "exactly matches" in window.saved_reference_status_verification_label.text()
    assert str(report) in detail
    assert digest in detail
    assert "saved-desktop-001" in detail
    assert "c" * 64 in detail
    assert "Mutation by this verification: no" in detail
    assert "reads no current project" in detail
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert (
        window.export_saved_reference_status_verification_button.isEnabled() is True
    )
    assert window._review is None
    assert window.page_stack.currentIndex() == 0

    evidence_path = tmp_path / "verification-evidence-Käfer.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(evidence_path), "JSON-Dateien (*.json)"),
    )
    window.export_saved_reference_status_verification_button.click()

    assert evidence_path.read_bytes() == result.evidence_bytes
    assert list(tmp_path.glob("verification-evidence-Käfer.json*")) == [
        evidence_path
    ]
    assert result.evidence_sha256 in (
        window.saved_reference_status_verification_export_label.text()
    )

    preserved = evidence_path.read_bytes()
    window.export_saved_reference_status_verification_button.click()
    assert evidence_path.read_bytes() == preserved
    assert "not exported" in (
        window.saved_reference_status_verification_export_label.text()
    )

    drift_path = tmp_path / "must-not-exist-verification.json"

    def change_saved_inputs_while_dialog_is_open(*_args, **_kwargs):
        window.saved_reference_status_hash_edit.setText("e" * 64)
        return str(drift_path), "JSON-Dateien (*.json)"

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        change_saved_inputs_while_dialog_is_open,
    )
    window.export_saved_reference_status_verification_button.click()
    assert not drift_path.exists()
    assert window._saved_reference_preparation_status_verification is None
    assert "No saved" in window.saved_reference_status_verification_label.text()
    assert (
        window.export_saved_reference_status_verification_button.isEnabled() is False
    )
    window.close()
    application.processEvents()


def test_desktop_discards_saved_status_verification_after_inputs_change(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-saved-reference-status-stale-test"]
    )
    report = (tmp_path / "saved-status.json").resolve()
    report.write_text("{}\n", encoding="utf-8")
    digest = "f" * 64
    result = _saved_reference_status_verification_fixture(
        report=report,
        digest=digest,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.review_saved_reference_preparation_status",
        lambda *_args, **_kwargs: result,
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.saved_reference_status_report_edit.setText(str(report))
    window.saved_reference_status_hash_edit.setText(digest)
    window.verify_saved_reference_status_button.click()
    window.saved_reference_status_hash_edit.setText("0" * 64)
    queued[0].run()
    application.processEvents()

    assert window._saved_reference_preparation_status_verification is None
    assert "discarded" in window.saved_reference_status_verification_label.text()
    assert "Nothing was changed" in (
        window.saved_reference_status_verification_detail_label.text()
    )
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert (
        window.export_saved_reference_status_verification_button.isEnabled() is False
    )
    window.close()
    application.processEvents()


def test_desktop_saved_status_verification_failure_is_read_only(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-saved-reference-status-failure-test"]
    )
    report = (tmp_path / "invalid-saved-status.json").resolve()
    report.write_text("{}\n", encoding="utf-8")
    before = report.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.saved_reference_status_report_edit.setText(str(report))
    window.saved_reference_status_hash_edit.setText(digest)
    window.verify_saved_reference_status_button.click()
    queued[0].run()
    application.processEvents()

    assert report.read_bytes() == before
    assert window._saved_reference_preparation_status_verification is None
    assert "cannot be verified safely" in (
        window.saved_reference_status_verification_label.text()
    )
    assert "No artifact release" in (
        window.saved_reference_status_verification_detail_label.text()
    )
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert (
        window.export_saved_reference_status_verification_button.isEnabled() is False
    )
    window.close()
    application.processEvents()


def test_desktop_reference_environment_check_is_read_only_and_keeps_start_locked(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reference_readiness import DesktopReferenceReadiness
    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _ReferenceReadinessWorker
    from diffeoforge.diagnostics import DoctorCheck, DoctorReport

    application = QApplication.instance() or QApplication(
        ["diffeoforge-reference-readiness-test"]
    )
    config = (tmp_path / "atlas.yaml").resolve()
    config.write_text("reviewed\n", encoding="utf-8")
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=config,
        config_sha256="c" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="Reference boundary",
    )
    report = DoctorReport(
        status="ready",
        workspace=str(tmp_path.resolve()),
        engine="docker",
        image="local-reference:test",
        checks=(
            DoctorCheck("container_cli", "Container command", "pass", "docker.exe"),
            DoctorCheck(
                "reference_image",
                "Reference image",
                "pass",
                "sha256:abc",
            ),
        ),
    )
    readiness = DesktopReferenceReadiness(
        config_path=config,
        config_sha256=review.config_sha256,
        workspace=tmp_path.resolve(),
        engine="docker",
        image="local-reference:test",
        report=report,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.check_reference_environment",
        lambda observed: readiness if observed is review else pytest.fail("wrong review"),
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._review_succeeded(review)

    window.refresh_reference_readiness_button.click()

    assert len(queued) == 1
    assert isinstance(queued[0], _ReferenceReadinessWorker)
    assert window.refresh_reference_readiness_button.isEnabled() is False
    assert "No reference run" in window.reference_readiness_detail_label.text()
    queued[0].run()
    application.processEvents()

    detail = window.reference_readiness_detail_label.text().replace("\u200b", "")
    assert "local-reference:test" in detail
    assert "[PASS] Container command: docker.exe" in detail
    assert "sha256:abc" in detail
    assert "nothing installed" in detail
    assert "is ready" in window.reference_readiness_status_label.text()
    assert window.refresh_reference_readiness_button.isEnabled() is True
    assert window.show_run_button.isEnabled() is False
    assert "not connected yet" in window.show_run_button.text()
    assert window.page_stack.currentIndex() == 1
    window.close()
    application.processEvents()


def test_desktop_reference_preparation_status_is_read_only_and_keeps_start_locked(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import (
        DiffeoForgeWindow,
        _ReferencePreparationStatusWorker,
    )

    application = QApplication.instance() or QApplication(
        ["diffeoforge-reference-preparation-status-test"]
    )
    config = (tmp_path / "atlas.yaml").resolve()
    config.write_text("reviewed\n", encoding="utf-8")
    approval = (tmp_path / "approval.json").resolve()
    approval.write_text("{}\n", encoding="utf-8")
    digest = "d" * 64
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=config,
        config_sha256="c" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="Reference boundary",
    )
    destination = (tmp_path / "runs" / "reference-001").resolve()
    status = _reference_preparation_status_fixture(
        config=config,
        config_sha256=review.config_sha256,
        approval=approval,
        approval_sha256=digest,
        destination=destination,
        status="published_prepared_not_executed_verified",
        destination_status="verified_prepared_not_executed",
        destination_reason="Exact prepared bytes verified.",
        manifest_sha256="f" * 64,
        engine_execution_started=False,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.review_reference_preparation_status",
        lambda observed, path, expected: (
            status
            if observed is review
            and Path(path).resolve() == approval
            and expected == digest
            else pytest.fail("wrong preparation status inputs")
        ),
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._review_succeeded(review)
    window.reference_preparation_approval_edit.setText(str(approval))
    window.reference_preparation_hash_edit.setText(digest)
    application.processEvents()

    assert window.refresh_reference_preparation_status_button.isEnabled() is True
    window.refresh_reference_preparation_status_button.click()

    assert len(queued) == 1
    assert isinstance(queued[0], _ReferencePreparationStatusWorker)
    assert window.refresh_reference_preparation_status_button.isEnabled() is False
    queued[0].run()
    application.processEvents()

    detail = window.reference_preparation_detail_label.text().replace("\u200b", "")
    assert "fully verified" in window.reference_preparation_status_label.text()
    assert "Mutation by this check: no" in detail
    assert "Engine execution started: no" in detail
    assert "f" * 64 in detail
    assert status.report_sha256 in detail
    assert window._reference_preparation_status is status
    assert window.export_reference_preparation_status_button.isEnabled() is True

    export_path = tmp_path / "reviewed-status-Käfer.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(export_path), "JSON-Dateien (*.json)"),
    )
    window.export_reference_preparation_status_button.click()

    assert export_path.read_bytes() == status.report_bytes
    assert list(tmp_path.glob("reviewed-status-Käfer.json*")) == [export_path]
    assert status.report_sha256 in window.reference_preparation_export_label.text()
    assert "Private provenance" in window.reference_preparation_export_label.text()

    preserved = export_path.read_bytes()
    window.export_reference_preparation_status_button.click()
    assert export_path.read_bytes() == preserved
    assert "not exported" in window.reference_preparation_export_label.text()
    assert window.export_reference_preparation_status_button.isEnabled() is True

    drift_path = tmp_path / "must-not-exist.json"

    def change_inputs_while_dialog_is_open(*_args, **_kwargs):
        window.reference_preparation_hash_edit.setText("9" * 64)
        return str(drift_path), "JSON-Dateien (*.json)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", change_inputs_while_dialog_is_open)
    window.export_reference_preparation_status_button.click()
    assert not drift_path.exists()
    assert window._reference_preparation_status is None
    assert window.export_reference_preparation_status_button.isEnabled() is False
    assert "discarded" in window.reference_preparation_export_label.text()
    assert window.show_run_button.isEnabled() is False
    assert window.page_stack.currentIndex() == 1
    window.close()
    application.processEvents()


def test_desktop_discards_preparation_status_after_inputs_change(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-reference-preparation-stale-test"]
    )
    config = (tmp_path / "atlas.yaml").resolve()
    config.write_text("reviewed\n", encoding="utf-8")
    approval = (tmp_path / "approval.json").resolve()
    approval.write_text("{}\n", encoding="utf-8")
    digest = "a" * 64
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=config,
        config_sha256="b" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="Reference boundary",
    )
    status = _reference_preparation_status_fixture(
        config=config,
        config_sha256=review.config_sha256,
        approval=approval,
        approval_sha256=digest,
        destination=(tmp_path / "runs" / "reference-001").resolve(),
        status="clear_to_prepare",
        destination_status="absent",
        destination_reason="Destination absent.",
        manifest_sha256=None,
        engine_execution_started=None,
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.review_reference_preparation_status",
        lambda *_args, **_kwargs: status,
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._review_succeeded(review)
    window.reference_preparation_approval_edit.setText(str(approval))
    window.reference_preparation_hash_edit.setText(digest)
    window.refresh_reference_preparation_status_button.click()
    window.reference_preparation_hash_edit.setText("9" * 64)
    queued[0].run()
    application.processEvents()

    assert window._reference_preparation_status is None
    assert "discarded" in window.reference_preparation_status_label.text()
    assert "Nothing was changed" in window.reference_preparation_detail_label.text()
    assert window.refresh_reference_preparation_status_button.isEnabled() is True
    assert window.export_reference_preparation_status_button.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_loads_native_template_preview_without_modifying_source(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.mesh_preview import load_mesh_preview
    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import (
        DesktopEngine,
        ProjectSetupResult,
    )
    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _TemplatePreviewWorker
    from diffeoforge.mesh import write_vtk_polydata

    application = QApplication.instance() or QApplication(
        ["diffeoforge-template-preview-test"]
    )
    template = write_vtk_polydata(
        tmp_path / "template.vtk",
        (
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 3.0),
        ),
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    )
    config = tmp_path / "modern-atlas.yaml"
    config.write_text("reviewed\n", encoding="utf-8")
    result = ProjectSetupResult(
        engine=DesktopEngine.MODERN_CPU,
        config_path=config,
        template_path=template,
        subject_count=5,
        report_path=None,
        notices=(),
    )
    review = ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name="Preview",
        config_path=config,
        config_sha256="e" * 64,
        report_path=tmp_path / "workload.html",
        report_label="Modern-Workload-Report",
        subject_count=5,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="preview boundary",
    )
    model = load_mesh_preview(template)
    before = template.read_bytes()
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.load_mesh_preview",
        lambda observed: model if observed == template.resolve() else pytest.fail("wrong mesh"),
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._result = result
    window._review_succeeded(review)

    assert window.template_preview_card.isHidden() is False
    assert window.template_preview_plane_combo.isEnabled() is False
    window.refresh_template_preview_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], _TemplatePreviewWorker)
    assert window.refresh_template_preview_button.isEnabled() is False
    queued[0].run()
    application.processEvents()

    assert template.read_bytes() == before
    assert window.template_preview_plane_combo.isEnabled() is True
    assert "XY wireframe" in window.template_preview_status_label.text()
    assert "4 points · 4 triangles · 6 unique edges" in (
        window.template_preview_detail_label.text()
    )
    assert "6 of 6 edges" in window.template_preview_detail_label.text()
    assert "not a 3D" in window.template_preview_detail_label.text()
    window.template_preview_plane_combo.setCurrentIndex(1)
    application.processEvents()
    assert "XZ wireframe" in window.template_preview_status_label.text()
    assert window.show_run_button.isEnabled() is True
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
    assert "decision 1 of 6" in window.run_optimizer_label.text()
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
    from diffeoforge.desktop.reviewed_run import DesktopReviewedRunReadiness
    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _AtlasWorker
    from diffeoforge.desktop.worker_controller import DesktopWorkerControllerResult
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent, DesktopWorkerRequest
    from diffeoforge.private_runs import PrivateRunDiscovery

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
    readiness_checks = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    def readiness(_review, *, request_id):
        readiness_checks.append(request_id)
        return DesktopReviewedRunReadiness(
            request=request,
            discovery=PrivateRunDiscovery(destination, False, ()),
        )

    monkeypatch.setattr("diffeoforge.desktop.widgets.check_reviewed_run_readiness", readiness)
    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._review_succeeded(review)
    window._show_run_page()

    window._start_atlas()

    assert len(readiness_checks) == 2
    assert len(queued) == 1
    assert isinstance(window._worker, _AtlasWorker)
    assert window.start_atlas_button.isEnabled() is False
    assert window.cancel_atlas_button.isEnabled() is True
    assert window.refresh_run_readiness_button.isEnabled() is False
    assert "desktop-bound" in window.run_summary_label.text()
    assert "Destination is free" in window.run_readiness_status_label.text()
    assert "read only" in window.run_readiness_detail_label.text()
    window._cancel_atlas()
    assert window.cancel_atlas_button.isEnabled() is False
    assert "next safe point" in window.run_state_label.text()
    assert window.close() is False
    assert window._close_after_worker is True
    assert "window will remain" in window.run_state_label.text()

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
    assert "independently verified" in window.run_state_label.text()
    assert "Subjects: 5" in window.run_result_label.text()
    assert window.start_atlas_button.isEnabled() is False
    assert window.refresh_run_readiness_button.isEnabled() is True
    application.processEvents()


def test_desktop_window_blocks_private_candidate_before_worker_launch(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reviewed_run import DesktopReviewedRunReadiness
    from diffeoforge.desktop.widgets import DiffeoForgeWindow
    from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest
    from diffeoforge.private_runs import PrivateRunCandidate, PrivateRunDiscovery

    application = QApplication.instance() or QApplication(["diffeoforge-private-state-test"])
    config = (tmp_path / "modern-atlas.yaml").resolve()
    config.write_text("reviewed\n", encoding="utf-8")
    destination = (tmp_path / "modern-result").resolve()
    private = tmp_path / f".{destination.name}.tmp-{'a' * 32}"
    request = DesktopWorkerRequest(
        request_id="desktop-blocked",
        config_path=config,
        destination=destination,
        expected_config_sha256="d" * 64,
    )
    review = ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name="Blocked run",
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
    candidate = PrivateRunCandidate(
        path=private,
        status="abandoned",
        reason="No process holds the valid private-run lease; explicit review is required.",
    )
    readiness = DesktopReviewedRunReadiness(
        request=request,
        discovery=PrivateRunDiscovery(destination, False, (candidate,)),
    )
    current_readiness = [readiness]
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.check_reviewed_run_readiness",
        lambda *_args, **_kwargs: current_readiness[0],
    )
    window = DiffeoForgeWindow()
    window._review_succeeded(review)

    window._show_run_page()
    window._start_atlas()

    assert window._worker is None
    assert window.start_atlas_button.isEnabled() is False
    assert window.refresh_run_readiness_button.isEnabled() is True
    assert "blocked" in window.run_readiness_status_label.text()
    assert "[abandoned]" in window.run_readiness_detail_label.text()
    assert str(private) in window.run_readiness_detail_label.text().replace("\u200b", "")
    assert "nothing deleted" in window.run_readiness_detail_label.text()
    assert "No worker started" in window.run_state_label.text()

    current_readiness[0] = DesktopReviewedRunReadiness(
        request=request,
        discovery=PrivateRunDiscovery(destination, False, ()),
    )
    window.refresh_run_readiness_button.click()
    assert window._worker is None
    assert window.start_atlas_button.isEnabled() is True
    assert "Destination is free" in window.run_readiness_status_label.text()
    application.processEvents()


def test_desktop_window_verifies_and_renders_step_four_before_artifact_handoff(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from diffeoforge.desktop.result_review import (
        ModernResultArtifact,
        ModernResultReview,
        ResultReviewItem,
    )
    from diffeoforge.desktop.widgets import (
        DiffeoForgeWindow,
        _ArtifactWorker,
        _ResultReviewWorker,
    )
    from diffeoforge.desktop.worker_controller import DesktopWorkerControllerResult
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent, sha256_file

    application = QApplication.instance() or QApplication(["diffeoforge-results-test"])
    run = (tmp_path / "run").resolve()
    bundle = run / "bundle"
    bundle.mkdir(parents=True)
    workflow_manifest = run / "workflow-manifest.json"
    bundle_manifest = bundle / "bundle-manifest.json"
    artifact_path = bundle / "pca-scree.svg"
    workflow_manifest.write_text("workflow\n", encoding="utf-8")
    bundle_manifest.write_text("bundle\n", encoding="utf-8")
    artifact_path.write_text("<svg/>\n", encoding="utf-8")
    item = ResultReviewItem("Projekt", "Käfer-Atlas", "Manifestierter Wert.")
    artifact = ModernResultArtifact(
        key="pca-scree",
        label="PCA-Screeplot (SVG)",
        path=artifact_path,
        kind="svg",
        bytes=artifact_path.stat().st_size,
        sha256=sha256_file(artifact_path),
        description="Statisches SVG.",
    )
    review = ModernResultReview(
        run_directory=run,
        bundle_directory=bundle,
        project_name="Käfer-Atlas",
        created_at="2026-07-17T12:00:00+00:00",
        workflow_manifest_path=workflow_manifest,
        workflow_manifest_sha256=sha256_file(workflow_manifest),
        bundle_manifest_path=bundle_manifest,
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        optimizer_converged=False,
        optimizer_termination_reason="max_cycles",
        optimizer_cycles_completed=3,
        optimizer_max_cycles=3,
        overview=(item,),
        optimization=(
            ResultReviewItem(
                "Terminierung",
                "max_cycles · converged=false",
                "Technischer Zustand, keine biologische Validität.",
            ),
        ),
        pca=(ResultReviewItem("PC1", "75%", "Vorzeichen ist konventionell."),),
        quality=(ResultReviewItem("Output-QC", "9 Meshes", "Recomputet."),),
        artifacts=(artifact,),
        scientific_boundaries=("No biological validity claim is made.",),
    )
    terminal = DesktopWorkerEvent(
        request_id="desktop-results",
        sequence=1,
        kind="completed",
        payload={
            "destination": str(run),
            "manifest_sha256": "f" * 64,
            "subject_count": 5,
            "bundle_path": "bundle/bundle-manifest.json",
        },
    )
    result = DesktopWorkerControllerResult(
        request_id="desktop-results",
        exit_code=0,
        terminal_event=terminal,
        events=(terminal,),
        stderr="",
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window._run_result = result

    window._review_run_result()

    assert isinstance(window._worker, _ResultReviewWorker)
    assert isinstance(queued[-1], _ResultReviewWorker)
    assert "fully reverified" in window.run_state_label.text()

    window._result_review_succeeded(review)
    application.processEvents()

    assert window.page_stack.currentIndex() == 3
    assert window.rail_steps[3].objectName() == "stepActive"
    assert "Käfer-Atlas" in window.result_summary_label.text()
    assert "did not converge" in window.result_completion_label.text()
    assert window.result_completion_label.objectName() == "statusWarning"
    assert "biological validity" in window.result_boundary_label.text()
    result_pca = window.findChild(QWidget, "resultPca")
    assert result_pca is not None
    assert "PC1" in result_pca.findChildren(QLabel)[0].text()
    assert len(window.result_artifact_buttons) == 1

    window._open_result_artifact("pca-scree")

    assert isinstance(window._worker, _ArtifactWorker)
    assert isinstance(queued[-1], _ArtifactWorker)
    assert window.result_artifact_buttons[0].isEnabled() is False
    window._artifact_failed("tamper detected")
    assert "not opened" in window.result_status_label.text()
    assert window.result_artifact_buttons[0].isEnabled() is True

    window._result_review_succeeded(
        replace(
            review,
            optimizer_converged=True,
            optimizer_termination_reason="gradient_tolerance",
            optimizer_cycles_completed=2,
        )
    )
    assert window.result_completion_label.objectName() == "statusSuccess"
    assert "optimizer converged" in window.result_completion_label.text()
    window._show_run_page_from_results()
    assert window.page_stack.currentIndex() == 2
    window.close()
    application.processEvents()
