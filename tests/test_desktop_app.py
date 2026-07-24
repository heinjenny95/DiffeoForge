from __future__ import annotations

import csv
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.desktop.app import build_parser
from diffeoforge.mesh import read_vtk_polydata

ROOT = Path(__file__).parents[1]


def _write_desktop_landmarks(path: Path) -> Path:
    mesh_directory = ROOT / "examples" / "synthetic" / "meshes"
    meshes = [
        mesh_directory / "template.vtk",
        *sorted(mesh_directory.glob("subject-*.vtk")),
    ]
    labels = ("anterior", "dorsal", "posterior")
    indices = (0, 40, 80)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in meshes:
            vertices = read_vtk_polydata(mesh).vertices
            for label, index in zip(labels, indices, strict=True):
                writer.writerow((mesh.name, label, *vertices[index]))
    return path


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
    evidence_bytes = serialize_reference_preparation_reconciliation_verification(evidence)
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
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from diffeoforge.desktop.app import build_parser; "
            "assert build_parser().parse_args([]).smoke is False; "
            "assert 'PySide6' not in sys.modules",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert args.smoke is False
    assert completed.returncode == 0, completed.stderr


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
        image.pixel(x, y) != background for y in range(image.height()) for x in range(image.width())
    )
    assert non_background > 100
    application.processEvents()


def test_desktop_window_exposes_required_project_controls(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QLineEdit,
        QPushButton,
        QSpinBox,
    )

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-desktop-test"])
    window = DiffeoForgeWindow()

    assert window.windowTitle() == "DiffeoForge Desktop"
    assert window.findChild(QLineEdit, "meshDirectoryEdit") is not None
    assert window.findChild(QLineEdit, "projectDirectoryEdit") is not None
    assert window.findChild(QComboBox, "engineCombo") is not None
    assert window.findChild(QComboBox, "unitsCombo") is not None
    assert window.findChild(QComboBox, "pairwiseEvaluationCombo") is not None
    assert window.findChild(QComboBox, "optimizationEffortCombo") is not None
    landmark_count = window.findChild(QSpinBox, "landmarkCountSpin")
    assert landmark_count is not None
    assert landmark_count.minimum() == 3
    assert landmark_count.maximum() > 10
    assert landmark_count.value() == 3
    auto_advance = window.findChild(QCheckBox, "autoAdvanceLandmarkMeshCheck")
    assert auto_advance is not None
    assert auto_advance.isChecked() is True
    assert "next mesh" in auto_advance.text()
    assert window.place_landmarks_button.text().startswith("Place landmarks")
    assert window.create_button.isEnabled() is False
    assert all(isinstance(step, QPushButton) for step in window.rail_steps)
    assert window.rail_steps[0].isEnabled() is True
    assert all(step.isEnabled() is False for step in window.rail_steps[1:])
    assert window.rail_steps[3].accessibleName() == "Go to step 4: Results & PCA"
    assert "CPU/float64" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is True
    assert window.procrustes_box.isHidden() is True
    assert window.pairwise_combo.isEnabled() is True
    assert window.optimization_effort_combo.isEnabled() is True
    assert "small pilot" in window.pairwise_combo.currentText()
    assert window.optimization_effort_combo.currentData() == 3
    assert "three-cycle cap" in window.optimization_effort_hint.text()
    window.optimization_effort_combo.setCurrentIndex(1)
    assert window._request().max_cycles == 50
    assert "does not guarantee convergence" in window.optimization_effort_hint.text()
    window.pairwise_combo.setCurrentIndex(1)
    assert "bounds one pairwise allocation" in window.pairwise_hint.text()
    blockwise_request = window._request()
    assert blockwise_request.pairwise_mode == "blockwise"
    assert blockwise_request.query_tile_size == 256
    assert blockwise_request.source_tile_size == 256
    window.engine_combo.setCurrentIndex(1)
    application.processEvents()
    assert "Deformetrica 4.3" in window.engine_hint.text()
    assert window.landmarks_edit.isEnabled() is True
    window.landmarks_edit.setText("landmarks.csv")
    application.processEvents()
    assert window.procrustes_box.isHidden() is False
    assert window._request().landmarks_file == Path("landmarks.csv")
    assert window.preview_procrustes_button.isEnabled() is True
    assert window.approve_procrustes_check.isEnabled() is False
    window.procrustes_scale_check.setChecked(False)
    window.procrustes_reflection_check.setChecked(True)
    window.procrustes_tolerance_spin.setValue(0.00000001)
    window.procrustes_iterations_spin.setValue(250)
    procrustes_request = window._request()
    assert procrustes_request.procrustes_scale_to_unit_centroid_size is False
    assert procrustes_request.procrustes_allow_reflection is True
    assert procrustes_request.procrustes_tolerance == pytest.approx(0.00000001)
    assert procrustes_request.procrustes_max_iterations == 250
    window.procrustes_apply_check.setChecked(False)
    assert window._request().landmarks_file is None
    assert window.procrustes_scale_check.isEnabled() is False
    assert window.preview_procrustes_button.isEnabled() is False
    window.procrustes_apply_check.setChecked(True)
    assert window.pairwise_box.isHidden() is True
    assert window.optimization_effort_box.isHidden() is True
    assert window.reference_parameter_box.isHidden() is False
    assert window.reference_parameter_profile_combo.currentData() == "pending"
    assert window.reference_attachment_ratio_spin.isHidden() is True
    assert window.analyze_reference_parameters_button.isEnabled() is False
    assert window.already_gpa_check.isEnabled() is False
    window.reference_parameter_profile_combo.setCurrentIndex(
        window.reference_parameter_profile_combo.findData("advanced")
    )
    attachment_field = window._reference_parameter_field(window.reference_attachment_ratio_spin)
    attachment_label = window.reference_parameter_form.labelForField(attachment_field)
    assert attachment_label is not None
    assert "Attachment kernel width" in attachment_label.text()
    assert "template diagonal" in window.reference_attachment_ratio_spin.suffix()
    window.reference_attachment_ratio_spin.setValue(0.035)
    window.reference_max_iterations_spin.setValue(345)
    advanced_request = window._request()
    assert advanced_request.reference_parameter_profile == "advanced"
    assert advanced_request.reference_parameter_ratios["attachment_kernel_width"] == pytest.approx(
        0.035
    )
    assert advanced_request.reference_max_iterations == 345
    assert window.reference_expert_box.isHidden() is True
    window.reference_expert_toggle.setChecked(True)
    application.processEvents()
    assert window.reference_expert_box.isHidden() is False
    window.reference_attachment_type_combo.setCurrentIndex(
        window.reference_attachment_type_combo.findData("varifold")
    )
    window.reference_timepoints_spin.setValue(19)
    window.reference_rk2_check.setChecked(True)
    window.reference_sobolev_check.setChecked(False)
    assert window.reference_sobolev_ratio_spin.isEnabled() is False
    window.reference_threads_spin.setValue(8)
    window.reference_random_seed_spin.setValue(123)
    expert_request = window._request()
    assert expert_request.reference_attachment_type == "varifold"
    assert expert_request.reference_timepoints == 19
    assert expert_request.reference_use_rk2 is True
    assert expert_request.reference_use_sobolev_gradient is False
    assert expert_request.reference_threads == 8
    assert expert_request.reference_random_seed == 123
    assert window._request().pairwise_mode == "dense"
    window.close()
    application.processEvents()


