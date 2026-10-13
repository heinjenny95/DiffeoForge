"""Isolated, offline presentation UI using public, already computed examples.

No production window/controller, run service, approvals, settings or filesystem
writes are used here. Reuse is limited to display-only geometry/plot widgets.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from diffeoforge import display_version
from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.demo_fixture import demo_mesh, load_demo_fixture
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.live_optimizer_plot import LiveOptimizerPlot

STATIONS = (
    (
        "Meshes",
        "Explore the example cohort",
        "Five small synthetic surfaces, ready to inspect. No files need to be selected.",
    ),
    (
        "Landmarks & alignment",
        "Try landmarks and prealignment",
        "Place points in the 3D view or inspect the stored before/after alignment example.",
    ),
    (
        "Parameters & pilot",
        "Explain the pilot workflow",
        "Try parameter controls and walk through screening, detail checks and fit review.",
    ),
    (
        "Atlas replay",
        "Replay a recorded atlas",
        "The curve comes from a completed public example. Playback starts no optimizer.",
    ),
    (
        "Visual QC",
        "Inspect reconstruction quality",
        "Compare each original surface with its saved native reconstruction.",
    ),
    (
        "PCA & deformations",
        "Explore shape space",
        "Precomputed Cartesian momenta PCA of the five public reconstructions.",
    ),
    (
        "Comparison & validation",
        "Compare and qualify results",
        "Illustrative metadata groups and recorded public repeatability evidence.",
    ),
    (
        "Report & exports",
        "Show the result handoff",
        "A presentation preview of reporting, provenance and export contents.",
    ),
)

_STYLE = """
QMainWindow, QWidget { background: #f4f6f5;
    color: #213c39;
    font-family: 'Segoe UI';
    font-size: 14px;
    }
QFrame#rail { background: #153e39; border: none; }
QFrame#rail QLabel { background: transparent; color: #d8e8e2; }
QLabel#brand { color: white; font-size: 26px; font-weight: 700; }
QLabel#title { font-size: 29px; font-weight: 650; }
QLabel#eyebrow { color: #227c6d; font-weight: 700; letter-spacing: 1px; }
QLabel#hint { color: #60746f; }
QFrame#banner { background: #fff0cf; border-bottom: 1px solid #e1c887; }
QFrame#banner QLabel { background: transparent; color: #62491d; font-weight: 600; }
QPushButton { background: white; border: 1px solid #c5d3cd; border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { background: #e0efea; border-color: #78a99b; }
QPushButton#nav { text-align: left;
    color: #d9ebe4;
    background: transparent;
    border: none;
    padding: 12px;
    }
QPushButton#nav:checked { color: white; background: #2e6158; }
QPushButton#primary { background: #1c7667; color: white; border-color: #1c7667; font-weight: 600; }
QComboBox, QDoubleSpinBox { background: white;
    border: 1px solid #bccfc7;
    border-radius: 5px;
    padding: 7px;
    }
