"""PySide6 widgets for the first DiffeoForge Desktop vertical slice."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    ProjectSetupResult,
    create_project,
)
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
QLabel#status { background: #f2f5f6; border-radius: 7px; color: #526b70; padding: 10px; }
QLabel#statusSuccess { background: #e5f5ed; border-radius: 7px; color: #176345; padding: 10px; }
QLabel#statusError { background: #fff0ed; border-radius: 7px; color: #a13a2d; padding: 10px; }
"""


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
        self._worker: _ProjectWorker | None = None
        self._result: ProjectSetupResult | None = None
        self._build_ui()
        self._update_engine_explanation()
        self._sync_ready_state()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_rail())
        root_layout.addWidget(self._build_content(), 1)
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
            ("1  Daten & Engine", True),
            ("2  Parameter prüfen", False),
            ("3  Atlas berechnen", False),
            ("4  Ergebnisse & PCA", False),
        )
        for text, active in steps:
            label = QLabel(text)
            label.setObjectName("stepActive" if active else "stepFuture")
            layout.addWidget(label)
        layout.addStretch()
        boundary = QLabel("PRE-ALPHA\nKeine wissenschaftliche Validierung")
        boundary.setObjectName("railCaption")
        boundary.setWordWrap(True)
        layout.addWidget(boundary)
        return rail

    def _build_content(self) -> QWidget:
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
        button_row.addWidget(open_config)
        button_row.addWidget(open_folder)
        button_row.addStretch()
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
        self._sync_ready_state()

    @Slot(str)
    def _project_failed(self, message: str) -> None:
        self._worker = None
        self.status_label.setObjectName("statusError")
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Projekt konnte nicht angelegt werden: {message}")
        self._sync_ready_state()

    @Slot()
    def _open_config(self) -> None:
        if self._result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.config_path)))

    @Slot()
    def _open_project_directory(self) -> None:
        if self._result is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.config_path.parent)))
