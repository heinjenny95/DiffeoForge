"""PySide6 widgets for the first DiffeoForge Desktop vertical slice."""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
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
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.aspect_svg_widget import AspectRatioSvgWidget
from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog
from diffeoforge.desktop.mesh_preview import (
    DEFAULT_EDGE_BUDGET,
    MeshPreviewError,
    MeshPreviewModel,
    load_mesh_preview,
)
from diffeoforge.desktop.mesh_preview_widget import MeshPreviewCanvas
from diffeoforge.desktop.project_review import ProjectReviewResult, review_project
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    ProjectSetupResult,
    create_project,
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
from diffeoforge.desktop.reference_result_review import review_reference_result
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    review_modern_result,
    verify_result_artifact,
)
from diffeoforge.desktop.reviewed_run import (
    DesktopReviewedRunError,
    DesktopReviewedRunReadiness,
    check_reviewed_run_readiness,
)
from diffeoforge.desktop.worker_controller import (
    DesktopWorkerController,
    DesktopWorkerControllerError,
    DesktopWorkerControllerResult,
)
from diffeoforge.desktop.worker_protocol import DesktopWorkerEvent
from diffeoforge.initialization import SUPPORTED_UNITS, detect_template
from diffeoforge.preprocessing import (
    LandmarkAlignmentPreview,
    preview_landmark_alignment,
)
from diffeoforge.reference_parameters import reference_parameter_profile
from diffeoforge.reference_recommendation import (
    ReferenceParameterRecommendation,
    recommend_reference_parameters,
)
from diffeoforge.reference_runtime import launcher_label
from diffeoforge.surface_io import (
    SUPPORTED_SURFACE_EXTENSIONS,
    is_supported_surface_path,
)

_SURFACE_FILE_FILTER = (
    "Supported surface meshes (*.vtk *.ply *.obj *.stl);;"
    "Legacy VTK PolyData (*.vtk);;PLY meshes (*.ply);;"
    "Wavefront OBJ meshes (*.obj);;STL meshes (*.stl)"
)
_DEFAULT_SURFACE_PATTERNS = {
    f"*{extension}" for extension in SUPPORTED_SURFACE_EXTENSIONS
}

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
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #bdcbce; border-radius: 6px;
                      min-height: 34px; padding: 2px 9px; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #268f7a; }
QPushButton { border-radius: 6px; min-height: 34px; padding: 2px 13px; font-weight: 600; }
QPushButton#secondary { background: #eef3f4; border: 1px solid #c8d5d7; color: #24474b; }
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


