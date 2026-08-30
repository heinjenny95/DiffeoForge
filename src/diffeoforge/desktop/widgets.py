"""PySide6 widgets for the first DiffeoForge Desktop vertical slice."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.config import load_config
from diffeoforge.desktop.aspect_svg_widget import AspectRatioSvgWidget
from diffeoforge.desktop.calibration_comparison_widget import (
    CalibrationComparisonCanvas3D,
)
from diffeoforge.desktop.completed_results import (
    CompletedResultDiscoveryError,
    CompletedResultRun,
    discover_completed_results,
)
from diffeoforge.desktop.feature_scale_dialog import FeatureScaleRulerDialog
from diffeoforge.desktop.gpa_review_dialog import GpaAlignmentReviewDialog
from diffeoforge.desktop.gpa_visualization import (
    GpaAlignmentVisual,
    build_gpa_alignment_visual,
)
from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog
from diffeoforge.desktop.mesh_preview import (
    DEFAULT_EDGE_BUDGET,
    MeshPreviewError,
    MeshPreviewModel,
    load_mesh_preview,
)
from diffeoforge.desktop.mesh_preview_widget import MeshPreviewCanvas
from diffeoforge.desktop.parameter_guidance import (
    DEFORMETRICA_PARAMETER_GUIDANCE,
    ParameterGuidance,
)
from diffeoforge.desktop.project_review import ProjectReviewResult, review_project
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    ProjectSetupResult,
    create_project,
)
from diffeoforge.desktop.reference_calibration_dialog import (
    ReferenceCalibrationDialog,
)
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerError,
    ReferenceExecutionControllerResult,
)
from diffeoforge.desktop.reference_prelaunch import (
    DesktopReferenceLaunchRequest,
    DesktopReferencePrelaunchError,
    build_reference_launch_request,
    build_reference_resume_launch_request,
)
from diffeoforge.desktop.reference_preparation_status import (
    DesktopReferencePreparationStatus,
    DesktopReferencePreparationStatusError,
    DesktopReferencePreparationStatusExportError,
    export_reference_preparation_status_report,
    review_reference_preparation_status,
)
from diffeoforge.desktop.reference_preparation_status_verification import (
    DesktopSavedReferencePreparationStatusVerification,
    DesktopSavedReferencePreparationStatusVerificationError,
    DesktopSavedReferencePreparationStatusVerificationExportError,
    export_saved_reference_preparation_status_verification,
    review_saved_reference_preparation_status,
)
from diffeoforge.desktop.reference_readiness import (
    DesktopReferenceReadiness,
    DesktopReferenceReadinessError,
    check_reference_environment,
)
from diffeoforge.desktop.reference_result_review import (
    export_registration_qc_review,
    load_registration_qc_draft,
    review_reference_result,
    save_registration_qc_draft,
)
from diffeoforge.desktop.reference_validation_dialog import ReferenceValidationDialog
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.desktop.remote_atlas_controller import (
    DesktopRemoteAtlasController,
    DesktopRemoteAtlasDeletionController,
    DesktopRemoteAtlasDeletionResult,
    DesktopRemoteAtlasError,
    DesktopRemoteAtlasResult,
    create_desktop_remote_atlas_session,
    verify_desktop_remote_atlas_session,
)
from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    review_modern_result,
    verify_result_artifact,
)
from diffeoforge.desktop.resumable_results import (
    AbandonedReferenceRun,
    RecoveredReferenceRun,
    ResumableReferenceRun,
    ResumableResultDiscoveryError,
    discover_abandoned_reference_runs,
    discover_resumable_reference_runs,
    recover_abandoned_reference_run,
)
from diffeoforge.desktop.reviewed_run import (
    DesktopReviewedRemoteRunReadiness,
    DesktopReviewedRunError,
    DesktopReviewedRunReadiness,
    check_reviewed_remote_run_readiness,
    check_reviewed_run_readiness,
)
from diffeoforge.desktop.worker_controller import (
    DesktopWorkerController,
    DesktopWorkerControllerError,
    DesktopWorkerControllerResult,
)
from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent
from diffeoforge.initialization import SUPPORTED_UNITS, detect_template
from diffeoforge.mesh import sha256_file
from diffeoforge.preprocessing import (
    LandmarkAlignmentPreview,
    preview_landmark_alignment,
)
from diffeoforge.reference_calibration import (
    PilotSubjectDeclaration,
    ReferenceCalibrationPlan,
    build_reference_calibration_plan,
    read_pilot_subject_declarations,
    reference_calibration_plan_from_provenance,
)
from diffeoforge.reference_calibration_report import (
    CalibrationPlanExport,
    export_reference_calibration_plan,
)
from diffeoforge.reference_calibration_study import (
    create_reference_calibration_study,
    load_reference_calibration_study,
)
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    verify_reference_pca_bundle,
)
from diffeoforge.reference_pca_deformations import (
    DEFAULT_DIRECTORY_NAME as DEFAULT_REFERENCE_PCA_DEFORMATION_DESIGN_DIRECTORY,
)
from diffeoforge.reference_pca_deformations import (
    DEFAULT_RESULT_DIRECTORY as DEFAULT_REFERENCE_PCA_DEFORMATION_RESULT_DIRECTORY,
)
from diffeoforge.reference_pca_deformations import (
    ReferencePCADeformationError,
    create_reference_pca_deformation_design,
    execute_reference_pca_deformation_design,
    verify_reference_pca_deformation_design,
    verify_reference_pca_deformation_result,
)
from diffeoforge.reference_recommendation import (
    ReferenceParameterRecommendation,
    recommend_reference_parameters,
)
from diffeoforge.reference_runtime import launcher_label
from diffeoforge.reference_validation_study import (
    create_reference_validation_study,
    load_reference_validation_study,
)
from diffeoforge.result_report import collect_run_report
from diffeoforge.surface_io import (
    SUPPORTED_SURFACE_EXTENSIONS,
    is_supported_surface_path,
)

_SURFACE_FILE_FILTER = (
    "Supported surface meshes (*.vtk *.ply *.obj *.stl);;"
    "Legacy VTK PolyData (*.vtk);;PLY meshes (*.ply);;"
    "Wavefront OBJ meshes (*.obj);;STL meshes (*.stl)"
)
_DEFAULT_SURFACE_PATTERNS = {f"*{extension}" for extension in SUPPORTED_SURFACE_EXTENSIONS}

_STYLE = """
QMainWindow { background: #f4f7f8; }
QWidget { color: #17252a; font-size: 14px; }
QFrame#rail { background: #123b3a; border: 0; }
QLabel#brandMark { background: #54c6a1; color: #0b302f; border-radius: 18px;
                   font-size: 17px; font-weight: 800; }
QLabel#brand { color: #ffffff; font-size: 20px; font-weight: 700; }
QLabel#railCaption { color: #b9d1cd; font-size: 12px; }
QPushButton#stepActive, QPushButton#stepAvailable, QPushButton#stepFuture {
    background: transparent; border: 0; border-radius: 6px; min-height: 20px;
    padding: 10px 6px; text-align: left;
}
QPushButton#stepActive { color: #ffffff; font-weight: 700; }
QPushButton#stepActive:disabled { color: #ffffff; }
QPushButton#stepAvailable { color: #c9dedb; font-weight: 500; }
QPushButton#stepAvailable:hover { background: #1b4b49; color: #ffffff; }
QPushButton#stepFuture { color: #789b97; font-weight: 400; }
QPushButton#stepFuture:disabled { color: #789b97; }
QLabel#eyebrow { color: #167c6b; font-size: 12px; font-weight: 700; }
QLabel#title { color: #123b3a; font-size: 30px; font-weight: 750; }
QLabel#subtitle { color: #526b70; font-size: 15px; }
QFrame#boundary { background: #e8f4f0; border: 1px solid #b7dcd2; border-radius: 10px; }
QLabel#boundaryText { color: #245b52; padding: 3px; }
QFrame#card { background: #ffffff; border: 1px solid #dbe4e6; border-radius: 12px; }
QFrame#resultPlotPanel { background: #f7f9f9; border: 1px solid #dbe4e6; border-radius: 8px; }
QFrame#footer { background: #ffffff; border-top: 1px solid #dbe4e6; }
QLabel#sectionTitle { color: #123b3a; font-size: 17px; font-weight: 700; }
QLabel#hint { color: #64777c; font-size: 12px; }
QLabel#conceptDifference {
    background: #eaf7f4; border: 1px solid #9bd5c8; border-radius: 8px;
    color: #123b3a; padding: 12px;
}
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #bdcbce; border-radius: 6px;
                      min-height: 34px; padding: 2px 9px; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #268f7a; }
QComboBox#primaryChoice {
    background: #e5f5ed; border: 2px solid #167c6b; color: #123b3a;
    font-weight: 700;
}
QPushButton { border-radius: 6px; min-height: 34px; padding: 2px 13px; font-weight: 600; }
QPushButton#secondary { background: #eef3f4; border: 1px solid #c8d5d7; color: #24474b; }
QPushButton#parameterHelpButton {
    background: transparent; border: 0; color: #167c6b; min-height: 24px;
    padding: 2px 1px; text-align: left; font-size: 12px; font-weight: 650;
}
QPushButton#parameterHelpButton:hover { color: #0f5f52; text-decoration: underline; }
QPushButton#infoDisclosureButton {
    background: transparent; border: 0; color: #167c6b; min-height: 25px;
    padding: 2px 1px; text-align: left; font-size: 12px; font-weight: 700;
}
QPushButton#infoDisclosureButton:hover { color: #0f5f52; text-decoration: underline; }
QFrame#infoDisclosurePanel {
    background: #f2f8f6; border: 1px solid #cee3dd; border-radius: 7px;
}
QLabel#infoDisclosureText { color: #405d61; font-size: 12px; }
QFrame#parameterHelpPanel {
    background: #f2f8f6; border: 1px solid #cee3dd; border-radius: 7px;
}
QTextBrowser#parameterHelpText {
    background: transparent; border: 0; color: #405d61; font-size: 12px;
    padding: 0;
}
QPushButton#primary { background: #167c6b; border: 1px solid #167c6b; color: #ffffff;
                      min-height: 42px; padding: 2px 20px; }
QPushButton#primary:hover { background: #116858; }
QPushButton#primary:disabled { background: #a9bdb9; border-color: #a9bdb9; }
QPushButton#danger { background: #fff0ed; border: 1px solid #d98a7d; color: #8d3025; }
QLabel#status, QPlainTextEdit#status {
    background: #f2f5f6; border-radius: 7px; color: #526b70; padding: 10px;
}
QLabel#statusSuccess, QPlainTextEdit#statusSuccess {
    background: #e5f5ed; border-radius: 7px; color: #176345; padding: 10px;
}
QLabel#statusWarning, QPlainTextEdit#statusWarning {
    background: #fff7df; border-radius: 7px; color: #765500; padding: 10px;
}
QLabel#statusError, QPlainTextEdit#statusError {
    background: #fff0ed; border-radius: 7px; color: #a13a2d; padding: 10px;
}
QLabel#tradeoffLegend {
    background: #eef3f4; border-radius: 7px; color: #526b70; padding: 8px;
    font-size: 12px;
}
QLabel#tradeoffFavorable {
    background: #e5f5ed; border: 1px solid #b7dcca; border-radius: 7px;
    color: #176345; padding: 9px;
}
QLabel#tradeoffCaution {
    background: #fff7df; border: 1px solid #e8cf86; border-radius: 7px;
    color: #765500; padding: 9px;
}
QLabel#tradeoffUnfavorable {
    background: #fff0ed; border: 1px solid #e2aaa1; border-radius: 7px;
    color: #91382e; padding: 9px;
}
QPlainTextEdit#status, QPlainTextEdit#statusSuccess,
QPlainTextEdit#statusWarning, QPlainTextEdit#statusError {
    border: 0; font-family: "Segoe UI"; font-size: 13px;
}
QLabel#reviewValue { color: #123b3a; font-weight: 700; }
QLabel#reviewDetail { color: #526b70; font-size: 12px; }
QProgressBar { border: 1px solid #bdcbce; border-radius: 6px; text-align: center;
               background: #eef3f4; min-height: 26px; }
QProgressBar::chunk { background: #54c6a1; border-radius: 5px; }
QPlainTextEdit { background: #f7f9f9; border: 1px solid #dbe4e6; border-radius: 6px;
                 color: #314f53; font-family: Consolas, monospace; font-size: 12px; }
"""

_PRIVATE_STATUS_EXPLANATIONS = {
    "active": "A process holds the lease; this does not yet prove progress.",
    "abandoned": "The valid lease is free; the private state may be abandoned.",
    "unattributed": "The matching directory lacks a trustworthy marker.",
    "invalid_metadata": "The marker or lease does not satisfy the bound contract.",
    "indeterminate": "Permissions or file-system behavior prevent a safe decision.",
    "unsafe_link": "The matching path is a link and was not followed.",
}


class _ReadOnlyStatusText(QPlainTextEdit):
    """Scrollable status report with the QLabel-compatible API used by the window."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumHeight(150)
        self.setMaximumHeight(190)
        self.setAccessibleName("Alignment preview report")
        self.setToolTip(
            "Read-only GPA diagnostics. Scroll to review the complete report; "
            "the text can also be selected and copied."
        )

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.verticalScrollBar().setValue(0)

    def text(self) -> str:
        return self.toPlainText()


class _ExpandableParameterHelp(QWidget):
    """Accessible disclosure containing guidance for one parameter."""

    def __init__(
        self,
        parameter_name: str,
        guidance: ParameterGuidance,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.parameter_name = parameter_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle_button = QPushButton("ⓘ Parameter info")
        self.toggle_button.setObjectName("parameterHelpButton")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setAccessibleName(f"Explain {parameter_name}")
        self.toggle_button.setAccessibleDescription(guidance.summary)
        self.toggle_button.toggled.connect(self._set_expanded)
        layout.addWidget(self.toggle_button)

        self.panel = QFrame()
        self.panel.setObjectName("parameterHelpPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 7, 10, 7)
        self.text_browser = QTextBrowser()
        self.text_browser.setObjectName("parameterHelpText")
        self.text_browser.setHtml(guidance.to_html())
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.text_browser.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.text_browser.setMinimumHeight(145)
        self.text_browser.setMaximumHeight(210)
        self.text_browser.setAccessibleName(f"{parameter_name} parameter guidance")
        self.text_browser.setToolTip(
            "Scroll inside this panel to read the complete parameter explanation."
        )
        # Compatibility alias used by existing callers and tests.
        self.text_label = self.text_browser
        panel_layout.addWidget(self.text_browser)
        self.panel.hide()
        layout.addWidget(self.panel)

    @Slot(bool)
    def _set_expanded(self, expanded: bool) -> None:
        self.panel.setVisible(expanded)
        self.toggle_button.setText(
            "ⓘ Hide parameter info" if expanded else "ⓘ Parameter info"
        )


class _WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _ProjectWorker(QRunnable):
    def __init__(self, request: ProjectSetupRequest) -> None:
        super().__init__()
        self.request = request
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = create_project(self.request)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(result)


class _ReviewWorker(QRunnable):
    def __init__(self, result: ProjectSetupResult) -> None:
        super().__init__()
        self.result = result
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            review = review_project(self.result.config_path, self.result.engine)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(review)


class _TemplatePreviewWorker(QRunnable):
    """Load one immutable template preview model outside the GUI thread."""

    def __init__(self, template_path: Path) -> None:
        super().__init__()
        self.template_path = template_path
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            model = load_mesh_preview(self.template_path)
        except (MeshPreviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(model)


class _ProcrustesPreviewWorker(QRunnable):
    """Compute one immutable landmark-alignment preview outside the GUI thread."""

    def __init__(
        self,
        *,
        mesh_directory: Path,
        landmarks_file: Path,
        template: Path | None,
        subject_pattern: str,
        scale_to_unit_centroid_size: bool,
        allow_reflection: bool,
        tolerance: float,
        max_iterations: int,
    ) -> None:
        super().__init__()
        self.mesh_directory = mesh_directory
        self.landmarks_file = landmarks_file
        self.template = template
        self.subject_pattern = subject_pattern
        self.scale_to_unit_centroid_size = scale_to_unit_centroid_size
        self.allow_reflection = allow_reflection
        self.tolerance = tolerance
        self.max_iterations = max_iterations
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            preview = preview_landmark_alignment(
                self.mesh_directory,
                landmarks_file=self.landmarks_file,
                template=self.template,
                subject_pattern=self.subject_pattern,
                scale_to_unit_centroid_size=self.scale_to_unit_centroid_size,
                allow_reflection=self.allow_reflection,
                tolerance=self.tolerance,
                max_iterations=self.max_iterations,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(preview)


class _ProcrustesVisualWorker(QRunnable):
    """Build one memory-bounded, hash-bound visual GPA cohort."""

    def __init__(self, preview: LandmarkAlignmentPreview) -> None:
        super().__init__()
        self.preview = preview
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            visual = build_gpa_alignment_visual(self.preview)
        except (MeshPreviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(visual)


class _ReferenceParameterWorker(QRunnable):
    """Analyze one aligned cohort without blocking the Qt event loop."""

    def __init__(
        self,
        *,
        mesh_paths: tuple[Path, ...],
        alignment_basis: str,
        surface_detail_intent: str,
        deformation_scale_intent: str,
        expected_shape_disparity: str,
        transforms: tuple[object, ...] | None,
        alignment_fingerprint: str | None,
    ) -> None:
        super().__init__()
        self.mesh_paths = mesh_paths
        self.alignment_basis = alignment_basis
        self.surface_detail_intent = surface_detail_intent
        self.deformation_scale_intent = deformation_scale_intent
        self.expected_shape_disparity = expected_shape_disparity
        self.transforms = transforms
        self.alignment_fingerprint = alignment_fingerprint
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            recommendation = recommend_reference_parameters(
                self.mesh_paths,
                alignment_basis=self.alignment_basis,
                surface_detail_intent=self.surface_detail_intent,
                deformation_scale_intent=self.deformation_scale_intent,
                expected_shape_disparity=self.expected_shape_disparity,
                transforms=self.transforms,
                alignment_fingerprint=self.alignment_fingerprint,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(recommendation)


class _ReferenceReadinessWorker(QRunnable):
    """Run exact-config external environment diagnostics outside the GUI thread."""

    def __init__(self, review: ProjectReviewResult) -> None:
        super().__init__()
        self.review = review
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            readiness = check_reference_environment(self.review)
        except (
            DesktopReferenceReadinessError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(readiness)


class _ReferencePreparationStatusWorker(QRunnable):
    """Reconcile one approval-bound preparation outside the GUI thread."""

    def __init__(
        self,
        review: ProjectReviewResult,
        approval_path: Path,
        expected_approval_sha256: str,
    ) -> None:
        super().__init__()
        self.review = review
        self.approval_path = approval_path
        self.expected_approval_sha256 = expected_approval_sha256
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            status = review_reference_preparation_status(
                self.review,
                self.approval_path,
                self.expected_approval_sha256,
            )
        except (
            DesktopReferencePreparationStatusError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(status)


class _SavedReferencePreparationStatusVerificationWorker(QRunnable):
    """Verify one saved preparation status artifact outside the GUI thread."""

    def __init__(self, report_path: Path, expected_report_sha256: str) -> None:
        super().__init__()
        self.report_path = report_path
        self.expected_report_sha256 = expected_report_sha256
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = review_saved_reference_preparation_status(
                self.report_path,
                self.expected_report_sha256,
            )
        except (
            DesktopSavedReferencePreparationStatusVerificationError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(result)


class _ResultReviewWorker(QRunnable):
    """Fully verify one completed atlas/PCA workflow outside the GUI thread."""

    def __init__(self, directory: Path, *, reference: bool = False) -> None:
        super().__init__()
        self.directory = directory
        self.reference = reference
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            review = (
                review_reference_result(self.directory)
                if self.reference
                else review_modern_result(self.directory)
            )
        except (ModernResultReviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(review)


class _ReferencePCADeformationWorker(QRunnable):
    """Create, execute, and verify default reference PCA Shooting endpoints."""

    def __init__(self, run_directory: Path) -> None:
        super().__init__()
        self.run_directory = run_directory.expanduser().resolve()
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            bundle = verify_reference_pca_bundle(
                self.run_directory / DEFAULT_REFERENCE_PCA_DIRECTORY,
                source_run=self.run_directory,
            )
            components = min(3, bundle.pca.number_of_components)
            if components < 1:
                raise ReferencePCADeformationError(
                    "Reference PCA has no component available for Shooting"
                )
            design = (
                self.run_directory
                / "analysis"
                / DEFAULT_REFERENCE_PCA_DEFORMATION_DESIGN_DIRECTORY
            )
            if design.exists():
                verify_reference_pca_deformation_design(
                    design,
                    source_run=self.run_directory,
                )
            else:
                create_reference_pca_deformation_design(
                    self.run_directory,
                    design,
                    components=components,
                    standard_deviations=2.0,
                )
            result = execute_reference_pca_deformation_design(
                design,
                self.run_directory / DEFAULT_REFERENCE_PCA_DEFORMATION_RESULT_DIRECTORY,
            )
            verify_reference_pca_deformation_result(
                result,
                source_run=self.run_directory,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(result)


class _AbandonedReferenceRecoveryWorker(QRunnable):
    """Finalize one user-confirmed unclean stop outside the GUI thread."""

    def __init__(self, abandoned: AbandonedReferenceRun) -> None:
        super().__init__()
        self.abandoned = abandoned
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            recovered = recover_abandoned_reference_run(
                self.abandoned,
                reason=(
                    "Desktop recovery after an unclean stop; the user explicitly "
                    "confirmed that no Deformetrica process is still writing to the run."
                ),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(recovered)


class _ArtifactWorker(QRunnable):
    """Recheck one reviewed artifact immediately before handing it to the OS."""

    def __init__(self, review: ModernResultReview, key: str) -> None:
        super().__init__()
        self.review = review
        self.key = key
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            path = verify_result_artifact(self.review, self.key)
        except (ModernResultReviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.succeeded.emit(path)


class _AtlasWorkerSignals(QObject):
    event = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    cancel_failed = Signal(str)


class _AtlasWorker(QRunnable):
    """Run one controller off the GUI thread and bridge validated events to Qt."""

    def __init__(self, controller: DesktopWorkerController) -> None:
        super().__init__()
        self.controller = controller
        self.signals = _AtlasWorkerSignals()
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._finished = False

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished or self._cancel_requested:
                return False
            self._cancel_requested = True
            idle = self.controller.state == "idle"
        if idle:
            return True
        try:
            self.controller.request_cancel()
        except DesktopWorkerControllerError as error:
            self.signals.cancel_failed.emit(str(error))
        return True

    def _forward_event(self, event: DesktopWorkerEvent) -> None:
        with self._lock:
            cancel_requested = self._cancel_requested
        if cancel_requested:
            self.controller.request_cancel()
        self.signals.event.emit(event)

    @Slot()
    def run(self) -> None:
        try:
            result = self.controller.run(event_callback=self._forward_event)
        except DesktopWorkerControllerError as error:
            message = str(error)
            stderr = getattr(error, "stderr", "").strip()
            if stderr:
                message = f"{message}\n\nWorker stderr:\n{stderr}"
            self.signals.failed.emit(message)
        else:
            self.signals.succeeded.emit(result)
        finally:
            with self._lock:
                self._finished = True


class _RemoteAtlasWorker(QRunnable):
    """Bridge one persistent remote controller into the Qt event loop."""

    def __init__(self, controller: DesktopRemoteAtlasController) -> None:
        super().__init__()
        self.controller = controller
        self.signals = _AtlasWorkerSignals()
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._finished = False

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished or self._cancel_requested:
                return False
            self._cancel_requested = True
        return self.controller.request_cancel()

    def request_detach(self) -> bool:
        with self._lock:
            if self._finished:
                return False
        return self.controller.request_detach()

    def _forward_event(self, event: dict[str, object]) -> None:
        self.signals.event.emit(event)

    @Slot()
    def run(self) -> None:
        try:
            result = self.controller.run(event_callback=self._forward_event)
        except DesktopRemoteAtlasError as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(result)
        finally:
            with self._lock:
                self._finished = True


class _RemoteAtlasDeletionWorker(QRunnable):
    """Run one explicit terminal server-copy deletion outside the Qt event loop."""

    def __init__(self, controller: DesktopRemoteAtlasDeletionController) -> None:
        super().__init__()
        self.controller = controller
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.controller.run()
        except DesktopRemoteAtlasError as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(result)


class _ReferenceAtlasWorker(QRunnable):
    """Bridge the contained Deformetrica controller into the Qt event loop."""

    def __init__(self, controller: ReferenceExecutionController) -> None:
        super().__init__()
        self.controller = controller
        self.signals = _AtlasWorkerSignals()
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._finished = False

    def request_cancel(self) -> bool:
        with self._lock:
            if self._finished or self._cancel_requested:
                return False
            self._cancel_requested = True
            idle = self.controller.state == "idle"
        if idle:
            return True
        try:
            self.controller.request_cancel()
        except ReferenceExecutionControllerError as error:
            self.signals.cancel_failed.emit(str(error))
        return True

    def _forward_event(self, event: DesktopReferenceWorkerEvent) -> None:
        with self._lock:
            cancel_requested = self._cancel_requested
        if cancel_requested:
            self.controller.request_cancel()
        self.signals.event.emit(event)

    @Slot()
    def run(self) -> None:
        try:
            result = self.controller.run(event_callback=self._forward_event)
        except ReferenceExecutionControllerError as error:
            message = str(error)
            stderr = getattr(error, "stderr", "").strip()
            if stderr:
                message = f"{message}\n\nWorker stderr:\n{stderr}"
            self.signals.failed.emit(message)
        else:
            self.signals.succeeded.emit(result)
        finally:
            with self._lock:
                self._finished = True


def _path_row(edit: QLineEdit, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


class _FormControlWheelGuard(QObject):
    """Route wheel input over value controls to their containing page."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return super().eventFilter(watched, event)
        if isinstance(watched, QComboBox) and watched.view().isVisible():
            return super().eventFilter(watched, event)

        ancestor = watched.parent()
        while ancestor is not None and not isinstance(ancestor, QScrollArea):
            ancestor = ancestor.parent()
        if not isinstance(ancestor, QScrollArea):
            return super().eventFilter(watched, event)

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            distance = pixel_delta
        else:
            angle_delta = event.angleDelta().y()
            distance = round(
                (angle_delta / 120.0) * max(ancestor.verticalScrollBar().singleStep(), 20) * 3
            )
        if distance:
            bar = ancestor.verticalScrollBar()
            bar.setValue(bar.value() - distance)
        event.accept()
        return True


class DiffeoForgeWindow(QMainWindow):
    """Project creation window backed by the Qt-independent setup service."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("diffeoforgeWindow")
        self.setWindowTitle("DiffeoForge Desktop")
        self.resize(1120, 780)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(_STYLE)
        self._thread_pool = QThreadPool.globalInstance()
        self._worker: (
            _ProjectWorker
            | _ReviewWorker
            | _TemplatePreviewWorker
            | _ProcrustesPreviewWorker
            | _ProcrustesVisualWorker
            | _ReferenceParameterWorker
            | _ReferenceReadinessWorker
            | _ReferencePreparationStatusWorker
            | _SavedReferencePreparationStatusVerificationWorker
            | _ResultReviewWorker
            | _ReferencePCADeformationWorker
            | _AbandonedReferenceRecoveryWorker
            | _ArtifactWorker
            | _AtlasWorker
            | _RemoteAtlasWorker
            | _RemoteAtlasDeletionWorker
            | _ReferenceAtlasWorker
            | None
        ) = None
        self._result: ProjectSetupResult | None = None
        self._review: ProjectReviewResult | None = None
        self._template_preview: MeshPreviewModel | None = None
        self._procrustes_preview: LandmarkAlignmentPreview | None = None
        self._procrustes_visual: GpaAlignmentVisual | None = None
        self._procrustes_visual_reviewed_fingerprint: str | None = None
        self._reference_recommendation: ReferenceParameterRecommendation | None = None
        self._reference_recommendation_paths: tuple[Path, ...] | None = None
        self._reference_calibration_plan: ReferenceCalibrationPlan | None = None
        self._reference_pilot_subject_declarations: tuple[
            PilotSubjectDeclaration, ...
        ] = ()
        self._reference_pilot_declarations_path: Path | None = None
        self._reference_calibration_export: CalibrationPlanExport | None = None
        self._reference_calibration_study_directory: Path | None = None
        self._reference_calibrated_config_path: Path | None = None
        self._guided_reference_calibration_requested = False
        self._template_preview_worker: _TemplatePreviewWorker | None = None
        self._template_preview_scroll_value: int | None = None
        self._reference_readiness: DesktopReferenceReadiness | None = None
        self._reference_preparation_status: DesktopReferencePreparationStatus | None = None
        self._saved_reference_preparation_status_verification: (
            DesktopSavedReferencePreparationStatusVerification | None
        ) = None
        self._run_readiness: (
            DesktopReviewedRunReadiness | DesktopReviewedRemoteRunReadiness | None
        ) = None
        self._reference_run_request: DesktopReferenceLaunchRequest | None = None
        self._run_result: (
            DesktopWorkerControllerResult
            | DesktopRemoteAtlasResult
            | ReferenceExecutionControllerResult
            | None
        ) = None
        self._remote_session_directory: Path | None = None
        self._result_review: ModernResultReview | None = None
        self._reference_pca_deformation_started_at: float | None = None
        self._reference_pca_deformation_timer = QTimer(self)
        self._reference_pca_deformation_timer.setInterval(1_000)
        self._reference_pca_deformation_timer.timeout.connect(
            self._update_reference_pca_deformation_elapsed
        )
        self._registration_qc_decisions: dict[str, str] = {}
        self._result_atlas_mesh_total = 0
        self._result_atlas_mesh_filtered = 0
        self._close_after_worker = False
        self._active_step = 0
        self.reference_parameter_help_panels: dict[str, _ExpandableParameterHelp] = {}
        self._reference_parameter_field_pairs: list[tuple[QWidget, QWidget]] = []
        self._build_ui()
        self._form_control_wheel_guard = _FormControlWheelGuard(self)
        for control_type in (QComboBox, QSpinBox, QDoubleSpinBox):
            for control in self.findChildren(control_type):
                control.installEventFilter(self._form_control_wheel_guard)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_engine_explanation()
        self._sync_ready_state()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_rail())
        data_form_card, parameter_form_card = self._build_form_cards()
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        self.page_stack.addWidget(self._build_setup_content(data_form_card))
        self.page_stack.addWidget(self._build_parameter_content(parameter_form_card))
        self.page_stack.addWidget(self._build_review_content())
        self.page_stack.addWidget(self._build_run_content())
        self.page_stack.addWidget(self._build_results_content())
        root_layout.addWidget(self.page_stack, 1)
        self.setCentralWidget(root)

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(250)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(7)

        brand_row = QHBoxLayout()
        mark = QLabel("DF")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(36, 36)
        brand = QLabel("DiffeoForge")
        brand.setObjectName("brand")
        brand_row.addWidget(mark)
        brand_row.addSpacing(8)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        layout.addLayout(brand_row)
        caption = QLabel("Reproducible surface-atlas workflows")
        caption.setObjectName("railCaption")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        layout.addSpacing(38)

        steps = (
            "1  Data & engine",
            "2  Parameter setting",
            "3  Review parameters",
            "4  Compute atlas",
            "5  Results & PCA",
        )
        self.rail_steps: list[QPushButton] = []
        for index, text in enumerate(steps):
            step_label = text.split("  ", 1)[1]
            button = QPushButton(text.replace("&", "&&"))
            button.setObjectName("stepActive" if index == 0 else "stepFuture")
            button.setProperty("stepLabel", step_label)
            button.setAccessibleName(f"Go to step {index + 1}: {step_label}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, step=index: self._navigate_to_step(step))
            layout.addWidget(button)
            self.rail_steps.append(button)
        layout.addStretch()
        boundary = QLabel("PRE-ALPHA\nNo scientific validation")
        boundary.setObjectName("railCaption")
        boundary.setWordWrap(True)
        layout.addWidget(boundary)
        return rail

    def _build_setup_content(self, data_form_card: QWidget) -> QWidget:
        scroll = QScrollArea()
        self.setup_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("content")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 1 OF 5")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("New atlas project")
        title.setObjectName("title")
        subtitle = QLabel(
            "Select the engine, meshes, coordinate unit, and optional alignment inputs."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        boundary = QFrame()
        boundary.setObjectName("boundary")
        boundary_layout = QHBoxLayout(boundary)
        boundary_layout.setContentsMargins(13, 9, 13, 9)
        boundary_text = QLabel(
            "This step identifies the data and alignment workflow. Parameter analysis, "
            "pilot calibration, and project creation happen together in Step 2."
        )
        boundary_text.setObjectName("boundaryText")
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        layout.addWidget(boundary)
        resume_row = QWidget()
        resume_layout = QHBoxLayout(resume_row)
        resume_layout.setContentsMargins(0, 0, 0, 0)
        resume_layout.setSpacing(10)
        resume_label = QLabel("Returning to an existing analysis?")
        resume_label.setObjectName("hint")
        self.open_completed_run_button = QPushButton("Open completed run…")
        self.open_completed_run_button.setObjectName("secondary")
        self.open_completed_run_button.setToolTip(
            "Select a completed run folder or its DiffeoForge project folder."
        )
        self.open_completed_run_button.clicked.connect(self._select_completed_run)
        self.resume_interrupted_run_button = QPushButton("Resume interrupted run…")
        self.resume_interrupted_run_button.setObjectName("secondary")
        self.resume_interrupted_run_button.setToolTip(
            "Select an interrupted Deformetrica run with a verified checkpoint."
        )
        self.resume_interrupted_run_button.clicked.connect(self._select_interrupted_run)
        self.recover_abandoned_run_button = QPushButton("Recover after crashâ€¦")
        self.recover_abandoned_run_button.setObjectName("secondary")
        self.recover_abandoned_run_button.setToolTip(
            "Finalize a run left nonterminal by a power loss or hard process stop, then "
            "continue a verified checkpoint as a new run."
        )
        self.recover_abandoned_run_button.clicked.connect(self._select_abandoned_run)
        resume_layout.addWidget(resume_label)
        resume_layout.addWidget(self.open_completed_run_button)
        resume_layout.addWidget(self.resume_interrupted_run_button)
        resume_layout.addWidget(self.recover_abandoned_run_button)
        resume_layout.addStretch()
        layout.addWidget(resume_row)
        layout.addWidget(data_form_card)
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(18)
        self.data_status_label = QLabel("Enter a mesh folder, project folder, and coordinate unit.")
        self.data_status_label.setObjectName("status")
        self.data_status_label.setWordWrap(True)
        footer_layout.addWidget(self.data_status_label, 1)
        self.continue_parameter_button = QPushButton("Continue to parameter setting")
        self.continue_parameter_button.setObjectName("primary")
        self.continue_parameter_button.clicked.connect(lambda: self._navigate_to_step(1))
        footer_layout.addWidget(self.continue_parameter_button)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(scroll, 1)
        content_layout.addWidget(footer)
        return content

    def _build_parameter_content(self, parameter_form_card: QWidget) -> QWidget:
        scroll = QScrollArea()
        self.parameter_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("content")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 2 OF 5")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Parameter setting")
        title.setObjectName("title")
        subtitle = QLabel(
            "Analyze the aligned meshes, choose or calibrate engine parameters, "
            "and create the reproducible project configuration."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        boundary = QFrame()
        boundary.setObjectName("boundary")
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.setContentsMargins(13, 9, 13, 9)
        boundary_text = QLabel(
            "Follow the green action. This page prepares parameters; it does not start "
            "the full-cohort atlas."
        )
        boundary_text.setObjectName("boundaryText")
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        boundary_layout.addWidget(
            InfoDisclosure(
                "Workflow details",
                "Analyze the aligned meshes, build the pilot plan, run its candidates, "
                "compare the explained trade-offs, and select an option. Visual "
                "reconstruction QC remains available but is optional.",
            )
        )
        layout.addWidget(boundary)
        layout.addWidget(parameter_form_card)

        self.result_card = self._build_result_card()
        self.result_card.hide()
        layout.addWidget(self.result_card)
        layout.addWidget(self._build_saved_reference_preparation_status_card())
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(12)
        back = QPushButton("Back to data & engine")
        back.setObjectName("secondary")
        back.clicked.connect(self._show_setup_page)
        footer_layout.addWidget(back)
        self.status_label = QLabel("Analyze the aligned meshes before creating the project.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label, 1)
        self.create_button = QPushButton("Validate data & create project")
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self._setup_primary_action)
        footer_layout.addWidget(self.create_button)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(scroll, 1)
        page_layout.addWidget(footer)
        return page

    def _build_reference_calibration_execution_card(self) -> QWidget:
        calibration = QFrame()
        calibration.setObjectName("card")
        calibration_layout = QVBoxLayout(calibration)
        calibration_layout.setContentsMargins(24, 22, 24, 24)
        calibration_layout.setSpacing(10)
        calibration_title = QLabel("3. Run and review the automatic pilot calibration")
        calibration_title.setObjectName("sectionTitle")
        self.reference_calibration_execution_status = QLabel(
            "Complete the aligned-mesh analysis and build the calibration plan first."
        )
        self.reference_calibration_execution_status.setObjectName("status")
        self.reference_calibration_execution_status.setWordWrap(True)
        calibration_detail = QLabel(
            "DiffeoForge creates a provisional starting configuration automatically, "
            "checks the managed Deformetrica installation, and runs every candidate in "
            "the current stage. You can select from the explained pros and cons without "
            "opening every reconstruction. The guided viewer remains available as "
            "optional visual QC, and its status is recorded. The selected values become "
            "the final read-only parameter set shown below."
        )
        calibration_detail.setObjectName("reviewDetail")
        calibration_detail.setWordWrap(True)
        self.open_reference_calibration_button = QPushButton(
            "Prepare & start pilot calibration…"
        )
        self.open_reference_calibration_button.setObjectName("secondary")
        self.open_reference_calibration_button.clicked.connect(
            self._prepare_or_open_reference_calibration
        )
        self.open_reference_calibration_button.setEnabled(False)
        calibration_layout.addWidget(calibration_title)
        calibration_layout.addWidget(self.reference_calibration_execution_status)
        calibration_layout.addWidget(
            InfoDisclosure("What happens during calibration", calibration_detail)
        )
        calibration_layout.addWidget(
            self.open_reference_calibration_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.reference_calibration_execution_card = calibration
        self.reference_calibration_execution_card.hide()
        return calibration

    def _build_saved_reference_preparation_status_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Verify a saved reference status")
        title.setObjectName("sectionTitle")
        self.saved_reference_status_verification_label = QLabel(
            "No saved status report has been verified."
        )
        self.saved_reference_status_verification_label.setObjectName("status")
        self.saved_reference_status_verification_label.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.saved_reference_status_report_edit = QLineEdit()
        self.saved_reference_status_report_edit.setObjectName("savedReferenceStatusReportEdit")
        self.saved_reference_status_report_edit.setPlaceholderText(
            "Previously exported preparation-status JSON report"
        )
        self.saved_reference_status_report_edit.textChanged.connect(
            self._saved_reference_status_inputs_changed
        )
        choose = QPushButton("Browse…")
        choose.setObjectName("secondary")
        choose.clicked.connect(self._choose_saved_reference_status_report)
        form.addRow(
            "Status report",
            _path_row(self.saved_reference_status_report_edit, choose),
        )
        self.saved_reference_status_hash_edit = QLineEdit()
        self.saved_reference_status_hash_edit.setObjectName("savedReferenceStatusHashEdit")
        self.saved_reference_status_hash_edit.setPlaceholderText(
            "Independently recorded SHA-256 of the complete report file"
        )
        self.saved_reference_status_hash_edit.textChanged.connect(
            self._saved_reference_status_inputs_changed
        )
        form.addRow("Report-SHA-256", self.saved_reference_status_hash_edit)

        self.saved_reference_status_verification_detail_label = QLabel(
            "This check reads only the selected report file. It opens no project, YAML, "
            "approval, run, container, or engine state and changes nothing."
        )
        self.saved_reference_status_verification_detail_label.setObjectName("reviewDetail")
        self.saved_reference_status_verification_detail_label.setWordWrap(True)
        self.saved_reference_status_verification_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.verify_saved_reference_status_button = QPushButton("Verify saved report read-only")
        self.verify_saved_reference_status_button.setObjectName("secondary")
        self.verify_saved_reference_status_button.clicked.connect(
            self._verify_saved_reference_status
        )
        self.saved_reference_status_verification_export_label = QLabel(
            "Evidence export is available only after a successful check that remains "
            "bound to the current inputs. The file contains private provenance."
        )
        self.saved_reference_status_verification_export_label.setObjectName("hint")
        self.saved_reference_status_verification_export_label.setWordWrap(True)
        self.saved_reference_status_verification_export_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.export_saved_reference_status_verification_button = QPushButton(
            "Export verified evidence as a new JSON file"
        )
        self.export_saved_reference_status_verification_button.setObjectName("secondary")
        self.export_saved_reference_status_verification_button.clicked.connect(
            self._export_saved_reference_status_verification
        )

        layout.addWidget(title)
        layout.addWidget(self.saved_reference_status_verification_label)
        layout.addLayout(form)
        layout.addWidget(self.saved_reference_status_verification_detail_label)
        layout.addWidget(
            self.verify_saved_reference_status_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(self.saved_reference_status_verification_export_label)
        layout.addWidget(
            self.export_saved_reference_status_verification_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        return card

    def _build_review_content(self) -> QWidget:
        scroll = QScrollArea()
        self.review_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 3 OF 5")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Review parameters and workload")
        title.setObjectName("title")
        subtitle = QLabel(
            "Inspect the stored values and auditable compute operations before any engine starts."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        boundary = QFrame()
        boundary.setObjectName("boundary")
        boundary_layout = QHBoxLayout(boundary)
        boundary_layout.setContentsMargins(13, 9, 13, 9)
        self.review_boundary_label = QLabel()
        self.review_boundary_label.setObjectName("boundaryText")
        self.review_boundary_label.setWordWrap(True)
        boundary_layout.addWidget(self.review_boundary_label)
        layout.addWidget(boundary)

        summary = QFrame()
        summary.setObjectName("card")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(24, 22, 24, 24)
        summary_title = QLabel("Verified project")
        summary_title.setObjectName("sectionTitle")
        self.review_summary_label = QLabel()
        self.review_summary_label.setObjectName("reviewSummary")
        self.review_summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.review_summary_label.setWordWrap(True)
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.review_summary_label)
        layout.addWidget(summary)

        template_preview = QFrame()
        template_preview.setObjectName("card")
        template_preview_layout = QVBoxLayout(template_preview)
        template_preview_layout.setContentsMargins(24, 22, 24, 24)
        template_preview_layout.setSpacing(10)
        template_preview_title = QLabel("Native template preview")
        template_preview_title.setObjectName("sectionTitle")
        self.template_preview_status_label = QLabel(
            "The read-only wireframe preview has not been loaded."
        )
        self.template_preview_status_label.setObjectName("status")
        self.template_preview_status_label.setWordWrap(True)
        self.template_preview_canvas = MeshPreviewCanvas()
        self.template_preview_plane_combo = QComboBox()
        self.template_preview_plane_combo.setObjectName("templatePreviewPlane")
        self.template_preview_plane_combo.addItem("XY · view along Z", "xy")
        self.template_preview_plane_combo.addItem("XZ · view along Y", "xz")
        self.template_preview_plane_combo.addItem("YZ · view along X", "yz")
        self.template_preview_plane_combo.setEnabled(False)
        self.template_preview_plane_combo.currentIndexChanged.connect(
            self._update_template_preview_plane
        )
        self.template_preview_detail_label = QLabel(
            "This projection does not modify the mesh and does not replace 3D inspection, "
            "mesh QC, or landmark picking."
        )
        self.template_preview_detail_label.setObjectName("reviewDetail")
        self.template_preview_detail_label.setWordWrap(True)
        self.template_preview_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_template_preview_button = QPushButton("Load template read-only")
        self.refresh_template_preview_button.setObjectName("secondary")
        self.refresh_template_preview_button.clicked.connect(self._load_template_preview)
        preview_controls = QHBoxLayout()
        preview_controls.addWidget(QLabel("Projection"))
        preview_controls.addWidget(self.template_preview_plane_combo)
        preview_controls.addStretch()
        preview_controls.addWidget(self.refresh_template_preview_button)
        template_preview_layout.addWidget(template_preview_title)
        template_preview_layout.addWidget(self.template_preview_status_label)
        template_preview_layout.addWidget(self.template_preview_canvas)
        template_preview_layout.addLayout(preview_controls)
        template_preview_layout.addWidget(self.template_preview_detail_label)
        self.template_preview_card = template_preview
        self.template_preview_card.hide()
        layout.addWidget(self.template_preview_card)

        layout.addWidget(self._build_review_card("Effective parameters", "parameterReview"))
        self.workload_card = self._build_review_card("Workload evidence", "workloadReview")
        layout.addWidget(self.workload_card)

        reference_readiness = QFrame()
        reference_readiness.setObjectName("card")
        reference_readiness_layout = QVBoxLayout(reference_readiness)
        reference_readiness_layout.setContentsMargins(24, 22, 24, 24)
        reference_readiness_layout.setSpacing(10)
        reference_readiness_title = QLabel("Deformetrica installation & system check")
        reference_readiness_title.setObjectName("sectionTitle")
        self.reference_readiness_status_label = QLabel(
            "The automatic Deformetrica setup check has not started."
        )
        self.reference_readiness_status_label.setObjectName("status")
        self.reference_readiness_status_label.setWordWrap(True)
        self.reference_readiness_detail_label = QLabel(
            "DiffeoForge verifies the installed engine, available memory, and project folder "
            "automatically. This is a safety check, not an estimated computation time."
        )
        self.reference_readiness_detail_label.setObjectName("reviewDetail")
        self.reference_readiness_detail_label.setWordWrap(True)
        self.reference_readiness_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_reference_readiness_button = QPushButton("Check setup again")
        self.refresh_reference_readiness_button.setObjectName("secondary")
        self.refresh_reference_readiness_button.clicked.connect(self._check_reference_readiness)
        reference_readiness_layout.addWidget(reference_readiness_title)
        reference_readiness_layout.addWidget(self.reference_readiness_status_label)
        reference_readiness_layout.addWidget(self.reference_readiness_detail_label)
        reference_readiness_layout.addWidget(
            self.refresh_reference_readiness_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.reference_readiness_card = reference_readiness
        self.reference_readiness_card.hide()
        layout.addWidget(self.reference_readiness_card)

        reference_preparation_status = QFrame()
        reference_preparation_status.setObjectName("card")
        reference_preparation_status_layout = QVBoxLayout(reference_preparation_status)
        reference_preparation_status_layout.setContentsMargins(24, 22, 24, 24)
        reference_preparation_status_layout.setSpacing(10)
        reference_preparation_status_title = QLabel("Approval-bound preparation status")
        reference_preparation_status_title.setObjectName("sectionTitle")
        self.reference_preparation_status_label = QLabel(
            "No approval file has been checked read-only."
        )
        self.reference_preparation_status_label.setObjectName("status")
        self.reference_preparation_status_label.setWordWrap(True)
        preparation_form = QFormLayout()
        preparation_form.setHorizontalSpacing(22)
        preparation_form.setVerticalSpacing(10)
        preparation_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.reference_preparation_approval_edit = QLineEdit()
        self.reference_preparation_approval_edit.setObjectName("referencePreparationApprovalEdit")
        self.reference_preparation_approval_edit.setPlaceholderText(
            "Previously verified preparation-only approval file"
        )
        self.reference_preparation_approval_edit.textChanged.connect(
            self._reference_preparation_inputs_changed
        )
        reference_preparation_approval_button = QPushButton("Browse…")
        reference_preparation_approval_button.setObjectName("secondary")
        reference_preparation_approval_button.clicked.connect(
            self._choose_reference_preparation_approval
        )
        preparation_form.addRow(
            "Approval file",
            _path_row(
                self.reference_preparation_approval_edit,
                reference_preparation_approval_button,
            ),
        )
        self.reference_preparation_hash_edit = QLineEdit()
        self.reference_preparation_hash_edit.setObjectName("referencePreparationHashEdit")
        self.reference_preparation_hash_edit.setPlaceholderText(
            "Independently recorded SHA-256 of the complete approval file"
        )
        self.reference_preparation_hash_edit.textChanged.connect(
            self._reference_preparation_inputs_changed
        )
        preparation_form.addRow(
            "Approval-SHA-256",
            self.reference_preparation_hash_edit,
        )
        self.reference_preparation_detail_label = QLabel(
            "This view checks only the exact approved destination and explicitly named "
            "private stages. It follows no links and changes nothing."
        )
        self.reference_preparation_detail_label.setObjectName("reviewDetail")
        self.reference_preparation_detail_label.setWordWrap(True)
        self.reference_preparation_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_reference_preparation_status_button = QPushButton(
            "Check preparation status read-only"
        )
        self.refresh_reference_preparation_status_button.setObjectName("secondary")
        self.refresh_reference_preparation_status_button.clicked.connect(
            self._check_reference_preparation_status
        )
        self.reference_preparation_export_label = QLabel(
            "Export is available only after a successful check. The complete report contains "
            "absolute paths and file names and must be treated as private provenance."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setWordWrap(True)
        self.reference_preparation_export_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.export_reference_preparation_status_button = QPushButton(
            "Export verified status as a new JSON file"
        )
        self.export_reference_preparation_status_button.setObjectName("secondary")
        self.export_reference_preparation_status_button.clicked.connect(
            self._export_reference_preparation_status
        )
        reference_preparation_status_layout.addWidget(reference_preparation_status_title)
        reference_preparation_status_layout.addWidget(self.reference_preparation_status_label)
        reference_preparation_status_layout.addLayout(preparation_form)
        reference_preparation_status_layout.addWidget(self.reference_preparation_detail_label)
        reference_preparation_status_layout.addWidget(
            self.refresh_reference_preparation_status_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        reference_preparation_status_layout.addWidget(self.reference_preparation_export_label)
        reference_preparation_status_layout.addWidget(
            self.export_reference_preparation_status_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.reference_preparation_status_card = reference_preparation_status
        self.reference_preparation_status_card.hide()
        layout.addWidget(self.reference_preparation_status_card)

        warnings = QFrame()
        warnings.setObjectName("card")
        warnings_layout = QVBoxLayout(warnings)
        warnings_layout.setContentsMargins(24, 22, 24, 24)
        warnings_title = QLabel("Boundaries and notices")
        warnings_title.setObjectName("sectionTitle")
        self.review_warnings_label = QLabel()
        self.review_warnings_label.setObjectName("reviewWarnings")
        self.review_warnings_label.setWordWrap(True)
        self.review_warnings_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        warnings_layout.addWidget(warnings_title)
        warnings_layout.addWidget(self.review_warnings_label)
        layout.addWidget(warnings)
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(12)
        back = QPushButton("Back to parameter setting")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: self._navigate_to_step(1))
        footer_layout.addWidget(back)
        self.open_review_report_button = QPushButton("Open review report")
        self.open_review_report_button.setObjectName("secondary")
        self.open_review_report_button.clicked.connect(self._open_review_report)
        footer_layout.addWidget(self.open_review_report_button)
        footer_layout.addStretch()
        self.show_run_button = QPushButton("Atlas execution continues in Step 4")
        self.show_run_button.setObjectName("primary")
        self.show_run_button.clicked.connect(self._show_run_page)
        self.show_run_button.setEnabled(False)
        footer_layout.addWidget(self.show_run_button)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(scroll, 1)
        page_layout.addWidget(footer)
        return page

    def _build_run_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 4 OF 5")
        eyebrow.setObjectName("eyebrow")
        self.run_title_label = QLabel("Compute atlas")
        self.run_title_label.setObjectName("title")
        self.run_subtitle_label = QLabel(
            "Run the exact reviewed configuration in a separate process and observe real "
            "workflow events."
        )
        self.run_subtitle_label.setObjectName("subtitle")
        self.run_subtitle_label.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(self.run_title_label)
        layout.addWidget(self.run_subtitle_label)

        boundary = QFrame()
        boundary.setObjectName("boundary")
        boundary_layout = QHBoxLayout(boundary)
        boundary_layout.setContentsMargins(13, 9, 13, 9)
        self.run_boundary_label = QLabel(
            "Experimental Modern route. Runtime, peak RAM, and percentage progress are "
            "not estimated. Cancellation acts only at designated safe points and runs are "
            "not currently resumable."
        )
        self.run_boundary_label.setObjectName("boundaryText")
        self.run_boundary_label.setWordWrap(True)
        boundary_layout.addWidget(self.run_boundary_label)
        layout.addWidget(boundary)

        self.execution_location_card = QFrame()
        self.execution_location_card.setObjectName("card")
        execution_location_layout = QVBoxLayout(self.execution_location_card)
        execution_location_layout.setContentsMargins(24, 22, 24, 24)
        execution_location_layout.setSpacing(10)
        execution_location_title = QLabel("Execution location")
        execution_location_title.setObjectName("sectionTitle")
        self.execution_location_combo = QComboBox()
        self.execution_location_combo.addItem("This computer", "local")
        self.execution_location_combo.addItem("Private DiffeoForge server", "remote")
        self.execution_location_combo.currentIndexChanged.connect(
            self._execution_location_changed
        )
        execution_location_layout.addWidget(execution_location_title)
        execution_location_layout.addWidget(self.execution_location_combo)

        self.remote_execution_controls = QWidget()
        remote_form = QFormLayout(self.remote_execution_controls)
        remote_form.setContentsMargins(0, 6, 0, 0)
        remote_form.setSpacing(9)
        self.remote_server_edit = QLineEdit()
        self.remote_server_edit.setPlaceholderText("https://atlas.example.edu:8787")
        self.remote_server_edit.textChanged.connect(self._sync_ready_state)
        remote_form.addRow("Server URL", self.remote_server_edit)
        self.remote_token_edit = QLineEdit()
        self.remote_token_edit.setPlaceholderText("Private bearer-token file")
        self.remote_token_edit.textChanged.connect(self._sync_ready_state)
        remote_token_button = QPushButton("Browse…")
        remote_token_button.setObjectName("secondary")
        remote_token_button.clicked.connect(self._choose_remote_token)
        remote_form.addRow("Token file", _path_row(self.remote_token_edit, remote_token_button))
        self.remote_ca_edit = QLineEdit()
        self.remote_ca_edit.setPlaceholderText("Optional private CA PEM file")
        self.remote_ca_edit.textChanged.connect(self._sync_ready_state)
        remote_ca_button = QPushButton("Browse…")
        remote_ca_button.setObjectName("secondary")
        remote_ca_button.clicked.connect(self._choose_remote_ca)
        remote_form.addRow("TLS CA file", _path_row(self.remote_ca_edit, remote_ca_button))
        self.remote_session_edit = QLineEdit()
        self.remote_session_edit.setPlaceholderText(
            "Optional existing DiffeoForge remote-session folder"
        )
        self.remote_session_edit.textChanged.connect(self._sync_ready_state)
        remote_session_button = QPushButton("Browse…")
        remote_session_button.setObjectName("secondary")
        remote_session_button.clicked.connect(self._choose_remote_session)
        remote_form.addRow(
            "Reconnect session",
            _path_row(self.remote_session_edit, remote_session_button),
        )
        self.remote_upload_authorization = QCheckBox(
            "I authorize uploading the packaged raw meshes and specimen filenames "
            "to this exact private server."
        )
        self.remote_upload_authorization.toggled.connect(self._sync_ready_state)
        remote_form.addRow("", self.remote_upload_authorization)
        self.remote_execution_hint = QLabel(
            "The token is read from the selected file and is never copied into the project "
            "or remote-session folder. Closing this app does not implicitly cancel a server job."
        )
        self.remote_execution_hint.setObjectName("reviewDetail")
        self.remote_execution_hint.setWordWrap(True)
        remote_form.addRow("", self.remote_execution_hint)
        execution_location_layout.addWidget(self.remote_execution_controls)
        self.remote_execution_controls.hide()
        layout.addWidget(self.execution_location_card)

        self.run_technical_toggle = QPushButton("+ Technical details")
        self.run_technical_toggle.setObjectName("secondary")
        self.run_technical_toggle.setCheckable(True)
        self.run_technical_toggle.setAccessibleDescription(
            "Show configuration hashes, destination binding, and runtime installation details."
        )
        self.run_technical_toggle.toggled.connect(self._set_run_technical_details_expanded)
        layout.addWidget(self.run_technical_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.run_technical_details = QWidget()
        run_technical_layout = QVBoxLayout(self.run_technical_details)
        run_technical_layout.setContentsMargins(0, 0, 0, 0)
        run_technical_layout.setSpacing(15)

        summary = QFrame()
        summary.setObjectName("card")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(24, 22, 24, 24)
        summary_title = QLabel("Bound execution")
        summary_title.setObjectName("sectionTitle")
        self.run_summary_label = QLabel()
        self.run_summary_label.setWordWrap(True)
        self.run_summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.run_summary_label)
        run_technical_layout.addWidget(summary)

        readiness = QFrame()
        readiness.setObjectName("card")
        readiness_layout = QVBoxLayout(readiness)
        readiness_layout.setContentsMargins(24, 22, 24, 24)
        readiness_layout.setSpacing(10)
        readiness_title = QLabel("Private destination status before worker start")
        readiness_title.setObjectName("sectionTitle")
        self.run_readiness_status_label = QLabel("Destination status has not been checked.")
        self.run_readiness_status_label.setObjectName("status")
        self.run_readiness_status_label.setWordWrap(True)
        self.run_readiness_detail_label = QLabel(
            "This check is read-only and deletes, renames, publishes, and starts nothing."
        )
        self.run_readiness_detail_label.setObjectName("reviewDetail")
        self.run_readiness_detail_label.setWordWrap(True)
        self.run_readiness_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_run_readiness_button = QPushButton("Check destination status again")
        self.refresh_run_readiness_button.setObjectName("secondary")
        self.refresh_run_readiness_button.clicked.connect(self._refresh_run_readiness)
        readiness_layout.addWidget(readiness_title)
        readiness_layout.addWidget(self.run_readiness_status_label)
        readiness_layout.addWidget(self.run_readiness_detail_label)
        readiness_layout.addWidget(self.refresh_run_readiness_button, 0, Qt.AlignmentFlag.AlignLeft)
        run_technical_layout.addWidget(readiness)
        self.run_technical_details.hide()
        layout.addWidget(self.run_technical_details)

        progress = QFrame()
        progress.setObjectName("card")
        progress_layout = QVBoxLayout(progress)
        progress_layout.setContentsMargins(24, 22, 24, 24)
        progress_layout.setSpacing(10)
        progress_title = QLabel("Verified live events")
        progress_title.setObjectName("sectionTitle")
        self.run_state_label = QLabel("Ready; no worker has started.")
        self.run_state_label.setObjectName("status")
        self.run_state_label.setWordWrap(True)
        self.run_stage_label = QLabel("Workflow stage: not started")
        self.run_stage_label.setObjectName("reviewValue")
        self.run_stage_label.setWordWrap(True)
        self.run_progress_bar = QProgressBar()
        self.run_progress_bar.setRange(0, 7)
        self.run_progress_bar.setValue(0)
        self.run_progress_bar.setFormat("Completed stages: %v of %m")
        self.run_optimizer_label = QLabel("No optimization decision yet.")
        self.run_optimizer_label.setObjectName("reviewDetail")
        self.run_optimizer_label.setWordWrap(True)
        self.run_event_log = QPlainTextEdit()
        self.run_event_log.setObjectName("workerEventLog")
        self.run_event_log.setReadOnly(True)
        self.run_event_log.setMaximumBlockCount(500)
        self.run_event_log.setMaximumHeight(220)
        progress_layout.addWidget(progress_title)
        progress_layout.addWidget(self.run_state_label)
        progress_layout.addWidget(self.run_stage_label)
        progress_layout.addWidget(self.run_progress_bar)
        progress_layout.addWidget(self.run_optimizer_label)
        progress_layout.addWidget(self.run_event_log)
        layout.addWidget(progress)

        self.run_result_card = QFrame()
        self.run_result_card.setObjectName("card")
        result_layout = QVBoxLayout(self.run_result_card)
        result_layout.setContentsMargins(24, 22, 24, 24)
        result_title = QLabel("Independently verified result")
        result_title.setObjectName("sectionTitle")
        self.run_result_label = QLabel()
        self.run_result_label.setWordWrap(True)
        self.run_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_run_result_button = QPushButton("Open result folder")
        self.open_run_result_button.setObjectName("secondary")
        self.open_run_result_button.clicked.connect(self._open_run_result)
        self.delete_remote_server_copy_button = QPushButton("Delete server copy…")
        self.delete_remote_server_copy_button.setObjectName("danger")
        self.delete_remote_server_copy_button.clicked.connect(
            self._delete_remote_server_copy
        )
        self.delete_remote_server_copy_button.hide()
        result_button_row = QHBoxLayout()
        result_button_row.addWidget(self.open_run_result_button)
        result_button_row.addWidget(self.delete_remote_server_copy_button)
        result_button_row.addStretch()
        result_layout.addWidget(result_title)
        result_layout.addWidget(self.run_result_label)
        result_layout.addLayout(result_button_row)
        self.run_result_card.hide()
        layout.addWidget(self.run_result_card)
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(12)
        self.run_back_button = QPushButton("Back to parameter review")
        self.run_back_button.setObjectName("secondary")
        self.run_back_button.clicked.connect(self._show_review_page)
        self.cancel_atlas_button = QPushButton("Cancel safely")
        self.cancel_atlas_button.setObjectName("danger")
        self.cancel_atlas_button.clicked.connect(self._cancel_atlas)
        self.cancel_atlas_button.setEnabled(False)
        self.start_atlas_button = QPushButton("Start reviewed Modern atlas")
        self.start_atlas_button.setObjectName("primary")
        self.start_atlas_button.clicked.connect(self._run_primary_action)
        self.start_atlas_button.setEnabled(False)
        footer_layout.addWidget(self.run_back_button)
        footer_layout.addStretch()
        footer_layout.addWidget(self.cancel_atlas_button)
        footer_layout.addWidget(self.start_atlas_button)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(scroll, 1)
        page_layout.addWidget(footer)
        return page

    def _build_results_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 5 OF 5")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Verified results & PCA")
        title.setObjectName("title")
        subtitle = QLabel(
            "Read a bound summary and open only artifacts whose size and SHA-256 were "
            "rechecked immediately beforehand."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        boundary = QFrame()
        boundary.setObjectName("boundary")
        boundary_layout = QHBoxLayout(boundary)
        boundary_layout.setContentsMargins(13, 9, 13, 9)
        self.result_boundary_label = QLabel("Technical verification is not scientific validation.")
        self.result_boundary_label.setObjectName("boundaryText")
        self.result_boundary_label.setWordWrap(True)
        self.result_boundary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        boundary_layout.addWidget(self.result_boundary_label)
        layout.addWidget(boundary)

        summary = QFrame()
        summary.setObjectName("card")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(24, 22, 24, 24)
        summary_title = QLabel("Bound result snapshot")
        summary_title.setObjectName("sectionTitle")
        self.result_summary_label = QLabel()
        self.result_summary_label.setWordWrap(True)
        self.result_summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        summary_layout.addWidget(summary_title)
        self.result_completion_label = QLabel("Awaiting a verified result snapshot.")
        self.result_completion_label.setObjectName("status")
        self.result_completion_label.setWordWrap(True)
        summary_layout.addWidget(self.result_completion_label)
        summary_layout.addWidget(self.result_summary_label)
        layout.addWidget(summary)

        atlas_viewer = QFrame()
        atlas_viewer.setObjectName("card")
        atlas_viewer_layout = QVBoxLayout(atlas_viewer)
        atlas_viewer_layout.setContentsMargins(24, 22, 24, 24)
        atlas_viewer_layout.setSpacing(12)
        atlas_viewer_title = QLabel("Atlas & registration QC viewer")
        atlas_viewer_title.setObjectName("sectionTitle")
        atlas_viewer_hint = QLabel(
            "The selected VTK is rechecked against the verified result inventory before "
            "DiffeoForge renders it internally. Drag to rotate, right-drag to pan, use the "
            "mouse wheel to zoom, and double-click to reset."
        )
        atlas_viewer_hint.setObjectName("hint")
        atlas_viewer_hint.setWordWrap(True)
        atlas_mesh_group_controls = QHBoxLayout()
        atlas_mesh_group_controls.setSpacing(10)
        atlas_mesh_group_controls.addWidget(QLabel("Content"))
        self.result_atlas_mesh_group_combo = QComboBox()
        self.result_atlas_mesh_group_combo.setObjectName("resultAtlasMeshGroupCombo")
        self.result_atlas_mesh_group_combo.addItem(
            "Template & PCA end forms",
            "summary",
        )
        self.result_atlas_mesh_group_combo.addItem(
            "All specimen meshes",
            "specimens",
        )
        self.result_atlas_mesh_group_combo.currentIndexChanged.connect(
            self._populate_selected_atlas_mesh_group
        )
        atlas_mesh_group_controls.addWidget(self.result_atlas_mesh_group_combo, 1)
        atlas_mesh_controls = QHBoxLayout()
        atlas_mesh_controls.setSpacing(10)
        atlas_mesh_controls.addWidget(QLabel("Mesh"))
        self.result_atlas_mesh_combo = QComboBox()
        self.result_atlas_mesh_combo.setObjectName("resultAtlasMeshCombo")
        self.result_atlas_mesh_combo.currentIndexChanged.connect(self._load_selected_atlas_mesh)
        atlas_mesh_controls.addWidget(self.result_atlas_mesh_combo, 1)
        self.result_atlas_mesh_counter_label = QLabel("0 meshes")
        self.result_atlas_mesh_counter_label.setObjectName("hint")
        atlas_mesh_controls.addWidget(self.result_atlas_mesh_counter_label)
        atlas_mesh_search_controls = QHBoxLayout()
        atlas_mesh_search_controls.setSpacing(10)
        self.result_atlas_mesh_search_label = QLabel("Find specimen")
        self.result_atlas_mesh_search_edit = QLineEdit()
        self.result_atlas_mesh_search_edit.setObjectName("resultAtlasMeshSearchEdit")
        self.result_atlas_mesh_search_edit.setPlaceholderText(
            "Type part of a specimen name or number"
        )
        self.result_atlas_mesh_search_edit.textChanged.connect(
            self._populate_selected_atlas_mesh_group
        )
        atlas_mesh_search_controls.addWidget(self.result_atlas_mesh_search_label)
        atlas_mesh_search_controls.addWidget(self.result_atlas_mesh_search_edit, 1)
        self.result_atlas_mesh_search_label.hide()
        self.result_atlas_mesh_search_edit.hide()
        atlas_view_controls = QHBoxLayout()
        atlas_view_controls.setSpacing(10)
        atlas_view_controls.addWidget(QLabel("View"))
        self.result_atlas_view_combo = QComboBox()
        self.result_atlas_view_combo.setObjectName("resultAtlasViewCombo")
        for label, value in (
            ("Three-quarter", "three-quarter"),
            ("Front", "front"),
            ("Back", "back"),
            ("Left", "left"),
            ("Right", "right"),
            ("Top", "top"),
            ("Bottom", "bottom"),
        ):
            self.result_atlas_view_combo.addItem(label, value)
        self.result_atlas_view_combo.currentIndexChanged.connect(self._set_atlas_view_preset)
        atlas_view_controls.addWidget(self.result_atlas_view_combo)
        reset_atlas_view_button = QPushButton("Reset view")
        reset_atlas_view_button.setObjectName("secondary")
        reset_atlas_view_button.clicked.connect(self._reset_atlas_view)
        atlas_view_controls.addWidget(reset_atlas_view_button)
        atlas_view_controls.addStretch()
        self.result_atlas_status_label = QLabel("Awaiting a verified atlas or reconstruction.")
        self.result_atlas_status_label.setObjectName("status")
        self.result_atlas_status_label.setWordWrap(True)
        overlay_controls = QHBoxLayout()
        self.result_show_original_check = QCheckBox("Show original (blue wireframe)")
        self.result_show_original_check.setChecked(True)
        self.result_show_reconstruction_check = QCheckBox(
            "Show reconstruction (orange surface)"
        )
        self.result_show_reconstruction_check.setChecked(True)
        self.result_show_original_check.toggled.connect(
            self._set_registration_qc_original_visible
        )
        self.result_show_reconstruction_check.toggled.connect(
            self._set_registration_qc_reconstruction_visible
        )
        overlay_controls.addWidget(self.result_show_original_check)
        overlay_controls.addWidget(self.result_show_reconstruction_check)
        overlay_controls.addStretch()
        self.result_show_original_check.hide()
        self.result_show_reconstruction_check.hide()
        decision_controls = QHBoxLayout()
        decision_controls.addWidget(QLabel("Researcher decision"))
        self.result_qc_pass_button = QPushButton("Plausible")
        self.result_qc_uncertain_button = QPushButton("Uncertain")
        self.result_qc_fail_button = QPushButton("Implausible")
        for button, decision in (
            (self.result_qc_pass_button, "pass"),
            (self.result_qc_uncertain_button, "uncertain"),
            (self.result_qc_fail_button, "fail"),
        ):
            button.setObjectName("secondary")
            button.clicked.connect(
                lambda _checked=False, value=decision: self._record_registration_qc_decision(
                    value
                )
            )
            button.hide()
            decision_controls.addWidget(button)
        self.result_qc_export_button = QPushButton("Export QC status")
        self.result_qc_export_button.setObjectName("secondary")
        self.result_qc_export_button.clicked.connect(self._export_registration_qc_status)
        self.result_qc_export_button.hide()
        decision_controls.addWidget(self.result_qc_export_button)
        decision_controls.addStretch()
        self.result_atlas_canvas = InteractiveMeshCanvas3D()
        self.result_atlas_canvas.setObjectName("resultAtlasViewer3D")
        self.result_atlas_canvas.setAccessibleName(
            "Interactive verified atlas and registration quality-control viewer"
        )
        self.result_atlas_canvas.set_picking_enabled(False)
        self.result_atlas_canvas.setMinimumHeight(620)
        self.result_atlas_canvas.hide()
        self.result_registration_qc_canvas = CalibrationComparisonCanvas3D()
        self.result_registration_qc_canvas.setObjectName("resultRegistrationQcViewer3D")
        self.result_registration_qc_canvas.setAccessibleName(
            "Original and reconstruction overlay ranked by registration residual"
        )
        self.result_registration_qc_canvas.setMinimumHeight(620)
        self.result_registration_qc_canvas.hide()
        atlas_viewer_layout.addWidget(atlas_viewer_title)
        atlas_viewer_layout.addWidget(atlas_viewer_hint)
        atlas_viewer_layout.addLayout(atlas_mesh_group_controls)
        atlas_viewer_layout.addLayout(atlas_mesh_controls)
        atlas_viewer_layout.addLayout(atlas_mesh_search_controls)
        atlas_viewer_layout.addLayout(atlas_view_controls)
        atlas_viewer_layout.addLayout(overlay_controls)
        atlas_viewer_layout.addLayout(decision_controls)
        atlas_viewer_layout.addWidget(self.result_atlas_status_label)
        atlas_viewer_layout.addWidget(self.result_atlas_canvas)
        atlas_viewer_layout.addWidget(self.result_registration_qc_canvas)
        layout.addWidget(atlas_viewer)

        overview_card, self.result_overview_layout = self._build_result_items_card(
            "Atlas and dataset", "resultOverview"
        )
        optimization_card, self.result_optimization_layout = self._build_result_items_card(
            "Optimization", "resultOptimization"
        )
        pca_card, self.result_pca_layout = self._build_result_items_card("PCA", "resultPca")
        quality_card, self.result_quality_layout = self._build_result_items_card(
            "Verification and quality evidence", "resultQuality"
        )
        layout.addWidget(overview_card)
        layout.addWidget(optimization_card)

        convergence_plot_card = QFrame()
        convergence_plot_card.setObjectName("card")
        convergence_plot_layout = QVBoxLayout(convergence_plot_card)
        convergence_plot_layout.setContentsMargins(24, 22, 24, 24)
        convergence_plot_layout.setSpacing(14)
        convergence_plot_title = QLabel("Optimizer convergence")
        convergence_plot_title.setObjectName("sectionTitle")
        self.result_optimizer_convergence_hint = QLabel(
            "The upper panel shows committed objective components; the lower panel shows "
            "block-gradient norms against the configured tolerance. A completed curve is "
            "not automatically a converged curve."
        )
        self.result_optimizer_convergence_hint.setObjectName("hint")
        self.result_optimizer_convergence_hint.setWordWrap(True)
        (
            convergence_panel,
            self.result_optimizer_convergence_plot,
            self.result_optimizer_convergence_plot_status,
        ) = self._build_result_plot_panel(
            "Objective and block gradients",
            "resultOptimizerConvergencePlot",
            "Awaiting a verified optimizer-convergence plot.",
        )
        convergence_plot_layout.addWidget(convergence_plot_title)
        convergence_plot_layout.addWidget(self.result_optimizer_convergence_hint)
        convergence_plot_layout.addWidget(convergence_panel)
        layout.addWidget(convergence_plot_card)
        layout.addWidget(pca_card)

        pca_plots = QFrame()
        pca_plots.setObjectName("card")
        pca_plots_layout = QVBoxLayout(pca_plots)
        pca_plots_layout.setContentsMargins(24, 22, 24, 24)
        pca_plots_layout.setSpacing(14)
        pca_plots_title = QLabel("PCA plots")
        pca_plots_title.setObjectName("sectionTitle")
        pca_plots_hint = QLabel(
            "All views are loaded directly from independently verified, script-free SVG "
            "artifacts. Hover over a score point to see its specimen name and PC values. "
            "Axis labels report explained variance; PCA signs remain conventional."
        )
        pca_plots_hint.setObjectName("hint")
        pca_plots_hint.setWordWrap(True)
        (
            scree_panel,
            self.result_pca_scree_plot,
            self.result_pca_scree_plot_status,
        ) = self._build_result_plot_panel(
            "Explained variance", "resultPcaScreePlot", "Awaiting a verified scree plot."
        )
        (
            pc1_pc2_panel,
            self.result_pc1_pc2_plot,
            self.result_pc1_pc2_plot_status,
        ) = self._build_result_plot_panel(
            "PC1 vs PC2", "resultPc1Pc2Plot", "Awaiting a verified PCA plot."
        )
        (
            pc2_pc3_panel,
            self.result_pc2_pc3_plot,
            self.result_pc2_pc3_plot_status,
        ) = self._build_result_plot_panel(
            "PC2 vs PC3", "resultPc2Pc3Plot", "Awaiting a verified PCA plot."
        )
        pca_plots_layout.addWidget(pca_plots_title)
        pca_plots_layout.addWidget(pca_plots_hint)
        pca_plots_layout.addWidget(scree_panel)
        pca_plots_layout.addWidget(pc1_pc2_panel)
        pca_plots_layout.addWidget(pc2_pc3_panel)
        layout.addWidget(pca_plots)
        layout.addWidget(quality_card)

        self.reference_pca_deformation_card = QFrame()
        self.reference_pca_deformation_card.setObjectName("card")
        reference_pca_deformation_layout = QVBoxLayout(
            self.reference_pca_deformation_card
        )
        reference_pca_deformation_layout.setContentsMargins(24, 22, 24, 24)
        reference_pca_deformation_layout.setSpacing(10)
        reference_pca_deformation_title = QLabel("Deformetrica PC shape meshes")
        reference_pca_deformation_title.setObjectName("sectionTitle")
        reference_pca_deformation_summary = QLabel(
            "Generate the mean-momenta shape and the negative and positive 2-SD "
            "endpoints for up to the first three retained PCs. DiffeoForge uses the "
            "exact verified source Deformetrica runtime and adds only fully verified "
            "final-timepoint VTKs to the viewer above."
        )
        reference_pca_deformation_summary.setWordWrap(True)
        self.reference_pca_deformation_status_label = QLabel(
            "Load a completed Deformetrica result to inspect availability."
        )
        self.reference_pca_deformation_status_label.setObjectName("status")
        self.reference_pca_deformation_status_label.setWordWrap(True)
        self.generate_reference_pca_deformations_button = QPushButton(
            "Generate verified PC shape meshes…"
        )
        self.generate_reference_pca_deformations_button.setObjectName("primary")
        self.generate_reference_pca_deformations_button.clicked.connect(
            self._start_reference_pca_deformations
        )
        self.generate_reference_pca_deformations_button.setEnabled(False)
        reference_pca_deformation_layout.addWidget(reference_pca_deformation_title)
        reference_pca_deformation_layout.addWidget(reference_pca_deformation_summary)
        reference_pca_deformation_layout.addWidget(
            InfoDisclosure(
                "What this does and does not mean",
                (
                    "This runs one separate Deformetrica compute Shooting operation. It "
                    "does not refit or modify the atlas. PCA signs are conventional and "
                    "the endpoint meshes are visual aids, not observed specimens, "
                    "confidence intervals, group effects, or biological validation."
                ),
                parent=self.reference_pca_deformation_card,
            )
        )
        reference_pca_deformation_layout.addWidget(
            self.reference_pca_deformation_status_label
        )
        reference_pca_deformation_layout.addWidget(
            self.generate_reference_pca_deformations_button
        )
        self.reference_pca_deformation_card.hide()
        layout.addWidget(self.reference_pca_deformation_card)

        validation_lab = QFrame()
        validation_lab.setObjectName("card")
        validation_layout = QVBoxLayout(validation_lab)
        validation_layout.setContentsMargins(24, 22, 24, 24)
        validation_layout.setSpacing(10)
        validation_title = QLabel("DiffeoForge Validation Lab")
        validation_title.setObjectName("sectionTitle")
        validation_summary = QLabel(
            "After pilot calibration, test the frozen finalist parameters across a "
            "predeclared training comparison and deterministic cohort resamples. The "
            "result is an uncertainty-aware robustness report, not an automatic claim "
            "of universal biological optimality."
        )
        validation_summary.setWordWrap(True)
        self.open_validation_lab_button = QPushButton("Open Validation Lab…")
        self.open_validation_lab_button.setObjectName("primary")
        self.open_validation_lab_button.clicked.connect(self._open_validation_lab)
        self.open_validation_lab_button.setEnabled(False)
        validation_layout.addWidget(validation_title)
        validation_layout.addWidget(validation_summary)
        validation_layout.addWidget(
            InfoDisclosure(
                "What additional evidence it creates",
                (
                    "The lab reserves an untouched holdout, freezes the pilot-selected "
                    "parameter set and its nearest tested neighbors, runs every finalist "
                    "on identical predeclared cohorts, and compares external surface "
                    "error, deformation distortion, geometric validity, and stability. "
                    "Fixed-template heldout registration and independent biological "
                    "landmarks remain explicitly separate future gates."
                ),
                parent=validation_lab,
            )
        )
        validation_layout.addWidget(self.open_validation_lab_button)
        layout.addWidget(validation_lab)

        artifacts = QFrame()
        artifacts.setObjectName("card")
        artifacts_layout = QVBoxLayout(artifacts)
        artifacts_layout.setContentsMargins(24, 22, 24, 24)
        artifacts_title = QLabel("Verified open artifacts")
        artifacts_title.setObjectName("sectionTitle")
        artifacts_hint = QLabel(
            "Atlas and reconstruction VTK files are rendered in the internal viewer above. "
            "Tables, JSON, text, and static SVG files are handed to the locally associated "
            "application only after another size and SHA-256 check."
        )
        artifacts_hint.setObjectName("hint")
        artifacts_hint.setWordWrap(True)
        self.result_artifacts_widget = QWidget()
        self.result_artifacts_widget.setObjectName("resultArtifacts")
        self.result_artifacts_layout = QVBoxLayout(self.result_artifacts_widget)
        self.result_artifacts_layout.setContentsMargins(0, 4, 0, 0)
        self.result_artifacts_layout.setSpacing(10)
        self.result_artifact_buttons: list[QPushButton] = []
        artifacts_layout.addWidget(artifacts_title)
        artifacts_layout.addWidget(artifacts_hint)
        artifacts_layout.addWidget(self.result_artifacts_widget)
        layout.addWidget(artifacts)
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(12)
        self.result_back_button = QPushButton("Back to atlas run")
        self.result_back_button.setObjectName("secondary")
        self.result_back_button.clicked.connect(self._show_run_page_from_results)
        self.result_status_label = QLabel("No result snapshot has been loaded.")
        self.result_status_label.setObjectName("status")
        self.result_status_label.setWordWrap(True)
        footer_layout.addWidget(self.result_back_button)
        footer_layout.addWidget(self.result_status_label, 1)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(scroll, 1)
        page_layout.addWidget(footer)
        return page

    @staticmethod
    def _build_result_items_card(title: str, object_name: str) -> tuple[QWidget, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        rows = QWidget()
        rows.setObjectName(object_name)
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 4, 0, 0)
        rows_layout.setSpacing(13)
        layout.addWidget(heading)
        layout.addWidget(rows)
        return card, rows_layout

    @staticmethod
    def _build_result_plot_panel(
        title: str,
        object_name: str,
        pending_text: str,
    ) -> tuple[QWidget, AspectRatioSvgWidget, QLabel]:
        panel = QFrame()
        panel.setObjectName("resultPlotPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("reviewValue")
        status = QLabel(pending_text)
        status.setObjectName("status")
        status.setWordWrap(True)
        plot = AspectRatioSvgWidget()
        plot.setObjectName(object_name)
        plot.setMinimumHeight(440)
        plot.setMaximumHeight(900)
        plot.setMaximumWidth(1320)
        plot.hide()
        layout.addWidget(heading)
        layout.addWidget(status)
        layout.addWidget(plot, 0, Qt.AlignmentFlag.AlignHCenter)
        return panel, plot, status

    def _build_review_card(self, title: str, object_name: str) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        rows = QWidget()
        rows.setObjectName(object_name)
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 4, 0, 0)
        rows_layout.setSpacing(13)
        layout.addWidget(rows)
        if object_name == "parameterReview":
            self.parameter_review_layout = rows_layout
        else:
            self.workload_review_layout = rows_layout
        return card

    def _build_form_cards(self) -> tuple[QWidget, QWidget]:
        data_card = QFrame()
        data_card.setObjectName("card")
        data_card_layout = QVBoxLayout(data_card)
        data_card_layout.setContentsMargins(24, 22, 24, 24)
        data_card_layout.setSpacing(15)
        data_section = QLabel("Project and inputs")
        data_section.setObjectName("sectionTitle")
        data_card_layout.addWidget(data_section)

        parameter_card = QFrame()
        parameter_card.setObjectName("card")
        parameter_card_layout = QVBoxLayout(parameter_card)
        parameter_card_layout.setContentsMargins(24, 22, 24, 24)
        parameter_card_layout.setSpacing(15)
        parameter_section = QLabel("Guided parameter calibration")
        parameter_section.setObjectName("sectionTitle")
        parameter_card_layout.addWidget(parameter_section)

        data_form = QFormLayout()
        parameter_form = QFormLayout()
        for form in (data_form, parameter_form):
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.setHorizontalSpacing(22)
            form.setVerticalSpacing(12)

        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("engineCombo")
        self.engine_combo.addItem("DiffeoForge Modern (experimental)", DesktopEngine.MODERN_CPU)
        self.engine_combo.addItem(
            "Deformetrica 4.3 (recommended backend)",
            DesktopEngine.DEFORMETRICA_REFERENCE,
        )
        self.engine_combo.currentIndexChanged.connect(self._update_engine_explanation)
        engine_box = QWidget()
        engine_layout = QVBoxLayout(engine_box)
        engine_layout.setContentsMargins(0, 0, 0, 0)
        engine_layout.setSpacing(4)
        engine_layout.addWidget(self.engine_combo)
        self.engine_hint = QLabel()
        self.engine_hint.setObjectName("hint")
        self.engine_hint.setWordWrap(True)
        engine_layout.addWidget(self.engine_hint)
        data_form.addRow("Engine", engine_box)

        self.pairwise_combo = QComboBox()
        self.pairwise_combo.setObjectName("pairwiseEvaluationCombo")
        self.pairwise_combo.addItem(
            "Dense — small pilot / correctness baseline",
            "dense",
        )
        self.pairwise_combo.addItem(
            "Blockwise 256 × 256 — high-face-count experiment",
            "blockwise_256",
        )
        self.pairwise_combo.currentIndexChanged.connect(self._update_pairwise_explanation)
        pairwise_box = QWidget()
        self.pairwise_box = pairwise_box
        pairwise_layout = QVBoxLayout(pairwise_box)
        pairwise_layout.setContentsMargins(0, 0, 0, 0)
        pairwise_layout.setSpacing(4)
        pairwise_layout.addWidget(self.pairwise_combo)
        self.pairwise_hint = QLabel()
        self.pairwise_hint.setObjectName("hint")
        self.pairwise_hint.setWordWrap(True)
        pairwise_layout.addWidget(self.pairwise_hint)
        parameter_form.addRow("Pairwise evaluation", pairwise_box)

        self.optimization_effort_combo = QComboBox()
        self.optimization_effort_combo.setObjectName("optimizationEffortCombo")
        self.optimization_effort_combo.addItem(
            "Technical pilot — 3 cycles",
            3,
        )
        self.optimization_effort_combo.addItem(
            "Convergence attempt — up to 50 cycles",
            50,
        )
        self.optimization_effort_combo.currentIndexChanged.connect(
            self._update_optimization_explanation
        )
        optimization_effort_box = QWidget()
        self.optimization_effort_box = optimization_effort_box
        optimization_effort_layout = QVBoxLayout(optimization_effort_box)
        optimization_effort_layout.setContentsMargins(0, 0, 0, 0)
        optimization_effort_layout.setSpacing(4)
        optimization_effort_layout.addWidget(self.optimization_effort_combo)
        self.optimization_effort_hint = QLabel()
        self.optimization_effort_hint.setObjectName("hint")
        self.optimization_effort_hint.setWordWrap(True)
        optimization_effort_layout.addWidget(self.optimization_effort_hint)
        parameter_form.addRow("Optimization effort", optimization_effort_box)

        self.modern_device_combo = QComboBox()
        self.modern_device_combo.setObjectName("modernDeviceCombo")
        self.modern_device_combo.addItem("CPU / float64 — built into this app", "cpu")
        self.modern_device_combo.addItem(
            "NVIDIA CUDA / float64 — verified external runtime",
            "cuda",
        )
        self.modern_device_combo.currentIndexChanged.connect(
            self._update_modern_execution_explanation
        )
        modern_device_box = QWidget()
        self.modern_device_box = modern_device_box
        modern_device_layout = QVBoxLayout(modern_device_box)
        modern_device_layout.setContentsMargins(0, 0, 0, 0)
        modern_device_layout.setSpacing(4)
        modern_device_layout.addWidget(self.modern_device_combo)
        self.modern_device_hint = QLabel()
        self.modern_device_hint.setObjectName("hint")
        self.modern_device_hint.setWordWrap(True)
        modern_device_layout.addWidget(self.modern_device_hint)
        parameter_form.addRow("Modern execution device", modern_device_box)

        self.modern_template_gradient_combo = QComboBox()
        self.modern_template_gradient_combo.setObjectName("modernTemplateGradientCombo")
        self.modern_template_gradient_combo.addItem(
            "Euclidean — established Modern baseline",
            "euclidean",
        )
        self.modern_template_gradient_combo.addItem(
            "Sobolev — smooth template updates (opt-in)",
            "sobolev",
        )
        self.modern_template_gradient_combo.currentIndexChanged.connect(
            self._update_modern_execution_explanation
        )
        self.modern_sobolev_ratio_spin = QDoubleSpinBox()
        self.modern_sobolev_ratio_spin.setObjectName("modernSobolevRatioSpin")
        self.modern_sobolev_ratio_spin.setDecimals(6)
        self.modern_sobolev_ratio_spin.setRange(0.000001, 1000000.0)
        self.modern_sobolev_ratio_spin.setValue(1.0)
        self.modern_sobolev_ratio_spin.setToolTip(
            "Sobolev smoothing width = deformation-kernel width × this ratio."
        )
        modern_gradient_box = QWidget()
        self.modern_gradient_box = modern_gradient_box
        modern_gradient_layout = QVBoxLayout(modern_gradient_box)
        modern_gradient_layout.setContentsMargins(0, 0, 0, 0)
        modern_gradient_layout.setSpacing(4)
        modern_gradient_layout.addWidget(self.modern_template_gradient_combo)
        modern_gradient_layout.addWidget(self.modern_sobolev_ratio_spin)
        self.modern_gradient_hint = QLabel()
        self.modern_gradient_hint.setObjectName("hint")
        self.modern_gradient_hint.setWordWrap(True)
        modern_gradient_layout.addWidget(self.modern_gradient_hint)
        parameter_form.addRow("Template update gradient", modern_gradient_box)

        self.reference_parameter_box = QFrame()
        self.reference_parameter_box.setObjectName("parameterEditor")
        reference_parameter_layout = QVBoxLayout(self.reference_parameter_box)
        reference_parameter_layout.setContentsMargins(0, 0, 0, 0)
        reference_parameter_layout.setSpacing(8)
        self.reference_parameter_profile_combo = QComboBox()
        self.reference_parameter_profile_combo.setObjectName("referenceParameterProfileCombo")
        self.reference_parameter_profile_combo.addItem("Analyze aligned meshes first", "pending")
        self.reference_parameter_profile_combo.addItem(
            "Guided pilot calibration (recommended)", "data_assisted"
        )
        self.reference_parameter_profile_combo.addItem(
            "Advanced manual parameters (skip pilot calibration)", "advanced"
        )
        self.reference_parameter_profile_combo.currentIndexChanged.connect(
            self._update_reference_parameter_profile
        )
        self.reference_parameter_section_label = QLabel(
            "Final parameter values — complete the pilot calibration first"
        )
        self.reference_parameter_section_label.setObjectName("sectionTitle")
        self.reference_parameter_section_label.setWordWrap(True)
        reference_parameter_layout.addWidget(self.reference_parameter_section_label)
        reference_parameter_layout.addWidget(self.reference_parameter_profile_combo)
        reference_parameter_layout.addWidget(
            self._parameter_help(
                "recommendation_mode",
                "Deformetrica parameter mode",
            )
        )

        self.reference_parameter_form = QFormLayout()
        self.reference_parameter_form.setHorizontalSpacing(18)
        self.reference_parameter_form.setVerticalSpacing(7)
        self.reference_attachment_ratio_spin = self._length_spin_box(
            "Absolute attachment-kernel width in the current mesh coordinate system."
        )
        self.reference_deformation_ratio_spin = self._length_spin_box(
            "Absolute deformation-kernel width in the current mesh coordinate system."
        )
        self.reference_control_spacing_ratio_spin = self._length_spin_box(
            "Absolute initial control-point spacing in the current mesh coordinate system."
        )
        self.reference_noise_ratio_spin = self._length_spin_box(
            "Absolute noise standard deviation in the current mesh coordinate system."
        )
        self.reference_max_iterations_spin = QSpinBox()
        self.reference_max_iterations_spin.setRange(1, 100000)
        self.reference_max_iterations_spin.setSingleStep(10)
        self.reference_step_size_spin = QDoubleSpinBox()
        self.reference_step_size_spin.setDecimals(8)
        self.reference_step_size_spin.setRange(0.00000001, 1000000.0)
        self.reference_step_size_spin.setSingleStep(0.001)
        self.reference_tolerance_spin = QDoubleSpinBox()
        self.reference_tolerance_spin.setDecimals(10)
        self.reference_tolerance_spin.setRange(0.0000000001, 1.0)
        self.reference_tolerance_spin.setSingleStep(0.0001)
        for label, widget, key in (
            (
                "Attachment kernel width (surface-matching detail)",
                self.reference_attachment_ratio_spin,
                "attachment_ratio",
            ),
            (
                "Deformation kernel width (deformation smoothness)",
                self.reference_deformation_ratio_spin,
                "deformation_ratio",
            ),
            (
                "Initial control-point spacing",
                self.reference_control_spacing_ratio_spin,
                "control_spacing_ratio",
            ),
            ("Noise standard deviation", self.reference_noise_ratio_spin, "noise_ratio"),
            (
                "Maximum iterations",
                self.reference_max_iterations_spin,
                "maximum_iterations",
            ),
            (
                "Initial step size",
                self.reference_step_size_spin,
                "initial_step_size",
            ),
            (
                "Convergence tolerance",
                self.reference_tolerance_spin,
                "convergence_tolerance",
            ),
        ):
            self.reference_parameter_form.addRow(
                label,
                self._parameter_field_with_help(
                    widget,
                    key=key,
                    parameter_name=label,
                ),
            )
        reference_parameter_layout.addLayout(self.reference_parameter_form)
        self.reference_effective_widths_label = QLabel()
        self.reference_effective_widths_label.setObjectName("status")
        self.reference_effective_widths_label.setWordWrap(True)
        self.reference_effective_widths_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        reference_parameter_layout.addWidget(self.reference_effective_widths_label)
        for spin in (
            self.reference_attachment_ratio_spin,
            self.reference_deformation_ratio_spin,
            self.reference_control_spacing_ratio_spin,
            self.reference_noise_ratio_spin,
        ):
            spin.valueChanged.connect(self._update_reference_effective_widths)
        self.reference_expert_toggle = QCheckBox("Show expert settings")
        self.reference_expert_toggle.setObjectName("referenceExpertToggle")
        self.reference_expert_toggle.toggled.connect(self._update_reference_expert_visibility)
        reference_parameter_layout.addWidget(self.reference_expert_toggle)
        self.reference_expert_box = QWidget()
        self.reference_expert_box.setObjectName("referenceExpertBox")
        expert_form = QFormLayout(self.reference_expert_box)
        expert_form.setContentsMargins(0, 4, 0, 0)
        expert_form.setHorizontalSpacing(18)
        expert_form.setVerticalSpacing(7)
        self.reference_attachment_type_combo = QComboBox()
        self.reference_attachment_type_combo.addItem("Current (orientation-sensitive)", "current")
        self.reference_attachment_type_combo.addItem(
            "Varifold (orientation-insensitive)", "varifold"
        )
        self.reference_timepoints_spin = QSpinBox()
        self.reference_timepoints_spin.setRange(2, 1000)
        self.reference_timepoints_spin.setValue(10)
        self.reference_rk2_check = QCheckBox("Use RK2")
        self.reference_line_search_spin = QSpinBox()
        self.reference_line_search_spin.setRange(1, 10000)
        self.reference_line_search_spin.setValue(10)
        self.reference_save_every_spin = QSpinBox()
        self.reference_save_every_spin.setRange(1, 100000)
        self.reference_save_every_spin.setValue(5)
        self.reference_print_every_spin = QSpinBox()
        self.reference_print_every_spin.setRange(1, 100000)
        self.reference_print_every_spin.setValue(1)
        self.reference_scale_step_check = QCheckBox("Scale initial step size")
        self.reference_scale_step_check.setChecked(True)
        self.reference_sobolev_check = QCheckBox("Use Sobolev gradient")
        self.reference_sobolev_check.setChecked(True)
        self.reference_sobolev_check.toggled.connect(self._update_reference_expert_dependencies)
        self.reference_sobolev_ratio_spin = QDoubleSpinBox()
        self.reference_sobolev_ratio_spin.setDecimals(6)
        self.reference_sobolev_ratio_spin.setRange(0.000001, 1000000.0)
        self.reference_sobolev_ratio_spin.setValue(1.0)
        self.reference_freeze_template_check = QCheckBox("Freeze template")
        self.reference_freeze_control_points_check = QCheckBox("Freeze control points")
        self.reference_acceleration_combo = QComboBox()
        self.reference_acceleration_combo.setObjectName("referenceAccelerationCombo")
        self.reference_acceleration_combo.addItem(
            "Automatic — use GPU kernels when available (recommended)",
            "auto",
        )
        self.reference_acceleration_combo.addItem(
            "Require NVIDIA GPU kernels",
            "gpu",
        )
        self.reference_acceleration_combo.addItem("CPU only", "cpu")
        self.reference_threads_spin = QSpinBox()
        self.reference_threads_spin.setRange(1, 256)
        self.reference_threads_spin.setValue(4)
        self.reference_random_seed_spin = QSpinBox()
        self.reference_random_seed_spin.setRange(0, 2147483647)
        self.reference_random_seed_spin.setValue(20260715)
        for label, widget, key in (
            (
                "Attachment type",
                self.reference_attachment_type_combo,
                "attachment_type",
            ),
            ("Time points", self.reference_timepoints_spin, "time_points"),
            ("Integration", self.reference_rk2_check, "integration"),
            (
                "Line-search limit",
                self.reference_line_search_spin,
                "line_search_limit",
            ),
            ("Save interval", self.reference_save_every_spin, "save_interval"),
            ("Log interval", self.reference_print_every_spin, "log_interval"),
            (
                "Step-size scaling",
                self.reference_scale_step_check,
                "step_size_scaling",
            ),
            ("Sobolev gradient", self.reference_sobolev_check, "sobolev_gradient"),
            (
                "Sobolev width ratio",
                self.reference_sobolev_ratio_spin,
                "sobolev_width_ratio",
            ),
            (
                "Template update",
                self.reference_freeze_template_check,
                "template_update",
            ),
            (
                "Control-point update",
                self.reference_freeze_control_points_check,
                "control_point_update",
            ),
            (
                "Compute acceleration",
                self.reference_acceleration_combo,
                "compute_acceleration",
            ),
            ("CPU threads", self.reference_threads_spin, "cpu_threads"),
            ("Random seed", self.reference_random_seed_spin, "random_seed"),
        ):
            expert_form.addRow(
                label,
                self._parameter_field_with_help(
                    widget,
                    key=key,
                    parameter_name=label,
                ),
            )
        reference_parameter_layout.addWidget(self.reference_expert_box)
        self._reference_expert_widgets = (
            self.reference_attachment_type_combo,
            self.reference_timepoints_spin,
            self.reference_rk2_check,
            self.reference_line_search_spin,
            self.reference_save_every_spin,
            self.reference_print_every_spin,
            self.reference_scale_step_check,
            self.reference_sobolev_check,
            self.reference_sobolev_ratio_spin,
            self.reference_freeze_template_check,
            self.reference_freeze_control_points_check,
            self.reference_acceleration_combo,
            self.reference_threads_spin,
            self.reference_random_seed_spin,
        )
        self.reference_expert_box.hide()
        self.reference_parameter_hint = QLabel(
            "No values are active until aligned meshes are analyzed or Advanced manual "
            "control is selected. Every effective value will be shown again in Step 3."
        )
        self.reference_parameter_hint.setObjectName("hint")
        self.reference_parameter_hint.setWordWrap(True)
        reference_parameter_layout.addWidget(self.reference_parameter_hint)
        self.parameter_input_form = parameter_form
        self.data_input_form = data_form

        self.mesh_edit = QLineEdit()
        self.mesh_edit.setObjectName("meshDirectoryEdit")
        self.mesh_edit.setPlaceholderText(r"e.g. C:\Data\Beetles\meshes")
        self.mesh_edit.textChanged.connect(self._sync_ready_state)
        self.mesh_edit.textChanged.connect(self._invalidate_procrustes_preview)
        self.mesh_edit.editingFinished.connect(self._detect_template_from_text)
        mesh_button = QPushButton("Browse…")
        mesh_button.setObjectName("secondary")
        mesh_button.clicked.connect(self._choose_mesh_directory)
        data_form.addRow("Mesh folder", _path_row(self.mesh_edit, mesh_button))

        self.template_edit = QLineEdit()
        self.template_edit.setObjectName("templateEdit")
        self.template_edit.setPlaceholderText("automatic: template.vtk/.ply/.obj/.stl")
        self.template_edit.textChanged.connect(self._invalidate_procrustes_preview)
        template_button = QPushButton("Browse…")
        template_button.setObjectName("secondary")
        template_button.clicked.connect(self._choose_template)
        data_form.addRow("Template", _path_row(self.template_edit, template_button))

        self.pattern_edit = QLineEdit("*.vtk")
        self.pattern_edit.setObjectName("subjectPatternEdit")
        self.pattern_edit.setToolTip(
            "The template is automatically removed from the subject list. PLY, OBJ, "
            "and STL inputs require reviewed landmark Procrustes preprocessing and are "
            "then converted to canonical VTK copies."
        )
        self.pattern_edit.textChanged.connect(self._invalidate_procrustes_preview)
        data_form.addRow("File pattern", self.pattern_edit)

        self.project_edit = QLineEdit()
        self.project_edit.setObjectName("projectDirectoryEdit")
        self.project_edit.setPlaceholderText("Folder for configuration and later results")
        self.project_edit.textChanged.connect(self._sync_ready_state)
        project_button = QPushButton("Browse…")
        project_button.setObjectName("secondary")
        project_button.clicked.connect(self._choose_project_directory)
        data_form.addRow("Project folder", _path_row(self.project_edit, project_button))

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("projectNameEdit")
        self.name_edit.setPlaceholderText("optional; otherwise derived from the folder name")
        data_form.addRow("Project name", self.name_edit)

        self.units_combo = QComboBox()
        self.units_combo.setObjectName("unitsCombo")
        self.units_combo.addItem("Select a unit…", None)
        labels = {
            "unitless": "Unitless",
            "micrometer": "Micrometer (µm)",
            "millimeter": "Millimeter (mm)",
            "centimeter": "Centimeter (cm)",
            "meter": "Meter (m)",
        }
        for unit in SUPPORTED_UNITS:
            self.units_combo.addItem(labels[unit], unit)
        self.units_combo.currentIndexChanged.connect(self._sync_ready_state)
        self.units_combo.currentIndexChanged.connect(self._reference_recommendation_inputs_changed)
        data_form.addRow("Coordinate unit", self.units_combo)

        self.landmarks_edit = QLineEdit()
        self.landmarks_edit.setObjectName("landmarksEdit")
        self.landmarks_edit.setPlaceholderText("optional: homologous landmarks as CSV")
        self.landmarks_edit.textChanged.connect(self._update_procrustes_visibility)
        landmarks_button = QPushButton("Browse…")
        landmarks_button.setObjectName("secondary")
        landmarks_button.clicked.connect(self._choose_landmarks)
        self.landmarks_button = landmarks_button
        self.place_landmarks_button = QPushButton("Place landmarks…")
        self.place_landmarks_button.setObjectName("secondary")
        self.place_landmarks_button.clicked.connect(self._place_landmarks)
        landmarks_row = QHBoxLayout()
        landmarks_row.setContentsMargins(0, 0, 0, 0)
        landmarks_row.setSpacing(8)
        landmarks_row.addWidget(self.landmarks_edit, 1)
        landmarks_row.addWidget(landmarks_button)
        landmarks_row.addWidget(self.place_landmarks_button)
        data_form.addRow("Landmarks", landmarks_row)

        self.landmark_count_spin = QSpinBox()
        self.landmark_count_spin.setObjectName("landmarkCountSpin")
        self.landmark_count_spin.setRange(3, 2_147_483_647)
        self.landmark_count_spin.setValue(3)
        self.landmark_count_spin.setToolTip(
            "At least three non-collinear landmarks are required for generalized "
            "Procrustes. DiffeoForge imposes no study-specific ten-landmark cap."
        )
        self.landmark_auto_advance_check = QCheckBox(
            "Automatically load the next mesh after all planned landmarks are placed"
        )
        self.landmark_auto_advance_check.setObjectName("autoAdvanceLandmarkMeshCheck")
        self.landmark_auto_advance_check.setChecked(True)
        landmark_plan = QHBoxLayout()
        landmark_plan.setContentsMargins(0, 0, 0, 0)
        landmark_plan.setSpacing(12)
        landmark_plan.addWidget(self.landmark_count_spin)
        landmark_plan.addWidget(self.landmark_auto_advance_check, 1)
        data_form.addRow("Planned landmarks", landmark_plan)

        self.procrustes_box = QWidget()
        procrustes_layout = QVBoxLayout(self.procrustes_box)
        procrustes_layout.setContentsMargins(0, 0, 0, 0)
        procrustes_layout.setSpacing(6)
        self.procrustes_apply_check = QCheckBox(
            "Apply generalized Procrustes before atlas computation"
        )
        self.procrustes_apply_check.setChecked(True)
        self.procrustes_apply_check.toggled.connect(self._procrustes_inputs_changed)
        self.procrustes_scale_check = QCheckBox("Scale to unit centroid size")
        self.procrustes_scale_check.setChecked(True)
        self.procrustes_scale_check.toggled.connect(self._procrustes_inputs_changed)
        self.procrustes_reflection_check = QCheckBox("Allow reflections")
        self.procrustes_reflection_check.toggled.connect(self._procrustes_inputs_changed)
        procrustes_settings = QHBoxLayout()
        procrustes_settings.addWidget(self.procrustes_scale_check)
        procrustes_settings.addWidget(self.procrustes_reflection_check)
        procrustes_settings.addStretch()
        procrustes_advanced = QHBoxLayout()
        self.procrustes_tolerance_spin = QDoubleSpinBox()
        self.procrustes_tolerance_spin.setDecimals(12)
        self.procrustes_tolerance_spin.setRange(0.000000000001, 1.0)
        self.procrustes_tolerance_spin.setValue(0.0000000001)
        self.procrustes_tolerance_spin.valueChanged.connect(self._procrustes_inputs_changed)
        self.procrustes_iterations_spin = QSpinBox()
        self.procrustes_iterations_spin.setRange(1, 100000)
        self.procrustes_iterations_spin.setValue(100)
        self.procrustes_iterations_spin.valueChanged.connect(self._procrustes_inputs_changed)
        procrustes_advanced.addWidget(QLabel("Tolerance"))
        procrustes_advanced.addWidget(self.procrustes_tolerance_spin)
        procrustes_advanced.addWidget(QLabel("Maximum iterations"))
        procrustes_advanced.addWidget(self.procrustes_iterations_spin)
        procrustes_advanced.addStretch()
        procrustes_hint = QLabel(
            "This preview uses the homologous landmarks to estimate translation, "
            "rotation, and optional centroid-size scaling for the complete cohort. "
            "It writes nothing until you review and approve the report below. Raw "
            "meshes remain unchanged; approved project creation writes immutable "
            "aligned VTK copies and records every transform. Reflection is off by default."
        )
        procrustes_hint.setObjectName("hint")
        procrustes_hint.setWordWrap(True)
        procrustes_layout.addWidget(self.procrustes_apply_check)
        procrustes_layout.addLayout(procrustes_settings)
        procrustes_layout.addLayout(procrustes_advanced)
        procrustes_layout.addWidget(procrustes_hint)
        self.preview_procrustes_button = QPushButton("Preview alignment read-only")
        self.preview_procrustes_button.setObjectName("secondary")
        self.preview_procrustes_button.clicked.connect(self._preview_procrustes)
        self.procrustes_preview_status_label = _ReadOnlyStatusText(
            "No alignment preview has been reviewed."
        )
        self.procrustes_preview_status_label.setObjectName("status")
        self.review_procrustes_visual_button = QPushButton("Open visual GPA review...")
        self.review_procrustes_visual_button.setObjectName("secondary")
        self.review_procrustes_visual_button.setEnabled(False)
        self.review_procrustes_visual_button.clicked.connect(self._open_procrustes_visual_review)
        self.approve_procrustes_check = QCheckBox(
            "I reviewed the numerical report and completed the visual GPA review"
        )
        self.approve_procrustes_check.setEnabled(False)
        self.approve_procrustes_check.toggled.connect(self._reference_recommendation_inputs_changed)
        procrustes_layout.addWidget(self.preview_procrustes_button)
        procrustes_layout.addWidget(self.procrustes_preview_status_label)
        procrustes_layout.addWidget(self.review_procrustes_visual_button)
        procrustes_layout.addWidget(self.approve_procrustes_check)
        self._procrustes_setting_widgets = (
            self.procrustes_scale_check,
            self.procrustes_reflection_check,
            self.procrustes_tolerance_spin,
            self.procrustes_iterations_spin,
        )
        self.procrustes_box.hide()
        data_form.addRow("Alignment", self.procrustes_box)

        self.already_gpa_check = QCheckBox(
            "I confirm that these mesh coordinates are already GPA aligned"
        )
        self.already_gpa_check.setObjectName("alreadyGpaAlignedCheck")
        self.already_gpa_check.setToolTip(
            "Use this only when translation, rotation, and the intended size treatment "
            "have already been completed outside DiffeoForge. Geometry diagnostics can "
            "flag suspicious dispersion but cannot prove homologous alignment."
        )
        self.already_gpa_check.toggled.connect(self._reference_recommendation_inputs_changed)
        data_form.addRow("Existing alignment", self.already_gpa_check)

        self.reference_guidance_box = QWidget()
        guidance_layout = QVBoxLayout(self.reference_guidance_box)
        guidance_layout.setContentsMargins(0, 0, 0, 0)
        guidance_layout.setSpacing(7)
        guidance_title = QLabel("1. Analyze the aligned cohort")
        guidance_title.setObjectName("sectionTitle")
        guidance_layout.addWidget(guidance_title)
        guidance_intro = QLabel(
            "Choose the biological scales that matter, then let DiffeoForge measure "
            "the aligned geometry. The resulting numbers are provisional centers for "
            "the pilot comparisons, not final atlas parameters."
        )
        guidance_intro.setObjectName("hint")
        guidance_intro.setWordWrap(True)
        guidance_background = QWidget()
        guidance_background_layout = QVBoxLayout(guidance_background)
        guidance_background_layout.setContentsMargins(0, 0, 0, 0)
        guidance_background_layout.setSpacing(8)
        guidance_background_layout.addWidget(guidance_intro)
        self.reference_scale_difference_label = QLabel(
            "<b>These are three independent questions:</b><br>"
            "<b>1 · Matching resolution — What should DiffeoForge notice?</b> "
            "This is the measuring lens used to score surface fit.<br>"
            "<b>2 · Expected difference amplitude — How different may real specimens "
            "be?</b> This declares whether large required changes are expected biology, "
            "rather than automatically treating their size as a defect.<br>"
            "<b>3 · Deformation reach — How far should one adjustment spread?</b> "
            "This controls whether a region can move locally or must move smoothly with "
            "its neighbors.<br><br>"
            "<b>They do not have to match.</b> A cohort may contain extremely different "
            "shapes while their coordinated changes are broad/global; DiffeoForge now "
            "records those as separate scientific declarations."
        )
        self.reference_scale_difference_label.setObjectName("conceptDifference")
        self.reference_scale_difference_label.setAccessibleName(
            "Difference between matching resolution and deformation reach"
        )
        self.reference_scale_difference_label.setWordWrap(True)
        guidance_background_layout.addWidget(self.reference_scale_difference_label)
        self.reference_surface_detail_combo = QComboBox()
        self.reference_surface_detail_combo.setObjectName("referenceSurfaceDetailCombo")
        self.reference_surface_detail_combo.addItem(
            "Notice small ridges, pits, and edges (fine)", "fine"
        )
        self.reference_surface_detail_combo.addItem(
            "Balance small features and overall form", "balanced"
        )
        self.reference_surface_detail_combo.addItem(
            "Judge mainly broad overall form (coarse)", "coarse"
        )
        self.reference_surface_detail_combo.setCurrentIndex(
            self.reference_surface_detail_combo.findData("balanced")
        )
        self.reference_surface_detail_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        self.reference_deformation_scale_combo = QComboBox()
        self.reference_deformation_scale_combo.setObjectName("referenceDeformationScaleCombo")
        self.reference_deformation_scale_combo.addItem(
            "Keep changes confined to small regions (local)", "local"
        )
        self.reference_deformation_scale_combo.addItem(
            "Mix local changes and broad coordinated movement", "balanced"
        )
        self.reference_deformation_scale_combo.addItem(
            "Make wider regions move together (broad)", "global"
        )
        self.reference_deformation_scale_combo.setCurrentIndex(
            self.reference_deformation_scale_combo.findData("balanced")
        )
        self.reference_deformation_scale_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        self.reference_shape_disparity_combo = QComboBox()
        self.reference_shape_disparity_combo.setObjectName(
            "referenceShapeDisparityCombo"
        )
        self.reference_shape_disparity_combo.addItem(
            "Specimens differ only modestly", "low"
        )
        self.reference_shape_disparity_combo.addItem(
            "Moderate differences are expected", "moderate"
        )
        self.reference_shape_disparity_combo.addItem(
            "Large biological differences are expected", "high"
        )
        self.reference_shape_disparity_combo.addItem(
            "Extreme biological differences are expected", "extreme"
        )
        self.reference_shape_disparity_combo.setCurrentIndex(
            self.reference_shape_disparity_combo.findData("moderate")
        )
        self.reference_shape_disparity_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        guidance_form = QFormLayout()
        guidance_form.setContentsMargins(0, 0, 0, 0)
        guidance_form.setHorizontalSpacing(18)
        guidance_form.setVerticalSpacing(7)
        guidance_form.addRow(
            "1 · Detail used to judge the match",
            self._parameter_field_with_help(
                self.reference_surface_detail_combo,
                key="surface_detail",
                parameter_name="Matching resolution",
            ),
        )
        guidance_form.addRow(
            "2 · How different specimens may be",
            self._parameter_field_with_help(
                self.reference_shape_disparity_combo,
                key="shape_disparity",
                parameter_name="Expected difference amplitude",
            ),
        )
        guidance_form.addRow(
            "3 · How far deformation spreads",
            self._parameter_field_with_help(
                self.reference_deformation_scale_combo,
                key="deformation_scale",
                parameter_name="Deformation reach",
            ),
        )
        guidance_layout.addLayout(guidance_form)
        guidance_hint = QLabel(
            "DiffeoForge measures the mesh-sampling limit and turns these three "
            "independent choices into pilot candidates. High or extreme expected "
            "disparity widens the tested range without changing local/global reach."
        )
        guidance_hint.setObjectName("hint")
        guidance_hint.setWordWrap(True)
        guidance_background_layout.addWidget(guidance_hint)
        guidance_layout.addWidget(
            InfoDisclosure(
                "How these three choices work",
                guidance_background,
                accessible_name=(
                    "Information about matching resolution and deformation reach"
                ),
            )
        )
        self.analyze_reference_parameters_button = QPushButton(
            "Analyze aligned meshes & suggest parameters"
        )
        self.analyze_reference_parameters_button.setObjectName("secondary")
        self.analyze_reference_parameters_button.clicked.connect(self._analyze_reference_parameters)
        guidance_layout.addWidget(self.analyze_reference_parameters_button)
        self.reference_guidance_summary_label = QLabel(
            "No aligned-mesh analysis has been completed."
        )
        self.reference_guidance_summary_label.setObjectName("status")
        self.reference_guidance_summary_label.setWordWrap(True)
        guidance_layout.addWidget(self.reference_guidance_summary_label)
        self.reference_guidance_status_label = QLabel(
            "No aligned-mesh analysis has been completed."
        )
        self.reference_guidance_status_label.setObjectName("status")
        self.reference_guidance_status_label.setWordWrap(True)
        self.reference_guidance_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        guidance_layout.addWidget(
            InfoDisclosure(
                "Analysis details",
                self.reference_guidance_status_label,
                accessible_name="Detailed aligned-mesh analysis",
            )
        )

        calibration_box = QFrame()
        calibration_box.setObjectName("parameterEditor")
        calibration_layout = QVBoxLayout(calibration_box)
        calibration_layout.setContentsMargins(0, 10, 0, 0)
        calibration_layout.setSpacing(8)
        calibration_title = QLabel("2. Design the pilot comparison")
        calibration_title.setObjectName("sectionTitle")
        calibration_layout.addWidget(calibration_title)
        calibration_intro = QLabel(
            "After aligned-mesh analysis, predeclare a deterministic representative "
            "pilot cohort and sequential comparisons for surface detail, deformation "
            "locality, fit-versus-regularity weight, and numerical time points. Building "
            "the plan starts no Deformetrica process."
        )
        calibration_intro.setObjectName("hint")
        calibration_intro.setWordWrap(True)
        calibration_layout.addWidget(calibration_intro)
        calibration_form = QFormLayout()
        calibration_form.setContentsMargins(0, 0, 0, 0)
        calibration_form.setHorizontalSpacing(18)
        calibration_form.setVerticalSpacing(7)
        self.reference_feature_scale_spin = QDoubleSpinBox()
        self.reference_feature_scale_spin.setObjectName("referenceFeatureScaleSpin")
        self.reference_feature_scale_spin.setDecimals(8)
        self.reference_feature_scale_spin.setRange(0.0, 1_000_000_000.0)
        self.reference_feature_scale_spin.setSpecialValueText("Not measured")
        self.reference_feature_scale_spin.setToolTip(
            "Optional researcher-measured smallest anatomical feature to preserve. "
            "This is recorded as a scientific decision and constrained by the measured "
            "mesh-sampling floor."
        )
        self.reference_feature_scale_spin.valueChanged.connect(
            self._reference_calibration_inputs_changed
        )
        self.measure_reference_feature_button = QPushButton("Measure on 3D template…")
        self.measure_reference_feature_button.setObjectName("secondary")
        self.measure_reference_feature_button.clicked.connect(self._measure_reference_feature)
        feature_row = QWidget()
        feature_row_layout = QHBoxLayout(feature_row)
        feature_row_layout.setContentsMargins(0, 0, 0, 0)
        feature_row_layout.setSpacing(8)
        feature_row_layout.addWidget(self.reference_feature_scale_spin, 1)
        feature_row_layout.addWidget(self.measure_reference_feature_button)
        calibration_form.addRow("Smallest relevant feature", feature_row)

        self.reference_pilot_subject_count_spin = QSpinBox()
        self.reference_pilot_subject_count_spin.setObjectName("referencePilotSubjectCountSpin")
        self.reference_pilot_subject_count_spin.setRange(2, 20)
        self.reference_pilot_subject_count_spin.setValue(8)
        self.reference_pilot_subject_count_spin.setToolTip(
            "Requested pilot size. DiffeoForge selects a geometry-descriptor medoid "
            "plus deterministic farthest-first extremes and caps the request at the "
            "available subject count."
        )
        self.reference_pilot_subject_count_spin.valueChanged.connect(
            self._reference_calibration_inputs_changed
        )
        calibration_form.addRow(
            "Representative pilot subjects",
            self.reference_pilot_subject_count_spin,
        )

        self.reference_pilot_declarations_edit = QLineEdit()
        self.reference_pilot_declarations_edit.setObjectName(
            "referencePilotDeclarationsEdit"
        )
        self.reference_pilot_declarations_edit.setReadOnly(True)
        self.reference_pilot_declarations_edit.setPlaceholderText(
            "optional CSV: filename, stratum, is_extreme"
        )
        self.reference_pilot_declarations_edit.setToolTip(
            "Optional researcher declarations. DiffeoForge guarantees inclusion of "
            "every declared extreme and coverage of every declared stratum, or refuses "
            "to build an undersized pilot."
        )
        self.load_reference_pilot_declarations_button = QPushButton("Load CSV…")
        self.load_reference_pilot_declarations_button.setObjectName("secondary")
        self.load_reference_pilot_declarations_button.clicked.connect(
            self._load_reference_pilot_declarations
        )
        self.clear_reference_pilot_declarations_button = QPushButton("Clear")
        self.clear_reference_pilot_declarations_button.setObjectName("secondary")
        self.clear_reference_pilot_declarations_button.clicked.connect(
            self._clear_reference_pilot_declarations
        )
        declaration_row = QWidget()
        declaration_layout = QHBoxLayout(declaration_row)
        declaration_layout.setContentsMargins(0, 0, 0, 0)
        declaration_layout.setSpacing(8)
        declaration_layout.addWidget(self.reference_pilot_declarations_edit, 1)
        declaration_layout.addWidget(self.load_reference_pilot_declarations_button)
        declaration_layout.addWidget(self.clear_reference_pilot_declarations_button)
        calibration_form.addRow("Biological strata / extremes", declaration_row)
        calibration_layout.addLayout(calibration_form)

        calibration_actions = QHBoxLayout()
        self.build_reference_calibration_button = QPushButton("Build staged calibration plan")
        self.build_reference_calibration_button.setObjectName("secondary")
        self.build_reference_calibration_button.clicked.connect(
            self._build_reference_calibration_plan
        )
        self.export_reference_calibration_button = QPushButton("Export plan & methods report…")
        self.export_reference_calibration_button.setObjectName("secondary")
        self.export_reference_calibration_button.clicked.connect(
            self._export_reference_calibration_plan
        )
        calibration_actions.addWidget(self.build_reference_calibration_button)
        calibration_actions.addWidget(self.export_reference_calibration_button)
        calibration_actions.addStretch()
        calibration_layout.addLayout(calibration_actions)
        self.reference_calibration_summary_label = QLabel(
            "No pilot plan has been built."
        )
        self.reference_calibration_summary_label.setObjectName("status")
        self.reference_calibration_summary_label.setWordWrap(True)
        calibration_layout.addWidget(self.reference_calibration_summary_label)
        self.reference_calibration_status = _ReadOnlyStatusText(
            "Analyze the aligned meshes before building a calibration plan."
        )
        self.reference_calibration_status.setAccessibleName("Parameter calibration plan summary")
        calibration_layout.addWidget(
            InfoDisclosure(
                "Pilot plan details",
                self.reference_calibration_status,
                accessible_name="Detailed pilot calibration plan",
            )
        )
        calibration_layout.addWidget(self._build_reference_calibration_execution_card())
        guidance_layout.addWidget(calibration_box)
        parameter_form.addRow("Guided calibration", self.reference_guidance_box)
        parameter_form.addRow("Final parameter values", self.reference_parameter_box)

        data_card_layout.addLayout(data_form)
        parameter_card_layout.addLayout(parameter_form)
        return data_card, parameter_card

    def _build_result_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        heading = QLabel("Project created successfully")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.result_label = QLabel()
        self.result_label.setObjectName("resultSummary")
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        button_row = QHBoxLayout()
        open_config = QPushButton("Open configuration")
        open_config.setObjectName("secondary")
        open_config.clicked.connect(self._open_config)
        open_folder = QPushButton("Open project folder")
        open_folder.setObjectName("secondary")
        open_folder.clicked.connect(self._open_project_directory)
        button_row.addWidget(open_config)
        button_row.addWidget(open_folder)
        button_row.addStretch()
        layout.addLayout(button_row)
        return card

    @Slot()
    def _choose_mesh_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select mesh folder")
        if not selected:
            return
        self.mesh_edit.setText(selected)
        if not self.project_edit.text().strip():
            mesh_directory = Path(selected)
            self.project_edit.setText(str(mesh_directory.parent / "diffeoforge-project"))
        self._detect_template_from_text()

    @Slot()
    def _choose_project_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select project folder")
        if selected:
            self.project_edit.setText(selected)

    @Slot()
    def _choose_template(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select template",
            self.mesh_edit.text().strip(),
            _SURFACE_FILE_FILTER,
        )
        if selected:
            self.template_edit.setText(selected)
            self._adopt_template_format_pattern(Path(selected))

    @Slot()
    def _choose_landmarks(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select landmark file",
            self.mesh_edit.text().strip(),
            "CSV files (*.csv)",
        )
        if selected:
            self.landmarks_edit.setText(selected)

    @Slot()
    def _choose_remote_token(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select DiffeoForge server token file",
            filter="Token files (*.token *.txt);;All files (*)",
        )
        if selected:
            self.remote_token_edit.setText(selected)

    @Slot()
    def _choose_remote_ca(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select private TLS CA file",
            filter="PEM certificates (*.pem *.crt);;All files (*)",
        )
        if selected:
            self.remote_ca_edit.setText(selected)

    @Slot()
    def _choose_remote_session(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select existing DiffeoForge remote session",
        )
        if selected:
            self.remote_session_edit.setText(selected)

    def _remote_execution_selected(self) -> bool:
        return self.execution_location_combo.currentData() == "remote"

    def _remote_controls_ready(self) -> bool:
        if not self._remote_execution_selected():
            return True
        return bool(
            self.remote_token_edit.text().strip()
            and self.remote_upload_authorization.isChecked()
            and (
                self.remote_session_edit.text().strip()
                or self.remote_server_edit.text().strip()
            )
        )

    @Slot()
    def _execution_location_changed(self) -> None:
        remote = self._remote_execution_selected()
        self.remote_execution_controls.setVisible(remote)
        self.run_technical_toggle.setAccessibleDescription(
            "Show configuration hashes, destination binding, and remote session details."
            if remote
            else "Show configuration hashes, destination binding, and runtime details."
        )
        if (
            self._review is not None
            and self._review.engine is DesktopEngine.MODERN_CPU
            and self._worker is None
        ):
            self._refresh_run_readiness()
        self._sync_ready_state()

    @Slot()
    def _place_landmarks(self) -> None:
        try:
            mesh_directory = Path(self.mesh_edit.text().strip()).expanduser().resolve()
            project_directory = Path(self.project_edit.text().strip()).expanduser().resolve()
            if not mesh_directory.is_dir() or not self.project_edit.text().strip():
                raise ValueError("Select the mesh folder and project folder first.")
            template_text = self.template_edit.text().strip()
            template = (
                Path(template_text).expanduser().resolve()
                if template_text
                else detect_template(mesh_directory)
            )
            if template is None:
                raise ValueError("Select an explicit template mesh first.")
            subjects = tuple(
                path.resolve()
                for path in sorted(mesh_directory.glob(self.pattern_edit.text().strip()))
                if (
                    path.is_file()
                    and path.resolve() != template
                    and is_supported_surface_path(path)
                )
            )
            if not subjects:
                raise ValueError("No subject meshes match the current file pattern.")
            dialog = LandmarkEditorDialog(
                (template, *subjects),
                project_directory / "landmarks.csv",
                self,
                initial_landmark_count=self.landmark_count_spin.value(),
                auto_advance_mesh=self.landmark_auto_advance_check.isChecked(),
            )
            result = dialog.exec()
            self.landmark_count_spin.setValue(len(dialog.labels))
            self.landmark_auto_advance_check.setChecked(dialog.auto_advance_mesh_check.isChecked())
            if result == QDialog.DialogCode.Accepted:
                self.landmarks_edit.setText(str(dialog.output_path))
        except (OSError, TypeError, ValueError, MeshPreviewError) as error:
            QMessageBox.warning(self, "Landmark placement unavailable", str(error))

    @Slot()
    def _update_procrustes_visibility(self) -> None:
        self.procrustes_box.setVisible(bool(self.landmarks_edit.text().strip()))
        self._invalidate_procrustes_preview()

    @Slot()
    def _procrustes_inputs_changed(self) -> None:
        self._invalidate_procrustes_preview()

    @Slot()
    def _invalidate_procrustes_preview(self) -> None:
        had_preview = self._procrustes_preview is not None
        preview_running = isinstance(
            self._worker,
            (_ProcrustesPreviewWorker, _ProcrustesVisualWorker),
        )
        self._procrustes_preview = None
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
        self.review_procrustes_visual_button.setText("Open visual GPA review...")
        self.review_procrustes_visual_button.setEnabled(False)
        self.procrustes_preview_status_label.setObjectName("status")
        self.procrustes_preview_status_label.setStyleSheet("")
        if preview_running:
            self.procrustes_preview_status_label.setText(
                "Inputs changed while the read-only preview was running. Its result will "
                "be discarded."
            )
        elif had_preview:
            self.procrustes_preview_status_label.setText(
                "The approved preview was invalidated because an input or alignment "
                "setting changed. Run the preview again."
            )
        else:
            self.procrustes_preview_status_label.setText("No alignment preview has been reviewed.")
        self._invalidate_reference_recommendation(
            "Alignment inputs changed; analyze the aligned meshes again.",
            sync=False,
        )
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot()
    def _update_procrustes_controls(self) -> None:
        enabled = self.procrustes_apply_check.isChecked()
        for widget in self._procrustes_setting_widgets:
            widget.setEnabled(enabled)
        self.preview_procrustes_button.setEnabled(
            enabled and bool(self.landmarks_edit.text().strip()) and self._worker is None
        )
        visual_ready = bool(
            enabled
            and self._procrustes_preview is not None
            and self._procrustes_preview.alignment.converged
            and self._preview_matches_current_procrustes_inputs()
        )
        self.review_procrustes_visual_button.setEnabled(visual_ready and self._worker is None)
        self.approve_procrustes_check.setEnabled(
            visual_ready
            and self._procrustes_preview is not None
            and self._procrustes_visual_reviewed_fingerprint == self._procrustes_preview.fingerprint
            and self._worker is None
        )
        self._set_action_emphasis(
            self.preview_procrustes_button,
            bool(
                self.preview_procrustes_button.isEnabled()
                and self._procrustes_preview is None
            ),
        )
        self._set_action_emphasis(
            self.review_procrustes_visual_button,
            bool(
                self.review_procrustes_visual_button.isEnabled()
                and self._procrustes_visual_reviewed_fingerprint
                != (
                    self._procrustes_preview.fingerprint
                    if self._procrustes_preview is not None
                    else None
                )
            ),
        )

    def _current_surface_cohort(self) -> tuple[Path, ...]:
        directory = Path(self.mesh_edit.text().strip()).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("Select an existing mesh folder first.")
        template_text = self.template_edit.text().strip()
        template = (
            Path(template_text).expanduser().resolve()
            if template_text
            else detect_template(directory)
        )
        if template is None or not template.is_file():
            raise ValueError("Select an explicit template mesh first.")
        if not is_supported_surface_path(template):
            raise ValueError("The selected template is not a supported surface mesh.")
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            raise ValueError("Enter a subject file pattern.")
        try:
            subjects = tuple(
                path.resolve()
                for path in sorted(directory.glob(pattern))
                if (
                    path.is_file()
                    and path.resolve() != template
                    and is_supported_surface_path(path)
                )
            )
        except (OSError, ValueError) as error:
            raise ValueError(f"Invalid subject file pattern: {error}") from error
        if len(subjects) < 2:
            raise ValueError(
                "Parameter guidance requires at least two subject meshes in addition "
                "to the template."
            )
        return (template, *subjects)

    def _reference_alignment_context(
        self,
    ) -> tuple[str, tuple[object, ...] | None, str | None]:
        uses_diffeoforge_gpa = bool(
            self.landmarks_edit.text().strip() and self.procrustes_apply_check.isChecked()
        )
        if uses_diffeoforge_gpa:
            fingerprint = self._approved_procrustes_fingerprint()
            preview = self._procrustes_preview
            if fingerprint is None or preview is None:
                raise ValueError(
                    "Complete and approve the read-only DiffeoForge GPA preview first."
                )
            return (
                "diffeoforge_gpa",
                tuple(preview.alignment.transforms),
                fingerprint,
            )
        if not self.already_gpa_check.isChecked():
            raise ValueError(
                "Confirm that the meshes are already GPA aligned, or place landmarks "
                "and complete the DiffeoForge GPA preview first."
            )
        return "declared_gpa", None, None

    def _reference_recommendation_matches_current_inputs(self) -> bool:
        recommendation = self._reference_recommendation
        if recommendation is None or self._reference_recommendation_paths is None:
            return False
        try:
            paths = self._current_surface_cohort()
            alignment_basis, _transforms, alignment_fingerprint = (
                self._reference_alignment_context()
            )
        except (OSError, TypeError, ValueError):
            return False
        return bool(
            paths == self._reference_recommendation_paths
            and recommendation.alignment_basis == alignment_basis
            and recommendation.alignment_fingerprint == alignment_fingerprint
            and recommendation.surface_detail_intent
            == self.reference_surface_detail_combo.currentData()
            and recommendation.deformation_scale_intent
            == self.reference_deformation_scale_combo.currentData()
            and recommendation.expected_shape_disparity
            == self.reference_shape_disparity_combo.currentData()
        )

    def _invalidate_reference_recommendation(
        self,
        message: str = "Inputs changed; analyze the aligned meshes again.",
        *,
        sync: bool = True,
    ) -> None:
        self._reference_calibrated_config_path = None
        self.reference_parameter_profile_combo.setEnabled(True)
        self.reference_expert_toggle.setEnabled(True)
        for expert_widget in self._reference_expert_widgets:
            expert_widget.setEnabled(True)
        self._update_reference_expert_dependencies()
        calibrated_index = self.reference_parameter_profile_combo.findData("data_assisted")
        if calibrated_index >= 0:
            self.reference_parameter_profile_combo.setItemText(
                calibrated_index,
                "Guided pilot calibration (recommended)",
            )
        self._invalidate_reference_calibration_plan(
            "Aligned-mesh inputs changed; rebuild the calibration plan after analysis.",
            sync=False,
        )
        had_recommendation = self._reference_recommendation is not None
        self._reference_recommendation = None
        self._reference_recommendation_paths = None
        if self.reference_parameter_profile_combo.currentData() in {
            "data_assisted",
            "advanced",
        }:
            self.reference_parameter_profile_combo.blockSignals(True)
            self.reference_parameter_profile_combo.setCurrentIndex(
                self.reference_parameter_profile_combo.findData("pending")
            )
            self.reference_parameter_profile_combo.blockSignals(False)
            self._set_reference_parameter_fields_visible(False)
            self.reference_parameter_hint.setText(
                "No parameter values are active. Analyze the aligned meshes again before "
                "reviewing or editing absolute kernel widths."
            )
        if had_recommendation:
            self.reference_guidance_summary_label.setObjectName("statusWarning")
            self.reference_guidance_summary_label.setStyleSheet("")
            self.reference_guidance_summary_label.setText(
                "Inputs changed. Analyze the aligned meshes again."
            )
            self.reference_guidance_status_label.setObjectName("statusWarning")
            self.reference_guidance_status_label.setStyleSheet("")
            self.reference_guidance_status_label.setText(message)
        elif not isinstance(self._worker, _ReferenceParameterWorker):
            self.reference_guidance_summary_label.setObjectName("status")
            self.reference_guidance_summary_label.setStyleSheet("")
            self.reference_guidance_summary_label.setText(
                "No aligned-mesh analysis has been completed."
            )
            self.reference_guidance_status_label.setObjectName("status")
            self.reference_guidance_status_label.setStyleSheet("")
            self.reference_guidance_status_label.setText(
                "No aligned-mesh analysis has been completed."
            )
        self._update_reference_effective_widths()
        if sync:
            self._update_reference_guidance_controls()
            self._sync_ready_state()

    @Slot()
    def _reference_recommendation_inputs_changed(self) -> None:
        self._invalidate_reference_recommendation()

    def _current_reference_feature_scale(self) -> float | None:
        value = self.reference_feature_scale_spin.value()
        return None if value <= 0 else float(value)

    def _reference_calibration_plan_matches_current_inputs(self) -> bool:
        plan = self._reference_calibration_plan
        recommendation = self._reference_recommendation
        if plan is None or recommendation is None:
            return False
        return bool(
            plan.recommendation_fingerprint == recommendation.fingerprint
            and plan.coordinate_unit == str(self.units_combo.currentData() or "unitless")
            and plan.requested_pilot_subject_count
            == self.reference_pilot_subject_count_spin.value()
            and plan.smallest_relevant_feature == self._current_reference_feature_scale()
            and plan.pilot_subject_declarations
            == self._reference_pilot_subject_declarations
        )

    def _invalidate_reference_calibration_plan(
        self,
        message: str = "Calibration inputs changed; rebuild the staged pilot plan.",
        *,
        sync: bool = True,
    ) -> None:
        had_plan = self._reference_calibration_plan is not None
        self._reference_calibration_plan = None
        self._reference_calibration_export = None
        if had_plan:
            self.reference_calibration_summary_label.setObjectName("statusWarning")
            self.reference_calibration_summary_label.setStyleSheet("")
            self.reference_calibration_summary_label.setText(
                "Pilot inputs changed. Rebuild the plan."
            )
            self.reference_calibration_status.setObjectName("statusWarning")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(message)
        elif self._reference_recommendation is None:
            self.reference_calibration_summary_label.setObjectName("status")
            self.reference_calibration_summary_label.setStyleSheet("")
            self.reference_calibration_summary_label.setText(
                "No pilot plan has been built."
            )
            self.reference_calibration_status.setObjectName("status")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(
                "Analyze the aligned meshes before building a calibration plan."
            )
        self._update_reference_guidance_controls()
        if sync:
            self._sync_ready_state()

    @Slot()
    def _reference_calibration_inputs_changed(self) -> None:
        self._invalidate_reference_calibration_plan()

    @Slot()
    def _load_reference_pilot_declarations(self) -> None:
        initial = self.mesh_edit.text().strip() or str(Path.cwd())
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select biological pilot declarations",
            initial,
            "CSV files (*.csv);;All files (*)",
        )
        if not selected:
            return
        path = Path(selected).expanduser().resolve()
        try:
            declarations = read_pilot_subject_declarations(path)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.reference_calibration_summary_label.setObjectName("statusError")
            self.reference_calibration_summary_label.setStyleSheet("")
            self.reference_calibration_summary_label.setText(
                "Biological pilot declarations could not be loaded."
            )
            self.reference_calibration_status.setObjectName("statusError")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(str(error))
            return
        self._reference_pilot_subject_declarations = declarations
        self._reference_pilot_declarations_path = path
        self.reference_pilot_declarations_edit.setText(str(path))
        self._invalidate_reference_calibration_plan(
            f"Loaded {len(declarations)} researcher declarations. Rebuild the pilot "
            "plan to bind their strata/extreme coverage."
        )

    @Slot()
    def _clear_reference_pilot_declarations(self) -> None:
        if not self._reference_pilot_subject_declarations:
            return
        self._reference_pilot_subject_declarations = ()
        self._reference_pilot_declarations_path = None
        self.reference_pilot_declarations_edit.clear()
        self._invalidate_reference_calibration_plan(
            "Biological pilot declarations were cleared. Rebuild the pilot plan."
        )

    @staticmethod
    def _set_action_emphasis(button: QPushButton, emphasized: bool) -> None:
        """Make only the contextually recommended action visually primary."""

        desired = "primary" if emphasized else "secondary"
        if button.objectName() == desired:
            return
        button.setObjectName(desired)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _reference_calibration_completed(self) -> bool:
        path = self._reference_calibrated_config_path
        return bool(path is not None and path.is_file())

    def _update_reference_guidance_controls(self) -> None:
        reference = self.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
        uses_diffeoforge_gpa = bool(
            self.landmarks_edit.text().strip() and self.procrustes_apply_check.isChecked()
        )
        self.already_gpa_check.setEnabled(
            reference and not uses_diffeoforge_gpa and self._worker is None
        )
        alignment_ready = bool(
            self._approved_procrustes_fingerprint() is not None
            if uses_diffeoforge_gpa
            else self.already_gpa_check.isChecked()
        )
        self.analyze_reference_parameters_button.setEnabled(
            reference and alignment_ready and self._worker is None
        )
        if isinstance(self._worker, _ReferenceParameterWorker):
            self.analyze_reference_parameters_button.setText("Analyzing aligned meshes…")
        else:
            self.analyze_reference_parameters_button.setText(
                "Analyze aligned meshes & suggest parameters"
            )
        recommendation_ready = bool(
            reference
            and self._reference_recommendation is not None
            and self._reference_recommendation_matches_current_inputs()
            and self._worker is None
        )
        guided_mode = (
            self.reference_parameter_profile_combo.currentData() == "data_assisted"
        )
        pilot_design_ready = bool(recommendation_ready and guided_mode)
        self.measure_reference_feature_button.setEnabled(pilot_design_ready)
        self.reference_feature_scale_spin.setEnabled(pilot_design_ready)
        self.reference_pilot_subject_count_spin.setEnabled(pilot_design_ready)
        self.reference_pilot_declarations_edit.setEnabled(pilot_design_ready)
        self.load_reference_pilot_declarations_button.setEnabled(pilot_design_ready)
        self.clear_reference_pilot_declarations_button.setEnabled(
            pilot_design_ready and bool(self._reference_pilot_subject_declarations)
        )
        self.build_reference_calibration_button.setEnabled(pilot_design_ready)
        self.export_reference_calibration_button.setEnabled(
            pilot_design_ready and self._reference_calibration_plan_matches_current_inputs()
        )
        plan_ready = bool(
            recommendation_ready
            and self._reference_calibration_plan_matches_current_inputs()
        )
        calibration_complete = self._reference_calibration_completed()
        self._set_action_emphasis(
            self.analyze_reference_parameters_button,
            bool(reference and alignment_ready and not recommendation_ready),
        )
        self._set_action_emphasis(
            self.build_reference_calibration_button,
            bool(guided_mode and recommendation_ready and not plan_ready),
        )
        self._set_action_emphasis(
            self.open_reference_calibration_button,
            bool(
                plan_ready
                and guided_mode
                and not calibration_complete
            ),
        )
        self._refresh_reference_calibration_execution_card()

    @Slot()
    def _measure_reference_feature(self) -> None:
        if (
            self._reference_recommendation is None
            or self._reference_recommendation_paths is None
            or not self._reference_recommendation_matches_current_inputs()
        ):
            self._invalidate_reference_calibration_plan(
                "Analyze the current aligned meshes before measuring a feature."
            )
            return
        try:
            model = load_mesh_preview(self._reference_recommendation_paths[0])
            distance_scale = 1.0
            coordinate_unit = str(self.units_combo.currentData() or "unitless")
            if self._reference_recommendation.alignment_basis == "diffeoforge_gpa":
                preview = self._procrustes_preview
                if preview is None or not preview.alignment.transforms:
                    raise ValueError(
                        "The approved GPA transform is unavailable for feature measurement."
                    )
                distance_scale = preview.alignment.transforms[0].scale
                if preview.scale_to_unit_centroid_size:
                    coordinate_unit = "unitless"
        except (MeshPreviewError, OSError, RuntimeError, TypeError, ValueError) as error:
            self.reference_calibration_status.setObjectName("statusError")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(
                f"The 3D feature ruler could not load the template: {error}"
            )
            return
        dialog = FeatureScaleRulerDialog(
            model,
            coordinate_unit=coordinate_unit,
            distance_scale=distance_scale,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        distance = dialog.measured_distance
        if distance is not None:
            self.reference_feature_scale_spin.setValue(distance)

    @Slot()
    def _build_reference_calibration_plan(self) -> None:
        recommendation = self._reference_recommendation
        if recommendation is None or not self._reference_recommendation_matches_current_inputs():
            self._invalidate_reference_calibration_plan(
                "Analyze the current aligned meshes before building a calibration plan."
            )
            return
        try:
            plan = build_reference_calibration_plan(
                recommendation,
                coordinate_unit=str(self.units_combo.currentData() or "unitless"),
                requested_pilot_subject_count=(self.reference_pilot_subject_count_spin.value()),
                smallest_relevant_feature=self._current_reference_feature_scale(),
                pilot_subject_declarations=self._reference_pilot_subject_declarations,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._reference_calibration_plan = None
            self._reference_calibration_export = None
            self.reference_calibration_summary_label.setObjectName("statusError")
            self.reference_calibration_summary_label.setStyleSheet("")
            self.reference_calibration_summary_label.setText(
                "Pilot plan could not be built. Open the info below for details."
            )
            self.reference_calibration_status.setObjectName("statusError")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(
                f"Calibration plan could not be built: {error}"
            )
            self._update_reference_guidance_controls()
            return
        self._reference_calibration_plan = plan
        self._reference_calibration_export = None
        candidate_count = sum(len(stage.candidates) for stage in plan.stages)
        self.reference_calibration_summary_label.setObjectName("statusSuccess")
        self.reference_calibration_summary_label.setStyleSheet("")
        self.reference_calibration_summary_label.setText(
            f"Pilot plan ready: {plan.pilot_subject_count} representative subjects, "
            f"{candidate_count} candidate atlases. No process has started."
        )
        self.reference_calibration_status.setObjectName("statusSuccess")
        self.reference_calibration_status.setStyleSheet("")
        self.reference_calibration_status.setText(plan.summary_text())
        self._update_reference_guidance_controls()
        self._sync_ready_state()

    @Slot()
    def _export_reference_calibration_plan(self) -> None:
        plan = self._reference_calibration_plan
        if plan is None or not self._reference_calibration_plan_matches_current_inputs():
            self._invalidate_reference_calibration_plan()
            return
        project_text = self.project_edit.text().strip()
        initial_directory = Path(project_text).expanduser() if project_text else Path.cwd()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select calibration-report folder",
            str(initial_directory),
        )
        if not selected:
            return
        destination = Path(selected).expanduser().resolve()
        targets = (
            destination / "parameter-calibration-plan.json",
            destination / "parameter-calibration-plan.html",
            destination / "parameter-calibration-plan.sha256",
            destination / "aligned-mesh-recommendation.json",
        )
        overwrite = False
        if any(path.exists() for path in targets):
            answer = QMessageBox.question(
                self,
                "Replace calibration-plan export?",
                "One or more calibration-plan files already exist in this folder. "
                "Replace the complete JSON, HTML, and SHA-256 bundle?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.reference_calibration_status.setObjectName("statusWarning")
                self.reference_calibration_status.setStyleSheet("")
                self.reference_calibration_status.setText(
                    "Calibration-plan export cancelled; existing files are unchanged."
                )
                return
            overwrite = True
        try:
            result = export_reference_calibration_plan(
                plan,
                destination,
                recommendation=self._reference_recommendation,
                overwrite=overwrite,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.reference_calibration_status.setObjectName("statusError")
            self.reference_calibration_status.setStyleSheet("")
            self.reference_calibration_status.setText(f"Calibration-plan export failed: {error}")
            return
        self._reference_calibration_export = result
        self.reference_calibration_status.setObjectName("statusSuccess")
        self.reference_calibration_status.setStyleSheet("")
        self.reference_calibration_status.setText(
            f"{plan.summary_text()}\n"
            "Exported JSON, HTML, SHA-256 sidecar, and full aligned-mesh "
            f"evidence to: {result.directory}\n"
            f"JSON SHA-256: {result.json_sha256}"
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.html_path)))

    @Slot()
    def _analyze_reference_parameters(self) -> None:
        if self._worker is not None:
            return
        try:
            paths = self._current_surface_cohort()
            alignment_basis, transforms, alignment_fingerprint = self._reference_alignment_context()
        except (OSError, TypeError, ValueError) as error:
            self._reference_parameter_analysis_failed(str(error))
            return
        worker = _ReferenceParameterWorker(
            mesh_paths=paths,
            alignment_basis=alignment_basis,
            surface_detail_intent=str(self.reference_surface_detail_combo.currentData()),
            deformation_scale_intent=str(self.reference_deformation_scale_combo.currentData()),
            expected_shape_disparity=str(
                self.reference_shape_disparity_combo.currentData()
            ),
            transforms=transforms,
            alignment_fingerprint=alignment_fingerprint,
        )
        worker.signals.succeeded.connect(self._reference_parameter_analysis_succeeded)
        worker.signals.failed.connect(self._reference_parameter_analysis_failed)
        self._worker = worker
        self._reference_recommendation = None
        self._reference_recommendation_paths = None
        self._reference_calibration_plan = None
        self._reference_calibration_export = None
        self.reference_guidance_status_label.setObjectName("status")
        self.reference_guidance_status_label.setStyleSheet("")
        self.reference_guidance_status_label.setText(
            "Reading the aligned coordinates and measuring cohort scale, centroid "
            "dispersion, and mesh sampling. No mesh is being changed."
        )
        self.reference_guidance_summary_label.setObjectName("status")
        self.reference_guidance_summary_label.setStyleSheet("")
        self.reference_guidance_summary_label.setText("Analyzing aligned meshes…")
        self._update_reference_guidance_controls()
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _reference_parameter_analysis_succeeded(
        self,
        recommendation: ReferenceParameterRecommendation,
    ) -> None:
        worker = self._worker
        self._worker = None
        if not isinstance(worker, _ReferenceParameterWorker):
            self._reference_parameter_analysis_failed(
                "The completed analysis is no longer bound to the active request."
            )
            return
        try:
            current_paths = self._current_surface_cohort()
            alignment_basis, _transforms, alignment_fingerprint = (
                self._reference_alignment_context()
            )
        except (OSError, TypeError, ValueError) as error:
            self._reference_parameter_analysis_failed(str(error))
            return
        inputs_match = bool(
            current_paths == worker.mesh_paths
            and alignment_basis == worker.alignment_basis
            and alignment_fingerprint == worker.alignment_fingerprint
            and self.reference_surface_detail_combo.currentData() == worker.surface_detail_intent
            and self.reference_deformation_scale_combo.currentData()
            == worker.deformation_scale_intent
            and self.reference_shape_disparity_combo.currentData()
            == worker.expected_shape_disparity
        )
        if not inputs_match:
            self._reference_parameter_analysis_failed(
                "Analysis discarded because alignment, mesh selection, or scientific "
                "scale choices changed while it was running."
            )
            return

        self._reference_calibrated_config_path = None
        self._reference_recommendation = recommendation
        self._reference_recommendation_paths = current_paths
        self.reference_parameter_profile_combo.blockSignals(True)
        self.reference_parameter_profile_combo.setCurrentIndex(
            self.reference_parameter_profile_combo.findData("data_assisted")
        )
        self.reference_parameter_profile_combo.blockSignals(False)
        self._update_reference_parameter_profile()
        effective = recommendation.effective_values
        coordinate_label = (
            "unit-centroid-size coordinates"
            if (
                recommendation.alignment_basis == "diffeoforge_gpa"
                and self._procrustes_preview is not None
                and self._procrustes_preview.scale_to_unit_centroid_size
            )
            else self.units_combo.currentText()
        )
        warning_lines = "\n".join(f"• {warning}" for warning in recommendation.warnings)
        _coordinate_description, feature_suffix = self._reference_coordinate_labels()
        self.reference_feature_scale_spin.setSuffix(feature_suffix)
        self.reference_feature_scale_spin.setSingleStep(
            max(recommendation.template_diagonal / 1000.0, 0.00000001)
        )
        self.reference_calibration_status.setObjectName("status")
        self.reference_calibration_status.setStyleSheet("")
        self.reference_calibration_status.setText(
            "Aligned-mesh evidence is ready. The values shown below are provisional "
            "centers, not final atlas parameters. Optionally measure the smallest "
            "relevant feature, choose a pilot size, and build the staged comparison plan. "
            "No Deformetrica process starts at this step."
        )
        self.reference_calibration_summary_label.setObjectName("status")
        self.reference_calibration_summary_label.setStyleSheet("")
        self.reference_calibration_summary_label.setText(
            "Analysis ready. Choose the pilot size and build the comparison plan."
        )
        self.reference_guidance_summary_label.setObjectName("statusSuccess")
        self.reference_guidance_summary_label.setStyleSheet("")
        self.reference_guidance_summary_label.setText(
            f"Analysis ready: {recommendation.subject_count} subjects plus template. "
            "Suggested starting values are shown below."
        )
        self.reference_guidance_status_label.setObjectName("statusSuccess")
        self.reference_guidance_status_label.setStyleSheet("")
        self.reference_guidance_status_label.setText(
            f"Analyzed {recommendation.mesh_count} aligned meshes "
            f"({recommendation.subject_count} subjects + template).\n"
            f"Cohort median diagonal: {recommendation.cohort_median_diagonal:.6g}; "
            f"median sampled edge / diagonal: "
            f"{recommendation.median_edge_to_diagonal_ratio:.4g}; "
            f"centroid dispersion / diagonal: "
            f"{recommendation.normalized_centroid_dispersion:.4g}.\n"
            f"Suggested absolute attachment KW: "
            f"{effective['attachment_kernel_width']:.6g}; deformation KW: "
            f"{effective['deformation_kernel_width']:.6g}; control spacing: "
            f"{effective['initial_control_point_spacing']:.6g} "
            f"({coordinate_label}). The corresponding proportions of the template "
            f"diagonal are {recommendation.attachment_kernel_width_ratio:.3%}, "
            f"{recommendation.deformation_kernel_width_ratio:.3%}, and "
            f"{recommendation.control_point_spacing_ratio:.3%}.\n"
            f"Provisional absolute noise SD: {effective['noise_std']:.6g} "
            f"({recommendation.provisional_noise_std_ratio:.3%} of the diagonal); "
            "this is not inferable from "
            "geometry and must be calibrated in pilot registrations.\n"
            f"Recommendation fingerprint: {recommendation.fingerprint}\n"
            f"{warning_lines}"
        )
        self._update_reference_guidance_controls()
        self._sync_ready_state()

    @Slot(str)
    def _reference_parameter_analysis_failed(self, message: str) -> None:
        self._worker = None
        self._reference_recommendation = None
        self._reference_recommendation_paths = None
        self._reference_calibration_plan = None
        self._reference_calibration_export = None
        self.reference_guidance_summary_label.setObjectName("statusError")
        self.reference_guidance_summary_label.setStyleSheet("")
        self.reference_guidance_summary_label.setText(
            "Aligned-mesh analysis failed. Open the info below for details."
        )
        self.reference_guidance_status_label.setObjectName("statusError")
        self.reference_guidance_status_label.setStyleSheet("")
        self.reference_guidance_status_label.setText(
            f"Aligned-mesh parameter analysis failed: {message}"
        )
        self._update_reference_effective_widths()
        self._update_reference_guidance_controls()
        self._sync_ready_state()

    def _current_procrustes_paths(
        self,
    ) -> tuple[Path, Path, Path | None, str]:
        mesh_text = self.mesh_edit.text().strip()
        landmark_text = self.landmarks_edit.text().strip()
        pattern = self.pattern_edit.text().strip()
        if not mesh_text:
            raise ValueError("Select a mesh folder first.")
        if not landmark_text:
            raise ValueError("Select or create a landmark CSV first.")
        if not pattern:
            raise ValueError("Enter a subject file pattern first.")
        mesh_directory = Path(mesh_text).expanduser().resolve()
        if not mesh_directory.is_dir():
            raise ValueError(f"Mesh folder does not exist: {mesh_directory}")
        landmarks_file = Path(landmark_text).expanduser().resolve()
        if not landmarks_file.is_file():
            raise ValueError(f"Landmark CSV does not exist: {landmarks_file}")
        template_text = self.template_edit.text().strip()
        template = Path(template_text).expanduser().resolve() if template_text else None
        if template is not None and not template.is_file():
            raise ValueError(f"Template mesh does not exist: {template}")
        return mesh_directory, landmarks_file, template, pattern

    def _preview_matches_current_procrustes_inputs(self) -> bool:
        preview = self._procrustes_preview
        if preview is None:
            return False
        try:
            mesh_directory, landmarks_file, template, pattern = self._current_procrustes_paths()
            resolved_template = template or detect_template(mesh_directory)
        except (OSError, TypeError, ValueError):
            return False
        return bool(
            resolved_template is not None
            and preview.mesh_directory == mesh_directory
            and preview.landmarks == landmarks_file
            and preview.template == resolved_template.resolve()
            and preview.subject_pattern == pattern
            and preview.scale_to_unit_centroid_size == self.procrustes_scale_check.isChecked()
            and preview.allow_reflection == self.procrustes_reflection_check.isChecked()
            and preview.tolerance == self.procrustes_tolerance_spin.value()
            and preview.max_iterations == self.procrustes_iterations_spin.value()
        )

    def _approved_procrustes_fingerprint(self) -> str | None:
        if (
            self.procrustes_apply_check.isChecked()
            and self.approve_procrustes_check.isChecked()
            and self._preview_matches_current_procrustes_inputs()
            and self._procrustes_preview is not None
            and self._procrustes_preview.alignment.converged
            and self._procrustes_visual_reviewed_fingerprint == self._procrustes_preview.fingerprint
        ):
            return self._procrustes_preview.fingerprint
        return None

    @Slot()
    def _preview_procrustes(self) -> None:
        if self._worker is not None or not self.procrustes_apply_check.isChecked():
            return
        try:
            mesh_directory, landmarks_file, template, pattern = self._current_procrustes_paths()
        except (OSError, TypeError, ValueError) as error:
            self._procrustes_preview_failed(str(error))
            return
        worker = _ProcrustesPreviewWorker(
            mesh_directory=mesh_directory,
            landmarks_file=landmarks_file,
            template=template,
            subject_pattern=pattern,
            scale_to_unit_centroid_size=self.procrustes_scale_check.isChecked(),
            allow_reflection=self.procrustes_reflection_check.isChecked(),
            tolerance=self.procrustes_tolerance_spin.value(),
            max_iterations=self.procrustes_iterations_spin.value(),
        )
        worker.signals.succeeded.connect(self._procrustes_preview_succeeded)
        worker.signals.failed.connect(self._procrustes_preview_failed)
        self._worker = worker
        self._procrustes_preview = None
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
        self.procrustes_preview_status_label.setObjectName("status")
        self.procrustes_preview_status_label.setStyleSheet("")
        self.procrustes_preview_status_label.setText(
            "Landmarks and meshes are being hashed and aligned read-only outside the "
            "event loop. No file is being created or changed."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _procrustes_preview_succeeded(
        self,
        preview: LandmarkAlignmentPreview,
    ) -> None:
        self._worker = None
        self._procrustes_preview = preview
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        if not self._preview_matches_current_procrustes_inputs():
            self._procrustes_preview = None
            self.approve_procrustes_check.setChecked(False)
            self.approve_procrustes_check.setEnabled(False)
            self.procrustes_preview_status_label.setObjectName("statusWarning")
            self.procrustes_preview_status_label.setStyleSheet("")
            self.procrustes_preview_status_label.setText(
                "Preview discarded because its path, file pattern, or settings no longer "
                "match the form. No file was changed; run the preview again."
            )
            self._update_procrustes_controls()
            self._sync_ready_state()
            return

        alignment = preview.alignment
        residuals = sorted(alignment.residuals)
        midpoint = len(residuals) // 2
        median_residual = (
            residuals[midpoint]
            if len(residuals) % 2
            else (residuals[midpoint - 1] + residuals[midpoint]) / 2.0
        )
        scales = tuple(transform.scale for transform in alignment.transforms)
        final_iteration = alignment.history[-1]
        specimen_count = len(preview.source_paths)
        format_counts: dict[str, int] = {}
        for metadata in preview.source_metadata:
            format_counts[metadata.source_format] = format_counts.get(metadata.source_format, 0) + 1
        format_summary = ", ".join(
            f"{name.upper()}: {count}" for name, count in sorted(format_counts.items())
        )
        status = "converged" if alignment.converged else "did not converge"
        self.procrustes_preview_status_label.setObjectName(
            "statusSuccess" if alignment.converged else "statusError"
        )
        self.procrustes_preview_status_label.setStyleSheet("")
        self.procrustes_preview_status_label.setText(
            f"Read-only preview {status}: {specimen_count} meshes, "
            f"{len(preview.landmark_labels)} landmarks, "
            f"{len(alignment.history)} iterations ({alignment.termination_reason}).\n"
            f"Source formats: {format_summary}. Approved publication will preserve "
            "byte-identical raw copies and write aligned-vtk/*.vtk for both engines.\n"
            f"Final mean change: {final_iteration.mean_change:.6g}; total squared "
            f"residual: {final_iteration.total_squared_residual:.6g}.\n"
            f"Per-mesh squared residual min / median / max: "
            f"{residuals[0]:.6g} / {median_residual:.6g} / {residuals[-1]:.6g}.\n"
            f"Applied scale min / max: {min(scales):.6g} / {max(scales):.6g}.\n"
            f"Exact preview fingerprint: {preview.fingerprint}\n"
            "Raw meshes and the landmark CSV remain unchanged. This numerical preview "
            "does not establish biological landmark quality.\n"
            "Next: open the visual GPA review to inspect the transformed cohort before "
            "the approval checkbox becomes available."
        )
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot()
    def _open_procrustes_visual_review(self) -> None:
        preview = self._procrustes_preview
        if (
            self._worker is not None
            or preview is None
            or not preview.alignment.converged
            or not self._preview_matches_current_procrustes_inputs()
        ):
            return
        if (
            self._procrustes_visual is not None
            and self._procrustes_visual.fingerprint == preview.fingerprint
        ):
            self._show_loaded_procrustes_visual_review()
            return
        worker = _ProcrustesVisualWorker(preview)
        worker.signals.succeeded.connect(self._procrustes_visual_succeeded)
        worker.signals.failed.connect(self._procrustes_visual_failed)
        self._worker = worker
        self.review_procrustes_visual_button.setText("Loading visual GPA review...")
        self._update_procrustes_controls()
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _procrustes_visual_succeeded(self, visual: GpaAlignmentVisual) -> None:
        self._worker = None
        preview = self._procrustes_preview
        self.review_procrustes_visual_button.setText("Open visual GPA review...")
        if (
            preview is None
            or visual.fingerprint != preview.fingerprint
            or not self._preview_matches_current_procrustes_inputs()
        ):
            self._procrustes_visual = None
            self._procrustes_visual_reviewed_fingerprint = None
            self.approve_procrustes_check.setChecked(False)
            self.procrustes_preview_status_label.setObjectName("statusWarning")
            self.procrustes_preview_status_label.setStyleSheet("")
            self.procrustes_preview_status_label.setText(
                "Visual GPA preview discarded because the numerical preview or its "
                "inputs changed while meshes were loading. Run the alignment preview "
                "again; no file was created or changed."
            )
            self._update_procrustes_controls()
            self._sync_ready_state()
            return
        self._procrustes_visual = visual
        self._update_procrustes_controls()
        self._sync_ready_state()
        self._show_loaded_procrustes_visual_review()

    def _show_loaded_procrustes_visual_review(self) -> None:
        preview = self._procrustes_preview
        visual = self._procrustes_visual
        if preview is None or visual is None or preview.fingerprint != visual.fingerprint:
            return
        try:
            dialog = GpaAlignmentReviewDialog(preview, visual, self)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._procrustes_visual_failed(str(error))
            return
        dialog.previewInvalidated.connect(self._procrustes_visual_invalidated)
        result = dialog.exec()
        if (
            result == QDialog.DialogCode.Accepted
            and dialog.reviewed_fingerprint == preview.fingerprint
            and self._preview_matches_current_procrustes_inputs()
        ):
            self._procrustes_visual_reviewed_fingerprint = preview.fingerprint
            report = self.procrustes_preview_status_label.text()
            completion = (
                "Visual GPA review completed for this exact fingerprint. "
                f"The reviewer opened {dialog.viewed_mesh_count} individual mesh(es); "
                "the cohort overlay included every mesh."
            )
            if "Visual GPA review completed for this exact fingerprint." not in report:
                self.procrustes_preview_status_label.setText(f"{report}\n{completion}")
            self.approve_procrustes_check.setChecked(False)
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot(str)
    def _procrustes_visual_failed(self, message: str) -> None:
        if isinstance(self._worker, _ProcrustesVisualWorker):
            self._worker = None
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        self.review_procrustes_visual_button.setText("Open visual GPA review...")
        self.approve_procrustes_check.setChecked(False)
        report = self.procrustes_preview_status_label.text()
        self.procrustes_preview_status_label.setObjectName("statusError")
        self.procrustes_preview_status_label.setStyleSheet("")
        self.procrustes_preview_status_label.setText(
            f"{report}\nVisual GPA review could not be built: {message}\n"
            "Approval remains locked. No source or aligned file was created or changed."
        )
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot(str)
    def _procrustes_visual_invalidated(self, message: str) -> None:
        self._procrustes_preview = None
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
        self.procrustes_preview_status_label.setObjectName("statusError")
        self.procrustes_preview_status_label.setStyleSheet("")
        self.procrustes_preview_status_label.setText(
            f"{message}\nRun the numerical GPA preview again. No file was changed."
        )
        self._invalidate_reference_recommendation(
            "The visual GPA review detected changed inputs; analyze again.",
            sync=False,
        )
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot(str)
    def _procrustes_preview_failed(self, message: str) -> None:
        if isinstance(self._worker, _ProcrustesPreviewWorker):
            self._worker = None
        self._procrustes_preview = None
        self._procrustes_visual = None
        self._procrustes_visual_reviewed_fingerprint = None
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
        self.procrustes_preview_status_label.setObjectName("statusError")
        self.procrustes_preview_status_label.setStyleSheet("")
        self.procrustes_preview_status_label.setText(
            f"Alignment preview failed: {message}\n"
            "No aligned meshes or project files were created or changed."
        )
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot()
    def _choose_reference_preparation_approval(self) -> None:
        start = (
            str(self._review.config_path.parent)
            if self._review is not None
            else self.project_edit.text().strip()
        )
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select preparation-only approval",
            start,
            "JSON files (*.json)",
        )
        if selected:
            self.reference_preparation_approval_edit.setText(selected)

    @Slot()
    def _choose_saved_reference_status_report(self) -> None:
        current = self.saved_reference_status_report_edit.text().strip()
        start = str(Path(current).expanduser().parent) if current else ""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select saved preparation-status report",
            start,
            "JSON files (*.json)",
        )
        if selected:
            self.saved_reference_status_report_edit.setText(selected)

    @Slot()
    def _saved_reference_status_inputs_changed(self) -> None:
        self._saved_reference_preparation_status_verification = None
        self.saved_reference_status_verification_label.setObjectName("status")
        self.saved_reference_status_verification_label.setStyleSheet("")
        if isinstance(
            self._worker,
            _SavedReferencePreparationStatusVerificationWorker,
        ):
            message = (
                "Inputs changed during verification; the in-progress result will be discarded."
            )
        else:
            message = "No saved status report has been verified."
        self.saved_reference_status_verification_label.setText(message)
        self.saved_reference_status_verification_detail_label.setText(
            "This check reads only the selected report file. It opens no project, YAML, "
            "approval, run, container, or engine state and changes nothing."
        )
        self.saved_reference_status_verification_export_label.setObjectName("hint")
        self.saved_reference_status_verification_export_label.setStyleSheet("")
        self.saved_reference_status_verification_export_label.setText(
            "Evidence export is available only after a successful check that remains "
            "bound to the current inputs. The file contains private provenance."
        )
        self._sync_saved_reference_status_verification_controls()

    def _saved_reference_status_inputs_valid(self) -> bool:
        digest = self.saved_reference_status_hash_edit.text().strip().lower()
        return bool(
            self.saved_reference_status_report_edit.text().strip()
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
        )

    def _saved_reference_status_worker_matches_inputs(
        self,
        worker: _SavedReferencePreparationStatusVerificationWorker,
    ) -> bool:
        report_text = self.saved_reference_status_report_edit.text().strip()
        digest = self.saved_reference_status_hash_edit.text().strip().lower()
        return bool(
            report_text
            and Path(report_text).expanduser().resolve()
            == worker.report_path.expanduser().resolve()
            and digest == worker.expected_report_sha256.strip().lower()
        )

    def _sync_saved_reference_status_verification_controls(self) -> None:
        self.verify_saved_reference_status_button.setEnabled(
            self._saved_reference_status_inputs_valid() and self._worker is None
        )
        self.export_saved_reference_status_verification_button.setEnabled(
            self._saved_reference_status_result_matches_inputs() and self._worker is None
        )

    def _saved_reference_status_result_matches_inputs(self) -> bool:
        result = self._saved_reference_preparation_status_verification
        report_text = self.saved_reference_status_report_edit.text().strip()
        return bool(
            result is not None
            and report_text
            and result.report_path == Path(report_text).expanduser().resolve()
            and result.expected_report_sha256
            == self.saved_reference_status_hash_edit.text().strip().lower()
        )

    @Slot()
    def _reference_preparation_inputs_changed(self) -> None:
        self._reference_preparation_status = None
        self.reference_preparation_status_label.setObjectName("status")
        self.reference_preparation_status_label.setStyleSheet("")
        if isinstance(self._worker, _ReferencePreparationStatusWorker):
            message = (
                "Inputs changed during verification; the in-progress result will be discarded."
            )
        else:
            message = "No approval file has been checked read-only."
        self.reference_preparation_status_label.setText(message)
        self.reference_preparation_detail_label.setText(
            "This view checks only the exact approved destination and explicitly named "
            "private stages. It follows no links and changes nothing."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export is available only after a successful check. The complete report contains "
            "absolute paths and file names and must be treated as private provenance."
        )
        self._sync_reference_preparation_status_controls()

    def _reference_preparation_inputs_valid(self) -> bool:
        digest = self.reference_preparation_hash_edit.text().strip().lower()
        return bool(
            self.reference_preparation_approval_edit.text().strip()
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
        )

    def _sync_reference_preparation_status_controls(self) -> None:
        ready = bool(
            self._review is not None
            and self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
            and self._reference_preparation_inputs_valid()
            and self._worker is None
        )
        self.refresh_reference_preparation_status_button.setEnabled(ready)
        self.export_reference_preparation_status_button.setEnabled(
            self._reference_preparation_status_matches_inputs() and self._worker is None
        )

    def _reference_preparation_status_matches_inputs(self) -> bool:
        status = self._reference_preparation_status
        review = self._review
        approval_text = self.reference_preparation_approval_edit.text().strip()
        return bool(
            status is not None
            and review is not None
            and review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
            and status.config_path == review.config_path.resolve()
            and status.config_sha256 == review.config_sha256
            and approval_text
            and status.approval_path == Path(approval_text).expanduser().resolve()
            and status.approval_sha256
            == self.reference_preparation_hash_edit.text().strip().lower()
        )

    @Slot()
    def _verify_saved_reference_status(self) -> None:
        if not self._saved_reference_status_inputs_valid() or self._worker is not None:
            return
        worker = _SavedReferencePreparationStatusVerificationWorker(
            Path(self.saved_reference_status_report_edit.text().strip()),
            self.saved_reference_status_hash_edit.text().strip(),
        )
        worker.signals.succeeded.connect(self._saved_reference_status_verification_succeeded)
        worker.signals.failed.connect(self._saved_reference_status_verification_failed)
        self._worker = worker
        self._saved_reference_preparation_status_verification = None
        self.saved_reference_status_verification_label.setObjectName("status")
        self.saved_reference_status_verification_label.setStyleSheet("")
        self.saved_reference_status_verification_label.setText(
            "File hash, strict JSON, schema, and deterministic bytes are being checked read-only…"
        )
        self.saved_reference_status_verification_detail_label.setText(
            "Current project, approval, run, container, and engine state is not read."
        )
        self.saved_reference_status_verification_export_label.setObjectName("hint")
        self.saved_reference_status_verification_export_label.setStyleSheet("")
        self.saved_reference_status_verification_export_label.setText(
            "Evidence export is locked until verification succeeds and remains bound to "
            "the exact same inputs."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _saved_reference_status_verification_succeeded(
        self,
        result: DesktopSavedReferencePreparationStatusVerification,
    ) -> None:
        worker = self._worker
        self._worker = None
        if (
            not isinstance(
                worker,
                _SavedReferencePreparationStatusVerificationWorker,
            )
            or not self._saved_reference_status_worker_matches_inputs(worker)
            or not isinstance(
                result,
                DesktopSavedReferencePreparationStatusVerification,
            )
            or result.report_path != worker.report_path.expanduser().resolve()
            or result.expected_report_sha256 != worker.expected_report_sha256.strip().lower()
        ):
            self._saved_reference_preparation_status_verification = None
            self.saved_reference_status_verification_label.setObjectName("statusError")
            self.saved_reference_status_verification_label.setStyleSheet("")
            self.saved_reference_status_verification_label.setText(
                "Verification result discarded because the report path or hash input no "
                "longer matches exactly."
            )
            self.saved_reference_status_verification_detail_label.setText(
                "Nothing was changed. Verify again with the current inputs."
            )
            self.saved_reference_status_verification_export_label.setObjectName("statusError")
            self.saved_reference_status_verification_export_label.setStyleSheet("")
            self.saved_reference_status_verification_export_label.setText(
                "No evidence export: the discarded result is no longer bound to the current inputs."
            )
            self._sync_ready_state()
            return

        self._saved_reference_preparation_status_verification = result
        engine_started = (
            "no" if result.engine_execution_started is False else "not observed in the saved status"
        )
        details = [
            f"Report: {self._wrappable_path(result.report_path)}",
            f"Bytes: {result.report_byte_count}",
            f"Report-SHA-256: {result.report_sha256}",
            f"Report-Schema: {result.report_schema_version}",
            f"Recorded status: {result.report_status}",
            f"Recorded action required: {'yes' if result.action_required else 'no'}",
            "Deterministic DiffeoForge serialization: yes",
            f"Run-ID: {result.run_id}",
            f"Approval-SHA-256: {result.approval_sha256}",
            f"Plan-Fingerprint: {result.plan_fingerprint}",
            f"Recorded destination status: {result.destination_status}",
            f"Recorded engine execution: {engine_started}",
            f"Recorded private stages: {result.private_stage_count}",
            f"Verification-Schema: {result.verification_schema_version}",
            f"DiffeoForge-Verifier: {result.verifier_version}",
            f"Evidence-Bytes: {result.evidence_byte_count}",
            f"Evidence-SHA-256: {result.evidence_sha256}",
            f"Complete checks: {len(result.checks)}",
            "Report unchanged during verification: yes",
            "Mutation by this verification: no",
            f"Boundary: {result.scientific_boundary}",
        ]
        if result.manifest_sha256 is not None:
            details.insert(12, f"Manifest-SHA-256: {result.manifest_sha256}")
        self.saved_reference_status_verification_detail_label.setText("\n".join(details))
        self.saved_reference_status_verification_label.setObjectName("statusSuccess")
        self.saved_reference_status_verification_label.setStyleSheet("")
        self.saved_reference_status_verification_label.setText(
            "Saved status report exactly matches the external SHA-256, schema, and "
            "deterministic serialization."
        )
        self.saved_reference_status_verification_export_label.setObjectName("hint")
        self.saved_reference_status_verification_export_label.setStyleSheet("")
        self.saved_reference_status_verification_export_label.setText(
            "Evidence export ready: exactly the ASCII JSON bytes hashed above will be "
            "written to a new file. Review private provenance before sharing."
        )
        self._sync_ready_state()

    @Slot(str)
    def _saved_reference_status_verification_failed(self, message: str) -> None:
        worker = self._worker
        self._worker = None
        inputs_match = isinstance(
            worker,
            _SavedReferencePreparationStatusVerificationWorker,
        ) and self._saved_reference_status_worker_matches_inputs(worker)
        self._saved_reference_preparation_status_verification = None
        self.saved_reference_status_verification_label.setObjectName("statusError")
        self.saved_reference_status_verification_label.setStyleSheet("")
        if inputs_match:
            self.saved_reference_status_verification_label.setText(
                f"Saved status report cannot be verified safely: {message}"
            )
        else:
            self.saved_reference_status_verification_label.setText(
                "Failure result discarded because the report path or hash input changed."
            )
        self.saved_reference_status_verification_detail_label.setText(
            "No artifact release. No file was repaired or modified, and no project, run, "
            "container, or engine state was read."
        )
        self.saved_reference_status_verification_export_label.setObjectName("statusError")
        self.saved_reference_status_verification_export_label.setStyleSheet("")
        self.saved_reference_status_verification_export_label.setText(
            "No evidence export without a currently bound, fully validated verification."
        )
        self._sync_ready_state()

    @Slot()
    def _export_saved_reference_status_verification(self) -> None:
        result = self._saved_reference_preparation_status_verification
        if (
            result is None
            or not self._saved_reference_status_result_matches_inputs()
            or self._worker is not None
        ):
            self._sync_saved_reference_status_verification_controls()
            return
        default = result.report_path.parent / (
            f"reference-preparation-status-verification-{result.run_id}.json"
        )
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select a new verification-evidence file (no overwrite)",
            str(default),
            "JSON files (*.json)",
        )
        if not selected:
            return
        if not self._saved_reference_status_result_matches_inputs():
            self.saved_reference_status_verification_export_label.setObjectName("statusError")
            self.saved_reference_status_verification_export_label.setStyleSheet("")
            self.saved_reference_status_verification_export_label.setText(
                "Evidence export discarded because the report path or hash input no longer "
                "matches the verified evidence exactly."
            )
            self._sync_saved_reference_status_verification_controls()
            return
        try:
            exported = export_saved_reference_preparation_status_verification(
                result,
                selected,
            )
        except (
            DesktopSavedReferencePreparationStatusVerificationExportError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            self.saved_reference_status_verification_export_label.setObjectName("statusError")
            self.saved_reference_status_verification_export_label.setStyleSheet("")
            self.saved_reference_status_verification_export_label.setText(
                f"Verification evidence was not exported: {error}"
            )
            self._sync_saved_reference_status_verification_controls()
            return
        self.saved_reference_status_verification_export_label.setObjectName("statusSuccess")
        self.saved_reference_status_verification_export_label.setStyleSheet("")
        self.saved_reference_status_verification_export_label.setText(
            f"New verification evidence written: "
            f"{self._wrappable_path(exported.path)}\n"
            f"Schema: {exported.schema_version} · Bytes: {exported.byte_count} · "
            f"SHA-256: {exported.sha256}\n"
            "Private provenance; no project, run, or engine file was modified."
        )
        self._sync_saved_reference_status_verification_controls()

    @Slot()
    def _detect_template_from_text(self) -> None:
        mesh_text = self.mesh_edit.text().strip()
        if not mesh_text or self.template_edit.text().strip():
            return
        try:
            template = detect_template(mesh_text)
        except ValueError:
            return
        if template is not None:
            self.template_edit.setText(str(template))
            self._adopt_template_format_pattern(template)

    def _adopt_template_format_pattern(self, template: Path) -> None:
        """Follow a newly selected format while preserving an explicit custom glob."""

        current = self.pattern_edit.text().strip().casefold()
        if current in _DEFAULT_SURFACE_PATTERNS:
            self.pattern_edit.setText(f"*{template.suffix.casefold()}")

    @staticmethod
    def _length_spin_box(tooltip: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(8)
        spin.setRange(0.00000001, 1_000_000_000.0)
        spin.setSingleStep(0.01)
        spin.setSuffix(" coordinate units")
        spin.setToolTip(tooltip)
        return spin

    def _parameter_help(
        self,
        key: str,
        parameter_name: str,
    ) -> _ExpandableParameterHelp:
        help_panel = _ExpandableParameterHelp(
            parameter_name,
            DEFORMETRICA_PARAMETER_GUIDANCE[key],
        )
        help_panel.setObjectName(f"parameterHelp_{key}")
        self.reference_parameter_help_panels[key] = help_panel
        return help_panel

    def _parameter_field_with_help(
        self,
        widget: QWidget,
        *,
        key: str,
        parameter_name: str,
    ) -> QWidget:
        field = QWidget()
        field.setObjectName(f"parameterField_{key}")
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(widget)
        layout.addWidget(self._parameter_help(key, parameter_name))
        self._reference_parameter_field_pairs.append((widget, field))
        return field

    def _reference_parameter_field(self, widget: QWidget) -> QWidget:
        for candidate, field in self._reference_parameter_field_pairs:
            if candidate is widget:
                return field
        raise LookupError("No parameter field is registered for the requested widget")

    def _reference_parameter_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.reference_attachment_ratio_spin,
            self.reference_deformation_ratio_spin,
            self.reference_control_spacing_ratio_spin,
            self.reference_noise_ratio_spin,
            self.reference_max_iterations_spin,
            self.reference_step_size_spin,
            self.reference_tolerance_spin,
        )

    def _set_reference_parameter_fields_visible(self, visible: bool) -> None:
        for widget in self._reference_parameter_widgets():
            widget.setVisible(visible)
            field = self._reference_parameter_field(widget)
            field.setVisible(visible)
            label = self.reference_parameter_form.labelForField(field)
            if label is not None:
                label.setVisible(visible)
        self.reference_effective_widths_label.setVisible(visible)

    def _reference_coordinate_labels(self) -> tuple[str, str]:
        recommendation = self._reference_recommendation
        if (
            recommendation is not None
            and recommendation.alignment_basis == "diffeoforge_gpa"
            and self._procrustes_preview is not None
            and self._procrustes_preview.scale_to_unit_centroid_size
        ):
            return "normalized unit-centroid-size coordinates", " normalized units"
        unit = str(self.units_combo.currentData() or "unitless")
        labels = {
            "unitless": ("mesh coordinate units", " coordinate units"),
            "micrometer": ("micrometers", " micrometers"),
            "millimeter": ("millimeters", " mm"),
            "centimeter": ("centimeters", " cm"),
            "meter": ("meters", " m"),
        }
        return labels.get(unit, ("mesh coordinate units", " coordinate units"))

    @Slot()
    def _update_reference_effective_widths(self) -> None:
        recommendation = self._reference_recommendation
        if recommendation is None:
            self.reference_effective_widths_label.setText(
                "There is no single KW: attachment KW controls matching detail; "
                "deformation KW controls deformation smoothness. Analyze the aligned "
                "meshes before choosing absolute values."
            )
            return
        diagonal = recommendation.template_diagonal
        coordinate_label, suffix = self._reference_coordinate_labels()
        length_spins = (
            self.reference_attachment_ratio_spin,
            self.reference_deformation_ratio_spin,
            self.reference_control_spacing_ratio_spin,
            self.reference_noise_ratio_spin,
        )
        for spin in length_spins:
            spin.setSuffix(suffix)
            spin.setSingleStep(max(diagonal / 1000.0, 0.00000001))
        attachment = self.reference_attachment_ratio_spin.value()
        deformation = self.reference_deformation_ratio_spin.value()
        control_spacing = self.reference_control_spacing_ratio_spin.value()
        noise = self.reference_noise_ratio_spin.value()
        self.reference_effective_widths_label.setText(
            f"Absolute values in {coordinate_label}; template diagonal {diagonal:.6g}. "
            f"Attachment KW {attachment:.6g} "
            f"({100.0 * attachment / diagonal:.3g}% of diagonal) | "
            f"deformation KW {deformation:.6g} "
            f"({100.0 * deformation / diagonal:.3g}%) | "
            f"control-point spacing {control_spacing:.6g} "
            f"({100.0 * control_spacing / diagonal:.3g}%) | "
            f"noise SD {noise:.6g} ({100.0 * noise / diagonal:.3g}%)"
        )

    @Slot()
    def _update_reference_parameter_profile(self) -> None:
        key = str(self.reference_parameter_profile_combo.currentData())
        calibrated = self._reference_calibration_completed()
        self.reference_parameter_profile_combo.setEnabled(not calibrated)
        self.reference_expert_toggle.setEnabled(not calibrated)
        for expert_widget in self._reference_expert_widgets:
            expert_widget.setEnabled(not calibrated)
        if not calibrated:
            self._update_reference_expert_dependencies()
        if key == "pending":
            self._set_reference_parameter_fields_visible(False)
            self.reference_parameter_section_label.setText(
                "Final parameter values — complete the pilot calibration first"
            )
            self.reference_parameter_hint.setText(
                "No parameter values are active. Confirm existing GPA alignment or complete "
                "the DiffeoForge landmark-GPA preview, then analyze the aligned meshes."
            )
            self._update_reference_effective_widths()
            self._sync_ready_state()
            return

        recommendation = self._reference_recommendation
        if key == "data_assisted":
            if recommendation is None:
                self._set_reference_parameter_fields_visible(False)
                self.reference_parameter_section_label.setText(
                    "Final parameter values — aligned-mesh analysis required"
                )
                self.reference_parameter_hint.setText(
                    "No current aligned-mesh recommendation is available. Run the geometry "
                    "analysis again or choose Advanced manual control."
                )
                self._update_reference_effective_widths()
                self._sync_ready_state()
                return
            effective = recommendation.effective_values
            values = (
                (
                    self.reference_attachment_ratio_spin,
                    effective["attachment_kernel_width"],
                ),
                (
                    self.reference_deformation_ratio_spin,
                    effective["deformation_kernel_width"],
                ),
                (
                    self.reference_control_spacing_ratio_spin,
                    effective["initial_control_point_spacing"],
                ),
                (
                    self.reference_noise_ratio_spin,
                    effective["noise_std"],
                ),
                (self.reference_max_iterations_spin, recommendation.max_iterations),
                (self.reference_step_size_spin, recommendation.initial_step_size),
                (
                    self.reference_tolerance_spin,
                    recommendation.convergence_tolerance,
                ),
            )
            self._set_reference_parameter_fields_visible(True)
            if not calibrated:
                for widget, value in values:
                    widget.setValue(value)
            for widget, _value in values:
                widget.setEnabled(False)
            if calibrated:
                for expert_widget in self._reference_expert_widgets:
                    expert_widget.setEnabled(False)
            if calibrated:
                self.reference_parameter_section_label.setText(
                    "Final pilot-calibrated parameter values"
                )
                self.reference_parameter_hint.setText(
                    "These read-only values are the candidate selections you approved "
                    "during the staged pilot calibration. They are the values sent to "
                    "Step 3 for final full-cohort review."
                )
            else:
                self.reference_parameter_section_label.setText(
                    "Provisional starting values — pilot calibration still required"
                )
                self.reference_parameter_hint.setText(
                    "These geometry-derived values only center the pilot comparisons. "
                    "They are deliberately locked and are not yet the final atlas "
                    "parameters. Complete Steps 2 and 3 above."
                )
            self._update_reference_effective_widths()
            self._sync_ready_state()
            return

        if recommendation is None:
            self._set_reference_parameter_fields_visible(False)
            self.reference_parameter_section_label.setText(
                "Advanced manual parameters — aligned-mesh analysis required"
            )
            self.reference_parameter_hint.setText(
                "Analyze the aligned meshes first. DiffeoForge needs their measured "
                "coordinate scale before manual kernel widths can be entered in intuitive "
                "absolute units."
            )
            self._update_reference_effective_widths()
            self._sync_ready_state()
            return
        self._set_reference_parameter_fields_visible(True)
        for widget in self._reference_parameter_widgets():
            widget.setEnabled(True)
        if key == "advanced":
            self.reference_parameter_section_label.setText(
                "Advanced manual parameters — pilot calibration will be skipped"
            )
            self.reference_parameter_hint.setText(
                "Advanced values are editable in the mesh coordinate system. DiffeoForge "
                "also records each value as a percentage of the measured template diagonal "
                "for reproducibility. This explicitly bypasses the guided pilot-calibration "
                "requirement; the full-cohort result still requires scientific validation."
            )
        self._update_reference_effective_widths()
        self._sync_ready_state()

    @Slot()
    def _update_reference_expert_visibility(self) -> None:
        self.reference_expert_box.setVisible(self.reference_expert_toggle.isChecked())

    @Slot()
    def _update_reference_expert_dependencies(self) -> None:
        self.reference_sobolev_ratio_spin.setEnabled(self.reference_sobolev_check.isChecked())

    @Slot()
    def _update_engine_explanation(self) -> None:
        modern = self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
        self.landmarks_edit.setEnabled(True)
        self.landmarks_button.setEnabled(True)
        self.parameter_input_form.setRowVisible(self.pairwise_box, modern)
        self.parameter_input_form.setRowVisible(self.optimization_effort_box, modern)
        self.parameter_input_form.setRowVisible(self.modern_device_box, modern)
        self.parameter_input_form.setRowVisible(self.modern_gradient_box, modern)
        self.data_input_form.setRowVisible(self.already_gpa_check, not modern)
        self.parameter_input_form.setRowVisible(self.reference_guidance_box, not modern)
        self.parameter_input_form.setRowVisible(self.reference_parameter_box, not modern)
        if modern:
            self.engine_hint.setText(
                "Evidence-gated Modern engine. CPU/float64 is contained in the app; CUDA is "
                "started only through a separately verified local runtime. PCA is part "
                "of the verified result bundle."
            )
        else:
            self.engine_hint.setText(
                "Deformetrica 4.3 is the recommended numerical backend. Optional landmark "
                "Procrustes is performed by DiffeoForge first; its verified execution "
                "environment is "
                "managed automatically."
            )
        self._update_pairwise_explanation()
        self._update_optimization_explanation()
        self._update_modern_execution_explanation()
        self._update_reference_parameter_profile()
        self._update_reference_guidance_controls()

    @Slot()
    def _update_modern_execution_explanation(self) -> None:
        modern = self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
        sobolev = self.modern_template_gradient_combo.currentData() == "sobolev"
        self.modern_sobolev_ratio_spin.setVisible(modern and sobolev)
        if not modern:
            return
        if self.modern_device_combo.currentData() == "cuda":
            self.modern_device_hint.setText(
                "Requires a read-only verified CUDA-capable DiffeoForge runtime. "
                "Project review blocks execution if CUDA, the device, or Engine 1.8 "
                "cannot be verified; the CPU installer never pretends to provide CUDA."
            )
        else:
            self.modern_device_hint.setText(
                "Uses the contained CPU/float64 worker shipped with DiffeoForge."
            )
        if sobolev:
            self.modern_gradient_hint.setText(
                "Smooths each template update with the deformation-kernel Gaussian. "
                "Ratio 1.0 passed the prospective 236-subject Trochanter engineering "
                "gate, but remains anatomy-specific evidence rather than a universal preset."
            )
        else:
            self.modern_gradient_hint.setText(
                "Uses the raw template gradient and preserves the established Modern "
                "baseline. The 236-subject Euclidean arm also passed its frozen gate."
            )

    @Slot()
    def _update_pairwise_explanation(self) -> None:
        if self.engine_combo.currentData() != DesktopEngine.MODERN_CPU:
            self.pairwise_hint.setText(
                "Pairwise execution is configured inside the external Deformetrica route."
            )
            return
        if self.pairwise_combo.currentData() == "blockwise_256":
            self.pairwise_hint.setText(
                "Exact same all-pairs mathematics in explicit tiles. This bounds one "
                "pairwise allocation, not total RAM or computation time; benchmark "
                "representative meshes before production."
            )
            return
        self.pairwise_hint.setText(
            "Full pair matrices provide the correctness baseline and are intended for "
            "small pilot meshes."
        )

    @Slot()
    def _update_optimization_explanation(self) -> None:
        if self.engine_combo.currentData() != DesktopEngine.MODERN_CPU:
            self.optimization_effort_hint.setText(
                "Optimization settings are defined by the external Deformetrica configuration."
            )
            return
        if self.optimization_effort_combo.currentData() == 50:
            self.optimization_effort_hint.setText(
                "Runs up to 50 complete block cycles but stops earlier at the gradient "
                "tolerance. This may take much longer and still does not guarantee convergence."
            )
            return
        self.optimization_effort_hint.setText(
            "Fast end-to-end software check. Reaching the three-cycle cap is expected and "
            "must not be interpreted as optimizer convergence."
        )

    def _step_is_unlocked(self, step: int) -> bool:
        if self._worker is not None:
            return False
        if step == 0:
            return True
        if step == 1:
            return bool(
                self._data_inputs_ready()
                or self._result is not None
                or self._review is not None
                or self._run_result is not None
                or self._result_review is not None
            )
        if step == 2:
            return self._review is not None
        if step == 3:
            if self._run_result is not None or self._result_review is not None:
                return True
            if self._review is None:
                return False
            if self._review.engine is DesktopEngine.MODERN_CPU:
                return True
            if (
                self._reference_run_request is not None
                and self._reference_run_request.resume_source is not None
            ):
                return True
            return bool(self._reference_readiness is not None and self._reference_readiness.ready)
        if step == 4:
            return self._result_review is not None
        return False

    def _sync_navigation_state(self) -> None:
        locked_reasons = (
            "Select the required data and coordinate unit in Step 1 first.",
            "Create and verify the parameterized project in Step 2 first.",
            "Complete parameter review in Step 3 before atlas computation.",
            "Complete and verify an atlas run before opening Results & PCA.",
        )
        for index, button in enumerate(self.rail_steps):
            unlocked = self._step_is_unlocked(index)
            button.setEnabled(unlocked)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor if unlocked else Qt.CursorShape.ArrowCursor
            )
            if index == self._active_step:
                button.setObjectName("stepActive")
            elif unlocked:
                button.setObjectName("stepAvailable")
            else:
                button.setObjectName("stepFuture")
            if self._worker is not None:
                button.setToolTip(
                    "Navigation is locked while DiffeoForge completes the current operation."
                )
            elif unlocked:
                button.setToolTip(f"Open {button.property('stepLabel')}.")
            elif index > 0:
                button.setToolTip(locked_reasons[index - 1])
            else:
                button.setToolTip("")
            button.setStyleSheet("")

    def _data_inputs_ready(self) -> bool:
        return bool(
            self.mesh_edit.text().strip()
            and self.project_edit.text().strip()
            and self.units_combo.currentData() is not None
        )

    def _sync_setup_primary_action(self, *, form_ready: bool) -> None:
        if isinstance(self._worker, _ProjectWorker):
            self.create_button.setText("Validating data…")
            self.create_button.setEnabled(False)
        elif isinstance(self._worker, _ReviewWorker):
            self.create_button.setText("Reviewing parameters…")
            self.create_button.setEnabled(False)
        elif self._review is not None:
            if self._reference_calibration_pending():
                self.create_button.setText("Run or continue pilot calibration")
                self.create_button.setEnabled(
                    self._worker is None
                    and self._reference_readiness is not None
                    and self._reference_readiness.ready
                )
            else:
                self.create_button.setText("Continue to review parameters")
                self.create_button.setEnabled(self._worker is None)
        elif self._result is not None:
            self.create_button.setText("Generate parameter review")
            self.create_button.setEnabled(self._worker is None)
        else:
            approval_required = bool(
                self.landmarks_edit.text().strip()
                and self.procrustes_apply_check.isChecked()
                and self._approved_procrustes_fingerprint() is None
            )
            parameter_guidance_required = bool(
                self.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
                and (
                    self.reference_parameter_profile_combo.currentData() == "pending"
                    or (
                        self.reference_parameter_profile_combo.currentData()
                        in {"data_assisted", "advanced"}
                        and not self._reference_recommendation_matches_current_inputs()
                    )
                )
            )
            guided_reference = bool(
                self.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
                and self.reference_parameter_profile_combo.currentData() == "data_assisted"
                and self._reference_recommendation_matches_current_inputs()
                and not self._reference_calibration_completed()
            )
            if self._procrustes_preview is None:
                alignment_action = "Preview & approve alignment first"
            elif (
                self._procrustes_visual_reviewed_fingerprint != self._procrustes_preview.fingerprint
            ):
                alignment_action = "Complete visual GPA review first"
            else:
                alignment_action = "Approve reviewed alignment first"
            if approval_required:
                self.create_button.setText(alignment_action)
                self.create_button.setEnabled(False)
            elif parameter_guidance_required:
                self.create_button.setText("Analyze aligned meshes")
                self.create_button.setEnabled(
                    self.analyze_reference_parameters_button.isEnabled()
                )
            elif guided_reference:
                plan_ready = self._reference_calibration_plan_matches_current_inputs()
                self.create_button.setText(
                    "Prepare & start pilot calibration"
                    if plan_ready
                    else "Build pilot calibration plan"
                )
                self.create_button.setEnabled(
                    bool(
                        self._worker is None
                        and (
                            plan_ready
                            or self._reference_recommendation_matches_current_inputs()
                        )
                    )
                )
            else:
                self.create_button.setText("Validate data & create project")
                self.create_button.setEnabled(form_ready and self._worker is None)

    def _sync_run_primary_action(self) -> None:
        if isinstance(self._worker, (_AtlasWorker, _RemoteAtlasWorker, _ReferenceAtlasWorker)):
            self.start_atlas_button.setText("Atlas computation running…")
            self.start_atlas_button.setEnabled(False)
        elif isinstance(self._worker, _ResultReviewWorker):
            self.start_atlas_button.setText("Verifying Results & PCA…")
            self.start_atlas_button.setEnabled(False)
        elif self._result_review is not None:
            self.start_atlas_button.setText("Open Results & PCA")
            self.start_atlas_button.setEnabled(self._worker is None)
        elif self._run_result is not None:
            if self._run_result.completed:
                self.start_atlas_button.setText("Continue to Results & PCA")
                self.start_atlas_button.setEnabled(self._worker is None)
        else:
            reference = bool(
                self._review is not None
                and self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
            )
            resume = bool(
                reference
                and self._reference_run_request is not None
                and self._reference_run_request.resume_source is not None
            )
            self.start_atlas_button.setText(
                "Resume interrupted Deformetrica run"
                if resume
                else (
                    "Start reviewed Deformetrica atlas"
                    if reference
                    else (
                        "Submit or reconnect remote Modern atlas"
                        if self._remote_execution_selected()
                        else "Start reviewed Modern atlas"
                    )
                )
            )
            self.start_atlas_button.setEnabled(
                bool(
                    self._worker is None
                    and (
                        self._reference_run_request is not None
                        if reference
                        else self._run_readiness is not None
                        and self._run_readiness.ready_for_worker
                        and self._remote_controls_ready()
                    )
                )
            )

    @Slot()
    def _sync_ready_state(self) -> None:
        approved_alignment = self._approved_procrustes_fingerprint()
        alignment_ready = bool(
            not self.landmarks_edit.text().strip()
            or not self.procrustes_apply_check.isChecked()
            or approved_alignment is not None
        )
        reference_profile = self.reference_parameter_profile_combo.currentData()
        reference_parameters_ready = bool(
            self.engine_combo.currentData() != DesktopEngine.DEFORMETRICA_REFERENCE
            or (
                reference_profile in {"data_assisted", "advanced"}
                and self._reference_recommendation_matches_current_inputs()
            )
        )
        ready = bool(self._data_inputs_ready() and alignment_ready and reference_parameters_ready)
        data_ready = self._data_inputs_ready()
        self.continue_parameter_button.setEnabled(data_ready and self._worker is None)
        if data_ready:
            self.data_status_label.setObjectName("statusSuccess")
            self.data_status_label.setText(
                "Required data locations and coordinate unit are present. "
                "Continue to parameter setting."
            )
        else:
            self.data_status_label.setObjectName("status")
            self.data_status_label.setText(
                "Enter a mesh folder, project folder, and coordinate unit."
            )
        self.data_status_label.setStyleSheet("")
        self._update_procrustes_controls()
        self._update_reference_guidance_controls()
        self._sync_setup_primary_action(form_ready=ready)
        self._sync_run_primary_action()
        self._sync_navigation_state()
        self._sync_reference_preparation_status_controls()
        self._sync_saved_reference_status_verification_controls()
        self.open_completed_run_button.setEnabled(self._worker is None)
        self.resume_interrupted_run_button.setEnabled(self._worker is None)
        self.recover_abandoned_run_button.setEnabled(self._worker is None)

    @Slot()
    def _select_completed_run(self) -> None:
        if self._worker is not None:
            return
        initial = self.project_edit.text().strip() or self.mesh_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select a completed run or DiffeoForge project folder",
            initial,
        )
        if not selected:
            return
        try:
            results = discover_completed_results(selected)
        except CompletedResultDiscoveryError as error:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"Completed runs could not be inspected: {error}")
            return
        if not results:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "No completed DiffeoForge run was found there. Select either the exact "
                "completed run folder or the project folder that contains its runs."
            )
            return
        result = results[0]
        if len(results) > 1:
            labels = [
                (f"{candidate.run_directory.name} — {candidate.run_directory.parent}")
                for candidate in results
            ]
            chosen, accepted = QInputDialog.getItem(
                self,
                "Choose completed run",
                "More than one completed run was found:",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            result = results[labels.index(chosen)]
        self._open_completed_result(result)

    @Slot()
    def _select_interrupted_run(self) -> None:
        if self._worker is not None:
            return
        initial = self.project_edit.text().strip() or self.mesh_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select an interrupted Deformetrica run or project folder",
            initial,
        )
        if not selected:
            return
        try:
            results = discover_resumable_reference_runs(selected)
        except ResumableResultDiscoveryError as error:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"Interrupted runs could not be inspected: {error}")
            return
        if not results:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "No fully verified interrupted Deformetrica run with an inventoried "
                "checkpoint was found there."
            )
            return
        result = results[0]
        if len(results) > 1:
            labels = [
                (
                    f"{candidate.run_directory.name} — {candidate.terminal_status} — "
                    f"{candidate.checkpoint_bytes:,} checkpoint bytes"
                )
                for candidate in results
            ]
            chosen, accepted = QInputDialog.getItem(
                self,
                "Choose interrupted run",
                "More than one resumable run was found:",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            result = results[labels.index(chosen)]
        self._prepare_reference_resume(result)

    @Slot()
    def _select_abandoned_run(self) -> None:
        if self._worker is not None:
            return
        initial = self.project_edit.text().strip() or self.mesh_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select a crashed Deformetrica run or project folder",
            initial,
        )
        if not selected:
            return
        try:
            results = discover_abandoned_reference_runs(selected)
        except ResumableResultDiscoveryError as error:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"Crashed runs could not be inspected: {error}")
            return
        if not results:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "No fully verified Deformetrica run left in the nonterminal 'started' "
                "state was found there."
            )
            return
        result = results[0]
        if len(results) > 1:
            labels = [
                (
                    f"{candidate.run_directory.name} â€” started {candidate.started_at} â€” "
                    + (
                        f"retained {candidate.retained_terminal_status} result"
                        if candidate.retained_terminal_status is not None
                        else (
                            f"{candidate.checkpoint_bytes:,} checkpoint bytes"
                            if candidate.checkpoint_bytes is not None
                            else "no checkpoint"
                        )
                    )
                )
                for candidate in results
            ]
            chosen, accepted = QInputDialog.getItem(
                self,
                "Choose crashed run",
                "More than one nonterminal run was found:",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            result = results[labels.index(chosen)]

        if result.retained_terminal_status is not None:
            checkpoint_detail = (
                f"A complete {result.retained_terminal_status} result is already present; "
                "recovery will verify it and reconcile only its missing lifecycle event."
            )
        elif result.checkpoint_bytes is not None:
            checkpoint_detail = (
                f"A {result.checkpoint_bytes:,}-byte checkpoint was verified."
            )
        else:
            checkpoint_detail = (
                "No checkpoint was found, so this run cannot be continued afterward."
            )
        choice = QMessageBox.warning(
            self,
            "Confirm Deformetrica is stopped",
            "Use crash recovery only after a power loss or hard process stop. Confirm "
            "that no DiffeoForge, Deformetrica, WSL, or container process is still "
            f"writing to this run:\n\n{result.run_directory}\n\n{checkpoint_detail}\n\n"
            "Recovery does not restart or overwrite output. It hashes the retained "
            "artifacts, reconciles any complete terminal result already present, or "
            "otherwise appends an interrupted terminal record.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        worker = _AbandonedReferenceRecoveryWorker(result)
        worker.signals.succeeded.connect(self._abandoned_recovery_succeeded)
        worker.signals.failed.connect(self._abandoned_recovery_failed)
        self._worker = worker
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Finalizing the stopped run and hashing retained output. Nothing is being "
            "restarted or overwrittenâ€¦"
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _abandoned_recovery_succeeded(self, recovered: RecoveredReferenceRun) -> None:
        self._worker = None
        if recovered.terminal_status == "completed":
            self.status_label.setObjectName("statusSuccess")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "The complete terminal result was already present and has now been "
                "reconciled with the lifecycle log. Reverification is starting."
            )
            self._open_completed_result(
                CompletedResultRun(recovered.run_directory, reference=True)
            )
            return
        if recovered.resumable is None:
            self.status_label.setObjectName("statusWarning")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "The stopped run is now recorded as interrupted, but no checkpoint was "
                "available. Its retained artifacts remain unchanged and it cannot be "
                "continued."
            )
            self._sync_ready_state()
            return
        self._prepare_reference_resume(recovered.resumable)

    @Slot(str)
    def _abandoned_recovery_failed(self, message: str) -> None:
        self._worker = None
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Crash recovery stopped without declaring the run terminal: " + message
        )
        self._sync_ready_state()

    def _prepare_reference_resume(self, result: ResumableReferenceRun) -> None:
        run_id = f"{result.run_directory.name[:100]}-resume-{uuid.uuid4().hex[:8]}"
        try:
            request = build_reference_resume_launch_request(
                result.run_directory,
                request_id=f"reference-resume-{uuid.uuid4().hex}",
                run_id=run_id,
            )
        except (
            DesktopReferencePrelaunchError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"Interrupted run cannot be resumed safely: {error}")
            return

        self._result = None
        self._run_readiness = None
        self._run_result = None
        self._result_review = None
        self._reference_readiness = None
        self._reference_run_request = request
        self._review = ProjectReviewResult(
            engine=DesktopEngine.DEFORMETRICA_REFERENCE,
            project_name=result.project_name,
            config_path=result.source_config_path,
            config_sha256=result.source_config_sha256,
            report_path=result.run_directory / "result-report.html",
            report_label="Interrupted Deformetrica run",
            subject_count=result.subject_count,
            parameters=(),
            workload=(),
            warnings=(
                "Resume restores parameters and iteration, but Deformetrica reinitializes "
                "the objective baseline, gradient, and line-search step sizes.",
            ),
            scientific_boundary=(
                "Checkpoint recovery preserves the model state but does not guarantee an "
                "identical optimizer trajectory."
            ),
        )
        self.run_title_label.setText("Resume interrupted Deformetrica atlas")
        self.run_subtitle_label.setText(
            "Create a new immutable successor from the verified checkpoint and continue "
            "the protected Deformetrica calculation."
        )
        self.run_boundary_label.setText(
            "The interrupted source remains unchanged. Parameters and iteration are "
            "restored; objective, gradient, and line-search state are reinitialized by "
            "Deformetrica 4.3."
        )
        self.run_summary_label.setText(
            f"Project: {result.project_name}\n"
            f"Interrupted source: {self._wrappable_path(result.run_directory)}\n"
            f"Checkpoint: {result.checkpoint_bytes:,} bytes\n"
            f"New immutable destination: {self._wrappable_path(request.destination)}"
        )
        self.run_readiness_status_label.setObjectName("statusSuccess")
        self.run_readiness_status_label.setStyleSheet("")
        self.run_readiness_status_label.setText(
            "Source manifest, protected inputs, terminal evidence, inventory, and "
            "checkpoint all verified."
        )
        self.run_readiness_detail_label.setText(
            f"Deformetrica installation: {launcher_label(request.launcher)}\n"
            "No source file was changed. Starting will create a new successor next to "
            "the interrupted run."
        )
        self.run_progress_bar.setRange(0, 1)
        self.run_progress_bar.setValue(0)
        self.run_progress_bar.setFormat("Recovery not started")
        self.run_optimizer_label.setText(
            "Runtime estimate unavailable for checkpoint recovery. Live timing begins "
            "when Deformetrica reports activity."
        )
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText("Ready; no successor or Deformetrica process has started.")
        self.run_result_card.hide()
        self.refresh_run_readiness_button.setEnabled(False)
        self._navigate_to_step(3)
        self._sync_ready_state()

    @Slot()
    def _start_reference_pca_deformations(self) -> None:
        review = self._result_review
        if (
            review is None
            or review.engine_route != "deformetrica_reference"
            or self._worker is not None
        ):
            return
        try:
            review.artifact("pca-mean-shape")
        except KeyError:
            pass
        else:
            self._sync_reference_pca_deformation_action(review)
            return
        choice = QMessageBox.warning(
            self,
            "Run Deformetrica PC shape generation",
            "DiffeoForge will run one separate Deformetrica compute Shooting operation "
            "for the mean and the negative and positive 2-SD endpoints of up to the "
            "first three retained PCs. It uses the exact source runtime, including its "
            "configured CPU/GPU device, and may take substantial time.\n\n"
            "The completed atlas and PCA remain unchanged. Only a new immutable result "
            "directory is published, and only after every endpoint passes verification.\n\n"
            "These shapes are visualizations, not biological validation. Start now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        worker = _ReferencePCADeformationWorker(review.run_directory)
        worker.signals.succeeded.connect(self._reference_pca_deformation_succeeded)
        worker.signals.failed.connect(self._reference_pca_deformation_failed)
        self._worker = worker
        self._reference_pca_deformation_started_at = time.monotonic()
        self._reference_pca_deformation_timer.start()
        self._set_result_controls_enabled(False)
        self.generate_reference_pca_deformations_button.setText(
            "Generating PC shape meshes…"
        )
        self.reference_pca_deformation_status_label.setObjectName("status")
        self.reference_pca_deformation_status_label.setStyleSheet("")
        self.reference_pca_deformation_status_label.setText(
            "Deformetrica Shooting is running in the background · elapsed 0 s. "
            "No endpoint is exposed before atomic publication and full verification."
        )
        self.result_status_label.setObjectName("status")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "Generating verified Deformetrica PC shape meshes in the background…"
        )
        self._thread_pool.start(worker)

    @Slot()
    def _update_reference_pca_deformation_elapsed(self) -> None:
        if self._reference_pca_deformation_started_at is None:
            self._reference_pca_deformation_timer.stop()
            return
        elapsed = time.monotonic() - self._reference_pca_deformation_started_at
        self.reference_pca_deformation_status_label.setText(
            "Deformetrica Shooting is running in the background · elapsed "
            f"{self._format_result_duration(elapsed)}. No endpoint is exposed before "
            "atomic publication and full verification."
        )

    @Slot(object)
    def _reference_pca_deformation_succeeded(self, _result: Path) -> None:
        review = self._result_review
        self._reference_pca_deformation_timer.stop()
        self._reference_pca_deformation_started_at = None
        if review is None:
            self._reference_pca_deformation_failed(
                "The source result review disappeared before final reverification"
            )
            return
        worker = _ResultReviewWorker(review.run_directory, reference=True)
        worker.signals.succeeded.connect(self._result_review_succeeded)
        worker.signals.failed.connect(self._reference_pca_deformation_reload_failed)
        self._worker = worker
        self.reference_pca_deformation_status_label.setObjectName("status")
        self.reference_pca_deformation_status_label.setStyleSheet("")
        self.reference_pca_deformation_status_label.setText(
            "Shooting completed. Rechecking the source run, PCA snapshot, new result "
            "inventory, hashes, topology, and every endpoint before viewer reload…"
        )
        self.result_status_label.setObjectName("status")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "PC shapes were published; the complete result snapshot is being reverified…"
        )
        self._thread_pool.start(worker)

    @Slot(str)
    def _reference_pca_deformation_reload_failed(self, message: str) -> None:
        self._reference_pca_deformation_failed(
            f"Shooting completed, but the refreshed result did not verify: {message}"
        )

    @Slot(str)
    def _reference_pca_deformation_failed(self, message: str) -> None:
        self._worker = None
        self._reference_pca_deformation_timer.stop()
        self._reference_pca_deformation_started_at = None
        self._set_result_controls_enabled(True)
        if self._result_review is not None:
            self._sync_reference_pca_deformation_action(self._result_review)
        self.reference_pca_deformation_status_label.setObjectName("statusError")
        self.reference_pca_deformation_status_label.setStyleSheet("")
        self.reference_pca_deformation_status_label.setText(
            f"PC shape generation did not produce a usable result: {message} "
            "Nothing was restarted automatically."
        )
        self.result_status_label.setObjectName("statusError")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "PC shape generation failed closed; the previously verified result remains "
            "loaded."
        )
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _sync_reference_pca_deformation_action(
        self,
        review: ModernResultReview | None,
    ) -> None:
        reference = review is not None and review.engine_route == "deformetrica_reference"
        self.reference_pca_deformation_card.setVisible(reference)
        if not reference or review is None:
            self.generate_reference_pca_deformations_button.setEnabled(False)
            return
        try:
            review.artifact("pca-mean-shape")
        except KeyError:
            generated = False
        else:
            generated = True
        self.generate_reference_pca_deformations_button.setText(
            "PC shape meshes generated"
            if generated
            else "Generate verified PC shape meshes…"
        )
        self.generate_reference_pca_deformations_button.setEnabled(
            not generated and self._worker is None
        )
        self.reference_pca_deformation_status_label.setObjectName(
            "statusSuccess" if generated else "status"
        )
        self.reference_pca_deformation_status_label.setStyleSheet("")
        self.reference_pca_deformation_status_label.setText(
            "Verified mean and ±PC endpoint meshes are loaded in the atlas viewer."
            if generated
            else (
                "No endpoint meshes exist yet. Starting creates a separate immutable "
                "Shooting result; it does not refit the atlas."
            )
        )

    @Slot()
    def _open_validation_lab(self) -> None:
        review = self._result_review
        if review is None or review.engine_route != "deformetrica_reference":
            QMessageBox.information(
                self,
                "Validation Lab unavailable",
                "Load a completed Deformetrica result first.",
            )
            return
        candidates: list[Path] = []
        if self._reference_calibrated_config_path is not None:
            candidates.append(self._reference_calibrated_config_path)
        try:
            report = collect_run_report(review.run_directory)
            candidates.extend(
                (
                    Path(str(report.manifest["source_config"]["path"])),
                    review.run_directory / "config" / "source-config.yaml",
                )
            )
            expected_sha256 = str(report.manifest["source_config"]["sha256"])
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            expected_sha256 = ""

        def calibrated_candidate(path: Path) -> bool:
            candidate = path.expanduser()
            if not candidate.is_file():
                return False
            try:
                if expected_sha256 and sha256_file(candidate) != expected_sha256:
                    return False
                config = load_config(candidate)
                result = (
                    config.get("project", {})
                    .get("parameter_provenance", {})
                    .get("recommendation", {})
                    .get("calibration_result", {})
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return False
            return result.get("status") == "completed"

        config_path = next(
            (
                path.expanduser().resolve()
                for path in candidates
                if calibrated_candidate(path)
            ),
            None,
        )
        if config_path is None:
            selected, _filter = QFileDialog.getOpenFileName(
                self,
                "Select the pilot-calibrated atlas configuration",
                str(review.run_directory),
                "DiffeoForge atlas configuration (atlas*.yaml *.yml)",
            )
            if not selected:
                return
            config_path = Path(selected).expanduser().resolve()
        digest = sha256_file(config_path)
        validation_root = config_path.parent
        if config_path.is_relative_to(review.run_directory):
            validation_root = review.run_directory.parent.parent
        study_directory = validation_root / "diffeoforge-validation-lab"
        if study_directory.exists():
            try:
                existing = load_reference_validation_study(study_directory)
            except (OSError, RuntimeError, TypeError, ValueError):
                study_directory = validation_root / (
                    f"diffeoforge-validation-lab-{digest[:10]}"
                )
            else:
                if existing.plan.source_config_sha256 != digest:
                    study_directory = validation_root / (
                        f"diffeoforge-validation-lab-{digest[:10]}"
                    )
        try:
            if not study_directory.exists():
                create_reference_validation_study(config_path, study_directory)
            dialog = ReferenceValidationDialog(study_directory, self)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Validation Lab could not be opened",
                str(error),
            )
            return
        dialog.exec()

    def _open_completed_result(self, result: CompletedResultRun) -> None:
        if self._worker is not None:
            return
        worker = _ResultReviewWorker(
            result.run_directory,
            reference=result.reference,
        )
        worker.signals.succeeded.connect(self._result_review_succeeded)
        worker.signals.failed.connect(self._completed_result_review_failed)
        self._worker = worker
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Reverifying the complete Deformetrica run and rebuilding its bound PCA snapshot…"
            if result.reference
            else "Reverifying the complete Modern workflow and result bundle…"
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot()
    def _setup_primary_action(self) -> None:
        if self._worker is not None:
            return
        if self._review is not None:
            if self._reference_calibration_pending():
                self._open_reference_calibration()
            else:
                self._navigate_to_step(2)
        elif self._result is not None:
            self._review_project()
        else:
            reference = (
                self.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
            )
            profile = self.reference_parameter_profile_combo.currentData()
            if reference and profile == "pending":
                self._analyze_reference_parameters()
            elif (
                reference
                and profile == "data_assisted"
                and self._reference_recommendation_matches_current_inputs()
                and not self._reference_calibration_completed()
            ):
                if self._reference_calibration_plan_matches_current_inputs():
                    self._prepare_or_open_reference_calibration()
                else:
                    self._build_reference_calibration_plan()
            else:
                self._create_project()

    @Slot()
    def _run_primary_action(self) -> None:
        if self._worker is not None:
            return
        if self._result_review is not None:
            self._navigate_to_step(4)
        elif self._run_result is not None:
            if self._run_result.completed:
                self._review_run_result()
        else:
            self._start_atlas()

    def _request(self) -> ProjectSetupRequest:
        template = self.template_edit.text().strip()
        landmarks = self.landmarks_edit.text().strip()
        apply_procrustes = bool(landmarks and self.procrustes_apply_check.isChecked())
        blockwise = bool(
            self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
            and self.pairwise_combo.currentData() == "blockwise_256"
        )
        reference_profile = str(self.reference_parameter_profile_combo.currentData())
        recommendation_inputs_are_current = bool(
            reference_profile in {"data_assisted", "advanced"}
            and self._reference_recommendation is not None
            and self._reference_recommendation_matches_current_inputs()
        )
        data_assisted_recommendation_is_current = bool(
            reference_profile == "data_assisted" and recommendation_inputs_are_current
        )
        if (
            self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
            and reference_profile == "pending"
        ):
            reference_profile = "recommended"
        if recommendation_inputs_are_current and self._reference_recommendation is not None:
            if reference_profile == "data_assisted":
                reference_ratios = self._reference_recommendation.parameter_ratios
            else:
                diagonal = self._reference_recommendation.template_diagonal
                reference_ratios = {
                    "attachment_kernel_width": (
                        self.reference_attachment_ratio_spin.value() / diagonal
                    ),
                    "deformation_kernel_width": (
                        self.reference_deformation_ratio_spin.value() / diagonal
                    ),
                    "initial_control_point_spacing": (
                        self.reference_control_spacing_ratio_spin.value() / diagonal
                    ),
                    "noise_std": self.reference_noise_ratio_spin.value() / diagonal,
                }
        else:
            reference_ratios = {
                "attachment_kernel_width": self.reference_attachment_ratio_spin.value(),
                "deformation_kernel_width": self.reference_deformation_ratio_spin.value(),
                "initial_control_point_spacing": (
                    self.reference_control_spacing_ratio_spin.value()
                ),
                "noise_std": self.reference_noise_ratio_spin.value(),
            }
        recommendation_provenance: dict[str, object] | None = None
        if data_assisted_recommendation_is_current and self._reference_recommendation is not None:
            recommendation_provenance = dict(self._reference_recommendation.provenance)
            if self._reference_calibration_plan_matches_current_inputs():
                assert self._reference_calibration_plan is not None
                recommendation_provenance["calibration_plan"] = (
                    self._reference_calibration_plan.provenance
                )
        return ProjectSetupRequest(
            mesh_directory=Path(self.mesh_edit.text().strip()),
            project_directory=Path(self.project_edit.text().strip()),
            units=self.units_combo.currentData(),
            engine=self.engine_combo.currentData(),
            template=Path(template) if template else None,
            project_name=self.name_edit.text().strip() or None,
            subject_pattern=self.pattern_edit.text(),
            landmarks_file=(Path(landmarks) if apply_procrustes else None),
            pairwise_mode="blockwise" if blockwise else "dense",
            query_tile_size=256 if blockwise else None,
            source_tile_size=256 if blockwise else None,
            max_cycles=int(self.optimization_effort_combo.currentData()),
            modern_runtime_device=str(self.modern_device_combo.currentData()),
            modern_template_gradient=str(
                self.modern_template_gradient_combo.currentData()
            ),
            modern_sobolev_kernel_width_ratio=(
                self.modern_sobolev_ratio_spin.value()
            ),
            reference_parameter_profile=reference_profile,
            reference_parameter_ratios=reference_ratios,
            reference_parameter_recommendation=recommendation_provenance,
            reference_max_iterations=self.reference_max_iterations_spin.value(),
            reference_initial_step_size=self.reference_step_size_spin.value(),
            reference_convergence_tolerance=self.reference_tolerance_spin.value(),
            reference_attachment_type=self.reference_attachment_type_combo.currentData(),
            reference_timepoints=self.reference_timepoints_spin.value(),
            reference_use_rk2=self.reference_rk2_check.isChecked(),
            reference_max_line_search_iterations=self.reference_line_search_spin.value(),
            reference_save_every_n_iterations=self.reference_save_every_spin.value(),
            reference_print_every_n_iterations=self.reference_print_every_spin.value(),
            reference_scale_initial_step_size=self.reference_scale_step_check.isChecked(),
            reference_use_sobolev_gradient=self.reference_sobolev_check.isChecked(),
            reference_sobolev_kernel_width_ratio=self.reference_sobolev_ratio_spin.value(),
            reference_freeze_template=self.reference_freeze_template_check.isChecked(),
            reference_freeze_control_points=(
                self.reference_freeze_control_points_check.isChecked()
            ),
            reference_acceleration=self.reference_acceleration_combo.currentData(),
            reference_threads=self.reference_threads_spin.value(),
            reference_random_seed=self.reference_random_seed_spin.value(),
            procrustes_scale_to_unit_centroid_size=self.procrustes_scale_check.isChecked(),
            procrustes_allow_reflection=self.procrustes_reflection_check.isChecked(),
            procrustes_tolerance=self.procrustes_tolerance_spin.value(),
            procrustes_max_iterations=self.procrustes_iterations_spin.value(),
            approved_procrustes_fingerprint=(
                self._approved_procrustes_fingerprint() if apply_procrustes else None
            ),
        )

    @staticmethod
    def _configuration_path(request: ProjectSetupRequest) -> Path:
        filename = (
            "modern-atlas.yaml" if request.engine == DesktopEngine.MODERN_CPU else "atlas.yaml"
        )
        return (request.project_directory / filename).expanduser().resolve()

    def _confirm_configuration_overwrite(self, config_path: Path) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Overwrite existing project configuration?")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            "A project configuration already exists at:\n"
            f"{config_path}\n\nAre you sure you want to overwrite it?"
        )
        dialog.setInformativeText(
            "Only a recognized DiffeoForge-generated configuration can be replaced. "
            "Generated workload evidence will be refreshed during Step 3. Source meshes, "
            "landmarks, and completed run directories will not be overwritten or removed."
        )
        cancel_button = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        overwrite_button = dialog.addButton(
            "Overwrite",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is overwrite_button

    @Slot()
    def _create_project(self) -> None:
        if (
            self.landmarks_edit.text().strip()
            and self.procrustes_apply_check.isChecked()
            and self._approved_procrustes_fingerprint() is None
        ):
            self.status_label.setObjectName("statusWarning")
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                "Run the read-only Procrustes preview and approve that exact result "
                "before creating the project."
            )
            self._sync_ready_state()
            return
        request = self._request()
        config_path = self._configuration_path(request)
        if config_path.exists():
            if not self._confirm_configuration_overwrite(config_path):
                self._guided_reference_calibration_requested = False
                self.status_label.setObjectName("status")
                self.status_label.setStyleSheet("")
                self.status_label.setText(
                    "Project creation cancelled; the existing configuration and all data "
                    "remain unchanged."
                )
                return
            request = replace(request, overwrite_existing_configuration=True)
        self.result_card.hide()
        self._result = None
        self._review = None
        self._template_preview = None
        self._reference_readiness = None
        self._reference_preparation_status = None
        self._run_readiness = None
        self._reference_run_request = None
        self._run_result = None
        self._result_review = None
        self._reference_calibration_study_directory = None
        self.template_preview_card.hide()
        self.reference_preparation_status_card.hide()
        self.reference_preparation_approval_edit.clear()
        self.reference_preparation_hash_edit.clear()
        self.template_preview_canvas.set_model(None)
        self.show_run_button.setEnabled(False)
        self.start_atlas_button.setEnabled(False)
        self.run_result_card.hide()
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText("Meshes and configuration are being validated…")
        self._worker = _ProjectWorker(request)
        self._worker.signals.succeeded.connect(self._project_succeeded)
        self._worker.signals.failed.connect(self._project_failed)
        self._sync_ready_state()
        self._thread_pool.start(self._worker)

    @Slot(object)
    def _project_succeeded(self, result: ProjectSetupResult) -> None:
        self._worker = None
        self._result = result
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            f"Validation passed: {result.subject_count} subject meshes were accepted."
        )
        report = f"\nPreflight report: {result.report_path}" if result.report_path else ""
        preprocessing = (
            f"\nProcrustes evidence: {result.preprocessing_report_path}"
            if result.preprocessing_report_path
            else ""
        )
        notices = "\n".join(f"• {notice}" for notice in result.notices)
        self.result_label.setText(
            f"Engine: {result.engine_label}\n"
            f"Template: {result.template_path}\n"
            f"Configuration: {result.config_path}{report}{preprocessing}\n\n"
            f"Important notices:\n{notices}"
        )
        self.result_card.show()
        self._sync_ready_state()
        if self._guided_reference_calibration_requested:
            QTimer.singleShot(0, self._review_project)

    @Slot(str)
    def _project_failed(self, message: str) -> None:
        self._worker = None
        self._guided_reference_calibration_requested = False
        if self._approved_procrustes_fingerprint() is not None:
            self._invalidate_procrustes_preview()
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Project could not be created: {message}")
        self._sync_ready_state()

    @Slot()
    def _review_project(self) -> None:
        if self._result is None or self._worker is not None:
            return
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Effective parameters and available workload evidence are being collected…"
        )
        self._worker = _ReviewWorker(self._result)
        self._worker.signals.succeeded.connect(self._review_worker_succeeded)
        self._worker.signals.failed.connect(self._review_failed)
        self._sync_ready_state()
        self._thread_pool.start(self._worker)

    @Slot(object)
    def _review_worker_succeeded(self, review: ProjectReviewResult) -> None:
        """Publish a review and start the reference safety check automatically."""

        self._review_succeeded(review)
        if review.engine is DesktopEngine.DEFORMETRICA_REFERENCE:
            self._check_reference_readiness()

    @Slot(object)
    def _review_succeeded(self, review: ProjectReviewResult) -> None:
        self._worker = None
        self._review = review
        self._template_preview = None
        self._reference_readiness = None
        self._reference_preparation_status = None
        self._run_readiness = None
        self._reference_run_request = None
        self.reference_preparation_approval_edit.clear()
        self.reference_preparation_hash_edit.clear()
        self._populate_review_rows(self.parameter_review_layout, review.parameters)
        self._populate_review_rows(self.workload_review_layout, review.workload)
        self.review_boundary_label.setText(review.scientific_boundary)
        engine_label = (
            (
                "DiffeoForge Modern CUDA (experimental)"
                if review.modern_cuda_runtime is not None
                else "DiffeoForge Modern CPU (experimental)"
            )
            if review.engine is DesktopEngine.MODERN_CPU
            else "Deformetrica 4.3 (managed installation)"
        )
        config_display = self._wrappable_path(review.config_path)
        report_display = self._wrappable_path(review.report_path)
        self.review_summary_label.setText(
            f"Project: {review.project_name}\n"
            f"Engine: {engine_label}\n"
            f"Subjects: {review.subject_count}\n"
            f"Configuration: {config_display}\n"
            f"Verified SHA-256: {review.config_sha256}\n"
            f"{review.report_label}: {report_display}"
        )
        self.review_warnings_label.setText("\n".join(f"• {warning}" for warning in review.warnings))
        self.open_review_report_button.setText(f"Open {review.report_label}")
        if (
            self._result is not None
            and self._result.config_path.resolve() == review.config_path.resolve()
        ):
            self.template_preview_card.show()
            self.template_preview_canvas.set_model(None)
            self.template_preview_plane_combo.setEnabled(False)
            self.refresh_template_preview_button.setEnabled(True)
            self.template_preview_status_label.setObjectName("status")
            self.template_preview_status_label.setStyleSheet("")
            self.template_preview_status_label.setText(
                "The read-only wireframe preview has not been loaded."
            )
            self.template_preview_detail_label.setText(
                f"Template: {self._wrappable_path(self._result.template_path)}\n"
                "This projection does not modify the mesh and does not replace "
                "3D inspection, mesh QC, or landmark picking."
            )
        else:
            self.template_preview_card.hide()
        if review.engine is DesktopEngine.MODERN_CPU:
            self.reference_readiness_card.hide()
            self.reference_preparation_status_card.hide()
            self.show_run_button.setText("Continue to atlas execution")
            self.show_run_button.setEnabled(True)
        else:
            self.reference_readiness_card.show()
            # Advanced approval/status evidence remains implemented for developer and
            # provenance audits, but it is not an end-user prerequisite.
            self.reference_preparation_status_card.hide()
            self.reference_readiness_status_label.setObjectName("status")
            self.reference_readiness_status_label.setStyleSheet("")
            self.reference_readiness_status_label.setText(
                "The automatic Deformetrica setup check is pending."
            )
            self.reference_readiness_detail_label.setText(
                "DiffeoForge will verify the installed engine and current system resources "
                "in the background. This is not an estimate of atlas computation time."
            )
            self.refresh_reference_readiness_button.setEnabled(True)
            self.reference_preparation_status_label.setObjectName("status")
            self.reference_preparation_status_label.setStyleSheet("")
            self.reference_preparation_status_label.setText(
                "No approval file has been checked read-only."
            )
            self.reference_preparation_detail_label.setText(
                "An approval file and independently recorded SHA-256 are required. "
                "The check changes, publishes, deletes, and starts nothing."
            )
            self.show_run_button.setText("Checking Deformetrica setup automatically…")
            self.show_run_button.setEnabled(False)
        self._refresh_reference_calibration_execution_card()
        self._set_active_step(1)
        self.page_stack.setCurrentIndex(1)
        self._sync_ready_state()

    @Slot()
    def _load_template_preview(self) -> None:
        if (
            self._result is None
            or self._review is None
            or self._result.config_path.resolve() != self._review.config_path.resolve()
            or self._template_preview_worker is not None
        ):
            return
        worker = _TemplatePreviewWorker(self._result.template_path.resolve())
        worker.signals.succeeded.connect(self._template_preview_succeeded)
        worker.signals.failed.connect(self._template_preview_failed)
        self._template_preview_worker = worker
        self._template_preview_scroll_value = self.review_scroll.verticalScrollBar().value()
        self.refresh_template_preview_button.clearFocus()
        self._template_preview = None
        self.template_preview_canvas.set_model(None)
        self.template_preview_plane_combo.setEnabled(False)
        self.refresh_template_preview_button.setEnabled(False)
        self.template_preview_status_label.setObjectName("status")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(
            "Template geometry and unique edges are being loaded read-only outside the event loop…"
        )
        self.template_preview_detail_label.setText(
            "The source file is hashed before and after loading. No points, faces, or files "
            "are modified."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _template_preview_succeeded(self, model: MeshPreviewModel) -> None:
        self._template_preview_worker = None
        if self._result is None or model.path.resolve() != self._result.template_path.resolve():
            self._template_preview_failed(
                "The loaded preview model does not belong to the current template"
            )
            return
        self._template_preview = model
        self.template_preview_plane_combo.setEnabled(True)
        self.refresh_template_preview_button.setEnabled(True)
        self._update_template_preview_plane(self.template_preview_plane_combo.currentIndex())
        self._restore_template_preview_scroll()
        self._sync_ready_state()

    @Slot(int)
    def _update_template_preview_plane(self, _index: int) -> None:
        model = self._template_preview
        if model is None:
            return
        plane = self.template_preview_plane_combo.currentData()
        try:
            projection = model.project(plane, edge_budget=DEFAULT_EDGE_BUDGET)
        except (MeshPreviewError, TypeError, ValueError) as error:
            self.template_preview_canvas.set_model(None)
            self.template_preview_status_label.setObjectName("statusError")
            self.template_preview_status_label.setStyleSheet("")
            self.template_preview_status_label.setText(
                f"{str(plane).upper()} projection cannot be displayed: {error}"
            )
            return

        self.template_preview_canvas.set_plane(plane)
        self.template_preview_canvas.set_model(model)
        sampling = (
            "deterministically subsampled display"
            if projection.sampled
            else "all unique edges displayed"
        )
        bounds = ", ".join(f"{value:.6g}" for value in model.bounds)
        self.template_preview_detail_label.setText(
            f"Template: {self._wrappable_path(model.path)}\n"
            f"SHA-256: {model.sha256}\n"
            f"Geometry: {model.point_count} points · {model.triangle_count} triangles · "
            f"{model.edge_count} unique edges\n"
            f"Bounds (xmin, xmax, ymin, ymax, zmin, zmax): {bounds}\n"
            f"Display: {projection.displayed_edge_count} of "
            f"{projection.total_edge_count} edges · {sampling}.\n"
            "Orthographic inspection preview only; not a 3D, QC, registration, landmark, "
            "or biological assessment."
        )
        self.template_preview_status_label.setObjectName("statusSuccess")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(
            f"{str(plane).upper()} wireframe rendered from the unchanged template."
        )

    @Slot(str)
    def _template_preview_failed(self, message: str) -> None:
        self._template_preview_worker = None
        self._template_preview = None
        self.template_preview_canvas.set_model(None)
        self.template_preview_plane_combo.setEnabled(False)
        self.refresh_template_preview_button.setEnabled(
            self._result is not None and self._review is not None
        )
        self.template_preview_status_label.setObjectName("statusError")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(f"Template preview was not loaded: {message}")
        self.template_preview_detail_label.setText(
            "No preview released; the template file was not modified."
        )
        self._restore_template_preview_scroll()
        self._sync_ready_state()

    def _restore_template_preview_scroll(self) -> None:
        value = self._template_preview_scroll_value
        self._template_preview_scroll_value = None
        if value is None:
            return
        QTimer.singleShot(
            0,
            lambda saved=value: self.review_scroll.verticalScrollBar().setValue(saved),
        )

    def _reference_calibration_context(
        self,
    ) -> tuple[ReferenceCalibrationPlan, Path] | None:
        review = self._review
        if review is None or review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE:
            return None
        try:
            config = load_config(review.config_path)
            stored = config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"]
            plan = reference_calibration_plan_from_provenance(stored)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            return None
        directory = self._reference_calibration_study_directory
        if directory is None:
            directory = (
                review.config_path.parent
                / "calibration"
                / f"reference-pilot-{plan.fingerprint[:12]}"
            ).resolve()
            self._reference_calibration_study_directory = directory
        return plan, directory

    def _reference_calibration_pending(self) -> bool:
        context = self._reference_calibration_context()
        if context is None:
            return False
        _plan, directory = context
        if not directory.exists():
            return True
        try:
            snapshot = load_reference_calibration_study(directory)
        except (OSError, RuntimeError, TypeError, ValueError):
            return True
        return snapshot.status != "completed"

    def _refresh_reference_calibration_execution_card(self) -> None:
        reference = self.engine_combo.currentData() == DesktopEngine.DEFORMETRICA_REFERENCE
        if not reference:
            self.reference_calibration_execution_card.hide()
            self.open_reference_calibration_button.setEnabled(False)
            return
        self.reference_calibration_execution_card.show()
        if self.reference_parameter_profile_combo.currentData() == "advanced":
            self.reference_calibration_execution_status.setObjectName("statusWarning")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                "Advanced manual parameters are selected, so the guided pilot requirement "
                "is being skipped. Switch back to Guided pilot calibration if you want "
                "DiffeoForge to test and apply parameter candidates."
            )
            self.open_reference_calibration_button.setText(
                "Guided pilot calibration skipped"
            )
            self.open_reference_calibration_button.setEnabled(False)
            return
        plan_is_current = self._reference_calibration_plan_matches_current_inputs()
        if not plan_is_current:
            self.reference_calibration_execution_status.setObjectName("status")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                "Complete Step 1 above, then build the staged comparison plan in Step 2. "
                "No pilot can start before those inputs are fixed."
            )
            self.open_reference_calibration_button.setText(
                "Prepare & start pilot calibration…"
            )
            self.open_reference_calibration_button.setEnabled(False)
            return
        if self._reference_calibration_completed():
            assert self._reference_calibrated_config_path is not None
            self.reference_calibration_execution_status.setObjectName("statusSuccess")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                "Pilot calibration complete. Your explicit candidate selections have "
                "been applied to the final read-only parameters below; optional visual "
                "QC status remains in the calibration provenance.\n"
                f"Selected configuration: {self._reference_calibrated_config_path}"
            )
            self.open_reference_calibration_button.setText(
                "Pilot calibration completed"
            )
            self.open_reference_calibration_button.setEnabled(False)
            return
        context = self._reference_calibration_context()
        if context is None:
            assert self._reference_calibration_plan is not None
            plan = self._reference_calibration_plan
            self.reference_calibration_execution_status.setObjectName("statusSuccess")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                f"Plan ready · {plan.pilot_subject_count} pilot subjects · "
                f"{sum(len(stage.candidates) for stage in plan.stages)} candidate "
                "atlases across four sequential stages. Starting here automatically "
                "creates the provisional pilot configuration and runs the Deformetrica "
                "setup check before opening the calibration."
            )
            self.open_reference_calibration_button.setText(
                "Prepare & start pilot calibration…"
            )
            self.open_reference_calibration_button.setEnabled(self._worker is None)
            return
        plan, directory = context
        ready = bool(
            self._reference_readiness is not None
            and self._reference_readiness.ready
            and self._worker is None
        )
        self.open_reference_calibration_button.setEnabled(ready)
        self.open_reference_calibration_button.setText(
            "Run or continue pilot calibration…"
        )
        if not directory.exists():
            self.reference_calibration_execution_status.setObjectName("status")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                f"Planned, not started · {plan.pilot_subject_count} pilot subjects · "
                f"{sum(len(stage.candidates) for stage in plan.stages)} candidate "
                "atlases across four sequential stages. The Deformetrica setup check "
                "is running or must pass before execution."
            )
            return
        try:
            snapshot = load_reference_calibration_study(directory)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.reference_calibration_execution_status.setObjectName("statusError")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                f"Existing calibration study did not verify: {error}"
            )
            self.open_reference_calibration_button.setEnabled(False)
            return
        self.reference_calibration_execution_status.setObjectName(
            "statusSuccess" if snapshot.status == "completed" else "status"
        )
        self.reference_calibration_execution_status.setStyleSheet("")
        if snapshot.status == "completed":
            message = (
                "Calibration complete · selected full-cohort configuration: "
                f"{snapshot.final_config_path}"
            )
        else:
            assert snapshot.current_stage is not None
            complete = sum(candidate.status == "completed" for candidate in snapshot.candidates)
            message = (
                f"Stage {snapshot.current_stage.order}/"
                f"{len(snapshot.plan.stages)} · {snapshot.current_stage.title} · "
                f"{complete}/{len(snapshot.candidates)} candidates complete · "
                f"status {snapshot.status.replace('_', ' ')}"
            )
        self.reference_calibration_execution_status.setText(message)

    @Slot()
    def _prepare_or_open_reference_calibration(self) -> None:
        """Advance the complete guided pre-pilot chain from one explicit action."""

        if self._worker is not None:
            return
        if not self._reference_calibration_plan_matches_current_inputs():
            self.reference_calibration_execution_status.setObjectName("statusWarning")
            self.reference_calibration_execution_status.setStyleSheet("")
            self.reference_calibration_execution_status.setText(
                "Analyze the aligned meshes and build the current staged comparison "
                "plan before starting pilot calibration."
            )
            self._sync_ready_state()
            return
        if self._reference_calibration_completed():
            return
        context = self._reference_calibration_context()
        if context is not None and self._reference_readiness is not None:
            if self._reference_readiness.ready:
                self._guided_reference_calibration_requested = False
                self._open_reference_calibration()
            else:
                self._guided_reference_calibration_requested = True
                self._check_reference_readiness()
            return

        self._guided_reference_calibration_requested = True
        self.reference_calibration_execution_status.setObjectName("status")
        self.reference_calibration_execution_status.setStyleSheet("")
        if self._result is None:
            self.reference_calibration_execution_status.setText(
                "Creating and validating the provisional pilot configuration…"
            )
            self._create_project()
            return
        if self._review is None:
            self.reference_calibration_execution_status.setText(
                "Reviewing the provisional pilot configuration…"
            )
            self._review_project()
            return
        self.reference_calibration_execution_status.setText(
            "Checking the managed Deformetrica installation before pilot execution…"
        )
        self._check_reference_readiness()

    def _apply_reference_calibrated_configuration(self, config_path: Path) -> None:
        """Reflect one immutable pilot-selected configuration in the Step 2 editor."""

        resolved = config_path.expanduser().resolve()
        config = load_config(resolved)
        model = config["model"]
        deformation = model["deformation"]
        optimization = config["optimization"]
        runtime = config["runtime"]
        values = (
            (self.reference_attachment_ratio_spin, model["attachment"]["kernel_width"]),
            (self.reference_deformation_ratio_spin, deformation["kernel_width"]),
            (
                self.reference_control_spacing_ratio_spin,
                deformation["initial_control_point_spacing"],
            ),
            (self.reference_noise_ratio_spin, model["noise_std"]),
            (self.reference_max_iterations_spin, optimization["max_iterations"]),
            (self.reference_step_size_spin, optimization["initial_step_size"]),
            (
                self.reference_tolerance_spin,
                optimization["convergence_tolerance"],
            ),
            (self.reference_timepoints_spin, deformation["timepoints"]),
            (
                self.reference_line_search_spin,
                optimization["max_line_search_iterations"],
            ),
            (
                self.reference_save_every_spin,
                optimization["save_every_n_iterations"],
            ),
            (
                self.reference_print_every_spin,
                optimization["print_every_n_iterations"],
            ),
            (
                self.reference_sobolev_ratio_spin,
                optimization["sobolev_kernel_width_ratio"],
            ),
            (self.reference_threads_spin, runtime["threads"]),
            (self.reference_random_seed_spin, runtime["random_seed"]),
        )
        for widget, value in values:
            widget.setValue(value)
        attachment_index = self.reference_attachment_type_combo.findData(
            model["attachment"]["type"]
        )
        if attachment_index >= 0:
            self.reference_attachment_type_combo.setCurrentIndex(attachment_index)
        self.reference_rk2_check.setChecked(bool(deformation["use_rk2"]))
        self.reference_scale_step_check.setChecked(
            bool(optimization["scale_initial_step_size"])
        )
        self.reference_sobolev_check.setChecked(
            bool(optimization["use_sobolev_gradient"])
        )
        self.reference_freeze_template_check.setChecked(
            bool(optimization["freeze_template"])
        )
        self.reference_freeze_control_points_check.setChecked(
            bool(optimization["freeze_control_points"])
        )
        acceleration = {
            "cuda": "gpu",
            "gpu": "gpu",
            "cpu": "cpu",
        }.get(str(runtime["device"]).lower(), "auto")
        acceleration_index = self.reference_acceleration_combo.findData(acceleration)
        if acceleration_index >= 0:
            self.reference_acceleration_combo.setCurrentIndex(acceleration_index)

        self._reference_calibrated_config_path = resolved
        profile_index = self.reference_parameter_profile_combo.findData("data_assisted")
        self.reference_parameter_profile_combo.blockSignals(True)
        self.reference_parameter_profile_combo.setCurrentIndex(profile_index)
        self.reference_parameter_profile_combo.setItemText(
            profile_index,
            "Pilot-calibrated selection (read-only)",
        )
        self.reference_parameter_profile_combo.blockSignals(False)
        self._update_reference_parameter_profile()

    @Slot()
    def _open_reference_calibration(self) -> None:
        context = self._reference_calibration_context()
        if context is None or self._review is None:
            return
        if self._reference_readiness is None or not self._reference_readiness.ready:
            QMessageBox.warning(
                self,
                "Deformetrica setup not ready",
                "Wait for the automatic Deformetrica installation and system check "
                "to pass before starting pilot calibration.",
            )
            return
        _plan, directory = context
        try:
            if not directory.exists():
                create_reference_calibration_study(
                    self._review.config_path,
                    directory,
                    pilot_max_iterations=150,
                )
            dialog = ReferenceCalibrationDialog(directory, self)
            dialog.exec()
            snapshot = load_reference_calibration_study(directory)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Pilot calibration unavailable",
                str(error),
            )
            self._refresh_reference_calibration_execution_card()
            return
        self._refresh_reference_calibration_execution_card()
        if (
            snapshot.status != "completed"
            or snapshot.final_config_path is None
            or self._result is None
            or self._result.config_path.resolve() == snapshot.final_config_path.resolve()
        ):
            return
        self._apply_reference_calibrated_configuration(snapshot.final_config_path)
        self._result = replace(
            self._result,
            config_path=snapshot.final_config_path,
            report_path=None,
        )
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Pilot calibration complete. The visually selected parameter values were "
            "applied automatically and are being prepared for Step 3 review."
        )
        self._review = None
        self._reference_readiness = None
        self._reference_run_request = None
        self._refresh_reference_calibration_execution_card()
        self._review_project()

    @Slot()
    def _check_reference_readiness(self) -> None:
        if (
            self._review is None
            or self._review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE
            or self._worker is not None
        ):
            return
        worker = _ReferenceReadinessWorker(self._review)
        worker.signals.succeeded.connect(self._reference_readiness_succeeded)
        worker.signals.failed.connect(self._reference_readiness_failed)
        self._worker = worker
        self._reference_readiness = None
        self._refresh_reference_calibration_execution_card()
        self.refresh_reference_readiness_button.setEnabled(False)
        self.reference_readiness_status_label.setObjectName("status")
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(
            "Deformetrica 4.3, the selected CPU/GPU acceleration, available memory, and "
            "the project folder are being checked automatically…"
        )
        self.reference_readiness_detail_label.setText(
            "This safety check does not start an atlas. Estimated computation time is shown "
            "separately in Step 4 after several optimizer iterations have been observed."
        )
        self.show_run_button.setText("Checking Deformetrica setup automatically…")
        self.show_run_button.setEnabled(False)
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _reference_readiness_succeeded(self, readiness: DesktopReferenceReadiness) -> None:
        self._worker = None
        self._reference_readiness = readiness
        details = [
            f"Configuration: {self._wrappable_path(readiness.config_path)}",
            f"Bound SHA-256: {readiness.config_sha256}",
            f"Project folder: {self._wrappable_path(readiness.workspace)}",
            f"Deformetrica installation: {launcher_label(readiness.launcher)}",
            (
                "Acceleration: NVIDIA KeOps GPU kernels"
                if readiness.device == "cuda"
                else "Acceleration: CPU only"
            ),
            "Observed checks:",
        ]
        for check in readiness.report.checks:
            details.append(f"[{check.status.upper()}] {check.label}: {check.summary}")
            if check.guidance:
                details.append(f"  Guidance: {check.guidance}")
        details.append("No atlas process was started; nothing installed or changed by this check.")
        self.reference_readiness_detail_label.setText("\n".join(details))
        if readiness.report.status == "ready":
            self.reference_readiness_status_label.setObjectName("statusSuccess")
            message = (
                "The DiffeoForge Deformetrica installation is ready. "
                "The supervised Deformetrica execution step is now available."
            )
        elif readiness.report.status == "warning":
            self.reference_readiness_status_label.setObjectName("status")
            message = (
                "The Deformetrica setup check has no blocking error but has warnings. "
                "Reference execution remains locked."
            )
            self.show_run_button.setText("Setup check needs attention")
            self.show_run_button.setEnabled(False)
        else:
            self.reference_readiness_status_label.setObjectName("statusError")
            message = (
                "The DiffeoForge Deformetrica installation needs repair. Guidance appears "
                "below; "
                "nothing was changed or started."
            )
            self.show_run_button.setText("Setup check failed – see guidance")
            self.show_run_button.setEnabled(False)
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(message)
        self.refresh_reference_readiness_button.setEnabled(True)
        if readiness.ready:
            self.show_run_button.setText("Continue to supervised Deformetrica execution")
            self.show_run_button.setEnabled(True)
        self._refresh_reference_calibration_execution_card()
        self._sync_ready_state()
        if self._guided_reference_calibration_requested:
            if readiness.ready:
                self._guided_reference_calibration_requested = False
                QTimer.singleShot(0, self._open_reference_calibration)
            else:
                self._guided_reference_calibration_requested = False

    @Slot(str)
    def _reference_readiness_failed(self, message: str) -> None:
        self._worker = None
        self._guided_reference_calibration_requested = False
        self._reference_readiness = None
        self._reference_run_request = None
        self.reference_readiness_status_label.setObjectName("statusError")
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(
            f"Automatic Deformetrica setup check failed: {message}"
        )
        self.reference_readiness_detail_label.setText(
            "Diagnostic discarded. No reference run was prepared or started, and no "
            "environment setting was changed."
        )
        self.refresh_reference_readiness_button.setEnabled(
            self._review is not None and self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
        )
        self.show_run_button.setText("Setup check failed – check again")
        self.show_run_button.setEnabled(False)
        self._refresh_reference_calibration_execution_card()
        self._sync_ready_state()

    def _reference_preparation_worker_matches_inputs(
        self,
        worker: _ReferencePreparationStatusWorker,
    ) -> bool:
        approval_text = self.reference_preparation_approval_edit.text().strip()
        digest = self.reference_preparation_hash_edit.text().strip().lower()
        return bool(
            self._review is worker.review
            and approval_text
            and Path(approval_text).expanduser().resolve()
            == worker.approval_path.expanduser().resolve()
            and digest == worker.expected_approval_sha256.strip().lower()
        )

    @Slot()
    def _check_reference_preparation_status(self) -> None:
        if (
            self._review is None
            or self._review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE
            or not self._reference_preparation_inputs_valid()
            or self._worker is not None
        ):
            return
        worker = _ReferencePreparationStatusWorker(
            self._review,
            Path(self.reference_preparation_approval_edit.text().strip()),
            self.reference_preparation_hash_edit.text().strip(),
        )
        worker.signals.succeeded.connect(self._reference_preparation_status_succeeded)
        worker.signals.failed.connect(self._reference_preparation_status_failed)
        self._worker = worker
        self._reference_preparation_status = None
        self.reference_preparation_status_label.setObjectName("status")
        self.reference_preparation_status_label.setStyleSheet("")
        self.reference_preparation_status_label.setText(
            "Approval, current plan, destination, and private stages are being checked "
            "twice read-only…"
        )
        self.reference_preparation_detail_label.setText(
            "No path is deleted, moved, published, repaired, resumed, prepared, or executed."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export is locked until this read-only check succeeds and remains bound to "
            "the exact same inputs."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _reference_preparation_status_succeeded(
        self,
        status: DesktopReferencePreparationStatus,
    ) -> None:
        worker = self._worker
        self._worker = None
        if (
            not isinstance(worker, _ReferencePreparationStatusWorker)
            or not self._reference_preparation_worker_matches_inputs(worker)
            or self._review is None
            or status.config_path != self._review.config_path.resolve()
            or status.config_sha256 != self._review.config_sha256
            or status.approval_path != worker.approval_path.expanduser().resolve()
            or status.approval_sha256 != worker.expected_approval_sha256.strip().lower()
        ):
            self._reference_preparation_status = None
            self.reference_preparation_status_label.setObjectName("statusError")
            self.reference_preparation_status_label.setStyleSheet("")
            self.reference_preparation_status_label.setText(
                "Verification result discarded because the review or approval inputs no "
                "longer match exactly."
            )
            self.reference_preparation_detail_label.setText(
                "Nothing was changed. Check again with the current inputs."
            )
            self.reference_preparation_export_label.setObjectName("statusError")
            self.reference_preparation_export_label.setStyleSheet("")
            self.reference_preparation_export_label.setText(
                "No export: the discarded result is no longer bound to the current inputs."
            )
            self._sync_ready_state()
            return

        self._reference_preparation_status = status
        engine_started = (
            "yes"
            if status.engine_execution_started is True
            else "no"
            if status.engine_execution_started is False
            else "cannot be classified safely"
        )
        details = [
            f"Approval: {self._wrappable_path(status.approval_path)}",
            f"Approval-SHA-256: {status.approval_sha256}",
            f"Run-ID: {status.run_id}",
            f"Plan-Fingerprint: {status.plan_fingerprint}",
            f"Report-Schema: {status.report_schema_version}",
            f"Report-Bytes: {status.report_byte_count}",
            f"Report-SHA-256: {status.report_sha256}",
            f"Destination [{status.destination_status}]: "
            f"{self._wrappable_path(status.destination_path)}",
            f"Reason: {status.destination_reason}",
            f"Engine execution started: {engine_started}",
            f"Exactly matching private stages: {len(status.private_stages)}",
        ]
        if status.manifest_sha256 is not None:
            details.append(f"Manifest-SHA-256: {status.manifest_sha256}")
        for stage in status.private_stages:
            details.append(f"[{stage.status}] {self._wrappable_path(stage.path)}: {stage.reason}")
        details.extend(
            (
                "Stable double observation: yes",
                "Mutation by this check: no",
                f"Boundary: {status.scientific_boundary}",
            )
        )
        self.reference_preparation_detail_label.setText("\n".join(details))
        if status.status == "clear_to_prepare":
            self.reference_preparation_status_label.setObjectName("statusSuccess")
            message = (
                "The approved destination is free. The read-only check passed; nothing "
                "was prepared or started."
            )
        elif status.status == "published_prepared_not_executed_verified":
            self.reference_preparation_status_label.setObjectName("statusSuccess")
            message = "The prepared reference run is fully verified and was not executed."
        else:
            self.reference_preparation_status_label.setObjectName("statusError")
            message = "The observed state requires an explicit human decision. Nothing was changed."
        self.reference_preparation_status_label.setStyleSheet("")
        self.reference_preparation_status_label.setText(message)
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export ready: exactly the report bytes hashed above will be written to a new "
            "JSON file. The report contains absolute paths and file names; review private "
            "provenance before sharing."
        )
        self._sync_ready_state()

    @Slot(str)
    def _reference_preparation_status_failed(self, message: str) -> None:
        worker = self._worker
        self._worker = None
        inputs_match = isinstance(
            worker, _ReferencePreparationStatusWorker
        ) and self._reference_preparation_worker_matches_inputs(worker)
        self._reference_preparation_status = None
        self.reference_preparation_status_label.setObjectName("statusError")
        self.reference_preparation_status_label.setStyleSheet("")
        if inputs_match:
            self.reference_preparation_status_label.setText(
                f"Preparation status cannot be checked safely: {message}"
            )
        else:
            self.reference_preparation_status_label.setText(
                "Failure result discarded because the approval inputs changed."
            )
        self.reference_preparation_detail_label.setText(
            "No status release. Nothing was deleted, moved, published, repaired, resumed, "
            "prepared, or executed."
        )
        self.reference_preparation_export_label.setObjectName("statusError")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "No export without a currently bound, fully validated status report."
        )
        self._sync_ready_state()

    @Slot()
    def _export_reference_preparation_status(self) -> None:
        status = self._reference_preparation_status
        if (
            status is None
            or not self._reference_preparation_status_matches_inputs()
            or self._worker is not None
        ):
            self._sync_reference_preparation_status_controls()
            return
        default = status.config_path.parent / (f"reference-preparation-status-{status.run_id}.json")
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select a new status-report file (no overwrite)",
            str(default),
            "JSON files (*.json)",
        )
        if not selected:
            return
        if not self._reference_preparation_status_matches_inputs():
            self.reference_preparation_export_label.setObjectName("statusError")
            self.reference_preparation_export_label.setStyleSheet("")
            self.reference_preparation_export_label.setText(
                "Export discarded because the review or approval inputs no longer match "
                "the verified report exactly."
            )
            self._sync_reference_preparation_status_controls()
            return
        try:
            exported = export_reference_preparation_status_report(status, selected)
        except (
            DesktopReferencePreparationStatusExportError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            self.reference_preparation_export_label.setObjectName("statusError")
            self.reference_preparation_export_label.setStyleSheet("")
            self.reference_preparation_export_label.setText(
                f"Status report was not exported: {error}"
            )
            self._sync_reference_preparation_status_controls()
            return
        self.reference_preparation_export_label.setObjectName("statusSuccess")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            f"New status report written: {self._wrappable_path(exported.path)}\n"
            f"Schema: {exported.schema_version} · Bytes: {exported.byte_count} · "
            f"SHA-256: {exported.sha256}\n"
            "Private provenance with absolute paths; no run or engine file was modified."
        )
        self._sync_reference_preparation_status_controls()

    @Slot()
    def _show_run_page(self) -> None:
        self._navigate_to_step(3)

    @Slot()
    def _refresh_run_readiness(
        self,
    ) -> (
        DesktopReviewedRunReadiness
        | DesktopReviewedRemoteRunReadiness
        | DesktopReferenceLaunchRequest
        | None
    ):
        review = self._review
        if review is None:
            return None
        if review.engine is DesktopEngine.DEFORMETRICA_REFERENCE:
            return self._refresh_reference_run_readiness(review)
        try:
            if self._remote_execution_selected():
                readiness = check_reviewed_remote_run_readiness(
                    review,
                    request_id=f"desktop-remote-{uuid.uuid4().hex}",
                )
            else:
                readiness = check_reviewed_run_readiness(
                    review,
                    request_id=f"desktop-{uuid.uuid4().hex}",
                )
        except (DesktopReviewedRunError, OSError, RuntimeError, TypeError, ValueError) as error:
            self._run_readiness = None
            self.run_summary_label.setText(
                f"Project: {review.project_name}\n"
                f"Configuration: {self._wrappable_path(review.config_path)}\n"
                f"Verified SHA-256: {review.config_sha256}\n"
                "Destination: could not be bound safely from the reviewed configuration"
            )
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                f"Destination status cannot be checked: {error}"
            )
            self.run_readiness_detail_label.setText(
                "No worker was started. No private or published files were modified."
            )
            self.run_state_label.setObjectName("statusError")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "No worker started. Destination and configuration binding could not be "
                "checked safely."
            )
            self.start_atlas_button.setEnabled(False)
            return None
        self._apply_run_readiness(readiness)
        return readiness

    def _refresh_reference_run_readiness(
        self,
        review: ProjectReviewResult,
    ) -> DesktopReferenceLaunchRequest | None:
        readiness = self._reference_readiness
        previous_request = self._reference_run_request
        self._run_readiness = None
        self._reference_run_request = None
        self.execution_location_card.hide()
        self.run_title_label.setText("Compute Deformetrica atlas")
        self.run_subtitle_label.setText(
            "Run the exact reviewed configuration in a contained child process and observe "
            "Deformetrica iterations, objective values, elapsed time, and a live computation-"
            "time estimate."
        )
        self.run_boundary_label.setText(
            "A broad pre-run planning range is shown before launch and recalibrated from "
            "observed optimizer timing. It is not a convergence guarantee. Cancellation "
            "preserves terminal evidence and a checkpoint when Deformetrica produced one."
        )
        if readiness is None or not readiness.ready:
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Deformetrica execution is blocked until the reviewed environment check passes."
            )
            self.start_atlas_button.setEnabled(False)
            return None
        production_readiness = review.production_readiness
        if (
            production_readiness is not None
            and production_readiness.production_scale
            and not production_readiness.ready
        ):
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Production-scale execution is blocked until its recovery and storage "
                "requirements pass."
            )
            self.run_readiness_detail_label.setText(
                "\n".join(production_readiness.blockers)
            )
            self.start_atlas_button.setEnabled(False)
            return None
        try:
            request = build_reference_launch_request(
                review,
                readiness,
                request_id=(
                    previous_request.request_id
                    if previous_request is not None
                    else f"reference-{uuid.uuid4().hex}"
                ),
                run_id=(
                    previous_request.run_id
                    if previous_request is not None
                    else f"desktop-ref-{uuid.uuid4().hex[:12]}"
                ),
            )
        except (
            DesktopReferencePrelaunchError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                f"Reference destination cannot be bound safely: {error}"
            )
            self.run_readiness_detail_label.setText(
                "No worker was started and no run directory was created."
            )
            self.start_atlas_button.setEnabled(False)
            return None
        self._reference_run_request = request
        self.run_summary_label.setText(
            f"Project: {review.project_name}\n"
            f"Configuration: {self._wrappable_path(request.config_path)}\n"
            f"Bound SHA-256: {request.expected_config_sha256}\n"
            f"Non-overwritable destination: {self._wrappable_path(request.destination)}"
        )
        self.run_readiness_status_label.setObjectName("statusSuccess")
        self.run_readiness_status_label.setStyleSheet("")
        self.run_readiness_status_label.setText(
            "Reviewed configuration, ready environment, and absent destination are bound."
        )
        self.run_readiness_detail_label.setText(
            f"Deformetrica installation: {launcher_label(request.launcher)}\n"
            "This check was read-only. The destination and all reviewed inputs are checked "
            "again inside the worker immediately before preparation."
        )
        self.run_progress_bar.setRange(0, 1)
        self.run_progress_bar.setValue(0)
        self.run_progress_bar.setFormat("Not started")
        self.run_optimizer_label.setText(self._reference_runtime_estimate_text(review))
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText("Ready; no Deformetrica process has started.")
        self._sync_ready_state()
        return request

    def _apply_run_readiness(
        self,
        readiness: DesktopReviewedRunReadiness | DesktopReviewedRemoteRunReadiness,
    ) -> None:
        self._reference_run_request = None
        self.execution_location_card.show()
        remote = isinstance(readiness, DesktopReviewedRemoteRunReadiness)
        self.run_title_label.setText(
            "Compute Modern atlas on a private server" if remote else "Compute Modern atlas"
        )
        self.run_subtitle_label.setText(
            "Package the exact reviewed configuration, submit it explicitly, and reconnect "
            "to verified server events and a request-bound download."
            if remote
            else "Run the exact reviewed configuration in a separate process and observe "
            "real workflow events."
        )
        self.run_boundary_label.setText(
            (
                f"Experimental remote Modern {readiness.request.runtime_device.upper()} route. "
                "The request contains raw meshes and specimen filenames. Closing this app "
                "does not cancel the job; cancellation and terminal-data deletion are explicit."
            )
            if remote
            else (
                f"Experimental Modern {readiness.request.runtime_device.upper()} route. "
                "Runtime, peak RAM, and percentage progress are not estimated. Cancellation "
                "acts only at designated safe points and runs are not currently resumable."
            )
        )
        self._run_readiness = readiness
        request = readiness.request
        discovery = readiness.discovery
        self.run_summary_label.setText(
            f"Project: {self._review.project_name if self._review else 'unknown'}\n"
            f"Configuration: {self._wrappable_path(request.config_path)}\n"
            f"Bound SHA-256: {request.expected_config_sha256}\n"
            f"Non-overwritable destination: {self._wrappable_path(request.destination)}"
        )
        details = [
            f"Exact destination: {self._wrappable_path(discovery.destination)}",
            f"Discovery-Status: {discovery.status}",
            f"Destination exists: {'yes' if discovery.destination_exists else 'no'}",
        ]
        if remote:
            details.extend(
                (
                    "Execution host: exact operator-supplied private server",
                    "Local persistent session: created before upload; bearer token is not stored",
                    "Reconnect behavior: server job continues across client interruption",
                )
            )
        if (
            isinstance(readiness, DesktopReviewedRunReadiness)
            and readiness.worker_command is not None
            and self._review is not None
        ):
            runtime = self._review.modern_cuda_runtime
            assert runtime is not None
            details.extend(
                (
                    f"Verified CUDA runtime: {runtime.summary}",
                    f"Worker Python: {self._wrappable_path(runtime.python_path)}",
                    f"Worker Python SHA-256: {runtime.python_sha256}",
                    f"Worker module: {self._wrappable_path(runtime.worker_path)}",
                    f"Worker module SHA-256: {runtime.worker_sha256}",
                )
            )
        if discovery.candidates:
            details.append("Private unpublished candidates:")
            for candidate in discovery.candidates:
                details.append(
                    f"[{candidate.status}] {self._wrappable_path(candidate.path)}\n"
                    f"  Meaning: {_PRIVATE_STATUS_EXPLANATIONS[candidate.status]}\n"
                    f"  Technical reason: {candidate.reason}"
                )
        else:
            details.append("Private unpublished candidates: none")
        details.append(
            "Action by this check: read only; nothing deleted, renamed, resumed, or published."
        )
        self.run_readiness_detail_label.setText("\n".join(details))
        can_start = readiness.ready_for_worker and self._run_result is None and self._worker is None
        self.start_atlas_button.setEnabled(can_start)
        if readiness.ready_for_worker:
            self.run_readiness_status_label.setObjectName("statusSuccess")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Destination is free: no published result or exact private candidate was found."
            )
            if self._worker is None:
                self.run_state_label.setObjectName("status")
                self.run_state_label.setStyleSheet("")
                self.run_state_label.setText(
                    "Ready; destination status was checked read-only. It will be checked "
                    "again before execution."
                )
        else:
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Atlas execution blocked: this exact destination is not free."
            )
            if self._worker is None:
                self.run_state_label.setObjectName("statusError")
                self.run_state_label.setStyleSheet("")
                self.run_state_label.setText(
                    "No worker started. The private or published destination state requires "
                    "explicit review."
                )

    @Slot()
    def _show_review_page(self) -> None:
        self._navigate_to_step(2)

    @Slot(bool)
    def _set_run_technical_details_expanded(self, expanded: bool) -> None:
        self.run_technical_details.setVisible(expanded)
        self.run_technical_toggle.setText(
            "- Hide technical details" if expanded else "+ Technical details"
        )

    def _prepare_remote_session(
        self,
        readiness: DesktopReviewedRemoteRunReadiness,
    ) -> Path:
        existing_text = self.remote_session_edit.text().strip()
        if existing_text:
            session = Path(existing_text).expanduser().resolve()
            state = verify_desktop_remote_atlas_session(session)
            request_state = state["request"]
            if (
                request_state["original_config_sha256"]
                != readiness.request.expected_config_sha256
                or Path(request_state["original_config_path"]).resolve()
                != readiness.request.config_path.resolve()
                or Path(request_state["result_destination"]).resolve()
                != readiness.request.destination.resolve()
            ):
                raise DesktopRemoteAtlasError(
                    "Selected remote session does not match the reviewed configuration "
                    "and destination"
                )
            supplied_server = self.remote_server_edit.text().strip()
            if supplied_server and supplied_server != state["server_url"]:
                raise DesktopRemoteAtlasError(
                    "Selected remote session is bound to a different server URL"
                )
            stored_ca = state["tls"]["ca_file"]
            supplied_ca = self.remote_ca_edit.text().strip()
            if supplied_ca and (
                stored_ca is None
                or Path(supplied_ca).expanduser().resolve()
                != Path(stored_ca).resolve()
            ):
                raise DesktopRemoteAtlasError(
                    "Selected remote session is bound to a different TLS CA file"
                )
            self.remote_server_edit.setText(state["server_url"])
            self.remote_ca_edit.setText("" if stored_ca is None else stored_ca)
        else:
            server_url = self.remote_server_edit.text().strip()
            if not server_url:
                raise DesktopRemoteAtlasError("Enter the exact private server URL")
            ca_text = self.remote_ca_edit.text().strip()
            submission_id = uuid.uuid4().hex
            session = (
                readiness.request.config_path.parent
                / ".diffeoforge-remote"
                / submission_id
            )
            session = create_desktop_remote_atlas_session(
                readiness.request,
                session,
                server_url=server_url,
                ca_file=Path(ca_text) if ca_text else None,
                submission_id=submission_id,
            )
            self.remote_session_edit.setText(str(session))
        self._remote_session_directory = session
        return session

    @Slot()
    def _start_atlas(self) -> None:
        if self._review is None or self._worker is not None or self._run_result is not None:
            return
        reference = self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
        remote = not reference and self._remote_execution_selected()
        resume_request = (
            self._reference_run_request
            if reference
            and self._reference_run_request is not None
            and self._reference_run_request.resume_source is not None
            else None
        )
        readiness = resume_request or self._refresh_run_readiness()
        if reference:
            if not isinstance(readiness, DesktopReferenceLaunchRequest):
                return
            request = readiness
            worker: _AtlasWorker | _RemoteAtlasWorker | _ReferenceAtlasWorker = (
                _ReferenceAtlasWorker(ReferenceExecutionController(request))
            )
        elif remote:
            if (
                not isinstance(readiness, DesktopReviewedRemoteRunReadiness)
                or not readiness.ready_for_worker
                or not self._remote_controls_ready()
            ):
                return
            request = readiness.request
            try:
                session = self._prepare_remote_session(readiness)
                worker = _RemoteAtlasWorker(
                    DesktopRemoteAtlasController(
                        session,
                        token_file=Path(self.remote_token_edit.text().strip()),
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                self.run_state_label.setObjectName("statusError")
                self.run_state_label.setStyleSheet("")
                self.run_state_label.setText(
                    f"Remote atlas session could not be prepared: {error}"
                )
                self.run_event_log.appendPlainText(
                    f"GUI: remote session preparation failed: {error}"
                )
                self._sync_ready_state()
                return
        else:
            if (
                not isinstance(readiness, DesktopReviewedRunReadiness)
                or not readiness.ready_for_worker
            ):
                return
            request = readiness.request
            worker = _AtlasWorker(
                DesktopWorkerController(
                    request,
                    worker_command=readiness.worker_command,
                )
            )
        worker.signals.event.connect(self._atlas_event)
        worker.signals.succeeded.connect(self._atlas_succeeded)
        worker.signals.failed.connect(self._atlas_failed)
        worker.signals.cancel_failed.connect(self._atlas_cancel_failed)
        self._worker = worker
        self._result_review = None
        self.run_result_card.hide()
        self.run_event_log.clear()
        self.run_technical_toggle.setChecked(False)
        if reference:
            self.run_progress_bar.setRange(0, 0)
            self.run_progress_bar.setFormat("Starting Deformetrica")
        else:
            self.run_progress_bar.setRange(0, 7)
            self.run_progress_bar.setValue(0)
            self.run_progress_bar.setFormat("Completed stages: %v of %m")
        self.run_stage_label.setText("Workflow stage: worker is starting")
        self.run_optimizer_label.setText(
            (
                self._reference_runtime_estimate_text(self._review)
                + "\nLive timing: waiting for Deformetrica activity."
            )
            if reference
            else "No optimization decision yet."
        )
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Persistent session is starting; request, server identity, token file, and "
            "destination are being checked again."
            if remote
            else "Child process is starting; configuration binding and destination are "
            "being checked again."
        )
        self.run_summary_label.setText(
            f"Project: {self._review.project_name}\n"
            f"Request-ID: {request.request_id}\n"
            f"Configuration: {self._wrappable_path(request.config_path)}\n"
            f"Bound SHA-256: {request.expected_config_sha256}\n"
            + (
                f"Resume source: {self._wrappable_path(request.resume_source)}\n"
                if isinstance(request, DesktopReferenceLaunchRequest)
                and request.resume_source is not None
                else ""
            )
            + f"Non-overwritable destination: {self._wrappable_path(request.destination)}"
            + (
                f"\nRemote session: {self._wrappable_path(self._remote_session_directory)}"
                if remote and self._remote_session_directory is not None
                else ""
            )
        )
        self.start_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(False)
        self.cancel_atlas_button.setEnabled(True)
        self.run_back_button.setEnabled(False)
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot()
    def _cancel_atlas(self) -> None:
        worker = self._worker
        if (
            not isinstance(worker, (_AtlasWorker, _RemoteAtlasWorker, _ReferenceAtlasWorker))
            or not worker.request_cancel()
        ):
            return
        self.cancel_atlas_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        if isinstance(worker, _ReferenceAtlasWorker):
            self.run_state_label.setText(
                "Cancellation requested. Deformetrica will be interrupted after the current "
                "log/optimizer operation; terminal evidence and any checkpoint are preserved."
            )
        elif isinstance(worker, _RemoteAtlasWorker):
            self.run_state_label.setText(
                "Remote cancellation requested. The server may finish its current tensor "
                "operation before confirming cancellation; no local fallback will start."
            )
        else:
            self.run_state_label.setText(
                "Cancellation requested. The current tensor operation may finish; "
                "DiffeoForge will stop at the next safe point and will not publish a "
                "partial run."
            )
        self.run_event_log.appendPlainText("GUI: cooperative cancellation requested")

    @Slot(str)
    def _atlas_cancel_failed(self, message: str) -> None:
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Cancellation command could not be confirmed: {message}. "
            "The parent continues to monitor the child process."
        )
        self.run_event_log.appendPlainText(f"GUI: cancellation transfer failed: {message}")

    @Slot(object)
    def _atlas_event(
        self,
        event: DesktopWorkerEvent | DesktopReferenceWorkerEvent | dict[str, object],
    ) -> None:
        if isinstance(event, dict):
            self._remote_atlas_event(event)
            return
        if isinstance(event, DesktopReferenceWorkerEvent):
            self._reference_atlas_event(event)
            return
        message: str
        if event.kind == "started":
            message = "Worker started; the reviewed configuration is bound."
            self.run_state_label.setText(message)
        elif event.kind == "progress":
            progress = event.payload["modern_progress"]
            message = str(progress["message"])
            completed = int(progress["completed_stages"])
            total = int(progress["total_stages"])
            self.run_progress_bar.setRange(0, total)
            self.run_progress_bar.setValue(completed)
            self.run_stage_label.setText(
                f"Workflow stage: {progress['phase']} · {progress['status']} · {message}"
            )
            optimizer = progress["optimizer"]
            if optimizer is not None:
                block = optimizer["block"] or "initial"
                gradient = optimizer["gradient_norm"]
                gradient_text = "not computed" if gradient is None else f"{gradient:.6g}"
                self.run_optimizer_label.setText(
                    "Optimization: "
                    f"decision {optimizer['completed_decisions']} of "
                    f"{optimizer['maximum_decisions']} · cycle {optimizer['cycle']} of "
                    f"{optimizer['max_cycles']} · block {block} · status "
                    f"{optimizer['status']} · Objective {optimizer['objective']:.6g} · "
                    f"gradient norm {gradient_text}"
                )
        elif event.kind == "completed":
            message = "Worker reports completion; parent verification is running."
            self.run_state_label.setText(message)
        elif event.kind == "cancelled":
            message = str(event.payload["message"])
            self.run_state_label.setText(
                "Worker reports safe cancellation; the parent is checking the outcome."
            )
        else:
            message = str(event.payload["message"])
            self.run_state_label.setText(
                "Worker reports an error; the parent is reconciling process termination."
            )
        self.run_event_log.appendPlainText(f"#{event.sequence} {event.kind}: {message}")

    def _remote_atlas_event(self, event: dict[str, object]) -> None:
        index = int(event["index"])
        kind = str(event["kind"])
        status = str(event["status"])
        message = str(event["message"])
        progress = event["progress"]
        if kind == "modern_progress" and isinstance(progress, dict):
            completed = int(progress["completed_stages"])
            total = int(progress["total_stages"])
            self.run_progress_bar.setRange(0, total)
            self.run_progress_bar.setValue(completed)
            self.run_stage_label.setText(
                f"Remote workflow: {progress['phase']} · {progress['status']} · {message}"
            )
            optimizer = progress["optimizer"]
            if isinstance(optimizer, dict):
                block = optimizer["block"] or "initial"
                gradient = optimizer["gradient_norm"]
                gradient_text = "not computed" if gradient is None else f"{gradient:.6g}"
                self.run_optimizer_label.setText(
                    "Remote optimization: "
                    f"decision {optimizer['completed_decisions']} of "
                    f"{optimizer['maximum_decisions']} · cycle {optimizer['cycle']} of "
                    f"{optimizer['max_cycles']} · block {block} · "
                    f"Objective {optimizer['objective']:.6g} · gradient norm {gradient_text}"
                )
        else:
            self.run_stage_label.setText(f"Remote job: {status} · {message}")
        self.run_state_label.setText(f"Remote server: {message}")
        self.run_event_log.appendPlainText(
            f"remote #{index} {kind}/{status}: {message}"
        )

    def _reference_atlas_event(self, event: DesktopReferenceWorkerEvent) -> None:
        message: str
        if event.kind == "accepted":
            message = "Reference worker accepted the exact reviewed configuration."
            self.run_state_label.setText(message)
        elif event.kind == "phase":
            phase = str(event.payload["phase"])
            message = str(event.payload["message"])
            self.run_stage_label.setText(
                f"Deformetrica stage: {phase.replace('_', ' ')} · {message}"
            )
            if phase != "execute":
                self.run_progress_bar.setRange(0, 0)
                self.run_progress_bar.setFormat(f"Stage: {phase.replace('_', ' ')}")
            else:
                self.run_progress_bar.setRange(0, 0)
                self.run_progress_bar.setFormat("Computing first iteration")
            self.run_state_label.setText(message)
        elif event.kind == "activity":
            elapsed = float(event.payload["elapsed_seconds"])
            state = str(event.payload["state"])
            latest_message = str(event.payload["latest_message"])
            source = event.payload["log_source"]
            if state == "computing_first_iteration":
                message = (
                    "Deformetrica is active and computing its first complete objective and "
                    "gradient evaluation."
                )
                self.run_stage_label.setText(
                    "Deformetrica stage: execute | computing first iteration"
                )
                self.run_progress_bar.setRange(0, 0)
                self.run_progress_bar.setFormat(
                    f"First iteration active | {self._format_duration(elapsed)} elapsed"
                )
                self.run_optimizer_label.setText(
                    f"{self._reference_runtime_estimate_text(self._review)}\n"
                    f"Live activity: {self._format_duration(elapsed)} elapsed; no complete "
                    f"iteration logged yet. Latest Deformetrica message: {latest_message}"
                )
            else:
                last_iteration = event.payload["last_iteration"]
                message = "Deformetrica is active between logged optimizer iterations."
                self.run_stage_label.setText(
                    "Deformetrica stage: execute | optimizer computation is active"
                )
                self.run_optimizer_label.setText(
                    f"Live activity: {self._format_duration(elapsed)} elapsed | last logged "
                    f"iteration {last_iteration} of {event.payload['maximum_iterations']} | "
                    f"latest message: {latest_message}"
                )
            self.run_state_label.setText(message)
            source_text = "Deformetrica log" if source is None else str(source)
            message = f"{message} Elapsed {self._format_duration(elapsed)}; source {source_text}."
        elif event.kind == "progress":
            iteration = int(event.payload["iteration"])
            maximum = int(event.payload["maximum_iterations"])
            elapsed = float(event.payload["elapsed_seconds"])
            eta_value = event.payload["eta_to_iteration_cap_seconds"]
            eta_text = (
                "estimating from observed iterations…"
                if eta_value is None
                else self._format_duration(float(eta_value))
            )
            rate_value = event.payload["seconds_per_iteration"]
            rate_text = (
                "warming up" if rate_value is None else f"{float(rate_value):.2f} s/iteration"
            )
            likely_lower = event.payload.get(
                "likely_convergence_iteration_lower"
            )
            likely_upper = event.payload.get(
                "likely_convergence_iteration_upper"
            )
            likely_eta_lower = event.payload.get(
                "eta_to_likely_convergence_lower_seconds"
            )
            likely_eta_upper = event.payload.get(
                "eta_to_likely_convergence_upper_seconds"
            )
            if (
                likely_lower is not None
                and likely_upper is not None
                and likely_eta_lower is not None
                and likely_eta_upper is not None
            ):
                convergence_text = (
                    f"Likely stopping window: iterations {int(likely_lower)}–"
                    f"{int(likely_upper)} (about "
                    f"{self._format_duration(float(likely_eta_lower))}–"
                    f"{self._format_duration(float(likely_eta_upper))} remaining; "
                    "trend estimate, not a guarantee)"
                )
            else:
                convergence_text = (
                    "Likely stopping window: not stable enough to estimate yet"
                )
            contention_text = (
                " · Resource contention detected; recent iterations are slower than "
                "the earlier baseline"
                if bool(event.payload.get("resource_contention_detected", False))
                else ""
            )
            message = (
                f"Iteration {iteration} of {maximum}; objective "
                f"{float(event.payload['log_likelihood']):.6g}"
            )
            self.run_progress_bar.setRange(0, maximum)
            self.run_progress_bar.setValue(min(iteration, maximum))
            self.run_progress_bar.setFormat("Iteration %v of maximum %m")
            self.run_stage_label.setText(
                "Deformetrica stage: execute · optimizer output is being observed"
            )
            self.run_optimizer_label.setText(
                f"Iteration {iteration} of maximum {maximum} · objective "
                f"{float(event.payload['log_likelihood']):.6g} · attachment "
                f"{float(event.payload['attachment']):.6g} · regularity "
                f"{float(event.payload['regularity']):.6g}\n"
                f"Elapsed: {self._format_duration(elapsed)} · observed rate: {rate_text} · "
                f"Time to iteration cap: {eta_text} (live upper bound, not convergence)\n"
                f"{convergence_text}{contention_text}"
            )
            self.run_state_label.setText(message)
        else:
            message = str(event.payload["message"])
            self.run_state_label.setText(
                "Reference worker reported its terminal outcome; independent parent "
                "verification is running."
            )
        self.run_event_log.appendPlainText(f"#{event.sequence} {event.kind}: {message}")

    @Slot(object)
    def _atlas_succeeded(
        self,
        result: (
            DesktopWorkerControllerResult
            | DesktopRemoteAtlasResult
            | ReferenceExecutionControllerResult
        ),
    ) -> None:
        self._worker = None
        self.delete_remote_server_copy_button.hide()
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        if isinstance(result, ReferenceExecutionControllerResult):
            self._reference_atlas_succeeded(result)
            return
        if isinstance(result, DesktopRemoteAtlasResult):
            self._remote_atlas_succeeded(result)
            return
        terminal = result.terminal_event
        if result.completed:
            self._run_result = result
            self.run_state_label.setObjectName("statusSuccess")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Atlas and PCA were published and independently verified by the parent. "
                "Optimizer convergence has not yet been reviewed."
            )
            self.run_result_label.setText(
                f"Destination: {self._wrappable_path(Path(terminal.payload['destination']))}\n"
                f"Subjects: {terminal.payload['subject_count']}\n"
                f"Manifest SHA-256: {terminal.payload['manifest_sha256']}\n"
                f"Result bundle: {terminal.payload['bundle_path']}\n"
                f"Process exit code: {result.exit_code}"
            )
            self.run_result_card.show()
            self.start_atlas_button.setEnabled(False)
        else:
            self.run_state_label.setObjectName("status")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Cancelled safely: no destination was published. This Modern run has no "
                "checkpoint and must be restarted if needed."
            )
            self.start_atlas_button.setEnabled(True)
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()
        elif result.completed:
            self._review_run_result()

    @Slot()
    def _delete_remote_server_copy(self) -> None:
        result = self._run_result
        if not isinstance(result, DesktopRemoteAtlasResult) or self._worker is not None:
            return
        token_text = self.remote_token_edit.text().strip()
        if not token_text:
            self.run_state_label.setObjectName("statusError")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Select the bearer-token file before deleting the terminal server copy."
            )
            return
        choice = QMessageBox.warning(
            self,
            "Delete remote atlas server copy?",
            "This permanently deletes the terminal request, server-side workflow state, "
            "events, and result archive for this job. The verified local session, request, "
            "and downloaded result remain unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        worker = _RemoteAtlasDeletionWorker(
            DesktopRemoteAtlasDeletionController(
                result.session_directory,
                token_file=Path(token_text),
            )
        )
        worker.signals.succeeded.connect(self._remote_server_copy_deleted)
        worker.signals.failed.connect(self._remote_server_copy_delete_failed)
        self._worker = worker
        self.delete_remote_server_copy_button.setText("Deleting server copy…")
        self.delete_remote_server_copy_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Authenticated terminal-data deletion is running on the exact bound server."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _remote_server_copy_deleted(
        self,
        result: DesktopRemoteAtlasDeletionResult,
    ) -> None:
        self._worker = None
        self.delete_remote_server_copy_button.setText("Server copy deleted")
        self.delete_remote_server_copy_button.setEnabled(False)
        self.run_state_label.setObjectName("statusSuccess")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Server copy deletion recorded at {result.deleted_at}. The verified local "
            "session, request, and downloaded result were retained."
        )
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot(str)
    def _remote_server_copy_delete_failed(self, message: str) -> None:
        self._worker = None
        self.delete_remote_server_copy_button.setText("Delete server copy…")
        self.delete_remote_server_copy_button.setEnabled(True)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Server copy deletion was not confirmed: {message} Local evidence was retained."
        )
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _remote_atlas_succeeded(self, result: DesktopRemoteAtlasResult) -> None:
        if result.detached:
            self._run_result = None
            self.run_state_label.setObjectName("status")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Local monitoring stopped. The remote job was not cancelled; reopen the "
                "persistent session to reconnect."
            )
        elif result.completed:
            state = verify_desktop_remote_atlas_session(result.session_directory)
            deleted_at = state["remote"].get("server_deleted_at")
            self._run_result = result
            self.run_state_label.setObjectName("statusSuccess")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Remote atlas and PCA were downloaded, request-bound, and independently "
                + (
                    f"verified. Server-copy deletion was recorded at {deleted_at}."
                    if deleted_at is not None
                    else "verified. The server copy remains until explicit deletion."
                )
            )
            self.run_result_label.setText(
                f"Destination: {self._wrappable_path(result.destination)}\n"
                f"Subjects: {state['request']['subjects']}\n"
                f"Workflow manifest SHA-256: "
                f"{state['result']['workflow_manifest_sha256']}\n"
                f"Remote job ID: {result.submission_id}\n"
                f"Persistent session: {self._wrappable_path(result.session_directory)}"
            )
            self.run_result_card.show()
            self.delete_remote_server_copy_button.setText(
                "Server copy deleted"
                if deleted_at is not None
                else "Delete server copy…"
            )
            self.delete_remote_server_copy_button.setEnabled(deleted_at is None)
            self.delete_remote_server_copy_button.show()
            self.start_atlas_button.setEnabled(False)
        else:
            self._run_result = None
            self.run_state_label.setObjectName(
                "status" if result.cancelled else "statusError"
            )
            self.run_state_label.setStyleSheet("")
            error = None if result.remote_state is None else result.remote_state.get("error")
            detail = ""
            if isinstance(error, dict):
                detail = f" Server message: {error.get('message', 'unspecified failure')}"
            self.run_state_label.setText(
                f"Remote job ended as {result.status}.{detail} The persistent session "
                "was preserved; clear its field only when deliberately starting a new job."
            )
            self.start_atlas_button.setEnabled(True)
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()
        elif result.completed:
            self._review_run_result()

    def _reference_atlas_succeeded(
        self,
        result: ReferenceExecutionControllerResult,
    ) -> None:
        terminal = result.terminal_event
        outcome = result.outcome
        destination_exists = bool(terminal.payload["destination_exists"])
        if destination_exists:
            self._run_result = result
            result_hash = terminal.payload["result_sha256"] or "not created"
            self.run_result_label.setText(
                f"Destination: "
                f"{self._wrappable_path(Path(terminal.payload['destination']))}\n"
                f"Outcome: {outcome}\n"
                f"Result SHA-256: {result_hash}\n"
                f"Process exit code: {result.exit_code}\n"
                f"Worker message: {terminal.payload['message']}"
            )
            self.run_result_card.show()
        else:
            self._run_result = None
            self.run_result_card.hide()

        if result.completed:
            self.run_state_label.setObjectName("statusSuccess")
            self.run_state_label.setText(
                "Deformetrica completed and the result was independently verified. "
                "Its momenta will now be imported into a source-bound linear PCA snapshot."
            )
            self.run_progress_bar.setValue(self.run_progress_bar.maximum())
        elif result.interrupted:
            self.run_state_label.setObjectName("status")
            self.run_state_label.setText(
                "Deformetrica was interrupted safely. Terminal evidence and any checkpoint "
                "reported by the run were preserved and independently verified."
            )
        elif outcome == "prepared_not_executed":
            self.run_state_label.setObjectName("status")
            self.run_state_label.setText(
                "Cancelled after immutable preparation. Deformetrica was not started; the "
                "prepared run directory was verified and preserved."
            )
        else:
            self.run_state_label.setObjectName("status")
            self.run_state_label.setText(
                "Cancelled before preparation. No run directory was created or modified."
            )
        self.run_state_label.setStyleSheet("")
        self._reference_run_request = None
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()
        elif result.completed:
            self._review_run_result()

    @Slot(str)
    def _atlas_failed(self, message: str) -> None:
        remote = isinstance(self._worker, _RemoteAtlasWorker)
        self._worker = None
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        suffix = (
            " The persistent remote session was preserved for inspection or reconnection."
            if remote
            else ""
        )
        self.run_state_label.setText(
            f"Atlas run failed or was rejected: {message}{suffix}"
        )
        self.run_event_log.appendPlainText(f"Parent: error: {message}")
        self.start_atlas_button.setEnabled(True)
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot()
    def _review_run_result(self) -> None:
        if (
            not isinstance(
                self._run_result,
                (
                    DesktopWorkerControllerResult,
                    DesktopRemoteAtlasResult,
                    ReferenceExecutionControllerResult,
                ),
            )
            or not self._run_result.completed
            or self._worker is not None
        ):
            return
        destination = (
            self._run_result.destination
            if isinstance(self._run_result, DesktopRemoteAtlasResult)
            else Path(self._run_result.terminal_event.payload["destination"])
        )
        reference = isinstance(self._run_result, ReferenceExecutionControllerResult)
        worker = _ResultReviewWorker(destination, reference=reference)
        worker.signals.succeeded.connect(self._result_review_succeeded)
        worker.signals.failed.connect(self._result_review_failed)
        self._worker = worker
        self.run_back_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Deformetrica completion was independently verified; its output parameters "
            "are now being imported, every subject reconstruction is being ranked for "
            "registration QC, and a linear PCA snapshot is being recomputed. This can "
            "take several minutes for a large cohort."
            if reference
            else "Workflow, bundle, inventory, mesh QC, and static SVGs are being "
            "fully reverified before the results view is enabled."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _result_review_succeeded(self, review: ModernResultReview) -> None:
        self._worker = None
        self._result_review = review
        draft_warning: str | None = None
        try:
            self._registration_qc_decisions = load_registration_qc_draft(review)
        except ModernResultReviewError as error:
            self._registration_qc_decisions = {}
            draft_warning = str(error)
        self._populate_review_rows(self.result_overview_layout, review.overview)
        self._populate_review_rows(self.result_optimization_layout, review.optimization)
        self._populate_review_rows(self.result_pca_layout, review.pca)
        self._populate_review_rows(self.result_quality_layout, review.quality)
        if review.engine_route == "deformetrica_reference":
            self.result_optimizer_convergence_hint.setText(
                "The upper panel shows Deformetrica's logged objective and attachment; the "
                "lower panel shows its regularity term. The final accepted step that triggers "
                "Deformetrica 4.3's tolerance test is not printed in the terminal history."
            )
        else:
            self.result_optimizer_convergence_hint.setText(
                "The upper panel shows committed objective components; the lower panel shows "
                "block-gradient norms against the configured tolerance. A completed curve is "
                "not automatically a converged curve."
            )
        try:
            self._load_verified_optimizer_plot(review)
            self._load_verified_pca_plots(review)
        except ModernResultReviewError as error:
            self._result_review_failed(f"Verified result plots could not be displayed: {error}")
            return
        self._populate_atlas_viewer(review)
        self.result_boundary_label.setText(
            "\n".join(f"• {boundary}" for boundary in review.scientific_boundaries)
        )
        run_label = (
            "Deformetrica run" if review.engine_route == "deformetrica_reference" else "Workflow"
        )
        self.result_summary_label.setText(
            f"Project: {review.project_name}\n"
            f"Created: {review.created_at}\n"
            f"{run_label}: {self._wrappable_path(review.run_directory)}\n"
            f"Run/Workflow manifest SHA-256: {review.workflow_manifest_sha256}\n"
            f"Bundle-Manifest SHA-256: {review.bundle_manifest_sha256}"
        )
        if review.optimizer_converged is True:
            self.result_completion_label.setObjectName("statusSuccess")
            self.result_completion_label.setStyleSheet("")
            self.result_completion_label.setText(
                "Workflow complete and independently verified. The optimizer converged "
                f"({review.optimizer_termination_reason}; "
                f"{review.optimizer_cycles_completed} cycles). This still does not establish "
                "scientific validity."
            )
        elif review.optimizer_converged is False:
            self.result_completion_label.setObjectName("statusWarning")
            self.result_completion_label.setStyleSheet("")
            self.result_completion_label.setText(
                "Workflow complete and independently verified, but the optimizer did not "
                f"converge (termination: {review.optimizer_termination_reason}; "
                f"{review.optimizer_cycles_completed} of {review.optimizer_max_cycles} cycles). "
                "Inspect the convergence plot before selecting a longer convergence attempt. "
                "Treat this as a technical pilot result, not a converged scientific atlas."
            )
        elif (
            review.engine_route == "deformetrica_reference"
            and review.optimizer_termination_reason == "tolerance_threshold"
        ):
            self.result_completion_label.setObjectName("statusSuccess")
            self.result_completion_label.setStyleSheet("")
            duration = (
                self._format_result_duration(review.execution_duration_seconds)
                if review.execution_duration_seconds is not None
                else "an unreported duration"
            )
            self.result_completion_label.setText(
                f"Deformetrica completed in {duration} and reported that its configured "
                "numerical tolerance criterion was met. "
                f"{review.optimizer_cycles_completed} was the last visible logged iteration "
                f"of maximum {review.optimizer_max_cycles}; Deformetrica 4.3 does not print "
                "the final accepted step that triggers this test. This is technical "
                "convergence by the configured stopping rule, not proof of adequate "
                "registration or scientific validity."
            )
        else:
            self.result_completion_label.setObjectName("statusWarning")
            self.result_completion_label.setStyleSheet("")
            duration = (
                self._format_result_duration(review.execution_duration_seconds)
                if review.execution_duration_seconds is not None
                else "an unreported duration"
            )
            stop = review.optimizer_termination_reason.replace("_", " ")
            self.result_completion_label.setText(
                f"Deformetrica completed in {duration}; {review.optimizer_cycles_completed} "
                f"was the last logged iteration of maximum {review.optimizer_max_cycles}. "
                f"Reported stop signal: {stop}. This is independently verified execution "
                "evidence, not proof of adequate registration or scientific convergence."
            )
        self._populate_result_artifacts(review)
        self.open_validation_lab_button.setEnabled(
            review.engine_route == "deformetrica_reference"
        )
        self._sync_reference_pca_deformation_action(review)
        self.result_status_label.setObjectName("statusSuccess")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "Snapshot fully verified. Before each open action, the selected artifact is "
            "rebound to both manifest hashes, its file size, and SHA-256."
            + (
                f" Existing registration-QC autosave was ignored: {draft_warning}"
                if draft_warning is not None
                else ""
            )
        )
        self.run_back_button.setEnabled(True)
        self._sync_ready_state()
        self._set_active_step(4)
        self.page_stack.setCurrentIndex(4)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot(str)
    def _completed_result_review_failed(self, message: str) -> None:
        self._worker = None
        self._result_review = None
        self.open_validation_lab_button.setEnabled(False)
        self._sync_reference_pca_deformation_action(None)
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            f"Completed run could not be opened because full verification failed: {message}"
        )
        self._sync_ready_state()

    def _populate_atlas_viewer(self, review: ModernResultReview) -> None:
        vtk_artifacts = tuple(
            artifact for artifact in review.artifacts if artifact.kind == "vtk"
        )
        summary_count = sum(
            1
            for artifact in vtk_artifacts
            if not artifact.key.startswith(
                ("subject-original-", "subject-reconstruction-")
            )
        )
        specimen_count = (
            len(review.registration_qc)
            if review.registration_qc
            else sum(
                1
                for artifact in vtk_artifacts
                if artifact.key.startswith("subject-reconstruction-")
            )
        )
        self.result_atlas_mesh_group_combo.blockSignals(True)
        self.result_atlas_mesh_group_combo.clear()
        if summary_count:
            self.result_atlas_mesh_group_combo.addItem(
                f"Template & PCA end forms ({summary_count})",
                "summary",
            )
        if specimen_count:
            self.result_atlas_mesh_group_combo.addItem(
                f"All specimen meshes ({specimen_count})",
                "specimens",
            )
        self.result_atlas_mesh_group_combo.blockSignals(False)
        self.result_atlas_mesh_group_combo.setEnabled(
            self.result_atlas_mesh_group_combo.count() > 1
        )
        self.result_atlas_mesh_search_edit.clear()
        self._populate_selected_atlas_mesh_group()

    @Slot()
    def _populate_selected_atlas_mesh_group(self, _unused: object = None) -> None:
        review = self._result_review
        if review is None:
            return
        group = self.result_atlas_mesh_group_combo.currentData()
        is_specimen_group = group == "specimens"
        self.result_atlas_mesh_search_label.setVisible(is_specimen_group)
        self.result_atlas_mesh_search_edit.setVisible(is_specimen_group)
        self.result_qc_export_button.setVisible(
            is_specimen_group and bool(review.registration_qc)
        )
        current_key = self.result_atlas_mesh_combo.currentData()
        entries: list[tuple[str, str]] = []
        if is_specimen_group and review.registration_qc:
            for item in review.registration_qc:
                decision = self._registration_qc_decisions.get(
                    item.subject_name,
                    "unreviewed",
                )
                entries.append(
                    (
                        (
                            f"#{item.rank} · residual p95 {item.residual_p95:.6g} · "
                            f"{item.subject_name} · {decision}"
                        ),
                        f"registration-qc:{item.subject_name}",
                    )
                )
        else:
            artifacts = tuple(
                artifact
                for artifact in review.artifacts
                if artifact.kind == "vtk"
                and (
                    artifact.key.startswith("subject-reconstruction-")
                    if is_specimen_group
                    else not artifact.key.startswith(
                        ("subject-original-", "subject-reconstruction-")
                    )
                )
            )
            artifacts = tuple(
                sorted(
                    artifacts,
                    key=lambda artifact: (
                        0 if artifact.key.startswith("estimated-template") else 1,
                        0 if artifact.key == "pca-mean-shape" else 1,
                        artifact.label.casefold(),
                    ),
                )
            )
            entries.extend((artifact.label, artifact.key) for artifact in artifacts)

        self._result_atlas_mesh_total = len(entries)
        query = (
            self.result_atlas_mesh_search_edit.text().strip().casefold()
            if is_specimen_group
            else ""
        )
        if query:
            entries = [entry for entry in entries if query in entry[0].casefold()]
        self._result_atlas_mesh_filtered = len(entries)

        self.result_atlas_mesh_combo.blockSignals(True)
        self.result_atlas_mesh_combo.clear()
        for label, key in entries:
            self.result_atlas_mesh_combo.addItem(label, key)
        selected_index = next(
            (
                index
                for index in range(self.result_atlas_mesh_combo.count())
                if self.result_atlas_mesh_combo.itemData(index) == current_key
            ),
            0,
        )
        if entries:
            self.result_atlas_mesh_combo.setCurrentIndex(selected_index)
        self.result_atlas_mesh_combo.blockSignals(False)
        if self.result_atlas_mesh_combo.count() == 0:
            self.result_atlas_canvas.set_model(None)
            self.result_atlas_canvas.hide()
            self.result_registration_qc_canvas.hide()
            self.result_atlas_mesh_combo.setEnabled(False)
            self._update_atlas_mesh_counter()
            self.result_atlas_status_label.setObjectName("statusWarning")
            self.result_atlas_status_label.setStyleSheet("")
            self.result_atlas_status_label.setText(
                "No specimen mesh matches the current search."
                if query
                else "No verified VTK mesh is available in this result section."
            )
            return
        self.result_atlas_mesh_combo.setEnabled(True)
        self._load_selected_atlas_mesh(selected_index)

    def _update_atlas_mesh_counter(self) -> None:
        current = self.result_atlas_mesh_combo.currentIndex() + 1
        if self._result_atlas_mesh_filtered == 0:
            current = 0
        if self._result_atlas_mesh_filtered < self._result_atlas_mesh_total:
            text = (
                f"{current} of {self._result_atlas_mesh_filtered} matches · "
                f"{self._result_atlas_mesh_total} total"
            )
        else:
            text = f"{current} of {self._result_atlas_mesh_total}"
        self.result_atlas_mesh_counter_label.setText(text)

    @Slot(int)
    def _load_selected_atlas_mesh(self, _index: int) -> None:
        self._update_atlas_mesh_counter()
        if self._result_review is None:
            return
        key = self.result_atlas_mesh_combo.currentData()
        if not isinstance(key, str):
            return
        if key.startswith("registration-qc:"):
            subject_name = key.split(":", 1)[1]
            try:
                item = self._result_review.registration_qc_item(subject_name)
                original_path = verify_result_artifact(
                    self._result_review,
                    item.original_artifact_key,
                )
                reconstruction_path = verify_result_artifact(
                    self._result_review,
                    item.reconstruction_artifact_key,
                )
                original = load_mesh_preview(original_path)
                reconstruction = load_mesh_preview(reconstruction_path)
                self.result_registration_qc_canvas.set_models(
                    original,
                    reconstruction,
                )
            except (
                KeyError,
                MeshPreviewError,
                ModernResultReviewError,
                OSError,
                ValueError,
            ) as error:
                self.result_registration_qc_canvas.hide()
                self.result_atlas_canvas.hide()
                self.result_atlas_status_label.setObjectName("statusError")
                self.result_atlas_status_label.setStyleSheet("")
                self.result_atlas_status_label.setText(
                    "Registration overlay locked because verification or loading "
                    f"failed: {error}"
                )
                return
            self.result_atlas_canvas.hide()
            preset = self.result_atlas_view_combo.currentData()
            if isinstance(preset, str):
                self.result_registration_qc_canvas.set_view_preset(preset)
            self.result_registration_qc_canvas.show()
            self.result_show_original_check.show()
            self.result_show_reconstruction_check.show()
            self.result_qc_pass_button.show()
            self.result_qc_uncertain_button.show()
            self.result_qc_fail_button.show()
            decision = self._registration_qc_decisions.get(subject_name, "unreviewed")
            if decision == "implausible":
                decision_style = "statusError"
            elif decision in {"unreviewed", "uncertain"}:
                decision_style = "statusWarning"
            else:
                decision_style = "statusSuccess"
            self.result_atlas_status_label.setObjectName(decision_style)
            self.result_atlas_status_label.setStyleSheet("")
            self.result_atlas_status_label.setText(
                f"Outlier rank #{item.rank} · residual p95 {item.residual_p95:.6g} · "
                f"decision: {decision}. Blue = immutable original; orange = "
                "reconstruction. A high residual prioritizes inspection and is not an "
                "automatic exclusion rule."
            )
            return
        try:
            artifact = self._result_review.artifact(key)
            path = verify_result_artifact(self._result_review, key)
            model = load_mesh_preview(path)
            if model.sha256 != artifact.sha256:
                raise ModernResultReviewError(
                    "The internally loaded VTK differs from the verified artifact"
                )
        except (KeyError, MeshPreviewError, ModernResultReviewError, OSError) as error:
            self.result_atlas_canvas.set_model(None)
            self.result_atlas_canvas.hide()
            self.result_registration_qc_canvas.hide()
            self.result_atlas_status_label.setObjectName("statusError")
            self.result_atlas_status_label.setStyleSheet("")
            self.result_atlas_status_label.setText(
                f"Internal atlas viewer locked because verification or loading failed: {error}"
            )
            return
        self.result_atlas_canvas.set_model(model)
        self.result_registration_qc_canvas.hide()
        self.result_show_original_check.hide()
        self.result_show_reconstruction_check.hide()
        self.result_qc_pass_button.hide()
        self.result_qc_uncertain_button.hide()
        self.result_qc_fail_button.hide()
        preset = self.result_atlas_view_combo.currentData()
        if isinstance(preset, str):
            self.result_atlas_canvas.set_view_preset(preset)
        else:
            self.result_atlas_canvas.reset_view()
        self.result_atlas_canvas.show()
        self.result_atlas_status_label.setObjectName("statusSuccess")
        self.result_atlas_status_label.setStyleSheet("")
        self.result_atlas_status_label.setText(
            f"Verified and loaded internally: {artifact.label} | "
            f"{model.point_count} points | {model.triangle_count} triangles | "
            f"SHA-256 {artifact.sha256}"
        )

    @Slot(int)
    def _set_atlas_view_preset(self, _index: int) -> None:
        preset = self.result_atlas_view_combo.currentData()
        if isinstance(preset, str):
            self.result_atlas_canvas.set_view_preset(preset)
            self.result_registration_qc_canvas.set_view_preset(preset)

    @Slot()
    def _reset_atlas_view(self) -> None:
        self.result_atlas_view_combo.setCurrentIndex(0)
        self.result_atlas_canvas.reset_view()
        self.result_registration_qc_canvas.reset_view()

    @Slot(bool)
    def _set_registration_qc_original_visible(self, visible: bool) -> None:
        self.result_registration_qc_canvas.set_show_original(visible)

    @Slot(bool)
    def _set_registration_qc_reconstruction_visible(self, visible: bool) -> None:
        self.result_registration_qc_canvas.set_show_reconstruction(visible)

    @Slot(str)
    def _record_registration_qc_decision(self, decision: str) -> None:
        key = self.result_atlas_mesh_combo.currentData()
        if not isinstance(key, str) or not key.startswith("registration-qc:"):
            return
        subject_name = key.split(":", 1)[1]
        self._registration_qc_decisions[subject_name] = decision
        index = self.result_atlas_mesh_combo.currentIndex()
        item = (
            self._result_review.registration_qc_item(subject_name)
            if self._result_review
            else None
        )
        if item is not None:
            self.result_atlas_mesh_combo.setItemText(
                index,
                (
                    f"#{item.rank} · residual p95 {item.residual_p95:.6g} · "
                    f"{item.subject_name} · {decision}"
                ),
            )
        autosave_error: str | None = None
        if self._result_review is not None:
            try:
                save_registration_qc_draft(
                    self._result_review,
                    self._registration_qc_decisions,
                )
            except (ModernResultReviewError, OSError, TypeError, ValueError) as error:
                autosave_error = str(error)

        qc_items = self._result_review.registration_qc if self._result_review else ()
        subject_order = [item.subject_name for item in qc_items]
        current_position = subject_order.index(subject_name)
        unreviewed_subjects = [
            candidate
            for candidate in subject_order[current_position + 1 :]
            if candidate not in self._registration_qc_decisions
        ]
        wrapped = False
        if not unreviewed_subjects:
            unreviewed_subjects = [
                candidate
                for candidate in subject_order[:current_position]
                if candidate not in self._registration_qc_decisions
            ]
            wrapped = bool(unreviewed_subjects)
        next_subject = unreviewed_subjects[0] if unreviewed_subjects else None
        if next_subject is not None:
            next_key = f"registration-qc:{next_subject}"
            next_index = self.result_atlas_mesh_combo.findData(next_key)
            if next_index < 0 and self.result_atlas_mesh_search_edit.text():
                self.result_atlas_mesh_search_edit.clear()
                next_index = self.result_atlas_mesh_combo.findData(next_key)
            if next_index < 0:
                raise RuntimeError("The next verified registration-QC mesh is not selectable")
            self.result_atlas_mesh_combo.setCurrentIndex(next_index)
            if wrapped:
                self.result_atlas_status_label.setText(
                    self.result_atlas_status_label.text()
                    + " Continuing with an earlier item that is still unreviewed; this is "
                    "an explicit finite review pass, not a silent restart."
                )
        else:
            self._load_selected_atlas_mesh(index)
            self.result_atlas_status_label.setObjectName("statusSuccess")
            self.result_atlas_status_label.setStyleSheet("")
            self.result_atlas_status_label.setText(
                f"All {len(qc_items)} registration-QC meshes have a decision. "
                "The review will not restart automatically. The current draft is saved; "
                "use Export QC status for a timestamped immutable snapshot."
            )
        if autosave_error is not None:
            self.result_atlas_status_label.setObjectName("statusWarning")
            self.result_atlas_status_label.setStyleSheet("")
            self.result_atlas_status_label.setText(
                self.result_atlas_status_label.text()
                + f" Autosave failed; export before closing: {autosave_error}"
            )

    @Slot()
    def _export_registration_qc_status(self) -> None:
        if self._result_review is None:
            return
        try:
            exported = export_registration_qc_review(
                self._result_review,
                self._registration_qc_decisions,
            )
        except (ModernResultReviewError, OSError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "QC export failed", str(error))
            return
        self.result_atlas_status_label.setObjectName("statusSuccess")
        self.result_atlas_status_label.setStyleSheet("")
        self.result_atlas_status_label.setText(
            f"QC status exported without replacing prior reviews: {exported.path} · "
            f"SHA-256 {exported.sha256}"
        )

    def _load_verified_optimizer_plot(self, review: ModernResultReview) -> None:
        try:
            review.artifact("optimizer-convergence-plot")
        except KeyError:
            self.result_optimizer_convergence_plot.hide()
            self.result_optimizer_convergence_plot_status.setObjectName("statusWarning")
            self.result_optimizer_convergence_plot_status.setStyleSheet("")
            reason = review.optimizer_convergence_plot_unavailable_reason or (
                "This result does not contain a verified optimizer-convergence plot."
            )
            self.result_optimizer_convergence_plot_status.setText(
                f"Optimizer convergence plot unavailable: {reason}"
            )
            return

        path = verify_result_artifact(review, "optimizer-convergence-plot")
        self.result_optimizer_convergence_plot.load(str(path))
        if not self.result_optimizer_convergence_plot.renderer().isValid():
            raise ModernResultReviewError("The verified optimizer-convergence SVG is invalid")
        self.result_optimizer_convergence_plot.show()
        self.result_optimizer_convergence_plot_status.setObjectName("statusSuccess")
        self.result_optimizer_convergence_plot_status.setStyleSheet("")
        self.result_optimizer_convergence_plot_status.setText(
            "Verified Deformetrica objective, attachment, and regularity history from "
            "the versioned result-analysis bundle."
            if review.engine_route == "deformetrica_reference"
            else "Verified objective components and block-gradient norms from the bound "
            "optimizer history."
        )

    def _load_verified_pca_plots(self, review: ModernResultReview) -> None:
        scree = verify_result_artifact(review, "pca-scree")
        self.result_pca_scree_plot.load(str(scree))
        if not self.result_pca_scree_plot.renderer().isValid():
            raise ModernResultReviewError("The verified PCA scree SVG is invalid")
        self.result_pca_scree_plot.show()
        self.result_pca_scree_plot_status.setObjectName("statusSuccess")
        self.result_pca_scree_plot_status.setStyleSheet("")
        self.result_pca_scree_plot_status.setText(
            "Verified explained variance for all retained principal components."
        )

        primary = verify_result_artifact(review, "pca-score-plot")
        self.result_pc1_pc2_plot.load(str(primary))
        if not self.result_pc1_pc2_plot.renderer().isValid():
            raise ModernResultReviewError("The verified PC1-versus-PC2 SVG is invalid")
        self.result_pc1_pc2_plot.show()
        self.result_pc1_pc2_plot_status.setObjectName("statusSuccess")
        self.result_pc1_pc2_plot_status.setStyleSheet("")
        self.result_pc1_pc2_plot_status.setText(
            "Verified PC1-versus-PC2 scores from the bound result bundle. "
            "Hover over a point to identify the specimen."
        )

        try:
            review.artifact("pca-score-plot-pc2-pc3")
        except KeyError:
            self.result_pc2_pc3_plot.hide()
            self.result_pc2_pc3_plot_status.setObjectName("statusWarning")
            self.result_pc2_pc3_plot_status.setStyleSheet("")
            reason = review.pca_pc2_pc3_unavailable_reason or (
                "This result does not contain the mandatory PC2-versus-PC3 artifact."
            )
            self.result_pc2_pc3_plot_status.setText(f"PC2 versus PC3 unavailable: {reason}")
            return

        secondary = verify_result_artifact(review, "pca-score-plot-pc2-pc3")
        self.result_pc2_pc3_plot.load(str(secondary))
        if not self.result_pc2_pc3_plot.renderer().isValid():
            raise ModernResultReviewError("The verified PC2-versus-PC3 SVG is invalid")
        self.result_pc2_pc3_plot.show()
        self.result_pc2_pc3_plot_status.setObjectName("statusSuccess")
        self.result_pc2_pc3_plot_status.setStyleSheet("")
        self.result_pc2_pc3_plot_status.setText(
            "Verified PC2-versus-PC3 scores from the same score matrix and subject order. "
            "Hover over a point to identify the specimen."
        )

    @Slot(str)
    def _result_review_failed(self, message: str) -> None:
        self._worker = None
        self._result_review = None
        self.open_validation_lab_button.setEnabled(False)
        self._sync_reference_pca_deformation_action(None)
        self.run_back_button.setEnabled(True)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Results view locked: the complete snapshot did not verify: {message}"
        )
        self._sync_ready_state()
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _populate_result_artifacts(self, review: ModernResultReview) -> None:
        while self.result_artifacts_layout.count():
            child = self.result_artifacts_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self.result_artifact_buttons.clear()
        for artifact in review.artifacts:
            if artifact.kind == "vtk":
                continue
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            description = QLabel(
                f"{artifact.label}\n{artifact.description}\n"
                f"{artifact.kind.upper()} · {artifact.bytes} Bytes · SHA-256 {artifact.sha256}"
            )
            description.setObjectName("reviewDetail")
            description.setWordWrap(True)
            description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            button = QPushButton("Recheck & open")
            button.setObjectName("secondary")
            button.clicked.connect(
                lambda checked=False, key=artifact.key: self._open_result_artifact(key)
            )
            row_layout.addWidget(description, 1)
            row_layout.addWidget(button)
            self.result_artifacts_layout.addWidget(row)
            self.result_artifact_buttons.append(button)

    @Slot(str)
    def _open_result_artifact(self, key: str) -> None:
        if self._result_review is None or self._worker is not None:
            return
        try:
            artifact = self._result_review.artifact(key)
        except KeyError:
            self.result_status_label.setObjectName("statusError")
            self.result_status_label.setStyleSheet("")
            self.result_status_label.setText("Unknown artifact; nothing was opened.")
            return
        worker = _ArtifactWorker(self._result_review, key)
        worker.signals.succeeded.connect(self._artifact_succeeded)
        worker.signals.failed.connect(self._artifact_failed)
        self._worker = worker
        self._set_result_controls_enabled(False)
        self.result_status_label.setObjectName("status")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            f"{artifact.label} is being rechecked immediately before handoff…"
        )
        self._thread_pool.start(worker)

    @Slot(object)
    def _artifact_succeeded(self, path: Path) -> None:
        self._worker = None
        self._set_result_controls_enabled(True)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()
            return
        self.result_status_label.setObjectName("statusSuccess")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            f"Hash and size checks passed: {path.name}. Opening the local application."
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(str)
    def _artifact_failed(self, message: str) -> None:
        self._worker = None
        self._set_result_controls_enabled(True)
        self.result_status_label.setObjectName("statusError")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(f"Artifact was not opened: {message}")
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _set_result_controls_enabled(self, enabled: bool) -> None:
        self.result_back_button.setEnabled(enabled)
        for button in self.result_artifact_buttons:
            button.setEnabled(enabled)
        reference = (
            self._result_review is not None
            and self._result_review.engine_route == "deformetrica_reference"
        )
        self.open_validation_lab_button.setEnabled(enabled and reference)
        if enabled:
            self._sync_reference_pca_deformation_action(self._result_review)
        else:
            self.generate_reference_pca_deformations_button.setEnabled(False)

    @Slot()
    def _show_run_page_from_results(self) -> None:
        self._navigate_to_step(3 if self._run_result is not None else 0)

    @staticmethod
    def _wrappable_path(path: Path) -> str:
        return str(path).replace("\\", "\\\u200b").replace("/", "/\u200b")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        whole_seconds = max(0, round(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, remaining_seconds = divmod(remainder, 60)
        if hours:
            return f"{hours} h {minutes:02d} min {remaining_seconds:02d} s"
        if minutes:
            return f"{minutes} min {remaining_seconds:02d} s"
        return f"{remaining_seconds} s"

    def _reference_runtime_estimate_text(
        self,
        review: ProjectReviewResult | None,
    ) -> str:
        estimate = None if review is None else review.runtime_estimate
        if estimate is None:
            return (
                "Pre-run runtime estimate unavailable. Live timing begins when "
                "Deformetrica reports activity."
            )
        evidence = (
            f"calibrated from {estimate.pilot_observation_count} completed pilot runs"
            if estimate.basis == "same-project_pilot_observations"
            else "engineering heuristic; no same-project pilot timing was available"
        )
        return (
            f"Pre-run planning estimate ({estimate.confidence.replace('_', ' ')}): "
            "typically about "
            f"{self._format_duration(estimate.typical_seconds)}; broad range "
            f"{self._format_duration(estimate.lower_seconds)} to "
            f"{self._format_duration(estimate.upper_seconds)}. Based on mesh faces, "
            "cohort size, time points, control spacing, threads, and iteration cap; "
            f"{evidence}. Live observations will replace it."
        )

    @staticmethod
    def _format_result_duration(seconds: float) -> str:
        normalized = max(0.0, float(seconds))
        hours, remainder = divmod(normalized, 3600.0)
        minutes, remaining_seconds = divmod(remainder, 60.0)
        if hours >= 1:
            return f"{int(hours)} h {int(minutes):02d} min {remaining_seconds:04.1f} s"
        if minutes >= 1:
            return f"{int(minutes)} min {remaining_seconds:.1f} s"
        return f"{remaining_seconds:.1f} s"

    @Slot(str)
    def _review_failed(self, message: str) -> None:
        self._worker = None
        self._guided_reference_calibration_requested = False
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Parameter review failed: {message}")
        self._sync_ready_state()

    def _populate_review_rows(self, layout: QVBoxLayout, items: tuple) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        for item in items:
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            value = QLabel(f"{item.label}:  {item.value}")
            value.setObjectName("reviewValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail = QLabel(item.explanation)
            detail.setObjectName("reviewDetail")
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(value)
            row_layout.addWidget(detail)
            layout.addWidget(row)

    def _set_active_step(self, active: int) -> None:
        self._active_step = active
        self._sync_navigation_state()

    @Slot(int)
    def _navigate_to_step(self, step: int) -> None:
        if not self._step_is_unlocked(step):
            self._sync_navigation_state()
            return
        resume_request = bool(
            self._reference_run_request is not None
            and self._reference_run_request.resume_source is not None
        )
        if step == 3 and self._run_result is None and not resume_request:
            self._refresh_run_readiness()
        self._set_active_step(step)
        self.page_stack.setCurrentIndex(step)

    @Slot()
    def _show_setup_page(self) -> None:
        self._navigate_to_step(0)

    @Slot()
    def _open_review_report(self) -> None:
        if self._review is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._review.report_path)))

    @Slot()
    def _open_config(self) -> None:
        if self._result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.config_path)))

    @Slot()
    def _open_project_directory(self) -> None:
        if self._result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.config_path.parent)))

    @Slot()
    def _open_run_result(self) -> None:
        if self._run_result is None:
            return
        if isinstance(self._run_result, DesktopRemoteAtlasResult):
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._run_result.destination))
            )
            return
        payload = self._run_result.terminal_event.payload
        if not bool(payload.get("destination_exists", True)):
            return
        destination = Path(payload["destination"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if isinstance(self._worker, _RemoteAtlasWorker):
            self._close_after_worker = True
            self._worker.request_detach()
            self.run_state_label.setText(
                "Stopping local monitoring. The remote job will continue and can be "
                "reconnected from the persistent session folder."
            )
            event.ignore()
            return
        if isinstance(self._worker, _RemoteAtlasDeletionWorker):
            self._close_after_worker = True
            self.run_state_label.setText(
                "The window will remain open until the authenticated server-copy deletion "
                "is confirmed or rejected."
            )
            event.ignore()
            return
        if isinstance(self._worker, (_AtlasWorker, _ReferenceAtlasWorker)):
            self._close_after_worker = True
            self._cancel_atlas()
            self.run_state_label.setText(
                "The window will remain open until safe worker termination is confirmed. "
                "Cancellation was requested."
            )
            event.ignore()
            return
        if isinstance(
            self._worker,
            (_ResultReviewWorker, _ReferencePCADeformationWorker, _ArtifactWorker),
        ):
            self._close_after_worker = True
            if isinstance(self._worker, _ResultReviewWorker):
                self.run_state_label.setText(
                    "The window will remain open until result verification finishes."
                )
            elif isinstance(self._worker, _ReferencePCADeformationWorker):
                self.reference_pca_deformation_status_label.setText(
                    "The window will remain open until Deformetrica Shooting stops and "
                    "the atomic result is either verified or rejected."
                )
            else:
                self.result_status_label.setText(
                    "The window will remain open until the artifact check finishes."
                )
            event.ignore()
            return
        super().closeEvent(event)
