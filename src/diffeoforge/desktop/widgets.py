"""PySide6 widgets for the first DiffeoForge Desktop vertical slice."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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
from diffeoforge.desktop.reference_preparation_status import (
    DesktopReferencePreparationStatus,
    DesktopReferencePreparationStatusError,
    DesktopReferencePreparationStatusExportError,
    export_reference_preparation_status_report,
    review_reference_preparation_status,
)
from diffeoforge.desktop.reference_readiness import (
    DesktopReferenceReadiness,
    DesktopReferenceReadinessError,
    check_reference_environment,
)
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

_STYLE = """
QMainWindow { background: #f4f7f8; }
QWidget { color: #17252a; font-size: 14px; }
QFrame#rail { background: #123b3a; border: 0; }
QLabel#brandMark { background: #54c6a1; color: #0b302f; border-radius: 18px;
                   font-size: 17px; font-weight: 800; }
QLabel#brand { color: #ffffff; font-size: 20px; font-weight: 700; }
QLabel#railCaption { color: #b9d1cd; font-size: 12px; }
QLabel#stepActive { color: #ffffff; font-weight: 700; padding: 10px 0; }
QLabel#stepFuture { color: #9db8b4; padding: 10px 0; }
QLabel#eyebrow { color: #167c6b; font-size: 12px; font-weight: 700; }
QLabel#title { color: #123b3a; font-size: 30px; font-weight: 750; }
QLabel#subtitle { color: #526b70; font-size: 15px; }
QFrame#boundary { background: #e8f4f0; border: 1px solid #b7dcd2; border-radius: 10px; }
QLabel#boundaryText { color: #245b52; padding: 3px; }
QFrame#card { background: #ffffff; border: 1px solid #dbe4e6; border-radius: 12px; }
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
QLabel#status { background: #f2f5f6; border-radius: 7px; color: #526b70; padding: 10px; }
QLabel#statusSuccess { background: #e5f5ed; border-radius: 7px; color: #176345; padding: 10px; }
QLabel#statusError { background: #fff0ed; border-radius: 7px; color: #a13a2d; padding: 10px; }
QLabel#reviewValue { color: #123b3a; font-weight: 700; }
QLabel#reviewDetail { color: #526b70; font-size: 12px; }
QProgressBar { border: 1px solid #bdcbce; border-radius: 6px; text-align: center;
               background: #eef3f4; min-height: 26px; }
QProgressBar::chunk { background: #54c6a1; border-radius: 5px; }
QPlainTextEdit { background: #f7f9f9; border: 1px solid #dbe4e6; border-radius: 6px;
                 color: #314f53; font-family: Consolas, monospace; font-size: 12px; }
"""

_PRIVATE_STATUS_EXPLANATIONS = {
    "active": "Ein Prozess hält die Lease; dies beweist noch keinen Fortschritt.",
    "abandoned": "Die gültige Lease ist frei; der private Zustand kann verwaist sein.",
    "unattributed": "Dem passenden Verzeichnis fehlt ein vertrauenswürdiger Marker.",
    "invalid_metadata": "Marker oder Lease erfüllen den gebundenen Vertrag nicht.",
    "indeterminate": "Rechte oder Dateisystemverhalten erlauben keine sichere Entscheidung.",
    "unsafe_link": "Der passende Pfad ist ein Link und wurde nicht verfolgt.",
}


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


class _ResultReviewWorker(QRunnable):
    """Fully verify one completed Modern workflow outside the GUI thread."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            review = review_modern_result(self.directory)
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
            | _ReferenceReadinessWorker
            | _ReferencePreparationStatusWorker
            | _ResultReviewWorker
            | _ArtifactWorker
            | _AtlasWorker
            | None
        ) = None
        self._result: ProjectSetupResult | None = None
        self._review: ProjectReviewResult | None = None
        self._template_preview: MeshPreviewModel | None = None
        self._reference_readiness: DesktopReferenceReadiness | None = None
        self._reference_preparation_status: DesktopReferencePreparationStatus | None = None
        self._run_readiness: DesktopReviewedRunReadiness | None = None
        self._run_result: DesktopWorkerControllerResult | None = None
        self._result_review: ModernResultReview | None = None
        self._close_after_worker = False
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
            "1  Daten & Engine",
            "2  Parameter prüfen",
            "3  Atlas berechnen",
            "4  Ergebnisse & PCA",
        )
        self.rail_steps: list[QLabel] = []
        for index, text in enumerate(steps):
            label = QLabel(text)
            label.setObjectName("stepActive" if index == 0 else "stepFuture")
            layout.addWidget(label)
            self.rail_steps.append(label)
        layout.addStretch()
        boundary = QLabel("PRE-ALPHA\nKeine wissenschaftliche Validierung")
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

        eyebrow = QLabel("SCHRITT 1 VON 4")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Neues Atlasprojekt")
        title.setObjectName("title")
        subtitle = QLabel(
            "Wähle deine Meshes und erstelle eine transparente, geprüfte Startkonfiguration."
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
            "Dieser erste Desktop-Slice prüft Daten und erstellt eine Konfiguration. "
            "Er startet noch keine Atlasberechnung."
        )
        boundary_text.setObjectName("boundaryText")
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        layout.addWidget(boundary)
        layout.addWidget(self._build_form_card())

        self.result_card = self._build_result_card()
        self.result_card.hide()
        layout.addWidget(self.result_card)
        layout.addStretch()
        scroll.setWidget(container)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(18)
        self.status_label = QLabel("Fülle Mesh-Ordner, Projektordner und Einheiten aus.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label, 1)
        self.create_button = QPushButton("Daten prüfen & Projekt anlegen")
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self._create_project)
        footer_layout.addWidget(self.create_button)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(scroll, 1)
        content_layout.addWidget(footer)
        return content

    def _build_review_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(52, 40, 52, 24)
        layout.setSpacing(15)

        eyebrow = QLabel("SCHRITT 2 VON 4")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Parameter und Aufwand prüfen")
        title.setObjectName("title")
        subtitle = QLabel(
            "Sieh die tatsächlich gespeicherten Werte und nachprüfbare Rechenoperationen, "
            "bevor irgendeine Engine gestartet wird."
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
        summary_title = QLabel("Geprüftes Projekt")
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
        template_preview_title = QLabel("Native Template-Vorschau")
        template_preview_title.setObjectName("sectionTitle")
        self.template_preview_status_label = QLabel(
            "Die read-only-Wireframe-Vorschau wurde noch nicht geladen."
        )
        self.template_preview_status_label.setObjectName("status")
        self.template_preview_status_label.setWordWrap(True)
        self.template_preview_canvas = MeshPreviewCanvas()
        self.template_preview_plane_combo = QComboBox()
        self.template_preview_plane_combo.setObjectName("templatePreviewPlane")
        self.template_preview_plane_combo.addItem("XY · Ansicht entlang Z", "xy")
        self.template_preview_plane_combo.addItem("XZ · Ansicht entlang Y", "xz")
        self.template_preview_plane_combo.addItem("YZ · Ansicht entlang X", "yz")
        self.template_preview_plane_combo.setEnabled(False)
        self.template_preview_plane_combo.currentIndexChanged.connect(
            self._update_template_preview_plane
        )
        self.template_preview_detail_label = QLabel(
            "Diese Projektion verändert das Mesh nicht und ersetzt weder 3D-Inspektion "
            "noch Mesh-QC oder Landmark-Picking."
        )
        self.template_preview_detail_label.setObjectName("reviewDetail")
        self.template_preview_detail_label.setWordWrap(True)
        self.template_preview_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_template_preview_button = QPushButton(
            "Template read-only laden"
        )
        self.refresh_template_preview_button.setObjectName("secondary")
        self.refresh_template_preview_button.clicked.connect(
            self._load_template_preview
        )
        preview_controls = QHBoxLayout()
        preview_controls.addWidget(QLabel("Projektion"))
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

        layout.addWidget(self._build_review_card("Effektive Parameter", "parameterReview"))
        self.workload_card = self._build_review_card("Workload-Evidenz", "workloadReview")
        layout.addWidget(self.workload_card)

        reference_readiness = QFrame()
        reference_readiness.setObjectName("card")
        reference_readiness_layout = QVBoxLayout(reference_readiness)
        reference_readiness_layout.setContentsMargins(24, 22, 24, 24)
        reference_readiness_layout.setSpacing(10)
        reference_readiness_title = QLabel("Externe Deformetrica-Referenzumgebung")
        reference_readiness_title.setObjectName("sectionTitle")
        self.reference_readiness_status_label = QLabel(
            "Die konfigurierte Container-Umgebung wurde noch nicht geprüft."
        )
        self.reference_readiness_status_label.setObjectName("status")
        self.reference_readiness_status_label.setWordWrap(True)
        self.reference_readiness_detail_label = QLabel(
            "Diese Diagnose ist rein lesend. Sie installiert, baut, startet, bereitet oder "
            "repariert nichts."
        )
        self.reference_readiness_detail_label.setObjectName("reviewDetail")
        self.reference_readiness_detail_label.setWordWrap(True)
        self.reference_readiness_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_reference_readiness_button = QPushButton(
            "Referenzumgebung read-only prüfen"
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
            "Approval-bound Vorbereitungsstatus"
        )
        reference_preparation_status_title.setObjectName("sectionTitle")
        self.reference_preparation_status_label = QLabel(
            "Noch keine Approval-Datei read-only geprüft."
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
            "Zuvor geprüfte preparation-only Approval-Datei"
        )
        self.reference_preparation_approval_edit.textChanged.connect(
            self._reference_preparation_inputs_changed
        )
        reference_preparation_approval_button = QPushButton("Auswählen…")
        reference_preparation_approval_button.setObjectName("secondary")
        reference_preparation_approval_button.clicked.connect(
            self._choose_reference_preparation_approval
        )
        preparation_form.addRow(
            "Approval-Datei",
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
            "Unabhängig notierter SHA-256 der kompletten Approval-Datei"
        )
        self.reference_preparation_hash_edit.textChanged.connect(
            self._reference_preparation_inputs_changed
        )
        preparation_form.addRow(
            "Approval-SHA-256",
            self.reference_preparation_hash_edit,
        )
        self.reference_preparation_detail_label = QLabel(
            "Diese Ansicht prüft nur den exakt genehmigten Zielpfad und exakt benannte "
            "private Stages. Sie folgt keinen Links und verändert nichts."
        )
        self.reference_preparation_detail_label.setObjectName("reviewDetail")
        self.reference_preparation_detail_label.setWordWrap(True)
        self.reference_preparation_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_reference_preparation_status_button = QPushButton(
            "Vorbereitungsstatus read-only prüfen"
        )
        self.refresh_reference_preparation_status_button.setObjectName("secondary")
        self.refresh_reference_preparation_status_button.clicked.connect(
            self._check_reference_preparation_status
        )
        self.reference_preparation_export_label = QLabel(
            "Export erst nach erfolgreicher Prüfung. Der vollständige Report enthält "
            "absolute Pfade und Dateinamen und ist als private Provenienz zu behandeln."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setWordWrap(True)
        self.reference_preparation_export_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.export_reference_preparation_status_button = QPushButton(
            "Geprüften Status als neue JSON-Datei exportieren"
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
        warnings_title = QLabel("Grenzen und Hinweise")
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
        back = QPushButton("Zurück zu Daten & Engine")
        back.setObjectName("secondary")
        back.clicked.connect(self._show_setup_page)
        footer_layout.addWidget(back)
        self.open_review_report_button = QPushButton("Prüfbericht öffnen")
        self.open_review_report_button.setObjectName("secondary")
        self.open_review_report_button.clicked.connect(self._open_review_report)
        footer_layout.addWidget(self.open_review_report_button)
        footer_layout.addStretch()
        self.show_run_button = QPushButton("Atlasstart folgt in Schritt 3")
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

        eyebrow = QLabel("SCHRITT 3 VON 4")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Modern-Atlas berechnen")
        title.setObjectName("title")
        subtitle = QLabel(
            "Starte genau die geprüfte Konfiguration in einem getrennten Prozess und "
            "beobachte echte Workflow-Ereignisse."
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
            "Experimentelle Modern-CPU-Route. Es werden weder Laufzeit noch Peak-RAM oder "
            "Prozentfortschritt geschätzt. Abbruch wirkt nur an ausgewiesenen sicheren Punkten "
            "und ist derzeit nicht wiederaufnehmbar."
        )
        boundary_text.setObjectName("boundaryText")
        boundary_text.setWordWrap(True)
        boundary_layout.addWidget(boundary_text)
        layout.addWidget(boundary)

        summary = QFrame()
        summary.setObjectName("card")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(24, 22, 24, 24)
        summary_title = QLabel("Gebundener Start")
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
        readiness_title = QLabel("Privater Zielstatus vor Workerstart")
        readiness_title.setObjectName("sectionTitle")
        self.run_readiness_status_label = QLabel("Zielstatus wurde noch nicht geprüft.")
        self.run_readiness_status_label.setObjectName("status")
        self.run_readiness_status_label.setWordWrap(True)
        self.run_readiness_detail_label = QLabel(
            "Die Prüfung ist rein lesend und löscht, benennt, publiziert oder startet nichts."
        )
        self.run_readiness_detail_label.setObjectName("reviewDetail")
        self.run_readiness_detail_label.setWordWrap(True)
        self.run_readiness_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_run_readiness_button = QPushButton("Zielstatus erneut prüfen")
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
        progress_title = QLabel("Verifizierte Live-Ereignisse")
        progress_title.setObjectName("sectionTitle")
        self.run_state_label = QLabel("Bereit; noch kein Worker gestartet.")
        self.run_state_label.setObjectName("status")
        self.run_state_label.setWordWrap(True)
        self.run_stage_label = QLabel("Workflow-Stufe: noch nicht gestartet")
        self.run_stage_label.setObjectName("reviewValue")
        self.run_stage_label.setWordWrap(True)
        self.run_progress_bar = QProgressBar()
        self.run_progress_bar.setRange(0, 7)
        self.run_progress_bar.setValue(0)
        self.run_progress_bar.setFormat("Abgeschlossene Stufen: %v von %m")
        self.run_optimizer_label = QLabel("Noch keine Optimierungsentscheidung.")
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
        result_title = QLabel("Unabhängig verifiziertes Ergebnis")
        result_title.setObjectName("sectionTitle")
        self.run_result_label = QLabel()
        self.run_result_label.setWordWrap(True)
        self.run_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_run_result_button = QPushButton("Ergebnisordner öffnen")
        self.open_run_result_button.setObjectName("secondary")
        self.open_run_result_button.clicked.connect(self._open_run_result)
        self.review_run_result_button = QPushButton("Ergebnisse & PCA prüfen")
        self.review_run_result_button.setObjectName("primary")
        self.review_run_result_button.clicked.connect(self._review_run_result)
        self.review_run_result_button.setEnabled(False)
        result_button_row = QHBoxLayout()
        result_button_row.addWidget(self.open_run_result_button)
        result_button_row.addWidget(self.review_run_result_button)
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
        self.run_back_button = QPushButton("Zurück zur Parameterprüfung")
        self.run_back_button.setObjectName("secondary")
        self.run_back_button.clicked.connect(self._show_review_page)
        self.cancel_atlas_button = QPushButton("Sicher abbrechen")
        self.cancel_atlas_button.setObjectName("danger")
        self.cancel_atlas_button.clicked.connect(self._cancel_atlas)
        self.cancel_atlas_button.setEnabled(False)
        self.start_atlas_button = QPushButton("Geprüften Modern-Atlas starten")
        self.start_atlas_button.setObjectName("primary")
        self.start_atlas_button.clicked.connect(self._start_atlas)
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

        eyebrow = QLabel("SCHRITT 4 VON 4")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Verifizierte Ergebnisse & PCA")
        title.setObjectName("title")
        subtitle = QLabel(
            "Lies eine gebundene Zusammenfassung und öffne nur Artefakte, deren Größe und "
            "SHA-256 unmittelbar vorher erneut geprüft wurden."
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
            "Technische Verifikation ist keine wissenschaftliche Validierung."
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
        summary_title = QLabel("Gebundener Ergebnis-Snapshot")
        summary_title.setObjectName("sectionTitle")
        self.result_summary_label = QLabel()
        self.result_summary_label.setWordWrap(True)
        self.result_summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.result_summary_label)
        layout.addWidget(summary)

        overview_card, self.result_overview_layout = self._build_result_items_card(
            "Atlas und Datensatz", "resultOverview"
        )
        optimization_card, self.result_optimization_layout = self._build_result_items_card(
            "Optimierung", "resultOptimization"
        )
        pca_card, self.result_pca_layout = self._build_result_items_card("PCA", "resultPca")
        quality_card, self.result_quality_layout = self._build_result_items_card(
            "Verifikations- und Qualitätsnachweise", "resultQuality"
        )
        layout.addWidget(overview_card)
        layout.addWidget(optimization_card)
        layout.addWidget(pca_card)
        layout.addWidget(quality_card)

        artifacts = QFrame()
        artifacts.setObjectName("card")
        artifacts_layout = QVBoxLayout(artifacts)
        artifacts_layout.setContentsMargins(24, 22, 24, 24)
        artifacts_title = QLabel("Geprüfte offene Artefakte")
        artifacts_title.setObjectName("sectionTitle")
        artifacts_hint = QLabel(
            "DiffeoForge rendert VTK derzeit nicht intern. VTK, CSV, JSON und statische SVGs "
            "werden an die lokal zugeordnete Anwendung übergeben."
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
        self.result_back_button = QPushButton("Zurück zum Atlaslauf")
        self.result_back_button.setObjectName("secondary")
        self.result_back_button.clicked.connect(self._show_run_page_from_results)
        self.result_status_label = QLabel("Noch kein Ergebnis-Snapshot geladen.")
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
        section = QLabel("Projekt und Eingaben")
        section.setObjectName("sectionTitle")
        card_layout.addWidget(section)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(12)

        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("engineCombo")
        self.engine_combo.addItem(
            "DiffeoForge Modern CPU (experimentell)", DesktopEngine.MODERN_CPU
        )
        self.engine_combo.addItem(
            "Deformetrica 4.3 Referenz (extern)", DesktopEngine.DEFORMETRICA_REFERENCE
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

        self.mesh_edit = QLineEdit()
        self.mesh_edit.setObjectName("meshDirectoryEdit")
        self.mesh_edit.setPlaceholderText(r"z. B. C:\Daten\Käfer\meshes")
        self.mesh_edit.textChanged.connect(self._sync_ready_state)
        self.mesh_edit.editingFinished.connect(self._detect_template_from_text)
        mesh_button = QPushButton("Auswählen…")
        mesh_button.setObjectName("secondary")
        mesh_button.clicked.connect(self._choose_mesh_directory)
        form.addRow("Mesh-Ordner", _path_row(self.mesh_edit, mesh_button))

        self.template_edit = QLineEdit()
        self.template_edit.setObjectName("templateEdit")
        self.template_edit.setPlaceholderText("automatisch: template.vtk")
        template_button = QPushButton("Auswählen…")
        template_button.setObjectName("secondary")
        template_button.clicked.connect(self._choose_template)
        form.addRow("Template", _path_row(self.template_edit, template_button))

        self.pattern_edit = QLineEdit("*.vtk")
        self.pattern_edit.setObjectName("subjectPatternEdit")
        self.pattern_edit.setToolTip(
            "Das Template wird automatisch aus der Probandenliste entfernt."
        )
        form.addRow("Dateimuster", self.pattern_edit)

        self.project_edit = QLineEdit()
        self.project_edit.setObjectName("projectDirectoryEdit")
        self.project_edit.setPlaceholderText("Ordner für Konfiguration und spätere Ergebnisse")
        self.project_edit.textChanged.connect(self._sync_ready_state)
        project_button = QPushButton("Auswählen…")
        project_button.setObjectName("secondary")
        project_button.clicked.connect(self._choose_project_directory)
        form.addRow("Projektordner", _path_row(self.project_edit, project_button))

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("projectNameEdit")
        self.name_edit.setPlaceholderText("optional; sonst aus dem Ordnernamen")
        form.addRow("Projektname", self.name_edit)

        self.units_combo = QComboBox()
        self.units_combo.setObjectName("unitsCombo")
        self.units_combo.addItem("Bitte auswählen…", None)
        labels = {
            "unitless": "Einheitenlos",
            "micrometer": "Mikrometer (µm)",
            "millimeter": "Millimeter (mm)",
            "centimeter": "Zentimeter (cm)",
            "meter": "Meter (m)",
        }
        for unit in SUPPORTED_UNITS:
            self.units_combo.addItem(labels[unit], unit)
        self.units_combo.currentIndexChanged.connect(self._sync_ready_state)
        form.addRow("Koordinateneinheit", self.units_combo)

        self.landmarks_edit = QLineEdit()
        self.landmarks_edit.setObjectName("landmarksEdit")
        self.landmarks_edit.setPlaceholderText("optional: homologe Landmarks als CSV")
        landmarks_button = QPushButton("Auswählen…")
        landmarks_button.setObjectName("secondary")
        landmarks_button.clicked.connect(self._choose_landmarks)
        self.landmarks_button = landmarks_button
        form.addRow("Landmarks", _path_row(self.landmarks_edit, landmarks_button))

        card_layout.addLayout(form)
        return card

    def _build_result_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 24)
        heading = QLabel("Projekt erfolgreich angelegt")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.result_label = QLabel()
        self.result_label.setObjectName("resultSummary")
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        button_row = QHBoxLayout()
        open_config = QPushButton("Konfiguration öffnen")
        open_config.setObjectName("secondary")
        open_config.clicked.connect(self._open_config)
        open_folder = QPushButton("Projektordner öffnen")
        open_folder.setObjectName("secondary")
        open_folder.clicked.connect(self._open_project_directory)
        self.review_button = QPushButton("Parameter & Aufwand prüfen")
        self.review_button.setObjectName("primary")
        self.review_button.clicked.connect(self._review_project)
        self.review_button.setEnabled(False)
        button_row.addWidget(open_config)
        button_row.addWidget(open_folder)
        button_row.addStretch()
        button_row.addWidget(self.review_button)
        layout.addLayout(button_row)
        return card

    @Slot()
    def _choose_mesh_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Mesh-Ordner auswählen")
        if not selected:
            return
        self.mesh_edit.setText(selected)
        if not self.project_edit.text().strip():
            mesh_directory = Path(selected)
            self.project_edit.setText(str(mesh_directory.parent / "diffeoforge-project"))
        self._detect_template_from_text()

    @Slot()
    def _choose_project_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Projektordner auswählen")
        if selected:
            self.project_edit.setText(selected)

    @Slot()
    def _choose_template(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Template auswählen",
            self.mesh_edit.text().strip(),
            "VTK PolyData (*.vtk)",
        )
        if selected:
            self.template_edit.setText(selected)

    @Slot()
    def _choose_landmarks(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Landmark-Datei auswählen",
            self.mesh_edit.text().strip(),
            "CSV-Dateien (*.csv)",
        )
        if selected:
            self.landmarks_edit.setText(selected)

    @Slot()
    def _choose_reference_preparation_approval(self) -> None:
        start = (
            str(self._review.config_path.parent)
            if self._review is not None
            else self.project_edit.text().strip()
        )
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Preparation-only Approval auswählen",
            start,
            "JSON-Dateien (*.json)",
        )
        if selected:
            self.reference_preparation_approval_edit.setText(selected)

    @Slot()
    def _reference_preparation_inputs_changed(self) -> None:
        self._reference_preparation_status = None
        self.reference_preparation_status_label.setObjectName("status")
        self.reference_preparation_status_label.setStyleSheet("")
        if isinstance(self._worker, _ReferencePreparationStatusWorker):
            message = (
                "Eingaben wurden während der Prüfung geändert; das laufende Ergebnis "
                "wird verworfen."
            )
        else:
            message = "Noch keine Approval-Datei read-only geprüft."
        self.reference_preparation_status_label.setText(message)
        self.reference_preparation_detail_label.setText(
            "Diese Ansicht prüft nur den exakt genehmigten Zielpfad und exakt benannte "
            "private Stages. Sie folgt keinen Links und verändert nichts."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export erst nach erfolgreicher Prüfung. Der vollständige Report enthält "
            "absolute Pfade und Dateinamen und ist als private Provenienz zu behandeln."
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

    @Slot()
    def _update_engine_explanation(self) -> None:
        modern = self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
        self.landmarks_edit.setEnabled(modern)
        self.landmarks_button.setEnabled(modern)
        if modern:
            self.engine_hint.setText(
                "Aktuelle CPU/float64-Engine; PCA ist Teil des späteren Ergebnis-Bundles."
            )
        else:
            self.engine_hint.setText(
                "Unabhängige Deformetrica-4.3-Referenz; Docker bleibt extern und wird "
                "nicht gebündelt."
            )

    @Slot()
    def _sync_ready_state(self) -> None:
        ready = bool(
            self.mesh_edit.text().strip()
            and self.project_edit.text().strip()
            and self.units_combo.currentData() is not None
        )
        self.create_button.setEnabled(ready and self._worker is None)
        self._sync_reference_preparation_status_controls()

    def _request(self) -> ProjectSetupRequest:
        template = self.template_edit.text().strip()
        landmarks = self.landmarks_edit.text().strip()
        return ProjectSetupRequest(
            mesh_directory=Path(self.mesh_edit.text().strip()),
            project_directory=Path(self.project_edit.text().strip()),
            units=self.units_combo.currentData(),
            engine=self.engine_combo.currentData(),
            template=Path(template) if template else None,
            project_name=self.name_edit.text().strip() or None,
            subject_pattern=self.pattern_edit.text(),
            landmarks_file=(
                Path(landmarks)
                if landmarks and self.engine_combo.currentData() == DesktopEngine.MODERN_CPU
                else None
            ),
        )

    @Slot()
    def _create_project(self) -> None:
        self.result_card.hide()
        self._result = None
        self._review = None
        self._template_preview = None
        self._reference_readiness = None
        self._reference_preparation_status = None
        self._run_readiness = None
        self._run_result = None
        self._result_review = None
        self.template_preview_card.hide()
        self.reference_preparation_status_card.hide()
        self.reference_preparation_approval_edit.clear()
        self.reference_preparation_hash_edit.clear()
        self.template_preview_canvas.set_model(None)
        self.review_button.setEnabled(False)
        self.show_run_button.setEnabled(False)
        self.start_atlas_button.setEnabled(False)
        self.review_run_result_button.setEnabled(False)
        self.run_result_card.hide()
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText("Meshes und Konfiguration werden geprüft …")
        self._worker = _ProjectWorker(self._request())
        self._worker.signals.succeeded.connect(self._project_succeeded)
        self._worker.signals.failed.connect(self._project_failed)
        self.create_button.setEnabled(False)
        self._thread_pool.start(self._worker)

    @Slot(object)
    def _project_succeeded(self, result: ProjectSetupResult) -> None:
        self._worker = None
        self._result = result
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            f"Prüfung bestanden: {result.subject_count} Probandenmeshes wurden akzeptiert."
        )
        report = f"\nPreflight-Report: {result.report_path}" if result.report_path else ""
        notices = "\n".join(f"• {notice}" for notice in result.notices)
        self.result_label.setText(
            f"Engine: {result.engine_label}\n"
            f"Template: {result.template_path}\n"
            f"Konfiguration: {result.config_path}{report}\n\n"
            f"Wichtige Hinweise:\n{notices}"
        )
        self.result_card.show()
        self.review_button.setEnabled(True)
        self._sync_ready_state()

    @Slot(str)
    def _project_failed(self, message: str) -> None:
        self._worker = None
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Projekt konnte nicht angelegt werden: {message}")
        self._sync_ready_state()

    @Slot()
    def _review_project(self) -> None:
        if self._result is None or self._worker is not None:
            return
        self.review_button.setEnabled(False)
        self.status_label.setObjectName("status")
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Effektive Parameter und vorhandene Workload-Evidenz werden gesammelt …"
        )
        self._worker = _ReviewWorker(self._result)
        self._worker.signals.succeeded.connect(self._review_succeeded)
        self._worker.signals.failed.connect(self._review_failed)
        self._thread_pool.start(self._worker)

    @Slot(object)
    def _review_succeeded(self, review: ProjectReviewResult) -> None:
        self._worker = None
        self._review = review
        self._template_preview = None
        self._reference_readiness = None
        self._reference_preparation_status = None
        self._run_readiness = None
        self.reference_preparation_approval_edit.clear()
        self.reference_preparation_hash_edit.clear()
        self._populate_review_rows(self.parameter_review_layout, review.parameters)
        self._populate_review_rows(self.workload_review_layout, review.workload)
        self.review_boundary_label.setText(review.scientific_boundary)
        engine_label = (
            "DiffeoForge Modern CPU (experimentell)"
            if review.engine is DesktopEngine.MODERN_CPU
            else "Deformetrica 4.3 Referenz (extern)"
        )
        config_display = self._wrappable_path(review.config_path)
        report_display = self._wrappable_path(review.report_path)
        self.review_summary_label.setText(
            f"Projekt: {review.project_name}\n"
            f"Engine: {engine_label}\n"
            f"Probanden: {review.subject_count}\n"
            f"Konfiguration: {config_display}\n"
            f"Geprüfter SHA-256: {review.config_sha256}\n"
            f"{review.report_label}: {report_display}"
        )
        self.review_warnings_label.setText("\n".join(f"• {warning}" for warning in review.warnings))
        self.open_review_report_button.setText(f"{review.report_label} öffnen")
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
                "Die read-only-Wireframe-Vorschau wurde noch nicht geladen."
            )
            self.template_preview_detail_label.setText(
                f"Template: {self._wrappable_path(self._result.template_path)}\n"
                "Diese Projektion verändert das Mesh nicht und ersetzt weder "
                "3D-Inspektion noch Mesh-QC oder Landmark-Picking."
            )
        else:
            self.template_preview_card.hide()
        if review.engine is DesktopEngine.MODERN_CPU:
            self.reference_readiness_card.hide()
            self.reference_preparation_status_card.hide()
            self.show_run_button.setText("Weiter zu Atlasstart")
            self.show_run_button.setEnabled(True)
        else:
            self.reference_readiness_card.show()
            self.reference_preparation_status_card.show()
            self.reference_readiness_status_label.setObjectName("status")
            self.reference_readiness_status_label.setStyleSheet("")
            self.reference_readiness_status_label.setText(
                "Die konfigurierte Container-Umgebung wurde noch nicht geprüft."
            )
            self.reference_readiness_detail_label.setText(
                "Die Prüfung wird an den angezeigten Konfigurations-SHA-256 gebunden und "
                "ist rein lesend. Sie installiert, baut, startet, bereitet oder repariert "
                "nichts."
            )
            self.refresh_reference_readiness_button.setEnabled(True)
            self.reference_preparation_status_label.setObjectName("status")
            self.reference_preparation_status_label.setStyleSheet("")
            self.reference_preparation_status_label.setText(
                "Noch keine Approval-Datei read-only geprüft."
            )
            self.reference_preparation_detail_label.setText(
                "Approval-Datei und unabhängig notierter SHA-256 sind erforderlich. "
                "Die Prüfung verändert, publiziert, löscht oder startet nichts."
            )
            self.show_run_button.setText("Referenzstart noch nicht verbunden")
            self.show_run_button.setEnabled(False)
        self._set_active_step(1)
        self.page_stack.setCurrentIndex(1)
        self.review_button.setEnabled(True)
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
            "Template-Geometrie und eindeutige Kanten werden außerhalb des Event-Loops "
            "read-only geladen …"
        )
        self.template_preview_detail_label.setText(
            "Die Quelldatei wird vor und nach dem Laden gehasht. Es werden keine Punkte, "
            "Flächen oder Dateien verändert."
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
                "Geladenes Vorschaumodell gehört nicht zum aktuellen Template"
            )
            return
        self._template_preview = model
        self.template_preview_plane_combo.setEnabled(True)
        self.refresh_template_preview_button.setEnabled(True)
        self.review_button.setEnabled(self._result is not None)
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
                f"{str(plane).upper()}-Projektion nicht darstellbar: {error}"
            )
            return

        self.template_preview_canvas.set_plane(plane)
        self.template_preview_canvas.set_model(model)
        sampling = (
            "deterministisch ausgedünnte Anzeige"
            if projection.sampled
            else "alle eindeutigen Kanten angezeigt"
        )
        bounds = ", ".join(f"{value:.6g}" for value in model.bounds)
        self.template_preview_detail_label.setText(
            f"Template: {self._wrappable_path(model.path)}\n"
            f"SHA-256: {model.sha256}\n"
            f"Geometrie: {model.point_count} Punkte · {model.triangle_count} Dreiecke · "
            f"{model.edge_count} eindeutige Kanten\n"
            f"Bounds (xmin, xmax, ymin, ymax, zmin, zmax): {bounds}\n"
            f"Anzeige: {projection.displayed_edge_count} von "
            f"{projection.total_edge_count} Kanten · {sampling}.\n"
            "Nur orthografische Inspektionsvorschau; keine 3D-, QC-, Registrierungs-, "
            "Landmark- oder biologische Bewertung."
        )
        self.template_preview_status_label.setObjectName("statusSuccess")
        self.template_preview_status_label.setStyleSheet("")
        self.template_preview_status_label.setText(
            f"{str(plane).upper()}-Wireframe aus unverändertem Template gerendert."
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
            f"Template-Vorschau nicht geladen: {message}"
        )
        self.template_preview_detail_label.setText(
            "Keine Vorschau freigegeben; die Template-Datei wurde nicht verändert."
        )
        self.review_button.setEnabled(self._result is not None)
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
            "Host, Projektordner, Containerdienst und exakt konfiguriertes Image werden "
            "read-only geprüft …"
        )
        self.reference_readiness_detail_label.setText(
            "Kein Referenz-Run wird vorbereitet oder gestartet. Die Konfiguration wird "
            "vor und nach den externen Beobachtungen an ihren Review-Hash gebunden."
        )
        self._sync_ready_state()
        self._thread_pool.start(worker)

    @Slot(object)
    def _reference_readiness_succeeded(
        self, readiness: DesktopReferenceReadiness
    ) -> None:
        self._worker = None
        self._reference_readiness = readiness
        details = [
            f"Konfiguration: {self._wrappable_path(readiness.config_path)}",
            f"Gebundener SHA-256: {readiness.config_sha256}",
            f"Projektordner: {self._wrappable_path(readiness.workspace)}",
            f"Container-Engine: {readiness.engine}",
            f"Referenz-Image: {readiness.image}",
            "Beobachtete Checks:",
        ]
        for check in readiness.report.checks:
            details.append(f"[{check.status.upper()}] {check.label}: {check.summary}")
            if check.guidance:
                details.append(f"  Hinweis: {check.guidance}")
        details.append(
            "Aktion: nur beobachtet; nichts installiert, gebaut, gestartet, vorbereitet, "
            "fortgesetzt oder repariert."
        )
        self.reference_readiness_detail_label.setText("\n".join(details))
        if readiness.report.status == "ready":
            self.reference_readiness_status_label.setObjectName("statusSuccess")
            message = (
                "Externe Referenzumgebung ist für die beobachteten Checks bereit. "
                "Der Referenzstart bleibt bis zur separaten Prozessaufsicht gesperrt."
            )
        elif readiness.report.status == "warning":
            self.reference_readiness_status_label.setObjectName("status")
            message = (
                "Externe Referenzumgebung ist ohne blockierenden Fehler, aber mit Warnungen. "
                "Der Referenzstart bleibt gesperrt."
            )
        else:
            self.reference_readiness_status_label.setObjectName("statusError")
            message = (
                "Externe Referenzumgebung ist blockiert. Hinweise stehen unten; es wurde "
                "nichts verändert oder gestartet."
            )
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(message)
        self.refresh_reference_readiness_button.setEnabled(True)
        self.review_button.setEnabled(self._result is not None)
        self._sync_ready_state()

    @Slot(str)
    def _reference_readiness_failed(self, message: str) -> None:
        self._worker = None
        self._reference_readiness = None
        self.reference_readiness_status_label.setObjectName("statusError")
        self.reference_readiness_status_label.setStyleSheet("")
        self.reference_readiness_status_label.setText(
            f"Referenzumgebung nicht sicher prüfbar: {message}"
        )
        self.reference_readiness_detail_label.setText(
            "Diagnose verworfen. Kein Referenz-Run wurde vorbereitet oder gestartet; "
            "keine Umgebungseinstellung wurde verändert."
        )
        self.refresh_reference_readiness_button.setEnabled(
            self._review is not None
            and self._review.engine is DesktopEngine.DEFORMETRICA_REFERENCE
        )
        self.review_button.setEnabled(self._result is not None)
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
            "Approval, aktueller Plan, Zielpfad und private Stages werden zweimal "
            "read-only geprüft …"
        )
        self.reference_preparation_detail_label.setText(
            "Kein Pfad wird gelöscht, verschoben, publiziert, repariert, fortgesetzt, "
            "vorbereitet oder ausgeführt."
        )
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export gesperrt, bis diese read-only Prüfung erfolgreich und weiterhin "
            "an exakt dieselben Eingaben gebunden ist."
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
                "Prüfergebnis verworfen, weil Review oder Approval-Eingaben nicht mehr "
                "exakt übereinstimmen."
            )
            self.reference_preparation_detail_label.setText(
                "Es wurde nichts verändert. Mit den aktuellen Eingaben erneut prüfen."
            )
            self.reference_preparation_export_label.setObjectName("statusError")
            self.reference_preparation_export_label.setStyleSheet("")
            self.reference_preparation_export_label.setText(
                "Kein Export: Das verworfene Ergebnis ist nicht mehr an die aktuellen "
                "Eingaben gebunden."
            )
            self._sync_ready_state()
            return

        self._reference_preparation_status = status
        engine_started = (
            "ja"
            if status.engine_execution_started is True
            else "nein"
            if status.engine_execution_started is False
            else "nicht sicher klassifizierbar"
        )
        details = [
            f"Approval: {self._wrappable_path(status.approval_path)}",
            f"Approval-SHA-256: {status.approval_sha256}",
            f"Run-ID: {status.run_id}",
            f"Plan-Fingerprint: {status.plan_fingerprint}",
            f"Report-Schema: {status.report_schema_version}",
            f"Report-Bytes: {status.report_byte_count}",
            f"Report-SHA-256: {status.report_sha256}",
            f"Ziel [{status.destination_status}]: "
            f"{self._wrappable_path(status.destination_path)}",
            f"Begründung: {status.destination_reason}",
            f"Engine-Ausführung gestartet: {engine_started}",
            f"Exakt passende private Stages: {len(status.private_stages)}",
        ]
        if status.manifest_sha256 is not None:
            details.append(f"Manifest-SHA-256: {status.manifest_sha256}")
        for stage in status.private_stages:
            details.append(
                f"[{stage.status}] {self._wrappable_path(stage.path)}: {stage.reason}"
            )
        details.extend(
            (
                "Stabile Doppelbeobachtung: ja",
                "Mutation durch diese Prüfung: nein",
                f"Grenze: {status.scientific_boundary}",
            )
        )
        self.reference_preparation_detail_label.setText("\n".join(details))
        if status.status == "clear_to_prepare":
            self.reference_preparation_status_label.setObjectName("statusSuccess")
            message = (
                "Genehmigter Zielpfad ist frei. Read-only-Prüfung bestanden; es wurde "
                "nichts vorbereitet oder gestartet."
            )
        elif status.status == "published_prepared_not_executed_verified":
            self.reference_preparation_status_label.setObjectName("statusSuccess")
            message = (
                "Vorbereiteter Referenz-Run ist vollständig verifiziert und wurde nicht "
                "ausgeführt."
            )
        else:
            self.reference_preparation_status_label.setObjectName("statusError")
            message = (
                "Der beobachtete Zustand benötigt eine explizite menschliche "
                "Entscheidung. Es wurde nichts verändert."
            )
        self.reference_preparation_status_label.setStyleSheet("")
        self.reference_preparation_status_label.setText(message)
        self.reference_preparation_export_label.setObjectName("hint")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Export bereit: Es werden exakt die oben gehashten Report-Bytes in eine neue "
            "JSON-Datei geschrieben. Der Report enthält absolute Pfade und Dateinamen; "
            "vor Weitergabe auf vertrauliche Provenienz prüfen."
        )
        self.review_button.setEnabled(self._result is not None)
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
                f"Vorbereitungsstatus nicht sicher prüfbar: {message}"
            )
        else:
            self.reference_preparation_status_label.setText(
                "Fehlerergebnis verworfen, weil die Approval-Eingaben geändert wurden."
            )
        self.reference_preparation_detail_label.setText(
            "Keine Statusfreigabe. Es wurde nichts gelöscht, verschoben, publiziert, "
            "repariert, fortgesetzt, vorbereitet oder ausgeführt."
        )
        self.reference_preparation_export_label.setObjectName("statusError")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            "Kein Export ohne aktuell gebundenen, vollständig validierten Statusreport."
        )
        self.review_button.setEnabled(self._result is not None)
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
            "Neue Statusreport-Datei auswählen (kein Überschreiben)",
            str(default),
            "JSON-Dateien (*.json)",
        )
        if not selected:
            return
        if not self._reference_preparation_status_matches_inputs():
            self.reference_preparation_export_label.setObjectName("statusError")
            self.reference_preparation_export_label.setStyleSheet("")
            self.reference_preparation_export_label.setText(
                "Export verworfen, weil Review oder Approval-Eingaben nicht mehr exakt "
                "zum geprüften Report passen."
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
                f"Statusreport nicht exportiert: {error}"
            )
            self._sync_reference_preparation_status_controls()
            return
        self.reference_preparation_export_label.setObjectName("statusSuccess")
        self.reference_preparation_export_label.setStyleSheet("")
        self.reference_preparation_export_label.setText(
            f"Statusreport neu geschrieben: {self._wrappable_path(exported.path)}\n"
            f"Schema: {exported.schema_version} · Bytes: {exported.byte_count} · "
            f"SHA-256: {exported.sha256}\n"
            "Private Provenienz mit absoluten Pfaden; keine Run- oder Engine-Datei wurde "
            "verändert."
        )
        self._sync_reference_preparation_status_controls()

    @Slot()
    def _show_run_page(self) -> None:
        if (
            self._review is None
            or self._review.engine is not DesktopEngine.MODERN_CPU
            or self._worker is not None
        ):
            return
        self._refresh_run_readiness()
        self._set_active_step(2)
        self.page_stack.setCurrentIndex(2)

    @Slot()
    def _refresh_run_readiness(self) -> DesktopReviewedRunReadiness | None:
        review = self._review
        if review is None or review.engine is not DesktopEngine.MODERN_CPU:
            return None
        try:
            readiness = check_reviewed_run_readiness(
                review,
                request_id=f"desktop-{uuid.uuid4().hex}",
            )
        except (DesktopReviewedRunError, OSError, RuntimeError, TypeError, ValueError) as error:
            self._run_readiness = None
            self.run_summary_label.setText(
                f"Projekt: {review.project_name}\n"
                f"Konfiguration: {self._wrappable_path(review.config_path)}\n"
                f"Geprüfter SHA-256: {review.config_sha256}\n"
                "Ziel: konnte nicht sicher aus der geprüften Konfiguration gebunden werden"
            )
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(f"Zielstatus nicht prüfbar: {error}")
            self.run_readiness_detail_label.setText(
                "Kein Worker wurde gestartet. Es wurden keine privaten oder publizierten "
                "Dateien verändert."
            )
            self.run_state_label.setObjectName("statusError")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Kein Worker gestartet. Ziel und Konfigurationsbindung konnten nicht sicher "
                "geprüft werden."
            )
            self.start_atlas_button.setEnabled(False)
            return None
        self._apply_run_readiness(readiness)
        return readiness

    def _apply_run_readiness(self, readiness: DesktopReviewedRunReadiness) -> None:
        self._run_readiness = readiness
        request = readiness.request
        discovery = readiness.discovery
        self.run_summary_label.setText(
            f"Projekt: {self._review.project_name if self._review else 'unbekannt'}\n"
            f"Konfiguration: {self._wrappable_path(request.config_path)}\n"
            f"Gebundener SHA-256: {request.expected_config_sha256}\n"
            f"Nicht überschreibbares Ziel: {self._wrappable_path(request.destination)}"
        )
        details = [
            f"Exaktes Ziel: {self._wrappable_path(discovery.destination)}",
            f"Discovery-Status: {discovery.status}",
            f"Ziel existiert: {'ja' if discovery.destination_exists else 'nein'}",
        ]
        if discovery.candidates:
            details.append("Private unveröffentlichte Kandidaten:")
            for candidate in discovery.candidates:
                details.append(
                    f"[{candidate.status}] {self._wrappable_path(candidate.path)}\n"
                    f"  Bedeutung: {_PRIVATE_STATUS_EXPLANATIONS[candidate.status]}\n"
                    f"  Technischer Grund: {candidate.reason}"
                )
        else:
            details.append("Private unveröffentlichte Kandidaten: keine")
        details.append(
            "Aktion dieser Prüfung: nur gelesen; nichts gelöscht, umbenannt, fortgesetzt "
            "oder publiziert."
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
                "Ziel ist frei: kein publiziertes Ergebnis und kein exakter privater "
                "Kandidat gefunden."
            )
            if self._worker is None:
                self.run_state_label.setObjectName("status")
                self.run_state_label.setStyleSheet("")
                self.run_state_label.setText(
                    "Bereit; Zielstatus ist rein lesend geprüft. Vor dem Start wird erneut geprüft."
                )
        else:
            self.run_readiness_status_label.setObjectName("statusError")
            self.run_readiness_status_label.setStyleSheet("")
            self.run_readiness_status_label.setText(
                "Atlasstart blockiert: dieses exakte Ziel ist nicht frei."
            )
            if self._worker is None:
                self.run_state_label.setObjectName("statusError")
                self.run_state_label.setStyleSheet("")
                self.run_state_label.setText(
                    "Kein Worker gestartet. Privater oder publizierter Zielzustand verlangt "
                    "explizite Prüfung."
                )

    @Slot()
    def _show_review_page(self) -> None:
        if isinstance(self._worker, _AtlasWorker):
            return
        self._set_active_step(1)
        self.page_stack.setCurrentIndex(1)

    @Slot()
    def _start_atlas(self) -> None:
        if (
            self._review is None
            or self._review.engine is not DesktopEngine.MODERN_CPU
            or self._worker is not None
            or self._run_result is not None
        ):
            return
        readiness = self._refresh_run_readiness()
        if readiness is None or not readiness.ready_for_worker:
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
        self.review_run_result_button.setEnabled(False)
        self.run_event_log.clear()
        self.run_progress_bar.setValue(0)
        self.run_stage_label.setText("Workflow-Stufe: Worker wird gestartet")
        self.run_optimizer_label.setText("Noch keine Optimierungsentscheidung.")
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Kindprozess wird gestartet; Konfigurationsbindung und Zielpfad werden erneut geprüft."
        )
        self.run_summary_label.setText(
            f"Projekt: {self._review.project_name}\n"
            f"Request-ID: {request.request_id}\n"
            f"Konfiguration: {self._wrappable_path(request.config_path)}\n"
            f"Gebundener SHA-256: {request.expected_config_sha256}\n"
            f"Nicht überschreibbares Ziel: {self._wrappable_path(request.destination)}"
        )
        self.start_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(False)
        self.cancel_atlas_button.setEnabled(True)
        self.run_back_button.setEnabled(False)
        self._thread_pool.start(worker)

    @Slot()
    def _cancel_atlas(self) -> None:
        worker = self._worker
        if not isinstance(worker, _AtlasWorker) or not worker.request_cancel():
            return
        self.cancel_atlas_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Abbruch angefordert. Der aktuelle Tensor-Operator darf enden; DiffeoForge "
            "bricht am nächsten sicheren Punkt ab und publiziert keinen halbfertigen Run."
        )
        self.run_event_log.appendPlainText("GUI: kooperativer Abbruch angefordert")

    @Slot(str)
    def _atlas_cancel_failed(self, message: str) -> None:
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Abbruchkommando konnte nicht bestätigt werden: {message}. "
            "Der Parent überwacht den Kindprozess weiter."
        )
        self.run_event_log.appendPlainText(f"GUI: Abbruchübertragung fehlgeschlagen: {message}")

    @Slot(object)
    def _atlas_event(self, event: DesktopWorkerEvent) -> None:
        message: str
        if event.kind == "started":
            message = "Worker gestartet; überprüfte Konfiguration ist gebunden."
            self.run_state_label.setText(message)
        elif event.kind == "progress":
            progress = event.payload["modern_progress"]
            message = str(progress["message"])
            completed = int(progress["completed_stages"])
            total = int(progress["total_stages"])
            self.run_progress_bar.setRange(0, total)
            self.run_progress_bar.setValue(completed)
            self.run_stage_label.setText(
                f"Workflow-Stufe: {progress['phase']} · {progress['status']} · {message}"
            )
            optimizer = progress["optimizer"]
            if optimizer is not None:
                block = optimizer["block"] or "initial"
                gradient = optimizer["gradient_norm"]
                gradient_text = "nicht berechnet" if gradient is None else f"{gradient:.6g}"
                self.run_optimizer_label.setText(
                    "Optimierung: "
                    f"Entscheidung {optimizer['completed_decisions']} von "
                    f"{optimizer['maximum_decisions']} · Zyklus {optimizer['cycle']} von "
                    f"{optimizer['max_cycles']} · Block {block} · Status "
                    f"{optimizer['status']} · Objective {optimizer['objective']:.6g} · "
                    f"Gradientennorm {gradient_text}"
                )
        elif event.kind == "completed":
            message = "Worker meldet Fertigstellung; Parent-Verifikation läuft."
            self.run_state_label.setText(message)
        elif event.kind == "cancelled":
            message = str(event.payload["message"])
            self.run_state_label.setText(
                "Worker meldet sicheren Abbruch; Parent prüft den Ausgang."
            )
        else:
            message = str(event.payload["message"])
            self.run_state_label.setText(
                "Worker meldet einen Fehler; Parent gleicht Prozessende ab."
            )
        self.run_event_log.appendPlainText(f"#{event.sequence} {event.kind}: {message}")

    @Slot(object)
    def _atlas_succeeded(self, result: DesktopWorkerControllerResult) -> None:
        self._worker = None
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        terminal = result.terminal_event
        if result.completed:
            self._run_result = result
            self.run_state_label.setObjectName("statusSuccess")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Atlas und PCA wurden publiziert und vom Parent unabhängig verifiziert."
            )
            self.run_result_label.setText(
                f"Ziel: {self._wrappable_path(Path(terminal.payload['destination']))}\n"
                f"Probanden: {terminal.payload['subject_count']}\n"
                f"Manifest SHA-256: {terminal.payload['manifest_sha256']}\n"
                f"Resultat-Bundle: {terminal.payload['bundle_path']}\n"
                f"Prozess-Exitcode: {result.exit_code}"
            )
            self.run_result_card.show()
            self.review_run_result_button.setEnabled(True)
            self.start_atlas_button.setEnabled(False)
        else:
            self.run_state_label.setObjectName("status")
            self.run_state_label.setStyleSheet("")
            self.run_state_label.setText(
                "Sicher abgebrochen: kein Ziel wurde publiziert. Dieser Modern-Run besitzt "
                "keinen Checkpoint und muss bei Bedarf neu gestartet werden."
            )
            self.start_atlas_button.setEnabled(True)
            self.review_run_result_button.setEnabled(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot(str)
    def _atlas_failed(self, message: str) -> None:
        self._worker = None
        self.cancel_atlas_button.setEnabled(False)
        self.refresh_run_readiness_button.setEnabled(True)
        self.run_back_button.setEnabled(True)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(f"Atlaslauf fehlgeschlagen oder abgewiesen: {message}")
        self.run_event_log.appendPlainText(f"Parent: Fehler: {message}")
        self.start_atlas_button.setEnabled(True)
        self.review_run_result_button.setEnabled(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot()
    def _review_run_result(self) -> None:
        if self._run_result is None or not self._run_result.completed or self._worker is not None:
            return
        destination = Path(self._run_result.terminal_event.payload["destination"])
        worker = _ResultReviewWorker(destination)
        worker.signals.succeeded.connect(self._result_review_succeeded)
        worker.signals.failed.connect(self._result_review_failed)
        self._worker = worker
        self.review_run_result_button.setEnabled(False)
        self.run_back_button.setEnabled(False)
        self.run_state_label.setObjectName("status")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            "Workflow, Bundle, Inventar, Mesh-QC und statische SVGs werden vollständig "
            "neu verifiziert; erst danach wird die Ergebnisansicht freigegeben."
        )
        self._thread_pool.start(worker)

    @Slot(object)
    def _result_review_succeeded(self, review: ModernResultReview) -> None:
        self._worker = None
        self._result_review = review
        self._populate_review_rows(self.result_overview_layout, review.overview)
        self._populate_review_rows(self.result_optimization_layout, review.optimization)
        self._populate_review_rows(self.result_pca_layout, review.pca)
        self._populate_review_rows(self.result_quality_layout, review.quality)
        self.result_boundary_label.setText(
            "\n".join(f"• {boundary}" for boundary in review.scientific_boundaries)
        )
        self.result_summary_label.setText(
            f"Projekt: {review.project_name}\n"
            f"Erstellt: {review.created_at}\n"
            f"Workflow: {self._wrappable_path(review.run_directory)}\n"
            f"Workflow-Manifest SHA-256: {review.workflow_manifest_sha256}\n"
            f"Bundle-Manifest SHA-256: {review.bundle_manifest_sha256}"
        )
        self._populate_result_artifacts(review)
        self.result_status_label.setObjectName("statusSuccess")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            "Snapshot vollständig verifiziert. Vor jedem Öffnen wird das gewählte Artefakt "
            "erneut an beide Manifest-Hashes, Dateigröße und SHA-256 gebunden."
        )
        self.run_back_button.setEnabled(True)
        self.review_run_result_button.setEnabled(True)
        self._set_active_step(3)
        self.page_stack.setCurrentIndex(3)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot(str)
    def _result_review_failed(self, message: str) -> None:
        self._worker = None
        self._result_review = None
        self.run_back_button.setEnabled(True)
        self.review_run_result_button.setEnabled(self._run_result is not None)
        self.run_state_label.setObjectName("statusError")
        self.run_state_label.setStyleSheet("")
        self.run_state_label.setText(
            f"Ergebnisansicht gesperrt: der vollständige Snapshot verifiziert nicht: {message}"
        )
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
            button = QPushButton("Erneut prüfen & öffnen")
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
            self.result_status_label.setText("Unbekanntes Artefakt; nichts wurde geöffnet.")
            return
        worker = _ArtifactWorker(self._result_review, key)
        worker.signals.succeeded.connect(self._artifact_succeeded)
        worker.signals.failed.connect(self._artifact_failed)
        self._worker = worker
        self._set_result_controls_enabled(False)
        self.result_status_label.setObjectName("status")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(
            f"{artifact.label} wird unmittelbar vor der Übergabe erneut geprüft …"
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
            f"Hash- und Größenprüfung bestanden: {path.name}. Lokale Anwendung wird geöffnet."
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(str)
    def _artifact_failed(self, message: str) -> None:
        self._worker = None
        self._set_result_controls_enabled(True)
        self.result_status_label.setObjectName("statusError")
        self.result_status_label.setStyleSheet("")
        self.result_status_label.setText(f"Artefakt nicht geöffnet: {message}")
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _set_result_controls_enabled(self, enabled: bool) -> None:
        self.result_back_button.setEnabled(enabled)
        for button in self.result_artifact_buttons:
            button.setEnabled(enabled)

    @Slot()
    def _show_run_page_from_results(self) -> None:
        if self._worker is not None:
            return
        self._set_active_step(2)
        self.page_stack.setCurrentIndex(2)

    @staticmethod
    def _wrappable_path(path: Path) -> str:
        return str(path).replace("\\", "\\\u200b").replace("/", "/\u200b")

    @Slot(str)
    def _review_failed(self, message: str) -> None:
        self._worker = None
        self.review_button.setEnabled(self._result is not None)
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Parameterprüfung fehlgeschlagen: {message}")
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
        for index, label in enumerate(self.rail_steps):
            label.setObjectName("stepActive" if index == active else "stepFuture")
            label.setStyleSheet("")

    @Slot()
    def _show_setup_page(self) -> None:
        if isinstance(self._worker, _AtlasWorker):
            return
        self._set_active_step(0)
        self.page_stack.setCurrentIndex(0)

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
        if self._run_result is None or not self._run_result.completed:
            return
        destination = Path(self._run_result.terminal_event.payload["destination"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if isinstance(self._worker, _AtlasWorker):
            self._close_after_worker = True
            self._cancel_atlas()
            self.run_state_label.setText(
                "Fenster bleibt bis zum bestätigten sicheren Worker-Ende geöffnet. "
                "Der Abbruch wurde angefordert."
            )
            event.ignore()
            return
        if isinstance(self._worker, (_ResultReviewWorker, _ArtifactWorker)):
            self._close_after_worker = True
            if isinstance(self._worker, _ResultReviewWorker):
                self.run_state_label.setText(
                    "Fenster bleibt bis zum Ende der laufenden Ergebnisverifikation geöffnet."
                )
            else:
                self.result_status_label.setText(
                    "Fenster bleibt bis zum Ende der laufenden Artefaktprüfung geöffnet."
                )
            event.ignore()
            return
        super().closeEvent(event)