class _ReferenceParameterWorker(QRunnable):
    """Analyze one aligned cohort without blocking the Qt event loop."""

    def __init__(
        self,
        *,
        mesh_paths: tuple[Path, ...],
        alignment_basis: str,
        surface_detail_intent: str,
        deformation_scale_intent: str,
        transforms: tuple[object, ...] | None,
        alignment_fingerprint: str | None,
    ) -> None:
        super().__init__()
        self.mesh_paths = mesh_paths
        self.alignment_basis = alignment_basis
        self.surface_detail_intent = surface_detail_intent
        self.deformation_scale_intent = deformation_scale_intent
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
            | _ReferenceParameterWorker
            | _ReferenceReadinessWorker
            | _ReferencePreparationStatusWorker
            | _SavedReferencePreparationStatusVerificationWorker
            | _ResultReviewWorker
            | _ArtifactWorker
            | _AtlasWorker
            | _ReferenceAtlasWorker
            | None
        ) = None
        self._result: ProjectSetupResult | None = None
        self._review: ProjectReviewResult | None = None
        self._template_preview: MeshPreviewModel | None = None
        self._procrustes_preview: LandmarkAlignmentPreview | None = None
        self._reference_recommendation: ReferenceParameterRecommendation | None = None
        self._reference_recommendation_paths: tuple[Path, ...] | None = None
        self._reference_readiness: DesktopReferenceReadiness | None = None
        self._reference_preparation_status: DesktopReferencePreparationStatus | None = None
        self._saved_reference_preparation_status_verification: (
            DesktopSavedReferencePreparationStatusVerification | None
        ) = None
        self._run_readiness: DesktopReviewedRunReadiness | None = None
        self._reference_run_request: DesktopReferenceLaunchRequest | None = None
        self._run_result: (
            DesktopWorkerControllerResult | ReferenceExecutionControllerResult | None
        ) = None
        self._result_review: ModernResultReview | None = None
        self._close_after_worker = False
        self._active_step = 0
        self._build_ui()
        self._update_engine_explanation()
        self._sync_ready_state()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_rail())
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        self.page_stack.addWidget(self._build_setup_content())
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
            "2  Review parameters",
            "3  Compute atlas",
            "4  Results & PCA",
        )
        self.rail_steps: list[QPushButton] = []
        for index, text in enumerate(steps):
            step_label = text.split("  ", 1)[1]
            button = QPushButton(text.replace("&", "&&"))
            button.setObjectName("stepActive" if index == 0 else "stepFuture")
            button.setProperty("stepLabel", step_label)
            button.setAccessibleName(f"Go to step {index + 1}: {step_label}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, step=index: self._navigate_to_step(step)
            )
            layout.addWidget(button)
            self.rail_steps.append(button)
        layout.addStretch()
        boundary = QLabel("PRE-ALPHA\nNo scientific validation")
        boundary.setObjectName("railCaption")
        boundary.setWordWrap(True)
        layout.addWidget(boundary)
        return rail

    def _build_setup_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("content")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 1 OF 4")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("New atlas project")
        title.setObjectName("title")
        subtitle = QLabel(
            "Select your meshes and create a transparent, verified starter configuration."
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
            "This first desktop step validates data and creates a configuration. "
            "It does not start atlas computation."
        )
        boundary_text.setObjectName("boundaryText")
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        layout.addWidget(boundary)
        layout.addWidget(self._build_form_card())

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
        footer_layout.setSpacing(18)
        self.status_label = QLabel("Enter a mesh folder, project folder, and coordinate unit.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label, 1)
        self.create_button = QPushButton("Validate data & create project")
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self._setup_primary_action)
        footer_layout.addWidget(self.create_button)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(scroll, 1)
        content_layout.addWidget(footer)
        return content

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
        self.saved_reference_status_report_edit.setObjectName(
            "savedReferenceStatusReportEdit"
        )
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
        self.saved_reference_status_hash_edit.setObjectName(
            "savedReferenceStatusHashEdit"
        )
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
        self.saved_reference_status_verification_detail_label.setObjectName(
            "reviewDetail"
        )
        self.saved_reference_status_verification_detail_label.setWordWrap(True)
        self.saved_reference_status_verification_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.verify_saved_reference_status_button = QPushButton(
            "Verify saved report read-only"
        )
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
        self.export_saved_reference_status_verification_button.setObjectName(
            "secondary"
        )
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
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("STEP 2 OF 4")
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
        self.refresh_template_preview_button = QPushButton(
            "Load template read-only"
        )
        self.refresh_template_preview_button.setObjectName("secondary")
        self.refresh_template_preview_button.clicked.connect(
            self._load_template_preview
        )
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
        self.refresh_reference_readiness_button = QPushButton(
            "Check setup again"
        )
        self.refresh_reference_readiness_button.setObjectName("secondary")
        self.refresh_reference_readiness_button.clicked.connect(
            self._check_reference_readiness
        )
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
        reference_preparation_status_layout = QVBoxLayout(
            reference_preparation_status
        )
        reference_preparation_status_layout.setContentsMargins(24, 22, 24, 24)
        reference_preparation_status_layout.setSpacing(10)
        reference_preparation_status_title = QLabel(
            "Approval-bound preparation status"
        )
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
        self.reference_preparation_approval_edit.setObjectName(
            "referencePreparationApprovalEdit"
        )
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
        self.reference_preparation_hash_edit.setObjectName(
            "referencePreparationHashEdit"
        )
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
        reference_preparation_status_layout.addWidget(
            reference_preparation_status_title
        )
        reference_preparation_status_layout.addWidget(
            self.reference_preparation_status_label
        )
        reference_preparation_status_layout.addLayout(preparation_form)
        reference_preparation_status_layout.addWidget(
            self.reference_preparation_detail_label
        )
        reference_preparation_status_layout.addWidget(
            self.refresh_reference_preparation_status_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        reference_preparation_status_layout.addWidget(
            self.reference_preparation_export_label
        )
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
        back = QPushButton("Back to data & engine")
        back.setObjectName("secondary")
        back.clicked.connect(self._show_setup_page)
        footer_layout.addWidget(back)
        self.open_review_report_button = QPushButton("Open review report")
        self.open_review_report_button.setObjectName("secondary")
        self.open_review_report_button.clicked.connect(self._open_review_report)
        footer_layout.addWidget(self.open_review_report_button)
        footer_layout.addStretch()
        self.show_run_button = QPushButton("Atlas execution continues in Step 3")
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

        eyebrow = QLabel("STEP 3 OF 4")
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
            "Experimental Modern CPU route. Runtime, peak RAM, and percentage progress are "
            "not estimated. Cancellation acts only at designated safe points and runs are "
            "not currently resumable."
        )
        self.run_boundary_label.setObjectName("boundaryText")
        self.run_boundary_label.setWordWrap(True)
        boundary_layout.addWidget(self.run_boundary_label)
        layout.addWidget(boundary)

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
        layout.addWidget(summary)

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
        layout.addWidget(readiness)

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
        result_button_row = QHBoxLayout()
        result_button_row.addWidget(self.open_run_result_button)
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

        eyebrow = QLabel("STEP 4 OF 4")
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
        self.result_boundary_label = QLabel(
            "Technical verification is not scientific validation."
        )
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
            "artifacts. Axis labels report explained variance; PCA signs remain conventional."
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

        artifacts = QFrame()
        artifacts.setObjectName("card")
        artifacts_layout = QVBoxLayout(artifacts)
        artifacts_layout.setContentsMargins(24, 22, 24, 24)
        artifacts_title = QLabel("Verified open artifacts")
        artifacts_title.setObjectName("sectionTitle")
        artifacts_hint = QLabel(
            "DiffeoForge does not yet render VTK internally. VTK, CSV, JSON, and static SVG "
            "files are handed to the locally associated application."
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

    def _build_form_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 24)
        card_layout.setSpacing(15)
        section = QLabel("Project and inputs")
        section.setObjectName("sectionTitle")
        card_layout.addWidget(section)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(12)

        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("engineCombo")
        self.engine_combo.addItem(
            "DiffeoForge Modern CPU (experimental)", DesktopEngine.MODERN_CPU
        )
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
        form.addRow("Engine", engine_box)

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
        self.pairwise_combo.currentIndexChanged.connect(
            self._update_pairwise_explanation
        )
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
        form.addRow("Pairwise evaluation", pairwise_box)

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
        form.addRow("Optimization effort", optimization_effort_box)

        self.reference_parameter_box = QFrame()
        self.reference_parameter_box.setObjectName("parameterEditor")
        reference_parameter_layout = QVBoxLayout(self.reference_parameter_box)
        reference_parameter_layout.setContentsMargins(0, 0, 0, 0)
        reference_parameter_layout.setSpacing(8)
        self.reference_parameter_profile_combo = QComboBox()
        self.reference_parameter_profile_combo.setObjectName(
            "referenceParameterProfileCombo"
        )
        self.reference_parameter_profile_combo.addItem(
            "Analyze aligned meshes first", "pending"
        )
        self.reference_parameter_profile_combo.addItem(
            "Data-assisted recommendation", "data_assisted"
        )
        self.reference_parameter_profile_combo.addItem("Advanced manual control", "advanced")
        self.reference_parameter_profile_combo.currentIndexChanged.connect(
            self._update_reference_parameter_profile
        )
        reference_parameter_layout.addWidget(self.reference_parameter_profile_combo)

        self.reference_parameter_form = QFormLayout()
        self.reference_parameter_form.setHorizontalSpacing(18)
        self.reference_parameter_form.setVerticalSpacing(7)
        self.reference_attachment_ratio_spin = self._ratio_spin_box(
            "Attachment width as a fraction of the template bounding-box diagonal."
        )
        self.reference_deformation_ratio_spin = self._ratio_spin_box(
            "Deformation width as a fraction of the template bounding-box diagonal."
        )
        self.reference_control_spacing_ratio_spin = self._ratio_spin_box(
            "Initial control-point spacing as a fraction of the template diagonal."
        )
        self.reference_noise_ratio_spin = self._ratio_spin_box(
            "Noise standard deviation as a fraction of the template diagonal."
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
        for label, widget in (
            ("Attachment / diagonal", self.reference_attachment_ratio_spin),
            ("Deformation / diagonal", self.reference_deformation_ratio_spin),
            ("Control spacing / diagonal", self.reference_control_spacing_ratio_spin),
            ("Noise SD / diagonal", self.reference_noise_ratio_spin),
            ("Maximum iterations", self.reference_max_iterations_spin),
            ("Initial step size", self.reference_step_size_spin),
            ("Convergence tolerance", self.reference_tolerance_spin),
        ):
            self.reference_parameter_form.addRow(label, widget)
        reference_parameter_layout.addLayout(self.reference_parameter_form)
        self.reference_expert_toggle = QCheckBox("Show expert settings")
        self.reference_expert_toggle.setObjectName("referenceExpertToggle")
        self.reference_expert_toggle.toggled.connect(
            self._update_reference_expert_visibility
        )
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
        self.reference_save_every_spin.setValue(100)
        self.reference_print_every_spin = QSpinBox()
        self.reference_print_every_spin.setRange(1, 100000)
        self.reference_print_every_spin.setValue(1)
        self.reference_scale_step_check = QCheckBox("Scale initial step size")
        self.reference_scale_step_check.setChecked(True)
        self.reference_sobolev_check = QCheckBox("Use Sobolev gradient")
        self.reference_sobolev_check.setChecked(True)
        self.reference_sobolev_check.toggled.connect(
            self._update_reference_expert_dependencies
        )
        self.reference_sobolev_ratio_spin = QDoubleSpinBox()
        self.reference_sobolev_ratio_spin.setDecimals(6)
        self.reference_sobolev_ratio_spin.setRange(0.000001, 1000000.0)
        self.reference_sobolev_ratio_spin.setValue(1.0)
        self.reference_freeze_template_check = QCheckBox("Freeze template")
        self.reference_freeze_control_points_check = QCheckBox("Freeze control points")
        self.reference_threads_spin = QSpinBox()
        self.reference_threads_spin.setRange(1, 256)
        self.reference_threads_spin.setValue(4)
        self.reference_random_seed_spin = QSpinBox()
        self.reference_random_seed_spin.setRange(0, 2147483647)
        self.reference_random_seed_spin.setValue(20260715)
        for label, widget in (
            ("Attachment type", self.reference_attachment_type_combo),
            ("Time points", self.reference_timepoints_spin),
            ("Integration", self.reference_rk2_check),
            ("Line-search limit", self.reference_line_search_spin),
            ("Save interval", self.reference_save_every_spin),
            ("Log interval", self.reference_print_every_spin),
            ("Step-size scaling", self.reference_scale_step_check),
            ("Sobolev gradient", self.reference_sobolev_check),
            ("Sobolev width ratio", self.reference_sobolev_ratio_spin),
            ("Template update", self.reference_freeze_template_check),
            ("Control-point update", self.reference_freeze_control_points_check),
            ("CPU threads", self.reference_threads_spin),
            ("Random seed", self.reference_random_seed_spin),
        ):
            expert_form.addRow(label, widget)
        expert_help = QLabel(
            "Attachment type controls how surface orientation contributes to matching. "
            "Time points and RK2 control numerical trajectory integration. Line search and "
            "step scaling govern optimizer steps. Sobolev settings smooth the template "
            "gradient. Freeze options hold selected parameter blocks fixed. Save/log "
            "intervals affect checkpoints and reporting, while threads and seed define the "
            "execution contract. These choices require dataset-specific scientific review."
        )
        expert_help.setObjectName("hint")
        expert_help.setWordWrap(True)
        expert_form.addRow("What these control", expert_help)
        reference_parameter_layout.addWidget(self.reference_expert_box)
        self.reference_expert_box.hide()
        self.reference_parameter_hint = QLabel(
            "No values are active until aligned meshes are analyzed or Advanced manual "
            "control is selected. Every effective value will be shown again in Step 2."
        )
        self.reference_parameter_hint.setObjectName("hint")
        self.reference_parameter_hint.setWordWrap(True)
        reference_parameter_layout.addWidget(self.reference_parameter_hint)
        self.project_input_form = form

        self.mesh_edit = QLineEdit()
        self.mesh_edit.setObjectName("meshDirectoryEdit")
        self.mesh_edit.setPlaceholderText(r"e.g. C:\Data\Beetles\meshes")
        self.mesh_edit.textChanged.connect(self._sync_ready_state)
        self.mesh_edit.textChanged.connect(self._invalidate_procrustes_preview)
        self.mesh_edit.editingFinished.connect(self._detect_template_from_text)
        mesh_button = QPushButton("Browse…")
        mesh_button.setObjectName("secondary")
        mesh_button.clicked.connect(self._choose_mesh_directory)
        form.addRow("Mesh folder", _path_row(self.mesh_edit, mesh_button))

        self.template_edit = QLineEdit()
        self.template_edit.setObjectName("templateEdit")
        self.template_edit.setPlaceholderText(
            "automatic: template.vtk/.ply/.obj/.stl"
        )
        self.template_edit.textChanged.connect(self._invalidate_procrustes_preview)
        template_button = QPushButton("Browse…")
        template_button.setObjectName("secondary")
        template_button.clicked.connect(self._choose_template)
        form.addRow("Template", _path_row(self.template_edit, template_button))

        self.pattern_edit = QLineEdit("*.vtk")
        self.pattern_edit.setObjectName("subjectPatternEdit")
        self.pattern_edit.setToolTip(
            "The template is automatically removed from the subject list. PLY, OBJ, "
            "and STL inputs require reviewed landmark Procrustes preprocessing and are "
            "then converted to canonical VTK copies."
        )
        self.pattern_edit.textChanged.connect(self._invalidate_procrustes_preview)
        form.addRow("File pattern", self.pattern_edit)

        self.project_edit = QLineEdit()
        self.project_edit.setObjectName("projectDirectoryEdit")
        self.project_edit.setPlaceholderText("Folder for configuration and later results")
        self.project_edit.textChanged.connect(self._sync_ready_state)
        project_button = QPushButton("Browse…")
        project_button.setObjectName("secondary")
        project_button.clicked.connect(self._choose_project_directory)
        form.addRow("Project folder", _path_row(self.project_edit, project_button))

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("projectNameEdit")
        self.name_edit.setPlaceholderText("optional; otherwise derived from the folder name")
        form.addRow("Project name", self.name_edit)

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
        self.units_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        form.addRow("Coordinate unit", self.units_combo)

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
        form.addRow("Landmarks", landmarks_row)

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
        self.landmark_auto_advance_check.setObjectName(
            "autoAdvanceLandmarkMeshCheck"
        )
        self.landmark_auto_advance_check.setChecked(True)
        landmark_plan = QHBoxLayout()
        landmark_plan.setContentsMargins(0, 0, 0, 0)
        landmark_plan.setSpacing(12)
        landmark_plan.addWidget(self.landmark_count_spin)
        landmark_plan.addWidget(self.landmark_auto_advance_check, 1)
        form.addRow("Planned landmarks", landmark_plan)

        self.procrustes_box = QWidget()
        procrustes_layout = QVBoxLayout(self.procrustes_box)
        procrustes_layout.setContentsMargins(0, 0, 0, 0)
        procrustes_layout.setSpacing(6)
        self.procrustes_apply_check = QCheckBox(
            "Apply generalized Procrustes before atlas computation"
        )
        self.procrustes_apply_check.setChecked(True)
        self.procrustes_apply_check.toggled.connect(
            self._procrustes_inputs_changed
        )
        self.procrustes_scale_check = QCheckBox("Scale to unit centroid size")
        self.procrustes_scale_check.setChecked(True)
        self.procrustes_scale_check.toggled.connect(
            self._procrustes_inputs_changed
        )
        self.procrustes_reflection_check = QCheckBox("Allow reflections")
        self.procrustes_reflection_check.toggled.connect(
            self._procrustes_inputs_changed
        )
        procrustes_settings = QHBoxLayout()
        procrustes_settings.addWidget(self.procrustes_scale_check)
        procrustes_settings.addWidget(self.procrustes_reflection_check)
        procrustes_settings.addStretch()
        procrustes_advanced = QHBoxLayout()
        self.procrustes_tolerance_spin = QDoubleSpinBox()
        self.procrustes_tolerance_spin.setDecimals(12)
        self.procrustes_tolerance_spin.setRange(0.000000000001, 1.0)
        self.procrustes_tolerance_spin.setValue(0.0000000001)
        self.procrustes_tolerance_spin.valueChanged.connect(
            self._procrustes_inputs_changed
        )
        self.procrustes_iterations_spin = QSpinBox()
        self.procrustes_iterations_spin.setRange(1, 100000)
        self.procrustes_iterations_spin.setValue(100)
        self.procrustes_iterations_spin.valueChanged.connect(
            self._procrustes_inputs_changed
        )
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
        self.preview_procrustes_button = QPushButton(
            "Preview alignment read-only"
        )
        self.preview_procrustes_button.setObjectName("secondary")
        self.preview_procrustes_button.clicked.connect(self._preview_procrustes)
        self.procrustes_preview_status_label = _ReadOnlyStatusText(
            "No alignment preview has been reviewed."
        )
        self.procrustes_preview_status_label.setObjectName("status")
        self.approve_procrustes_check = QCheckBox(
            "I reviewed and approve this exact alignment preview"
        )
        self.approve_procrustes_check.setEnabled(False)
        self.approve_procrustes_check.toggled.connect(
            self._reference_recommendation_inputs_changed
        )
        procrustes_layout.addWidget(self.preview_procrustes_button)
        procrustes_layout.addWidget(self.procrustes_preview_status_label)
        procrustes_layout.addWidget(self.approve_procrustes_check)
        self._procrustes_setting_widgets = (
            self.procrustes_scale_check,
            self.procrustes_reflection_check,
            self.procrustes_tolerance_spin,
            self.procrustes_iterations_spin,
        )
        self.procrustes_box.hide()
        form.addRow("Alignment", self.procrustes_box)

        self.already_gpa_check = QCheckBox(
            "I confirm that these mesh coordinates are already GPA aligned"
        )
        self.already_gpa_check.setObjectName("alreadyGpaAlignedCheck")
        self.already_gpa_check.setToolTip(
            "Use this only when translation, rotation, and the intended size treatment "
            "have already been completed outside DiffeoForge. Geometry diagnostics can "
            "flag suspicious dispersion but cannot prove homologous alignment."
        )
        self.already_gpa_check.toggled.connect(
            self._reference_recommendation_inputs_changed
        )
        form.addRow("Existing alignment", self.already_gpa_check)

        self.reference_guidance_box = QWidget()
        guidance_layout = QVBoxLayout(self.reference_guidance_box)
        guidance_layout.setContentsMargins(0, 0, 0, 0)
        guidance_layout.setSpacing(7)
        self.reference_surface_detail_combo = QComboBox()
        self.reference_surface_detail_combo.setObjectName(
            "referenceSurfaceDetailCombo"
        )
        self.reference_surface_detail_combo.addItem(
            "Fine anatomical detail", "fine"
        )
        self.reference_surface_detail_combo.addItem(
            "Balanced anatomical detail", "balanced"
        )
        self.reference_surface_detail_combo.addItem(
            "Coarse / global surface detail", "coarse"
        )
        self.reference_surface_detail_combo.setCurrentIndex(
            self.reference_surface_detail_combo.findData("balanced")
        )
        self.reference_surface_detail_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        self.reference_deformation_scale_combo = QComboBox()
        self.reference_deformation_scale_combo.setObjectName(
            "referenceDeformationScaleCombo"
        )
        self.reference_deformation_scale_combo.addItem(
            "Local shape differences", "local"
        )
        self.reference_deformation_scale_combo.addItem(
            "Balanced local and global differences", "balanced"
        )
        self.reference_deformation_scale_combo.addItem(
            "Global shape differences", "global"
        )
        self.reference_deformation_scale_combo.setCurrentIndex(
            self.reference_deformation_scale_combo.findData("balanced")
        )
        self.reference_deformation_scale_combo.currentIndexChanged.connect(
            self._reference_recommendation_inputs_changed
        )
        guidance_form = QFormLayout()
        guidance_form.setContentsMargins(0, 0, 0, 0)
        guidance_form.setHorizontalSpacing(18)
        guidance_form.setVerticalSpacing(7)
        guidance_form.addRow("Surface detail to preserve", self.reference_surface_detail_combo)
        guidance_form.addRow(
            "Scale of biological variation",
            self.reference_deformation_scale_combo,
        )
        guidance_layout.addLayout(guidance_form)
        guidance_hint = QLabel(
            "DiffeoForge derives scale and a mesh-sampling lower bound. You decide which "
            "anatomical detail and deformation scale are scientifically relevant."
        )
        guidance_hint.setObjectName("hint")
        guidance_hint.setWordWrap(True)
        guidance_layout.addWidget(guidance_hint)
        self.analyze_reference_parameters_button = QPushButton(
            "Analyze aligned meshes & suggest parameters"
        )
        self.analyze_reference_parameters_button.setObjectName("secondary")
        self.analyze_reference_parameters_button.clicked.connect(
            self._analyze_reference_parameters
        )
        guidance_layout.addWidget(self.analyze_reference_parameters_button)
        self.reference_guidance_status_label = QLabel(
            "No aligned-mesh analysis has been completed."
        )
        self.reference_guidance_status_label.setObjectName("status")
        self.reference_guidance_status_label.setWordWrap(True)
        self.reference_guidance_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        guidance_layout.addWidget(self.reference_guidance_status_label)
        form.addRow("Parameter guidance", self.reference_guidance_box)
        form.addRow("Deformetrica parameters", self.reference_parameter_box)

        card_layout.addLayout(form)
        return card

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
            self.landmark_auto_advance_check.setChecked(
                dialog.auto_advance_mesh_check.isChecked()
            )
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
        preview_running = isinstance(self._worker, _ProcrustesPreviewWorker)
        self._procrustes_preview = None
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(False)
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
            self.procrustes_preview_status_label.setText(
                "No alignment preview has been reviewed."
            )
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
            enabled
            and bool(self.landmarks_edit.text().strip())
            and self._worker is None
        )
        self.approve_procrustes_check.setEnabled(
            enabled
            and self._procrustes_preview is not None
            and self._procrustes_preview.alignment.converged
            and self._preview_matches_current_procrustes_inputs()
            and self._worker is None
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
            self.landmarks_edit.text().strip()
            and self.procrustes_apply_check.isChecked()
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
        )

    def _invalidate_reference_recommendation(
        self,
        message: str = "Inputs changed; analyze the aligned meshes again.",
        *,
        sync: bool = True,
    ) -> None:
        had_recommendation = self._reference_recommendation is not None
        self._reference_recommendation = None
        self._reference_recommendation_paths = None
        if self.reference_parameter_profile_combo.currentData() == "data_assisted":
            self.reference_parameter_profile_combo.blockSignals(True)
            self.reference_parameter_profile_combo.setCurrentIndex(
                self.reference_parameter_profile_combo.findData("pending")
            )
            self.reference_parameter_profile_combo.blockSignals(False)
            self._set_reference_parameter_fields_visible(False)
            self.reference_parameter_hint.setText(
                "No parameter values are active. Analyze the aligned meshes again or "
                "choose Advanced manual control."
            )
        if had_recommendation:
            self.reference_guidance_status_label.setObjectName("statusWarning")
            self.reference_guidance_status_label.setStyleSheet("")
            self.reference_guidance_status_label.setText(message)
        elif not isinstance(self._worker, _ReferenceParameterWorker):
            self.reference_guidance_status_label.setObjectName("status")
            self.reference_guidance_status_label.setStyleSheet("")
            self.reference_guidance_status_label.setText(
                "No aligned-mesh analysis has been completed."
            )
        if sync:
            self._update_reference_guidance_controls()
            self._sync_ready_state()

    @Slot()
    def _reference_recommendation_inputs_changed(self) -> None:
        self._invalidate_reference_recommendation()

    def _update_reference_guidance_controls(self) -> None:
        reference = (
            self.engine_combo.currentData()
            == DesktopEngine.DEFORMETRICA_REFERENCE
        )
        uses_diffeoforge_gpa = bool(
            self.landmarks_edit.text().strip()
            and self.procrustes_apply_check.isChecked()
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
            self.analyze_reference_parameters_button.setText(
                "Analyzing aligned meshes…"
            )
        else:
            self.analyze_reference_parameters_button.setText(
                "Analyze aligned meshes & suggest parameters"
            )

    @Slot()
    def _analyze_reference_parameters(self) -> None:
        if self._worker is not None:
            return
        try:
            paths = self._current_surface_cohort()
            alignment_basis, transforms, alignment_fingerprint = (
                self._reference_alignment_context()
            )
        except (OSError, TypeError, ValueError) as error:
            self._reference_parameter_analysis_failed(str(error))
            return
        worker = _ReferenceParameterWorker(
            mesh_paths=paths,
            alignment_basis=alignment_basis,
            surface_detail_intent=str(
                self.reference_surface_detail_combo.currentData()
            ),
            deformation_scale_intent=str(
                self.reference_deformation_scale_combo.currentData()
            ),
            transforms=transforms,
            alignment_fingerprint=alignment_fingerprint,
        )
        worker.signals.succeeded.connect(
            self._reference_parameter_analysis_succeeded
        )
        worker.signals.failed.connect(self._reference_parameter_analysis_failed)
        self._worker = worker
        self._reference_recommendation = None
        self._reference_recommendation_paths = None
        self.reference_guidance_status_label.setObjectName("status")
        self.reference_guidance_status_label.setStyleSheet("")
        self.reference_guidance_status_label.setText(
            "Reading the aligned coordinates and measuring cohort scale, centroid "
            "dispersion, and mesh sampling. No mesh is being changed."
        )
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
            and self.reference_surface_detail_combo.currentData()
            == worker.surface_detail_intent
            and self.reference_deformation_scale_combo.currentData()
            == worker.deformation_scale_intent
        )
        if not inputs_match:
            self._reference_parameter_analysis_failed(
                "Analysis discarded because alignment, mesh selection, or scientific "
                "scale choices changed while it was running."
            )
            return

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
        warning_lines = "\n".join(
            f"• {warning}" for warning in recommendation.warnings
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
            f"Suggested attachment: {recommendation.attachment_kernel_width_ratio:.5g} × "
            f"template diagonal = {effective['attachment_kernel_width']:.6g}; "
            f"deformation: {recommendation.deformation_kernel_width_ratio:.5g} × "
            f"diagonal = {effective['deformation_kernel_width']:.6g}; "
            f"control spacing: {recommendation.control_point_spacing_ratio:.5g} × "
            f"diagonal = {effective['initial_control_point_spacing']:.6g} "
            f"({coordinate_label}).\n"
            f"Provisional noise SD: {recommendation.provisional_noise_std_ratio:.5g} × "
            f"diagonal = {effective['noise_std']:.6g}; this is not inferable from "
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
        self.reference_guidance_status_label.setObjectName("statusError")
        self.reference_guidance_status_label.setStyleSheet("")
        self.reference_guidance_status_label.setText(
            f"Aligned-mesh parameter analysis failed: {message}"
        )
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
            mesh_directory, landmarks_file, template, pattern = (
                self._current_procrustes_paths()
            )
            resolved_template = template or detect_template(mesh_directory)
        except (OSError, TypeError, ValueError):
            return False
        return bool(
            resolved_template is not None
            and preview.mesh_directory == mesh_directory
            and preview.landmarks == landmarks_file
            and preview.template == resolved_template.resolve()
            and preview.subject_pattern == pattern
            and preview.scale_to_unit_centroid_size
            == self.procrustes_scale_check.isChecked()
            and preview.allow_reflection
            == self.procrustes_reflection_check.isChecked()
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
        ):
            return self._procrustes_preview.fingerprint
        return None

    @Slot()
    def _preview_procrustes(self) -> None:
        if self._worker is not None or not self.procrustes_apply_check.isChecked():
            return
        try:
            mesh_directory, landmarks_file, template, pattern = (
                self._current_procrustes_paths()
            )
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
            format_counts[metadata.source_format] = (
                format_counts.get(metadata.source_format, 0) + 1
            )
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
            "does not establish biological landmark quality."
        )
        self.approve_procrustes_check.setChecked(False)
        self.approve_procrustes_check.setEnabled(alignment.converged)
        self._update_procrustes_controls()
        self._sync_ready_state()

    @Slot(str)
    def _procrustes_preview_failed(self, message: str) -> None:
        if isinstance(self._worker, _ProcrustesPreviewWorker):
            self._worker = None
        self._procrustes_preview = None
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
            self._saved_reference_status_result_matches_inputs()
            and self._worker is None
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
            self._reference_preparation_status_matches_inputs()
            and self._worker is None
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
        worker.signals.succeeded.connect(
            self._saved_reference_status_verification_succeeded
        )
        worker.signals.failed.connect(self._saved_reference_status_verification_failed)
        self._worker = worker
        self._saved_reference_preparation_status_verification = None
        self.saved_reference_status_verification_label.setObjectName("status")
        self.saved_reference_status_verification_label.setStyleSheet("")
        self.saved_reference_status_verification_label.setText(
            "File hash, strict JSON, schema, and deterministic bytes are being checked "
            "read-only…"
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
            or result.expected_report_sha256
            != worker.expected_report_sha256.strip().lower()
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
            self.saved_reference_status_verification_export_label.setObjectName(
                "statusError"
            )
            self.saved_reference_status_verification_export_label.setStyleSheet("")
            self.saved_reference_status_verification_export_label.setText(
                "No evidence export: the discarded result is no longer bound to the current inputs."
            )
            self._sync_ready_state()
            return

        self._saved_reference_preparation_status_verification = result
        engine_started = (
            "no"
            if result.engine_execution_started is False
            else "not observed in the saved status"
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
        self.saved_reference_status_verification_detail_label.setText(
            "\n".join(details)
        )
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
        self.saved_reference_status_verification_export_label.setObjectName(
            "statusError"
        )
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
            self.saved_reference_status_verification_export_label.setObjectName(
                "statusError"
            )
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
            self.saved_reference_status_verification_export_label.setObjectName(
                "statusError"
            )
            self.saved_reference_status_verification_export_label.setStyleSheet("")
            self.saved_reference_status_verification_export_label.setText(
                f"Verification evidence was not exported: {error}"
            )
            self._sync_saved_reference_status_verification_controls()
            return
        self.saved_reference_status_verification_export_label.setObjectName(
            "statusSuccess"
        )
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
    def _ratio_spin_box(tooltip: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(5)
        spin.setRange(0.00001, 2.0)
        spin.setSingleStep(0.01)
        spin.setToolTip(tooltip)
        return spin

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
            label = self.reference_parameter_form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)

    @Slot()
    def _update_reference_parameter_profile(self) -> None:
        key = str(self.reference_parameter_profile_combo.currentData())
        if key == "pending":
            self._set_reference_parameter_fields_visible(False)
            self.reference_parameter_hint.setText(
                "No parameter values are active. Confirm existing GPA alignment or complete "
                "the DiffeoForge landmark-GPA preview, then analyze the aligned meshes."
            )
            self._sync_ready_state()
            return

        recommendation = self._reference_recommendation
        if key == "data_assisted":
            if recommendation is None:
                self._set_reference_parameter_fields_visible(False)
                self.reference_parameter_hint.setText(
                    "No current aligned-mesh recommendation is available. Run the geometry "
                    "analysis again or choose Advanced manual control."
                )
                self._sync_ready_state()
                return
            values = (
                (
                    self.reference_attachment_ratio_spin,
                    recommendation.attachment_kernel_width_ratio,
                ),
                (
                    self.reference_deformation_ratio_spin,
                    recommendation.deformation_kernel_width_ratio,
                ),
                (
                    self.reference_control_spacing_ratio_spin,
                    recommendation.control_point_spacing_ratio,
                ),
                (
                    self.reference_noise_ratio_spin,
                    recommendation.provisional_noise_std_ratio,
                ),
                (self.reference_max_iterations_spin, recommendation.max_iterations),
                (self.reference_step_size_spin, recommendation.initial_step_size),
                (
                    self.reference_tolerance_spin,
                    recommendation.convergence_tolerance,
                ),
            )
            self._set_reference_parameter_fields_visible(True)
            for widget, value in values:
                widget.setValue(value)
                widget.setEnabled(False)
            self.reference_parameter_hint.setText(
                "Geometry-derived scale and sampling constraints plus your stated detail "
                "and deformation-scale choices. Noise and optimizer settings remain "
                "provisional and require pilot validation."
            )
            self._sync_ready_state()
            return

        profile = reference_parameter_profile("recommended")
        if self._reference_recommendation is None:
            values = (
                (self.reference_attachment_ratio_spin, profile.attachment_ratio),
                (self.reference_deformation_ratio_spin, profile.deformation_ratio),
                (
                    self.reference_control_spacing_ratio_spin,
                    profile.control_point_spacing_ratio,
                ),
                (self.reference_noise_ratio_spin, profile.noise_ratio),
                (self.reference_max_iterations_spin, profile.max_iterations),
                (self.reference_step_size_spin, profile.initial_step_size),
                (self.reference_tolerance_spin, profile.convergence_tolerance),
            )
            for widget, value in values:
                widget.setValue(value)
        self._set_reference_parameter_fields_visible(True)
        for widget in self._reference_parameter_widgets():
            widget.setEnabled(True)
        if key == "advanced":
            self.reference_parameter_hint.setText(
                "Advanced values are editable. Length parameters are dimensionless fractions "
                "of the template bounding-box diagonal; DiffeoForge converts them to the "
                "declared coordinate unit and records both ratios and effective values."
            )
        self._sync_ready_state()

    @Slot()
    def _update_reference_expert_visibility(self) -> None:
        self.reference_expert_box.setVisible(self.reference_expert_toggle.isChecked())

    @Slot()
    def _update_reference_expert_dependencies(self) -> None:
        self.reference_sobolev_ratio_spin.setEnabled(
            self.reference_sobolev_check.isChecked()
        )

    @Slot()
    def _update_engine_explanation(self) -> None:
        modern = self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
        self.landmarks_edit.setEnabled(True)
        self.landmarks_button.setEnabled(True)
        self.project_input_form.setRowVisible(self.pairwise_box, modern)
        self.project_input_form.setRowVisible(self.optimization_effort_box, modern)
        self.project_input_form.setRowVisible(self.already_gpa_check, not modern)
        self.project_input_form.setRowVisible(self.reference_guidance_box, not modern)
        self.project_input_form.setRowVisible(self.reference_parameter_box, not modern)
        if modern:
            self.engine_hint.setText(
                "Current CPU/float64 engine; PCA is part of the later result bundle."
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
        self._update_reference_parameter_profile()
        self._update_reference_guidance_controls()

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
            return self._review is not None
        if step == 2:
            if self._run_result is not None or self._result_review is not None:
                return True
            if self._review is None:
                return False
            if self._review.engine is DesktopEngine.MODERN_CPU:
                return True
            return bool(
                self._reference_readiness is not None
                and self._reference_readiness.ready
            )
        if step == 3:
            return self._result_review is not None
        return False

    def _sync_navigation_state(self) -> None:
        locked_reasons = (
            "Complete Step 1 before opening parameter review.",
            "Complete parameter review before opening atlas computation.",
            "Complete and verify an atlas run before opening Results & PCA.",
        )
        for index, button in enumerate(self.rail_steps):
            unlocked = self._step_is_unlocked(index)
            button.setEnabled(unlocked)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor
                if unlocked
                else Qt.CursorShape.ArrowCursor
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

    def _sync_setup_primary_action(self, *, form_ready: bool) -> None:
        if isinstance(self._worker, _ProjectWorker):
            self.create_button.setText("Validating data…")
            self.create_button.setEnabled(False)
        elif isinstance(self._worker, _ReviewWorker):
            self.create_button.setText("Reviewing parameters…")
            self.create_button.setEnabled(False)
        elif self._review is not None:
            self.create_button.setText("Continue to parameter review")
            self.create_button.setEnabled(self._worker is None)
        elif self._result is not None:
            self.create_button.setText("Review parameters & workload")
            self.create_button.setEnabled(self._worker is None)
        else:
            approval_required = bool(
                self.landmarks_edit.text().strip()
                and self.procrustes_apply_check.isChecked()
                and self._approved_procrustes_fingerprint() is None
            )
            parameter_guidance_required = bool(
                self.engine_combo.currentData()
                == DesktopEngine.DEFORMETRICA_REFERENCE
                and (
                    self.reference_parameter_profile_combo.currentData()
                    == "pending"
                    or (
                        self.reference_parameter_profile_combo.currentData()
                        == "data_assisted"
                        and not self._reference_recommendation_matches_current_inputs()
                    )
                )
            )
            self.create_button.setText(
                "Preview & approve alignment first"
                if approval_required
                else (
                    "Analyze aligned meshes or choose manual parameters"
                    if parameter_guidance_required
                    else "Validate data & create project"
                )
            )
            self.create_button.setEnabled(form_ready and self._worker is None)

    def _sync_run_primary_action(self) -> None:
        if isinstance(self._worker, (_AtlasWorker, _ReferenceAtlasWorker)):
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
            self.start_atlas_button.setText(
                "Start reviewed Deformetrica atlas"
                if reference
                else "Start reviewed Modern atlas"
            )
            self.start_atlas_button.setEnabled(
                bool(
                    self._worker is None
                    and (
                        self._reference_run_request is not None
                        if reference
                        else self._run_readiness is not None
                        and self._run_readiness.ready_for_worker
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
            or reference_profile == "advanced"
            or (
                reference_profile == "data_assisted"
                and self._reference_recommendation_matches_current_inputs()
            )
        )
        ready = bool(
            self.mesh_edit.text().strip()
            and self.project_edit.text().strip()
            and self.units_combo.currentData() is not None
            and alignment_ready
            and reference_parameters_ready
        )
        self._update_procrustes_controls()
        self._update_reference_guidance_controls()
        self._sync_setup_primary_action(form_ready=ready)
        self._sync_run_primary_action()
        self._sync_navigation_state()
        self._sync_reference_preparation_status_controls()
        self._sync_saved_reference_status_verification_controls()

    @Slot()
    def _setup_primary_action(self) -> None:
        if self._worker is not None:
            return
        if self._review is not None:
            self._navigate_to_step(1)
        elif self._result is not None:
            self._review_project()
        else:
            self._create_project()

    @Slot()
    def _run_primary_action(self) -> None:
        if self._worker is not None:
            return
        if self._result_review is not None:
            self._navigate_to_step(3)
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
        recommendation_is_current = bool(
            reference_profile == "data_assisted"
            and self._reference_recommendation is not None
            and self._reference_recommendation_matches_current_inputs()
        )
        if (
            self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
            and reference_profile == "pending"
        ):
            reference_profile = "recommended"
        reference_ratios = (
            self._reference_recommendation.parameter_ratios
            if recommendation_is_current and self._reference_recommendation is not None
            else {
                "attachment_kernel_width": self.reference_attachment_ratio_spin.value(),
                "deformation_kernel_width": self.reference_deformation_ratio_spin.value(),
                "initial_control_point_spacing": (
                    self.reference_control_spacing_ratio_spin.value()
                ),
                "noise_std": self.reference_noise_ratio_spin.value(),
            }
        )
        return ProjectSetupRequest(
            mesh_directory=Path(self.mesh_edit.text().strip()),
            project_directory=Path(self.project_edit.text().strip()),
            units=self.units_combo.currentData(),
            engine=self.engine_combo.currentData(),
            template=Path(template) if template else None,
            project_name=self.name_edit.text().strip() or None,
            subject_pattern=self.pattern_edit.text(),
            landmarks_file=(
                Path(landmarks) if apply_procrustes else None
            ),
            pairwise_mode="blockwise" if blockwise else "dense",
            query_tile_size=256 if blockwise else None,
            source_tile_size=256 if blockwise else None,
            max_cycles=int(self.optimization_effort_combo.currentData()),
            reference_parameter_profile=reference_profile,
            reference_parameter_ratios=reference_ratios,
            reference_parameter_recommendation=(
                self._reference_recommendation.provenance
                if recommendation_is_current
                and self._reference_recommendation is not None
                else None
            ),
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
            reference_threads=self.reference_threads_spin.value(),
            reference_random_seed=self.reference_random_seed_spin.value(),
            procrustes_scale_to_unit_centroid_size=self.procrustes_scale_check.isChecked(),
            procrustes_allow_reflection=self.procrustes_reflection_check.isChecked(),
            procrustes_tolerance=self.procrustes_tolerance_spin.value(),
            procrustes_max_iterations=self.procrustes_iterations_spin.value(),
            approved_procrustes_fingerprint=(
                self._approved_procrustes_fingerprint()
                if apply_procrustes
                else None
            ),
        )

    @staticmethod
    def _configuration_path(request: ProjectSetupRequest) -> Path:
        filename = (
            "modern-atlas.yaml"
            if request.engine == DesktopEngine.MODERN_CPU
            else "atlas.yaml"
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
            "Generated workload evidence will be refreshed during Step 2. Source meshes, "
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

    @Slot(str)
    def _project_failed(self, message: str) -> None:
        self._worker = None
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
            "DiffeoForge Modern CPU (experimental)"
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
        self._set_active_step(1)
        self.page_stack.setCurrentIndex(1)
        self._sync_ready_state()

    @Slot()
    def _load_template_preview(self) -> None:
        if (
            self._result is None
            or self._review is None
            or self._result.config_path.resolve() != self._review.config_path.resolve()
            or self._worker is not None
        ):
            return
        worker = _TemplatePreviewWorker(self._result.template_path.resolve())
        worker.signals.succeeded.connect(self._template_preview_succeeded)
        worker.signals.failed.connect(self._template_preview_failed)
        self._worker = worker
        self._template_preview = None
        self.template_preview_canvas.set_model(None)
        self.template_preview_plane_combo.setEnabled(False)
        self.refresh_template_preview_button.setEnabled(False)
        self.template_preview_status_label.setObjectName("status")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(
            "Template geometry and unique edges are being loaded read-only outside the "
            "event loop…"
        )
        self.template_preview_detail_label.setText(
            "The source file is hashed before and after loading. No points, faces, or files "
            "are modified."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _template_preview_succeeded(self, model: MeshPreviewModel) -> None:
        self._worker = None
        if (
            self._result is None
            or model.path.resolve() != self._result.template_path.resolve()
        ):
            self._template_preview_failed(
                "The loaded preview model does not belong to the current template"
            )
            return
        self._template_preview = model
        self.template_preview_plane_combo.setEnabled(True)
        self.refresh_template_preview_button.setEnabled(True)
        self._update_template_preview_plane(self.template_preview_plane_combo.currentIndex())
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
        self._worker = None
        self._template_preview = None
        self.template_preview_canvas.set_model(None)
        self.template_preview_plane_combo.setEnabled(False)
        self.refresh_template_preview_button.setEnabled(
            self._result is not None and self._review is not None
        )
        self.template_preview_status_label.setObjectName("statusError")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(
            f"Template preview was not loaded: {message}"
        )
        self.template_preview_detail_label.setText(
            "No preview released; the template file was not modified."
        )
        self._sync_ready_state()

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
        self.refresh_reference_readiness_button.setEnabled(False)
        self.reference_readiness_status_label.setObjectName("status")
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(
            "Deformetrica 4.3, available memory, and the project folder are being checked "
            "automatically…"
        )
        self.reference_readiness_detail_label.setText(
            "This safety check does not start an atlas. Estimated computation time is shown "
            "separately in Step 3 after several optimizer iterations have been observed."
        )
        self.show_run_button.setText("Checking Deformetrica setup automatically…")
        self.show_run_button.setEnabled(False)
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _reference_readiness_succeeded(
        self, readiness: DesktopReferenceReadiness
    ) -> None:
        self._worker = None
        self._reference_readiness = readiness
        details = [
            f"Configuration: {self._wrappable_path(readiness.config_path)}",
            f"Bound SHA-256: {readiness.config_sha256}",
            f"Project folder: {self._wrappable_path(readiness.workspace)}",
            f"Deformetrica installation: {launcher_label(readiness.launcher)}",
            "Observed checks:",
        ]
        for check in readiness.report.checks:
            details.append(f"[{check.status.upper()}] {check.label}: {check.summary}")
            if check.guidance:
                details.append(f"  Guidance: {check.guidance}")
        details.append(
            "No atlas process was started; nothing installed or changed by this check."
        )
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
        self._sync_ready_state()

    @Slot(str)
    def _reference_readiness_failed(self, message: str) -> None:
        self._worker = None
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
            self._review is not None
            and self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
        )
        self.show_run_button.setText("Setup check failed – check again")
        self.show_run_button.setEnabled(False)
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
        worker.signals.succeeded.connect(
            self._reference_preparation_status_succeeded
        )
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
            or status.approval_sha256
            != worker.expected_approval_sha256.strip().lower()
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
            details.append(
                f"[{stage.status}] {self._wrappable_path(stage.path)}: {stage.reason}"
            )
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
            message = (
                "The prepared reference run is fully verified and was not executed."
            )
        else:
            self.reference_preparation_status_label.setObjectName("statusError")
            message = (
                "The observed state requires an explicit human decision. Nothing was changed."
            )
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
        default = status.config_path.parent / (
            f"reference-preparation-status-{status.run_id}.json"
        )
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
        self._navigate_to_step(2)

    @Slot()
    def _refresh_run_readiness(
        self,
    ) -> DesktopReviewedRunReadiness | DesktopReferenceLaunchRequest | None:
        review = self._review
        if review is None:
            return None
        if review.engine is DesktopEngine.DEFORMETRICA_REFERENCE:
            return self._refresh_reference_run_readiness(review)
        try:
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
        self.run_title_label.setText("Compute Deformetrica atlas")
        self.run_subtitle_label.setText(
            "Run the exact reviewed configuration in a contained child process and observe "
            "Deformetrica iterations, objective values, elapsed time, and a live computation-"
            "time estimate."
        )
        self.run_boundary_label.setText(
            "Estimated computation time appears only after several observed iterations. It "
            "means time to the configured iteration maximum if the recent rate continues, "
            "not time to convergence. Cancellation preserves terminal evidence and a "
            "checkpoint when Deformetrica produced one."
        )
        if readiness is None or not readiness.ready:
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Deformetrica execution is blocked until the reviewed environment check passes."
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
        self.run_optimizer_label.setText(
            "Estimated computation time: waiting for several observed Deformetrica "
            "iterations."
        )
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText("Ready; no Deformetrica process has started.")
        self._sync_ready_state()
        return request

    def _apply_run_readiness(self, readiness: DesktopReviewedRunReadiness) -> None:
        self._reference_run_request = None
        self.run_title_label.setText("Compute Modern atlas")
        self.run_subtitle_label.setText(
            "Run the exact reviewed configuration in a separate process and observe real "
            "workflow events."
        )
        self.run_boundary_label.setText(
            "Experimental Modern CPU route. Runtime, peak RAM, and percentage progress are "
            "not estimated. Cancellation acts only at designated safe points and runs are "
            "not currently resumable."
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
        can_start = (
            readiness.ready_for_worker
            and self._run_result is None
            and self._worker is None
        )
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
        self._navigate_to_step(1)

    @Slot()
    def _start_atlas(self) -> None:
        if (
            self._review is None
            or self._worker is not None
            or self._run_result is not None
        ):
            return
        readiness = self._refresh_run_readiness()
        reference = self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
        if reference:
            if not isinstance(readiness, DesktopReferenceLaunchRequest):
                return
            request = readiness
            worker: _AtlasWorker | _ReferenceAtlasWorker = _ReferenceAtlasWorker(
                ReferenceExecutionController(request)
            )
        else:
            if (
                not isinstance(readiness, DesktopReviewedRunReadiness)
                or not readiness.ready_for_worker
            ):
                return
            request = readiness.request
            worker = _AtlasWorker(DesktopWorkerController(request))
        worker.signals.event.connect(self._atlas_event)
        worker.signals.succeeded.connect(self._atlas_succeeded)
        worker.signals.failed.connect(self._atlas_failed)
        worker.signals.cancel_failed.connect(self._atlas_cancel_failed)
        self._worker = worker
        self._result_review = None
        self.run_result_card.hide()
        self.run_event_log.clear()
        if reference:
            self.run_progress_bar.setRange(0, 0)
            self.run_progress_bar.setFormat("Starting Deformetrica")
        else:
            self.run_progress_bar.setRange(0, 7)
            self.run_progress_bar.setValue(0)
            self.run_progress_bar.setFormat("Completed stages: %v of %m")
        self.run_stage_label.setText("Workflow stage: worker is starting")
        self.run_optimizer_label.setText(
            "No Deformetrica iteration observed yet."
            if reference
            else "No optimization decision yet."
        )
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Child process is starting; configuration binding and destination are being "
            "checked again."
        )
        self.run_summary_label.setText(
            f"Project: {self._review.project_name}\n"
            f"Request-ID: {request.request_id}\n"
            f"Configuration: {self._wrappable_path(request.config_path)}\n"
            f"Bound SHA-256: {request.expected_config_sha256}\n"
            f"Non-overwritable destination: {self._wrappable_path(request.destination)}"
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
        if not isinstance(
            worker, (_AtlasWorker, _ReferenceAtlasWorker)
        ) or not worker.request_cancel():
            return
        self.cancel_atlas_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        if isinstance(worker, _ReferenceAtlasWorker):
            self.run_state_label.setText(
                "Cancellation requested. Deformetrica will be interrupted after the current "
                "log/optimizer operation; terminal evidence and any checkpoint are preserved."
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
        event: DesktopWorkerEvent | DesktopReferenceWorkerEvent,
    ) -> None:
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
            self.run_state_label.setText(message)
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
                "warming up"
                if rate_value is None
                else f"{float(rate_value):.2f} s/iteration"
            )
            message = (
                f"Iteration {iteration} of {maximum}; objective "
                f"{float(event.payload['log_likelihood']):.6g}"
            )
            self.run_progress_bar.setRange(0, maximum)
            self.run_progress_bar.setValue(min(iteration, maximum))
            self.run_progress_bar.setFormat(
                "Iteration %v of maximum %m"
            )
            self.run_stage_label.setText(
                "Deformetrica stage: execute · optimizer output is being observed"
            )
            self.run_optimizer_label.setText(
                f"Iteration {iteration} of maximum {maximum} · objective "
                f"{float(event.payload['log_likelihood']):.6g} · attachment "
                f"{float(event.payload['attachment']):.6g} · regularity "
                f"{float(event.payload['regularity']):.6g}\n"
                f"Elapsed: {self._format_duration(elapsed)} · observed rate: {rate_text} · "
                f"Estimated computation time to maximum: {eta_text} "
                "(live upper bound, not convergence)"
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
        result: DesktopWorkerControllerResult | ReferenceExecutionControllerResult,
    ) -> None:
        self._worker = None
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        if isinstance(result, ReferenceExecutionControllerResult):
            self._reference_atlas_succeeded(result)
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
        self._worker = None
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(f"Atlas run failed or was rejected: {message}")
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
                (DesktopWorkerControllerResult, ReferenceExecutionControllerResult),
            )
            or not self._run_result.completed
            or self._worker is not None
        ):
            return
        destination = Path(self._run_result.terminal_event.payload["destination"])
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
            "are now being imported and bound to a recomputed linear PCA snapshot."
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
        self.result_boundary_label.setText(
            "\n".join(f"• {boundary}" for boundary in review.scientific_boundaries)
        )
        run_label = (
            "Deformetrica run"
            if review.engine_route == "deformetrica_reference"
            else "Workflow"
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
        self.result_status_label.setObjectName("statusSuccess")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "Snapshot fully verified. Before each open action, the selected artifact is "
            "rebound to both manifest hashes, its file size, and SHA-256."
        )
        self.run_back_button.setEnabled(True)
        self._sync_ready_state()
        self._set_active_step(3)
        self.page_stack.setCurrentIndex(3)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

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
            "Verified PC1-versus-PC2 scores from the bound result bundle."
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
            self.result_pc2_pc3_plot_status.setText(
                f"PC2 versus PC3 unavailable: {reason}"
            )
            return

        secondary = verify_result_artifact(review, "pca-score-plot-pc2-pc3")
        self.result_pc2_pc3_plot.load(str(secondary))
        if not self.result_pc2_pc3_plot.renderer().isValid():
            raise ModernResultReviewError("The verified PC2-versus-PC3 SVG is invalid")
        self.result_pc2_pc3_plot.show()
        self.result_pc2_pc3_plot_status.setObjectName("statusSuccess")
        self.result_pc2_pc3_plot_status.setStyleSheet("")
        self.result_pc2_pc3_plot_status.setText(
            "Verified PC2-versus-PC3 scores from the same score matrix and subject order."
        )

    @Slot(str)
    def _result_review_failed(self, message: str) -> None:
        self._worker = None
        self._result_review = None
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

    @Slot()
    def _show_run_page_from_results(self) -> None:
        self._navigate_to_step(2)

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
        if step == 2 and self._run_result is None:
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
        payload = self._run_result.terminal_event.payload
        if not bool(payload.get("destination_exists", True)):
            return
        destination = Path(payload["destination"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if isinstance(self._worker, (_AtlasWorker, _ReferenceAtlasWorker)):
            self._close_after_worker = True
            self._cancel_atlas()
            self.run_state_label.setText(
                "The window will remain open until safe worker termination is confirmed. "
                "Cancellation was requested."
            )
            event.ignore()
            return
        if isinstance(self._worker, (_ResultReviewWorker, _ArtifactWorker)):
            self._close_after_worker = True
            if isinstance(self._worker, _ResultReviewWorker):
                self.run_state_label.setText(
                    "The window will remain open until result verification finishes."
                )
            else:
                self.result_status_label.setText(
                    "The window will remain open until the artifact check finishes."
                )
            event.ignore()
            return
        super().closeEvent(event)