QTableWidget, QTextBrowser { background: white; border: 1px solid #d5e1da; border-radius: 6px; }
QHeaderView::section { background: #e6eee9;
    color: #244c43;
    padding: 8px;
    border: none;
    font-weight: 600;
    }
QTableWidget::item { padding: 6px; }
QTableWidget::item:selected { background: #d5ede4; color: #193c33; }
QCheckBox { spacing: 7px; }
QSlider::groove:horizontal { background: #d4e0da; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #177563; width: 16px; margin: -6px 0; border-radius: 8px; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; }
"""


def _label(text: str, name: str = "hint") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName(name)
    return widget


def _table(headers: tuple[str, ...], rows: list[list[str]]) -> QTableWidget:
    widget = QTableWidget(len(rows), len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            widget.setItem(row, col, QTableWidgetItem(str(value)))
    widget.setMinimumHeight(70 + 39 * len(rows))
    return widget


class DemoScatter(QWidget):
    """Small selectable score plot; reads stored scores, performs no PCA."""

    subjectPicked = Signal(int)

    def __init__(self, fixture: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fixture = fixture
        self.x_axis, self.y_axis, self.selected = 0, 1, 0
        self.groups = False
        self.positions: list[QPointF] = []
        self.setMinimumSize(340, 300)
        self.setAccessibleName("Demo PCA scores; click a subject to inspect its reconstruction")

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        rect = QRectF(56, 28, self.width() - 95, self.height() - 88)
        scores = self.fixture["pca"]["scores"]
        xs = [row[self.x_axis] for row in scores]
        ys = [row[self.y_axis] for row in scores]
        x_range = max(max(xs) - min(xs), 1e-12) * 1.25
        y_range = max(max(ys) - min(ys), 1e-12) * 1.25
        x_mid, y_mid = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        painter.setPen(QPen(QColor("#bccfc7"), 1))
        painter.drawRect(rect)
        for part in range(1, 4):
            x = rect.left() + rect.width() * part / 4
            y = rect.top() + rect.height() * part / 4
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        ratios = self.fixture["pca"]["variance_ratio"]
        painter.setPen(QColor("#365d51"))
        painter.drawText(
            QRectF(0, self.height() - 40, self.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            f"PC{self.x_axis + 1} · {ratios[self.x_axis]:.1%} variance",
        )
        painter.drawText(QPointF(12, 19), f"PC{self.y_axis + 1} · {ratios[self.y_axis]:.1%}")
        self.positions = []
        for index, (x, y) in enumerate(zip(xs, ys, strict=True)):
            point = QPointF(
                rect.center().x() + (x - x_mid) / x_range * rect.width(),
                rect.center().y() - (y - y_mid) / y_range * rect.height(),
            )
            self.positions.append(point)
            color = "#b17b3a" if self.groups and index >= 2 else "#1a8070"
            painter.setPen(QPen(QColor("#183e34") if index == self.selected else QColor(color), 2))
            painter.setBrush(QColor(color))
            painter.drawEllipse(
                point, 8 if index == self.selected else 5, 8 if index == self.selected else 5
            )
            painter.drawText(point + QPointF(11, -9), str(index + 1))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.positions:
            distances = [(point - event.position()).manhattanLength() for point in self.positions]
            index = min(range(len(distances)), key=distances.__getitem__)
            if distances[index] < 24:
                self.subjectPicked.emit(index)


class DemoWindow(QMainWindow):
    """Freely navigable presentation session, entirely separate from real projects."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fixture = load_demo_fixture()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.models = [
            {
                kind: demo_mesh(subject[kind], f"{subject['label']}-{kind}")
                for kind in ("original", "reconstruction", "aligned")
            }
            for subject in self.fixture["subjects"]
        ]
        self.template = demo_mesh(self.fixture["estimated_template"], "estimated-template")
        self.landmarks = [deepcopy(subject["landmarks"]) for subject in self.fixture["subjects"]]
        self.decisions: dict[int, str] = {}
        self.pilot_stage = 0
        self.replay_timer = QTimer(self)
        self.replay_timer.setInterval(450)
        self.replay_timer.timeout.connect(self._advance_replay)
        self.setWindowTitle(f"DiffeoForge {display_version()} — DEMO")
        self.resize(1400, 930)
        self.setMinimumSize(1000, 720)
        self.setStyleSheet(_STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(250)
        navigation = QVBoxLayout(rail)
        navigation.setContentsMargins(18, 28, 18, 20)
        navigation.addWidget(_label("DiffeoForge", "brand"))
        navigation.addWidget(_label("PRESENTATION MODE"))
        navigation.addSpacing(22)
        self.nav_buttons = []
        for index, (name, _, _) in enumerate(STATIONS):
            button = QPushButton(f"{index + 1:02d}   {name.replace('&', '&&')}")
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self.show_station(i))
            navigation.addWidget(button)
            self.nav_buttons.append(button)
        navigation.addStretch()
        navigation.addWidget(_label("Jump to any station.\nNo prerequisites. No analysis."))
        self.reset_button = QPushButton("Reset demo")
        self.reset_button.clicked.connect(self.reset_session)
        navigation.addWidget(self.reset_button)
        close = QPushButton("Close demo")
        close.clicked.connect(self.close)
        navigation.addWidget(close)
        outer.addWidget(rail)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        banner = QFrame()
        banner.setObjectName("banner")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(24, 12, 24, 12)
        banner_layout.addWidget(
            _label(
                "DEMO  ·  Public synthetic examples  ·  No analysis running  ·  Changes stay "
                "in this window"
            )
        )
        main.addWidget(banner)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        outer.addLayout(main, 1)
        builders = (
            self._meshes,
            self._alignment,
            self._pilot,
            self._atlas,
            self._qc,
            self._pca,
            self._validation,
            self._reports,
        )
        for index, builder in enumerate(builders):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(28, 24, 28, 20)
            layout.setSpacing(15)
            layout.addWidget(_label(f"DEMO STATION {index + 1} / {len(STATIONS)}", "eyebrow"))
            layout.addWidget(_label(STATIONS[index][1], "title"))
            layout.addWidget(_label(STATIONS[index][2]))
            builder(layout)
            scroll.setWidget(content)
            self.pages.addWidget(scroll)
        self.show_station(0)

    def _subjects(self, callback) -> QComboBox:
        box = QComboBox()
        box.addItems([subject["label"] for subject in self.fixture["subjects"]])
        box.currentIndexChanged.connect(callback)
        return box

    def _overlay(self) -> CalibrationComparisonCanvas3D:
        canvas = CalibrationComparisonCanvas3D()
        canvas.setMinimumHeight(330)
        return canvas

    def _view_controls(self, layout: QVBoxLayout, canvas) -> None:
        row = QHBoxLayout()
        row.addWidget(_label("Drag to rotate · wheel to zoom · right drag to pan"), 1)
        for name in ("front", "left", "top"):
            button = QPushButton(name.capitalize())
            button.clicked.connect(
                lambda _checked=False, preset=name: canvas.set_view_preset(preset)
            )
            row.addWidget(button)
        reset = QPushButton("Reset view")
        reset.clicked.connect(canvas.reset_view)
        row.addWidget(reset)
        layout.addLayout(row)

    def _meshes(self, layout: QVBoxLayout) -> None:
        self.mesh_subject = self._subjects(self._change_mesh)
        layout.addWidget(self.mesh_subject)
        self.mesh_canvas = InteractiveMeshCanvas3D()
        self.mesh_canvas.setMinimumHeight(340)
        self.mesh_canvas.set_picking_enabled(False)
        self.mesh_canvas.set_model(self.models[0]["original"])
        layout.addWidget(self.mesh_canvas, 1)
        self._view_controls(layout, self.mesh_canvas)
        self.mesh_table = _table(
            ("Mesh", "Vertices", "Triangles", "Source"),
            [
                [
                    subject["label"],
                    str(model["original"].point_count),
                    str(model["original"].triangle_count),
                    "CC0 synthetic",
                ]
                for subject, model in zip(self.fixture["subjects"], self.models, strict=True)
            ],
        )
        self.mesh_table.cellClicked.connect(
            lambda row, _col: self.mesh_subject.setCurrentIndex(row)
        )
        layout.addWidget(self.mesh_table)
        layout.addWidget(
            _label(
                "Real workflow: input integrity, units, mesh checks and documented alignment "
                "precede the pilot. "
                "This small cohort is bundled; private data and recent projects are never opened."
            )
        )

    def _change_mesh(self, index: int) -> None:
        self.mesh_canvas.set_model(self.models[index]["original"])

    def _alignment(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self.landmark_subject = self._subjects(self._change_landmark_subject)
        row.addWidget(self.landmark_subject)
        self.landmark_label = QComboBox()
        self.landmark_label.addItems(["a", "b", "c", "d"])
        row.addWidget(self.landmark_label)
        self.alignment_mode = QComboBox()
        self.alignment_mode.addItems(["Place landmarks", "Stored alignment comparison"])
        self.alignment_mode.currentIndexChanged.connect(self._alignment_mode_changed)
        row.addWidget(self.alignment_mode, 1)
        layout.addLayout(row)
        self.alignment_stack = QStackedWidget()
        self.landmark_canvas = InteractiveMeshCanvas3D()
        self.landmark_canvas.setMinimumHeight(340)
        self.landmark_canvas.surfacePointPicked.connect(self._pick_landmark)
        self.alignment_canvas = self._overlay()
        self.alignment_stack.addWidget(self.landmark_canvas)
        self.alignment_stack.addWidget(self.alignment_canvas)
        layout.addWidget(self.alignment_stack, 1)
        row = QHBoxLayout()
        clear = QPushButton("Clear this subject's demo points")
        clear.clicked.connect(self._clear_landmarks)
        row.addWidget(clear)
        restore = QPushButton("Restore bundled points")
        restore.clicked.connect(self._restore_landmarks)
        row.addWidget(restore)
        row.addStretch()
        layout.addLayout(row)
        self.landmark_status = _label("")
        layout.addWidget(self.landmark_status)
        layout.addWidget(
            _label(
                "Stored alignment uses a similarity fit to the template's four landmarks. "
                "Moving a demo point does not recompute alignment. Landmarks are prealignment "
                "inputs, "
                "not atlas attachment terms. In the real workflow, GPA is computed and "
                "reviewed separately."
            )
        )
        self._change_landmark_subject(0)

    def _change_landmark_subject(self, index: int) -> None:
        self.landmark_canvas.set_model(self.models[index]["original"])
        self.alignment_canvas.set_models(
            self.models[index]["original"], self.models[index]["aligned"]
        )
        self._refresh_markers()

    def _alignment_mode_changed(self, index: int) -> None:
        self.alignment_stack.setCurrentIndex(index)

    def _refresh_markers(self) -> None:
        points = self.landmarks[self.landmark_subject.currentIndex()]
        self.landmark_canvas.set_markers(points)
        self.landmark_status.setText(
            f"{len(points)} demo landmarks · click the surface to replace the selected label · "
            f"in memory only"
        )

    def _pick_landmark(self, point: tuple) -> None:
        self.landmarks[self.landmark_subject.currentIndex()][self.landmark_label.currentText()] = (
            tuple(map(float, point))
        )
        self._refresh_markers()

    def _clear_landmarks(self) -> None:
        self.landmarks[self.landmark_subject.currentIndex()] = {}
        self._refresh_markers()

    def _restore_landmarks(self) -> None:
        index = self.landmark_subject.currentIndex()
        self.landmarks[index] = deepcopy(self.fixture["subjects"][index]["landmarks"])
        self._refresh_markers()

    def _pilot(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.parameter_fields = []
        for title, value in (
            ("Deformation width", 0.6),
            ("Attachment width", 0.45),
            ("Noise scale", 0.1),
        ):
            column = QVBoxLayout()
            column.addWidget(_label(title))
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(0.001, 100)
            field.setValue(value)
            field.setToolTip(
                "Presentation input only; does not alter saved results or dispatch a pilot."
            )
            field.valueChanged.connect(self._parameter_changed)
            column.addWidget(field)
            controls.addLayout(column)
            self.parameter_fields.append(field)
        layout.addLayout(controls)
        self.parameter_status = _label(
            "Illustrative controls; the saved public fit stays fixed. No recommendation has "
            "been generated."
        )
        layout.addWidget(self.parameter_status)
        layout.addWidget(
            _table(
                ("Pilot stage", "What it checks", "Demonstration"),
                [
                    ["Screening", "Broad parameter exploration", "Workflow illustration"],
                    [
                        "Detail qualification",
                        "Original geometry / bounded approximation",
                        "Workflow illustration",
                    ],
                    [
                        "Fit review",
                        "Residuals + visual reconstruction inspection",
                        "Saved public native overlay below",
                    ],
                    [
                        "Continuation",
                        "Keep tolerance after a cap; inspect stop reason",
                        "Explanation only; no run created",
                    ],
                ],
            )
        )
        self.pilot_button = QPushButton("Next pilot explanation")
        self.pilot_button.setObjectName("primary")
        self.pilot_button.clicked.connect(self._advance_pilot)
        layout.addWidget(self.pilot_button)
        self.pilot_status = _label(
            "1 / 4 · Screening suggests candidates; it does not approve anatomical fit."
        )
        layout.addWidget(self.pilot_status)
        self.pilot_canvas = self._overlay()
        self.pilot_canvas.set_models(self.models[0]["original"], self.models[0]["reconstruction"])
        layout.addWidget(self.pilot_canvas, 1)
        layout.addWidget(
            _label(
                "This overlay is the one recorded public fit, not a new candidate produced by "
                "the controls. "
                "Real fit criteria, visual review and readiness gates are unchanged."
            )
        )

    def _parameter_changed(self) -> None:
        self.parameter_status.setText(
            "Demo inputs changed. A real change would require a new pilot; stored examples and "
            "all real settings are unchanged."
        )

    def _advance_pilot(self) -> None:
        self.pilot_stage = (self.pilot_stage + 1) % 4
        messages = (
            "Screening suggests candidates; it does not approve anatomical fit.",
            "Detail qualification checks approximation loss; originals are used when "
            "qualification fails.",
            "Inspect every reconstruction. Numerical improvement alone is insufficient for "
            "approval.",
            "A verified capped checkpoint can continue with the same tolerance; errors require "
            "an explicit decision.",
        )
        self.pilot_status.setText(f"{self.pilot_stage + 1} / 4 · {messages[self.pilot_stage]}")

    def _atlas(self, layout: QVBoxLayout) -> None:
        self.optimizer_plot = LiveOptimizerPlot()
        # The production observer is reused strictly for display of recorded samples.
        for label in self.optimizer_plot.findChildren(QLabel):
            if label.text() == "Live optimizer convergence":
                label.setText("Recorded public optimizer curve")
        self.optimizer_plot.setToolTip(
            "Playback of bundled convergence.csv; no live worker or estimated timing."
        )
        layout.addWidget(self.optimizer_plot)
        self.replay_slider = QSlider(Qt.Orientation.Horizontal)
        self.replay_slider.setRange(0, len(self.fixture["convergence"]) - 1)
        self.replay_slider.valueChanged.connect(self._seek_replay)
        layout.addWidget(self.replay_slider)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play recorded run")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self._toggle_replay)
        controls.addWidget(self.play_button)
        last = QPushButton("Jump to recorded end")
        last.clicked.connect(lambda: self.replay_slider.setValue(self.replay_slider.maximum()))
        controls.addWidget(last)
        controls.addStretch()
        layout.addLayout(controls)
        self.replay_status = _label("")
        layout.addWidget(self.replay_status)
        layout.addWidget(
            _label(
                "Recorded example: Deformetrica 4.3.0, CPU, float32, five synthetic subjects, "
                "36 control points; explicit native tolerance at iteration 22. "
                "Playback speed is chosen for presentation and says nothing about a real "
                "dataset's runtime."
            )
        )
        layout.addWidget(
            _table(
                ("Real run feature", "Presentation"),
                [
                    [
                        "Convergence / attachment / regularity",
                        "Stored curve; enable the plot's component checkboxes",
                    ],
                    [
                        "Capped checkpoints and resume",
                        "Explained in station 3; no checkpoint is created or resumed",
                    ],
                    [
                        "Local / remote resources",
                        "No local or remote backend connection in demo mode",
                    ],
                    ["Final export", "Stored meshes only; no completion metadata is fabricated"],
                ],
            )
        )
        layout.addStretch()
        self._seek_replay(0)

    def _seek_replay(self, index: int) -> None:
        self.optimizer_plot.clear()
        for row in self.fixture["convergence"][: index + 1]:
            self.optimizer_plot.add_sample(
                row["iteration"], row["log_likelihood"], row["attachment"], row["regularity"]
            )
        row = self.fixture["convergence"][index]
        self.replay_status.setText(
            f"RECORDING · iteration {row['iteration']} / 22 · objective "
            f"{row['log_likelihood']:.6g} · no computation running"
        )
        if index == self.replay_slider.maximum():
            self._pause_replay()

    def _toggle_replay(self) -> None:
        if self.replay_timer.isActive():
            self._pause_replay()
        else:
            if self.replay_slider.value() == self.replay_slider.maximum():
                self.replay_slider.setValue(0)
            self.replay_timer.start()
            self.play_button.setText("Pause recording")

    def _advance_replay(self) -> None:
        self.replay_slider.setValue(
            min(self.replay_slider.maximum(), self.replay_slider.value() + 1)
        )

    def _pause_replay(self) -> None:
        self.replay_timer.stop()
        self.play_button.setText("Play recorded run")

    def _qc(self, layout: QVBoxLayout) -> None:
        controls = QHBoxLayout()
        self.qc_subject = self._subjects(self._change_qc)
        controls.addWidget(self.qc_subject, 1)
        self.show_original = QCheckBox("Original")
        self.show_original.setChecked(True)
        self.show_reconstruction = QCheckBox("Reconstruction")
        self.show_reconstruction.setChecked(True)
        controls.addWidget(self.show_original)
        controls.addWidget(self.show_reconstruction)
        layout.addLayout(controls)
        self.qc_canvas = self._overlay()
        self.show_original.toggled.connect(self.qc_canvas.set_show_original)
        self.show_reconstruction.toggled.connect(self.qc_canvas.set_show_reconstruction)
        layout.addWidget(self.qc_canvas, 1)
        self._view_controls(layout, self.qc_canvas)
        row = QHBoxLayout()
        for text in ("Looks good (demo)", "Needs review (demo)"):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, decision=text: self._demo_decision(decision)
            )
            row.addWidget(button)
        next_subject = QPushButton("Next subject")
        next_subject.clicked.connect(
            lambda: self.qc_subject.setCurrentIndex((self.qc_subject.currentIndex() + 1) % 5)
        )
        row.addWidget(next_subject)
        layout.addLayout(row)
        self.qc_status = _label("")
        layout.addWidget(self.qc_status)
        layout.addWidget(
            _label(
                "Orange wireframe: original / blue surface: reconstruction. "
                "Demo decisions are temporary; "
                "they never write an approval journal, unlock a real PCA or approve private "
                "anatomy."
            )
        )
        self._change_qc(0)

    def _change_qc(self, index: int) -> None:
        self.qc_canvas.set_models(
            self.models[index]["original"], self.models[index]["reconstruction"]
        )
        self.qc_status.setText(
            f"Saved residual {self.fixture['residuals'][index]:.8g} (native attachment output, "
            f"not a distance) · "
            f"{self.decisions.get(index, 'No demo decision yet')}"
        )

    def _demo_decision(self, decision: str) -> None:
        index = self.qc_subject.currentIndex()
        self.decisions[index] = decision
        self._change_qc(index)

    def _pca(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self.pca_subject = self._subjects(self._change_pca_subject)
        row.addWidget(self.pca_subject, 1)
        self.x_axis = QComboBox()
        self.y_axis = QComboBox()
        for box in (self.x_axis, self.y_axis):
            box.addItems([f"PC{index + 1}" for index in range(4)])
        self.y_axis.setCurrentIndex(1)
        self.x_axis.currentIndexChanged.connect(self._change_axes)
        self.y_axis.currentIndexChanged.connect(self._change_axes)
        row.addWidget(_label("X"))
        row.addWidget(self.x_axis)
        row.addWidget(_label("Y"))
        row.addWidget(self.y_axis)
        layout.addLayout(row)
        self.scatter = DemoScatter(self.fixture)
        self.scatter.subjectPicked.connect(self.pca_subject.setCurrentIndex)
        display = QHBoxLayout()
        display.addWidget(self.scatter, 1)
        self.pca_canvas = self._overlay()
        display.addWidget(self.pca_canvas, 1)
        layout.addLayout(display)
        self.morph_slider = QSlider(Qt.Orientation.Horizontal)
        self.morph_slider.setRange(0, 100)
        self.morph_slider.setValue(100)
        self.morph_slider.valueChanged.connect(self._update_morph)
        layout.addWidget(
            _label(
                "Endpoint blend: estimated template → selected native reconstruction (display "
                "illustration)"
            )
        )
        layout.addWidget(self.morph_slider)
        self.morph_status = _label("")
        layout.addWidget(self.morph_status)
        ratios = self.fixture["pca"]["variance_ratio"]
        layout.addWidget(
            _table(
                ("Component", "Explained variance", "Feature space"),
                [
                    [f"PC{index + 1}", f"{ratio:.2%}", "Cartesian momenta (stored)"]
                    for index, ratio in enumerate(ratios[:4])
                ],
            )
        )
        layout.addWidget(
            _label(
                "The slider interpolates corresponding endpoint vertices. It is not a PC "
                "deformation, "
                "diffeomorphic trajectory or native Shooting result. Real native PCA "
                "deformations require "
                "a separate qualified calculation; this station demonstrates selection and 3D "
                "interaction."
            )
        )
        self._change_pca_subject(0)

    def _change_axes(self) -> None:
        if self.x_axis.currentIndex() == self.y_axis.currentIndex():
            self.y_axis.blockSignals(True)
            self.y_axis.setCurrentIndex((self.x_axis.currentIndex() + 1) % 4)
            self.y_axis.blockSignals(False)
        self.scatter.x_axis, self.scatter.y_axis = (
            self.x_axis.currentIndex(),
            self.y_axis.currentIndex(),
        )
        self.scatter.update()

    def _change_pca_subject(self, index: int) -> None:
        self.scatter.selected = index
        self.scatter.update()
        self._update_morph()

    def _update_morph(self) -> None:
        index = self.pca_subject.currentIndex()
        fraction = self.morph_slider.value() / 100
        reconstruction = self.fixture["subjects"][index]["reconstruction"]
        vertices = [
            [a + fraction * (b - a) for a, b in zip(start, end, strict=True)]
            for start, end in zip(self.template.vertices, reconstruction["vertices"], strict=True)
        ]
        model = demo_mesh(
            {"vertices": vertices, "triangles": reconstruction["triangles"]}, "endpoint-blend"
        )
        self.pca_canvas.set_models(self.template, model)
        self.morph_status.setText(
            f"{fraction:.0%} endpoint blend · display only · stored PCA scores stay unchanged"
        )

    def _validation(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_label("Metadata and shape-space comparison", "sectionTitle"))
        self.group_checkbox = QCheckBox("Color by illustrative metadata group")
        layout.addWidget(self.group_checkbox)
        self.group_scatter = DemoScatter(self.fixture)
        self.group_scatter.groups = False
        self.group_checkbox.toggled.connect(self._groups_changed)
        self.group_scatter.subjectPicked.connect(self._select_group_subject)
        layout.addWidget(self.group_scatter, 1)
        self.group_status = _label(
            "Example A: subjects 1–2 · Example B: subjects 3–5. Arbitrary teaching labels, no "
            "biological inference."
        )
        layout.addWidget(self.group_status)
        layout.addWidget(
            _table(
                ("Validation / comparison feature", "Public example / boundary"),
                [
                    [
                        "Reference repeatability",
                        "Two recorded CPU native runs; 60 shared outputs byte-identical",
                    ],
                    ["Convergence", "23 recorded rows; native tolerance at iteration 22"],
                    [
                        "Feature-space comparison",
                        "Cartesian momenta scores shown; LDDMM/GPA alternatives require "
                        "separate results",
                    ],
                    [
                        "Validation lab",
                        "Known-input, reconstruction, robustness and held-out checks in real "
                        "workflow",
                    ],
                    [
                        "Interpretation",
                        "Five toy subjects; no robustness, biological or cross-platform "
                        "equivalence claim",
                    ],
                ],
            )
        )
        layout.addWidget(
            _label(
                "Recorded repeatability is evidence for the public fixture's recorded environment. "
                "It does not qualify another dataset, machine or the running server atlas."
            )
        )

    def _groups_changed(self, enabled: bool) -> None:
        self.group_scatter.groups = enabled
        self.group_scatter.update()

    def _select_group_subject(self, index: int) -> None:
        self.group_scatter.selected = index
        self.group_scatter.update()
        subject = self.fixture["subjects"][index]
        self.group_status.setText(
            f"{subject['label']} · {subject['group']} · illustrative label only"
        )

    def _reports(self, layout: QVBoxLayout) -> None:
        tabs = QHBoxLayout()
        self.report_kind = QComboBox()
        self.report_kind.addItems(
            [
                "Scientific report preview",
                "Export contents",
                "Provenance & limits",
                "Suggested presentation tour",
            ]
        )
        self.report_kind.currentIndexChanged.connect(self._change_report)
        tabs.addWidget(self.report_kind, 1)
        layout.addLayout(tabs)
        self.report_browser = QTextBrowser()
        self.report_browser.setOpenExternalLinks(False)
        self.report_browser.setMinimumHeight(420)
        layout.addWidget(self.report_browser, 1)
        layout.addWidget(
            _label(
                "Preview only. No PDF, publication bundle, study approval, checkpoint or "
                "scientific export is written. "
                "In the real app, reports bind verified evidence and documented review decisions."
            )
        )
        self._change_report(0)

    def _change_report(self, index: int) -> None:
        execution = self.fixture["execution"]
        bodies = (
            f"<h2>Public synthetic atlas</h2><p><b>DEMO REPORT PREVIEW</b> — generated from "
            f"bundled stored values.</p>"
            f"<p>Five synthetic surfaces; Deformetrica 4.3.0 CPU reference, recorded July 2026.</p>"
            f"<h3>Recorded computation</h3><p>Native tolerance at iteration "
            f"{execution['completed_iteration']}; "
            f"likelihood {execution['initial_log_likelihood']} → "
            f"{execution['final_log_likelihood']}. "
            f"Mean native residual {execution['residual_mean']:.8g}.</p>"
            "<h3>Interpretation</h3><p>Engineering example only, no biological meaning. "
            "Numerical completion and "
            "anatomical approval are separate. Temporary demo labels are not approval "
            "evidence.</p>",
            "<h2>Export contents preview</h2><ul><li>Estimated template and per-subject "
            "reconstructions</li>"
            "<li>Momenta, control points, residuals and convergence</li><li>PCA scores, "
            "loadings and declared feature space</li>"
            "<li>Scientific report, metadata tables and provenance</li><li>Publication bundle "
            "with reviewed figures</li></ul>"
            "<p>The bundled fixture contains selected public endpoints, not a complete new run "
            "or retained native trajectories. "
            "Real export eligibility is unchanged. No files are created by this preview.</p>",
            "<h2>Provenance & limits</h2><p>Sources: examples/synthetic and "
            "reference/synthetic-v1 (CC0-1.0). "
            "The bundle is size/hash checked when opened.</p><p>Native meshes, residuals and "
            "convergence are recorded. "
            "Cartesian momenta PCA and template-landmark alignment were precomputed when the "
            "fixture was prepared. "
            "Pilot stages and metadata groups are explanatory. Morphs are endpoint blends, not "
            "native Shooting.</p>"
            "<p>Demo inputs and review labels disappear on reset/close. No project history, "
            "production gates, backend "
            "processes, real settings or server data are changed.</p>",
            "<h2>A five-minute tour</h2><ol><li>Meshes: rotate a surface; choose a second "
            "specimen.</li>"
            "<li>Landmarks: move a point; switch to the stored alignment comparison.</li>"
            "<li>Pilot: explain screening, detail qualification and unchanged fit criteria.</li>"
            "<li>Atlas: play the recorded curve; enable attachment and regularity.</li>"
            "<li>QC: toggle original/reconstruction, mark a demo decision, select next "
            "subject.</li>"
            "<li>PCA: select axes and a point; try the explicitly illustrative endpoint blend.</li>"
            "<li>Comparison: color the arbitrary example groups; explain validation limits.</li>"
            "<li>Reports: show the provenance and export preview.</li></ol><p>Any station can "
            "be opened first.</p>",
        )
        self.report_browser.setHtml("<h1>DEMO · DiffeoForge</h1>" + bodies[index])

    def show_station(self, index: int) -> None:
        if not 0 <= index < len(STATIONS):
            raise ValueError("Unknown demo station")
        if index != 3 and hasattr(self, "play_button"):
            self._pause_replay()
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)

    def reset_session(self) -> None:
        self._pause_replay()
        self.decisions.clear()
        self.landmarks = [deepcopy(subject["landmarks"]) for subject in self.fixture["subjects"]]
        self.pilot_stage = 3
        self._advance_pilot()
        for field, value in zip(self.parameter_fields, (0.6, 0.45, 0.1), strict=True):
            field.setValue(value)
        self.parameter_status.setText(
            "Illustrative controls; the saved public fit stays fixed. No recommendation has "
            "been generated."
        )
        for box in (
            self.mesh_subject,
            self.landmark_subject,
            self.qc_subject,
            self.pca_subject,
            self.alignment_mode,
            self.landmark_label,
            self.report_kind,
            self.x_axis,
        ):
            box.setCurrentIndex(0)
        self.y_axis.setCurrentIndex(1)
        self.group_checkbox.setChecked(False)
        self.group_scatter.selected = 0
        self._select_group_subject(0)
        self.show_original.setChecked(True)
        self.show_reconstruction.setChecked(True)
        self.morph_slider.setValue(100)
        self.replay_slider.setValue(0)
        self._seek_replay(0)
        self.optimizer_plot.attachment_checkbox.setChecked(False)
        self.optimizer_plot.regularity_checkbox.setChecked(False)
        self._change_landmark_subject(0)
        self._change_qc(0)
        for canvas in (
            self.mesh_canvas,
            self.landmark_canvas,
            self.alignment_canvas,
            self.pilot_canvas,
            self.qc_canvas,
            self.pca_canvas,
        ):
            canvas.original_detail.setChecked(False)
            canvas.reset_view()
        self.show_station(0)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.replay_timer.stop()
        self.landmark_canvas.cancel_pending_pick()
        super().closeEvent(event)