def test_desktop_passes_landmark_plan_to_editor(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialog

    import diffeoforge.desktop.widgets as widgets_module
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-landmark-plan-test"])
    observed: dict[str, object] = {}

    class FakeLandmarkEditor:
        def __init__(
            self,
            mesh_paths,
            output_path,
            parent,
            *,
            initial_landmark_count,
            auto_advance_mesh,
        ) -> None:
            observed["mesh_paths"] = mesh_paths
            observed["output_path"] = output_path
            observed["parent"] = parent
            observed["initial_landmark_count"] = initial_landmark_count
            observed["auto_advance_mesh"] = auto_advance_mesh
            self.output_path = output_path
            self.labels = [f"LM{index}" for index in range(1, initial_landmark_count + 1)]
            self.auto_advance_mesh_check = QCheckBox()
            self.auto_advance_mesh_check.setChecked(auto_advance_mesh)

        @staticmethod
        def exec():
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(
        widgets_module,
        "LandmarkEditorDialog",
        FakeLandmarkEditor,
    )
    window = DiffeoForgeWindow()
    window.mesh_edit.setText(str(ROOT / "examples" / "synthetic" / "meshes"))
    window.project_edit.setText(str(tmp_path / "project"))
    window.landmark_count_spin.setValue(7)
    window.landmark_auto_advance_check.setChecked(False)

    window._place_landmarks()

    assert observed["initial_landmark_count"] == 7
    assert observed["auto_advance_mesh"] is False
    assert len(observed["mesh_paths"]) >= 2  # type: ignore[arg-type]
    assert observed["output_path"] == (tmp_path / "project" / "landmarks.csv")
    window.close()
    application.processEvents()


def test_desktop_requires_exact_procrustes_preview_approval_and_rejects_drift(
    monkeypatch,
    tmp_path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog

    import diffeoforge.desktop.widgets as widgets_module
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import (
        DiffeoForgeWindow,
        _ProcrustesPreviewWorker,
        _ProcrustesVisualWorker,
        _ProjectWorker,
        _ReferenceParameterWorker,
    )

    application = QApplication.instance() or QApplication(["diffeoforge-procrustes-preview-test"])
    mesh_directory = ROOT / "examples" / "synthetic" / "meshes"
    landmarks = _write_desktop_landmarks(tmp_path / "landmarks.csv")
    project_directory = tmp_path / "project"
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    class FakeSignal:
        @staticmethod
        def connect(_callback) -> None:
            return None

    class FakeVisualReviewDialog:
        def __init__(self, preview, visual, parent) -> None:
            assert visual.fingerprint == preview.fingerprint
            assert parent is window
            self.previewInvalidated = FakeSignal()
            self.reviewed_fingerprint = preview.fingerprint
            self.viewed_mesh_count = 3

        @staticmethod
        def exec():
            return QDialog.DialogCode.Accepted

    window = DiffeoForgeWindow()
    monkeypatch.setattr(
        widgets_module,
        "GpaAlignmentReviewDialog",
        FakeVisualReviewDialog,
    )
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.engine_combo.setCurrentIndex(
        window.engine_combo.findData(DesktopEngine.DEFORMETRICA_REFERENCE)
    )
    window.mesh_edit.setText(str(mesh_directory))
    window.project_edit.setText(str(project_directory))
    window.units_combo.setCurrentIndex(window.units_combo.findData("unitless"))
    window.landmarks_edit.setText(str(landmarks))
    application.processEvents()

    assert window.create_button.isEnabled() is False
    assert window.create_button.text() == "Preview & approve alignment first"
    assert window.preview_procrustes_button.isEnabled() is True
    window.preview_procrustes_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], _ProcrustesPreviewWorker)
    assert window.create_button.isEnabled() is False

    queued[0].run()
    application.processEvents()

    assert window._procrustes_preview is not None
    assert window._procrustes_preview.alignment.converged is True
    assert window.review_procrustes_visual_button.isEnabled() is True
    assert window.approve_procrustes_check.isEnabled() is False
    assert window.create_button.text() == "Complete visual GPA review first"
    preview_report = window.procrustes_preview_status_label
    assert preview_report.isReadOnly() is True
    assert preview_report.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert preview_report.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert "Final mean change" in preview_report.text()
    assert "fingerprint" in preview_report.text()
    assert "does not establish biological landmark quality." in preview_report.text()
    preview_report.resize(360, preview_report.height())
    application.processEvents()
    assert preview_report.verticalScrollBar().maximum() > 0
    window.review_procrustes_visual_button.click()
    assert len(queued) == 2
    assert isinstance(queued[1], _ProcrustesVisualWorker)
    queued[1].run()
    application.processEvents()
    assert window._procrustes_visual is not None
    assert window._procrustes_visual_reviewed_fingerprint == window._procrustes_preview.fingerprint
    assert window.approve_procrustes_check.isEnabled() is True
    assert "Visual GPA review completed" in preview_report.text()
    assert window.create_button.text() == "Approve reviewed alignment first"
    window.approve_procrustes_check.setChecked(True)
    application.processEvents()

    approved = window._request().approved_procrustes_fingerprint
    assert approved == window._procrustes_preview.fingerprint
    assert window.create_button.isEnabled() is False
    assert window.create_button.text() == "Analyze aligned meshes or choose manual parameters"
    assert window.analyze_reference_parameters_button.isEnabled() is True
    window.analyze_reference_parameters_button.click()
    assert len(queued) == 3
    assert isinstance(queued[2], _ReferenceParameterWorker)
    queued[2].run()
    application.processEvents()

    assert window._reference_recommendation is not None
    assert window.reference_parameter_profile_combo.currentData() == "data_assisted"
    assert "Analyzed 6 aligned meshes" in window.reference_guidance_status_label.text()
    assert "not inferable from geometry" in window.reference_guidance_status_label.text()
    assert "attachment KW (matching detail)" in (window.reference_effective_widths_label.text())
    original_effective_text = window.reference_effective_widths_label.text()
    window.reference_parameter_profile_combo.setCurrentIndex(
        window.reference_parameter_profile_combo.findData("advanced")
    )
    window.reference_attachment_ratio_spin.setValue(0.075)
    assert window.reference_effective_widths_label.text() != original_effective_text
    assert window.create_button.isEnabled() is True
    assert window.create_button.text() == "Validate data & create project"

    rows = landmarks.read_text(encoding="utf-8").splitlines()
    changed = rows[-1].split(",")
    changed[2] = str(float(changed[2]) + 0.001)
    rows[-1] = ",".join(changed)
    landmarks.write_text("\n".join(rows) + "\n", encoding="utf-8")
    window._create_project()
    assert len(queued) == 4
    assert isinstance(queued[3], _ProjectWorker)
    queued[3].run()
    application.processEvents()

    assert not (project_directory / "atlas.yaml").exists()
    assert "approved preview" in window.status_label.text()
    assert window._procrustes_preview is None
    assert window.approve_procrustes_check.isChecked() is False
    assert "invalidated" in window.procrustes_preview_status_label.text()

    window.procrustes_tolerance_spin.setValue(0.00000001)
    application.processEvents()
    assert window._procrustes_preview is None
    assert window.approve_procrustes_check.isChecked() is False
    assert window._request().approved_procrustes_fingerprint is None
    assert window.create_button.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_analyzes_user_declared_gpa_meshes_before_project_creation(
    monkeypatch,
    tmp_path,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import (
        DiffeoForgeWindow,
        _ReferenceParameterWorker,
    )

    application = QApplication.instance() or QApplication(
        ["diffeoforge-declared-gpa-guidance-test"]
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.engine_combo.setCurrentIndex(
        window.engine_combo.findData(DesktopEngine.DEFORMETRICA_REFERENCE)
    )
    window.mesh_edit.setText(str(ROOT / "examples" / "synthetic" / "meshes"))
    window.project_edit.setText(str(tmp_path / "project"))
    window.units_combo.setCurrentIndex(window.units_combo.findData("unitless"))
    window.already_gpa_check.setChecked(True)
    application.processEvents()

    assert window.analyze_reference_parameters_button.isEnabled() is True
    assert window.create_button.isEnabled() is False
    window.reference_surface_detail_combo.setCurrentIndex(
        window.reference_surface_detail_combo.findData("fine")
    )
    window.reference_deformation_scale_combo.setCurrentIndex(
        window.reference_deformation_scale_combo.findData("local")
    )
    window.analyze_reference_parameters_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], _ReferenceParameterWorker)
    queued[0].run()
    application.processEvents()

    recommendation = window._reference_recommendation
    assert recommendation is not None
    assert recommendation.alignment_basis == "declared_gpa"
    assert recommendation.surface_detail_intent == "fine"
    assert recommendation.deformation_scale_intent == "local"
    assert window._request().reference_parameter_recommendation == (recommendation.provenance)
    assert window.create_button.isEnabled() is True
    assert "cannot prove homologous alignment" in (window.reference_guidance_status_label.text())
    window.reference_deformation_scale_combo.setCurrentIndex(
        window.reference_deformation_scale_combo.findData("global")
    )
    application.processEvents()
    assert window._reference_recommendation is None
    assert window.reference_parameter_profile_combo.currentData() == "pending"
    assert window.create_button.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_project_overwrite_requires_explicit_confirmation(monkeypatch, tmp_path) -> None:
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
    assert window.create_button.text() == "Continue to parameter review"
    assert [step.isEnabled() for step in window.rail_steps] == [True, True, True, False]
    window.rail_steps[0].click()
    assert window.page_stack.currentIndex() == 0
    window.rail_steps[1].click()
    assert window.page_stack.currentIndex() == 1
    window.rail_steps[2].click()
    assert window.page_stack.currentIndex() == 2
    assert window.rail_steps[2].objectName() == "stepActive"
    assert window.run_technical_details.isHidden() is True
    window.run_technical_toggle.click()
    assert window.run_technical_details.isHidden() is False
    window.run_technical_toggle.click()
    assert window.run_technical_details.isHidden() is True
    assert "a" * 64 in window.run_summary_label.text()
    assert window.start_atlas_button.isEnabled() is True
    window._show_review_page()
    assert window.page_stack.currentIndex() == 1
    window._show_setup_page()
    assert window.page_stack.currentIndex() == 0
    window.close()
    application.processEvents()


def test_desktop_window_keeps_reference_compute_locked_until_automatic_setup_check(
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
    assert "Checking Deformetrica setup automatically" in window.show_run_button.text()
    assert window.reference_readiness_card.isHidden() is False
    assert window.reference_preparation_status_card.isHidden() is True
    assert window.refresh_reference_readiness_button.isEnabled() is True
    assert window.refresh_reference_preparation_status_button.isEnabled() is False
    assert window.export_reference_preparation_status_button.isEnabled() is False
    assert "automatic Deformetrica setup check" in (window.reference_readiness_status_label.text())
    assert "not an estimate of atlas computation time" in (
        window.reference_readiness_detail_label.text()
    )
    window.close()
    application.processEvents()


def test_desktop_verifies_saved_reference_status_without_a_project(monkeypatch, tmp_path) -> None:
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
    assert window.export_saved_reference_status_verification_button.isEnabled() is False
    window._choose_saved_reference_status_report()
    window.saved_reference_status_hash_edit.setText(digest)
    application.processEvents()

    assert window.verify_saved_reference_status_button.isEnabled() is True
    window.verify_saved_reference_status_button.click()
    assert len(queued) == 1
    assert isinstance(queued[0], _SavedReferencePreparationStatusVerificationWorker)
    assert window.verify_saved_reference_status_button.isEnabled() is False
    assert "checked read-only" in (window.saved_reference_status_verification_label.text())

    queued[0].run()
    application.processEvents()

    detail = window.saved_reference_status_verification_detail_label.text().replace("\u200b", "")
    assert window._saved_reference_preparation_status_verification is result
    assert "exactly matches" in window.saved_reference_status_verification_label.text()
    assert str(report) in detail
    assert digest in detail
    assert "saved-desktop-001" in detail
    assert "c" * 64 in detail
    assert "Mutation by this verification: no" in detail
    assert "reads no current project" in detail
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert window.export_saved_reference_status_verification_button.isEnabled() is True
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
    assert list(tmp_path.glob("verification-evidence-Käfer.json*")) == [evidence_path]
    assert result.evidence_sha256 in (
        window.saved_reference_status_verification_export_label.text()
    )

    preserved = evidence_path.read_bytes()
    window.export_saved_reference_status_verification_button.click()
    assert evidence_path.read_bytes() == preserved
    assert "not exported" in (window.saved_reference_status_verification_export_label.text())

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
    assert window.export_saved_reference_status_verification_button.isEnabled() is False
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
    assert "Nothing was changed" in (window.saved_reference_status_verification_detail_label.text())
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert window.export_saved_reference_status_verification_button.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_saved_status_verification_failure_is_read_only(monkeypatch, tmp_path) -> None:
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
    assert "cannot be verified safely" in (window.saved_reference_status_verification_label.text())
    assert "No artifact release" in (window.saved_reference_status_verification_detail_label.text())
    assert window.verify_saved_reference_status_button.isEnabled() is True
    assert window.export_saved_reference_status_verification_button.isEnabled() is False
    window.close()
    application.processEvents()


def test_desktop_reference_setup_check_starts_automatically_and_unlocks_execution(
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

    application = QApplication.instance() or QApplication(["diffeoforge-reference-readiness-test"])
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
    window._review_worker_succeeded(review)

    assert len(queued) == 1
    assert isinstance(queued[0], _ReferenceReadinessWorker)
    assert window.refresh_reference_readiness_button.isEnabled() is False
    assert "does not start an atlas" in window.reference_readiness_detail_label.text()
    assert "Estimated computation time" in window.reference_readiness_detail_label.text()
    queued[0].run()
    application.processEvents()

    detail = window.reference_readiness_detail_label.text().replace("\u200b", "")
    assert "local-reference:test" in detail
    assert "[PASS] Container command: docker.exe" in detail
    assert "sha256:abc" in detail
    assert "nothing installed" in detail
    assert "is ready" in window.reference_readiness_status_label.text()
    assert window.refresh_reference_readiness_button.isEnabled() is True
    assert window.show_run_button.isEnabled() is True
    assert "supervised Deformetrica execution" in window.show_run_button.text()
    assert window.rail_steps[2].isEnabled() is True
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
            if observed is review and Path(path).resolve() == approval and expected == digest
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


def test_desktop_discards_preparation_status_after_inputs_change(monkeypatch, tmp_path) -> None:
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

    application = QApplication.instance() or QApplication(["diffeoforge-template-preview-test"])
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
    window._project_succeeded(result)
    assert window.create_button.text() == "Review parameters & workload"
    window._review_succeeded(review)
    assert window.create_button.text() == "Continue to parameter review"

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


def test_desktop_window_renders_deformetrica_iteration_and_bounded_eta(
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-reference-progress-test"])
    window = DiffeoForgeWindow()
    event = DesktopReferenceWorkerEvent(
        request_id="reference-test",
        sequence=3,
        kind="progress",
        payload={
            "iteration": 12,
            "maximum_iterations": 100,
            "log_likelihood": -123.5,
            "attachment": -100.0,
            "regularity": -23.5,
            "elapsed_seconds": 3661.0,
            "seconds_per_iteration": 305.0,
            "eta_to_iteration_cap_seconds": 26840.0,
            "estimate_status": "observed_rate_to_iteration_cap",
        },
    )

    window._atlas_event(event)

    assert window.run_progress_bar.value() == 12
    assert window.run_progress_bar.maximum() == 100
    assert "maximum" in window.run_progress_bar.format()
    assert "Iteration 12 of maximum 100" in window.run_optimizer_label.text()
    assert "Elapsed: 1 h 01 min 01 s" in window.run_optimizer_label.text()
    assert "Estimated computation time to maximum: 7 h 27 min 20 s" in (
        window.run_optimizer_label.text()
    )
    assert "not convergence" in window.run_optimizer_label.text()
    assert "#3 progress" in window.run_event_log.toPlainText()
    window.close()
    application.processEvents()


def test_desktop_window_renders_deformetrica_first_iteration_heartbeat(
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-reference-activity-test"])
    window = DiffeoForgeWindow()
    event = DesktopReferenceWorkerEvent(
        request_id="reference-test",
        sequence=4,
        kind="activity",
        payload={
            "state": "computing_first_iteration",
            "elapsed_seconds": 367.0,
            "maximum_iterations": 150,
            "latest_message": "Started estimator: GradientAscent",
            "log_source": "output/reference_info.log",
            "last_iteration": None,
        },
    )

    window._atlas_event(event)

    assert "computing first iteration" in window.run_stage_label.text()
    assert "6 min 07 s elapsed" in window.run_progress_bar.format()
    assert "no complete iteration logged yet" in window.run_optimizer_label.text()
    assert "Started estimator" in window.run_optimizer_label.text()
    assert "#4 activity" in window.run_event_log.toPlainText()
    window.close()
    application.processEvents()


def test_desktop_reference_prelaunch_refresh_retains_visible_run_identity(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-reference-identity-test"])
    config = (tmp_path / "atlas.yaml").resolve()
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=config,
        config_sha256="a" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight report",
        subject_count=5,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="boundary",
    )
    observed_identities = []

    def build(_review, _readiness, *, request_id, run_id):
        observed_identities.append((request_id, run_id))
        return DesktopReferenceLaunchRequest(
            request_id=request_id,
            config_path=config,
            destination=(tmp_path / "runs" / run_id).resolve(),
            run_id=run_id,
            expected_config_sha256="a" * 64,
            launcher_engine="docker",
            launcher_image="reference:test",
        )

    monkeypatch.setattr("diffeoforge.desktop.widgets.build_reference_launch_request", build)
    window = DiffeoForgeWindow()
    window._review = review
    window._reference_readiness = SimpleNamespace(ready=True)  # type: ignore[assignment]

    first = window._refresh_reference_run_readiness(review)
    second = window._refresh_reference_run_readiness(review)

    assert first is not None
    assert second is not None
    assert observed_identities[0] == observed_identities[1]
    assert first.destination == second.destination
    assert str(second.destination).replace("\u200b", "") in (
        window.run_summary_label.text().replace("\u200b", "")
    )
    window.close()
    application.processEvents()


def test_desktop_accepts_only_parent_verified_deformetrica_terminal_result(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_review import ProjectReviewResult
    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.reference_execution_controller import (
        ReferenceExecutionControllerResult,
    )
    from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["diffeoforge-reference-result-test"])
    destination = (tmp_path / "runs" / "reference-001").resolve()
    destination.mkdir(parents=True)
    review = ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name="Reference",
        config_path=(tmp_path / "atlas.yaml").resolve(),
        config_sha256="a" * 64,
        report_path=tmp_path / "preflight.html",
        report_label="Preflight report",
        subject_count=5,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="boundary",
    )
    terminal = DesktopReferenceWorkerEvent(
        request_id="reference-result",
        sequence=7,
        kind="terminal",
        payload={
            "outcome": "completed",
            "destination": str(destination),
            "destination_exists": True,
            "result_sha256": "b" * 64,
            "message": "verified",
        },
    )
    result = ReferenceExecutionControllerResult(
        request_id="reference-result",
        exit_code=0,
        terminal_event=terminal,
        events=(terminal,),
        stderr="",
    )
    window = DiffeoForgeWindow()
    window._review = review

    window._atlas_succeeded(result)

    assert window._run_result is result
    assert window.run_result_card.isHidden() is False
    assert "independently verified" in window.run_state_label.text()
    assert "Outcome: completed" in window.run_result_label.text()
    assert window.start_atlas_button.text().startswith("Verifying Results & PCA")
    assert window.rail_steps[2].isEnabled() is False
    assert window.rail_steps[3].isEnabled() is False
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
    assert window.start_atlas_button.text() == "Atlas computation running…"
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
    assert window.start_atlas_button.isEnabled() is True
    assert window.start_atlas_button.text() == "Continue to Results & PCA"
    assert window.refresh_run_readiness_button.isEnabled() is True
    application.processEvents()


def test_successful_atlas_automatically_starts_verified_results_review(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _ResultReviewWorker
    from diffeoforge.desktop.worker_controller import DesktopWorkerControllerResult
    from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent

    application = QApplication.instance() or QApplication(["diffeoforge-auto-results-test"])
    destination = (tmp_path / "completed-run").resolve()
    destination.mkdir()
    terminal = DesktopWorkerEvent(
        request_id="auto-results",
        sequence=1,
        kind="completed",
        payload={
            "destination": str(destination),
            "manifest_sha256": "e" * 64,
            "subject_count": 5,
            "bundle_path": "result/atlas-bundle/bundle-manifest.json",
        },
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]

    window._atlas_succeeded(
        DesktopWorkerControllerResult(
            request_id="auto-results",
            exit_code=0,
            terminal_event=terminal,
            events=(terminal,),
            stderr="",
        )
    )

    assert isinstance(window._worker, _ResultReviewWorker)
    assert isinstance(queued[-1], _ResultReviewWorker)
    assert "fully reverified" in window.run_state_label.text()
    assert window.start_atlas_button.isEnabled() is False
    assert window.start_atlas_button.text() == "Verifying Results & PCA…"
    window._worker = None
    window.close()
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
    optimizer_plot_path = bundle / "optimizer-convergence.svg"
    primary_plot_path = bundle / "pca-scores.svg"
    secondary_plot_path = bundle / "pca-scores-pc2-pc3.svg"
    workflow_manifest.write_text("workflow\n", encoding="utf-8")
    bundle_manifest.write_text("bundle\n", encoding="utf-8")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600"></svg>\n'
    artifact_path.write_text(svg, encoding="utf-8")
    optimizer_plot_path.write_text(svg, encoding="utf-8")
    primary_plot_path.write_text(svg, encoding="utf-8")
    secondary_plot_path.write_text(svg, encoding="utf-8")
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
    optimizer_plot = ModernResultArtifact(
        key="optimizer-convergence-plot",
        label="Optimizer convergence (SVG)",
        path=optimizer_plot_path,
        kind="svg",
        bytes=optimizer_plot_path.stat().st_size,
        sha256=sha256_file(optimizer_plot_path),
        description="Verified convergence plot.",
    )
    primary_plot = ModernResultArtifact(
        key="pca-score-plot",
        label="PCA scores: PC1 vs PC2 (SVG)",
        path=primary_plot_path,
        kind="svg",
        bytes=primary_plot_path.stat().st_size,
        sha256=sha256_file(primary_plot_path),
        description="Verified first score plot.",
    )
    secondary_plot = ModernResultArtifact(
        key="pca-score-plot-pc2-pc3",
        label="PCA scores: PC2 vs PC3 (SVG)",
        path=secondary_plot_path,
        kind="svg",
        bytes=secondary_plot_path.stat().st_size,
        sha256=sha256_file(secondary_plot_path),
        description="Verified second score plot.",
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
        artifacts=(artifact, optimizer_plot, primary_plot, secondary_plot),
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
    window._sync_ready_state()

    assert window.start_atlas_button.text() == "Continue to Results & PCA"
    assert window.start_atlas_button.isEnabled() is True
    window.start_atlas_button.click()

    assert isinstance(window._worker, _ResultReviewWorker)
    assert isinstance(queued[-1], _ResultReviewWorker)
    assert "fully reverified" in window.run_state_label.text()

    window._result_review_succeeded(review)
    application.processEvents()

    assert window.page_stack.currentIndex() == 3
    assert window.rail_steps[3].objectName() == "stepActive"
    assert [step.isEnabled() for step in window.rail_steps] == [True, False, True, True]
    assert window.rail_steps[3].toolTip() == "Open Results & PCA."
    assert window.start_atlas_button.text() == "Open Results & PCA"
    assert "Käfer-Atlas" in window.result_summary_label.text()
    assert "did not converge" in window.result_completion_label.text()
    assert window.result_completion_label.objectName() == "statusWarning"
    assert "biological validity" in window.result_boundary_label.text()
    result_pca = window.findChild(QWidget, "resultPca")
    assert result_pca is not None
    assert "PC1" in result_pca.findChildren(QLabel)[0].text()
    assert len(window.result_artifact_buttons) == 4
    assert window.result_optimizer_convergence_plot.isHidden() is False
    assert "Verified objective components" in window.result_optimizer_convergence_plot_status.text()
    assert window.result_pca_scree_plot.isHidden() is False
    assert "Verified explained variance" in window.result_pca_scree_plot_status.text()
    assert window.result_pc1_pc2_plot.isHidden() is False
    assert window.result_pc2_pc3_plot.isHidden() is False
    assert "Verified PC1-versus-PC2" in window.result_pc1_pc2_plot_status.text()
    assert "same score matrix" in window.result_pc2_pc3_plot_status.text()

    window._open_result_artifact("pca-scree")

    assert isinstance(window._worker, _ArtifactWorker)
    assert isinstance(queued[-1], _ArtifactWorker)
    assert all(button.isEnabled() is False for button in window.result_artifact_buttons)
    window._artifact_failed("tamper detected")
    assert "not opened" in window.result_status_label.text()
    assert all(button.isEnabled() is True for button in window.result_artifact_buttons)

    window._result_review_succeeded(
        replace(
            review,
            artifacts=(artifact, optimizer_plot, primary_plot),
            pca_pc2_pc3_unavailable_reason=(
                "PC3 is not mathematically available because only two components exist."
            ),
        )
    )
    assert window.result_pc2_pc3_plot.isHidden() is True
    assert window.result_pc2_pc3_plot_status.objectName() == "statusWarning"
    assert "not mathematically available" in window.result_pc2_pc3_plot_status.text()

    window._result_review_succeeded(
        replace(
            review,
            artifacts=(artifact, primary_plot, secondary_plot),
            optimizer_convergence_plot_unavailable_reason=(
                "This result predates the verified optimizer-convergence plot artifact."
            ),
        )
    )
    assert window.result_optimizer_convergence_plot.isHidden() is True
    assert window.result_optimizer_convergence_plot_status.objectName() == "statusWarning"
    assert "predates" in window.result_optimizer_convergence_plot_status.text()

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
    window._result_review_succeeded(
        replace(
            review,
            engine_route="deformetrica_reference",
            optimizer_converged=None,
            optimizer_termination_reason="tolerance_threshold",
            optimizer_cycles_completed=65,
            optimizer_max_cycles=150,
            execution_duration_seconds=1394.469,
        )
    )
    assert window.result_completion_label.objectName() == "statusSuccess"
    assert "numerical tolerance criterion was met" in window.result_completion_label.text()
    assert "last visible logged iteration" in window.result_completion_label.text()
    assert "not proof" in window.result_completion_label.text()
    window._show_run_page_from_results()
    assert window.page_stack.currentIndex() == 2
    window.start_atlas_button.click()
    assert window.page_stack.currentIndex() == 3
    window.close()
    application.processEvents()


def test_desktop_can_select_a_saved_completed_run(monkeypatch, tmp_path) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from diffeoforge.desktop.widgets import DiffeoForgeWindow, _ResultReviewWorker

    application = QApplication.instance() or QApplication(["diffeoforge-open-completed-run-test"])
    project = tmp_path / "study"
    run = project / "diffeoforge-project" / "runs" / "desktop-ref-complete"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        '{"backend":{"id":"deformetrica_reference"}}\n',
        encoding="utf-8",
    )
    (run / "result.json").write_text(
        '{"status":"completed","return_code":0}\n',
        encoding="utf-8",
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(project),
    )
    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]

    assert window.open_completed_run_button.text() == "Open completed run…"
    window.open_completed_run_button.click()
    application.processEvents()

    assert isinstance(window._worker, _ResultReviewWorker)
    assert queued == [window._worker]
    assert window._worker.directory == run.resolve()
    assert window._worker.reference is True
    assert "Reverifying the complete Deformetrica run" in window.status_label.text()
    assert window.open_completed_run_button.isEnabled() is False
    window._completed_result_review_failed("test failure")
    assert window.open_completed_run_button.isEnabled() is True
    assert "full verification failed" in window.status_label.text()
    window.close()
    application.processEvents()
