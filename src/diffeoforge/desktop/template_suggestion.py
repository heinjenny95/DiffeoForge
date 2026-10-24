"""Optional background starting-template recommendation in the input step."""

from pathlib import Path
from threading import Event

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.pilot_design import suggest_templates


class TemplateSuggestionPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self._owner = window
        self.result = None
        self.cancelled = Event()
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(lambda _key, error: self._failed(error))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.suggest = QPushButton("Suggest a template")
        self.suggest.clicked.connect(self._suggest)
        row.addWidget(self.suggest)
        self.preview = QPushButton("Preview candidate")
        self.preview.clicked.connect(self._preview)
        self.use = QPushButton("Use suggested template")
        self.use.clicked.connect(self._apply)
        row.addWidget(self.preview)
        row.addWidget(self.use)
        row.addStretch()
        layout.addLayout(row)
        self.status = QLabel("Optional: recommend a representative starting form before alignment.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.alternatives = QComboBox()
        self.alternatives.setAccessibleName("Alternative initial templates")
        details = QWidget(self)
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(self.alternatives)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.explanation.setTextFormat(Qt.TextFormat.PlainText)
        details_layout.addWidget(self.explanation)
        self.alternatives.currentIndexChanged.connect(self._explain)
        self.more = InfoDisclosure("Alternative templates and previous reviews", details)
        layout.addWidget(self.more)
        self.preview.hide()
        self.use.hide()
        self.more.hide()
        for edit in (window.mesh_edit, window.template_edit):
            edit.textChanged.connect(self.invalidate)

    def _paths(self):
        from diffeoforge.surface_io import is_supported_surface_path

        directory = Path(self._owner.mesh_edit.text().strip()).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("Select an existing mesh folder first")
        # A recommendation may precede selecting a template/format. Inspect supported
        # direct children; the explicit pattern remains authoritative for the project.
        pattern = self._owner.pattern_edit.text().strip()
        paths = tuple(
            sorted(
                p.resolve()
                for p in directory.glob(pattern)
                if p.is_file() and is_supported_surface_path(p)
            )
        )
        if not paths and pattern in {"*.vtk", "*.ply", "*.obj", "*.stl"}:
            paths = tuple(
                sorted(
                    p.resolve()
                    for p in directory.iterdir()
                    if p.is_file() and is_supported_surface_path(p)
                )
            )
        if not paths:
            raise ValueError("No surfaces match the selected file pattern")
        return paths

    def invalidate(self, *_args):
        self._owner._template_suggestion_accepted = None
        self.cancelled.set()
        self.loader.cancel()
        self.result = None
        self.use.hide()
        self.preview.hide()
        self.more.hide()
        self.suggest.setEnabled(True)
        self.status.setText("Optional: recommend a representative starting form before alignment.")

    def _suggest(self):
        if self._owner._worker is not None:
            self.status.setText("Wait for the current preparation to finish.")
            return
        try:
            paths = self._paths()
        except (OSError, ValueError) as error:
            self._failed(str(error))
            return
        self.cancelled.set()
        self.cancelled = Event()
        cancelled = self.cancelled
        cache = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "mesh-measurements"
        )
        self.suggest.setEnabled(False)
        self.status.setText(f"Comparing {len(paths)} surfaces in background; no fitting…")
        project_edit = getattr(self._owner, "project_edit", None)
        project = project_edit.text().strip() if project_edit else None
        self.loader.request_operation(
            paths,
            lambda: self._measure(paths, cache, cancelled, project),
        )

    @staticmethod
    def _measure(paths, cache, cancelled, project):
        from diffeoforge.template_reviews import previous_template_reviews

        reviews = previous_template_reviews(project, cancel_requested=cancelled.is_set)
        return suggest_templates(paths, cache_directory=cache,
                                 cancel_requested=cancelled.is_set, review_evidence=reviews)

    def _explain(self, *_args):
        row = self.alternatives.currentData()
        if not row:
            return
        lines = [row["reason"],
                 f"Overall distance {row['global_distance']:.2f} · local distance "
                 f"{row['local_distance']:.2f} (smaller means more central)."]
        for review in row.get("previous_reviews", []):
            targets = ", ".join(r["filename"] for r in review["targets"])
            lines.append(
                f"Previous {'approved' if review['approved'] else 'unfit'} fit · "
                f"{review['method']} · targets: {targets}\n"
                f"Settings: {review['settings']}\nSource: {review['source_study']}"
            )
        if not row.get("previous_reviews"):
            lines.append("No compatible recorded review found in the selected project.")
        lines.append("Past reviews concern those targets and settings; they do not approve "
                     "or rule out this template for other fits.")
        lines.append("Review lookup covers up to 64 studies in the selected project; "
                     "it is not a complete history across projects.")
        self.explanation.setText("\n".join(lines))

    def _loaded(self, paths, result):
        if paths and paths[0] == "preview":
            from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D

            if self.result is None or self.alternatives.currentData()["path"] != paths[1]:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Initial template candidate")
            dialog.resize(760, 600)
            layout = QVBoxLayout(dialog)
            canvas = InteractiveMeshCanvas3D()
            canvas.set_picking_enabled(False)
            canvas.set_model(result[0])
            layout.addWidget(canvas)
            close = QPushButton("Close")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()
            return
        try:
            current = self._paths()
        except (OSError, ValueError):
            return
        if paths != current or self.cancelled.is_set():
            return
        self.result = result
        self.alternatives.clear()
        ranked = result["candidates"]
        contrasting = [r for r in ranked[1:] if r["contrasting_alternative"]]
        alternatives = [ranked[0], *contrasting, *[r for r in ranked[1:]
                                                if not r["contrasting_alternative"]]]
        for index, row in enumerate(alternatives):
            self.alternatives.addItem(
                ("Starting suggestion · " if index == 0 else "Contrasting form · "
                 if row["contrasting_alternative"] else "Alternative · ") + row["filename"], row
            )
        self.status.setText(
            result["candidates"][0]["filename"]
            + ": "
            + result["candidates"][0]["reason"]
            + (" Similar scores: inspect alternatives before choosing."
               if result["uncertain"] else "")
            + (
                f" {len(result['unreadable_meshes'])} meshes need inspection."
                if result["unreadable_meshes"]
                else ""
            )
        )
        self.status.setToolTip(result["limitation"])
        self._explain()
        self.use.show()
        self.preview.show()
        self.more.show()
        self.suggest.setEnabled(True)

    def _apply(self):
        from diffeoforge.mesh import sha256_file

        if self._owner._worker is not None or self.result is None:
            return
        row = self.alternatives.currentData()
        try:
            if {str(p) for p in self._paths()} != {
                r["path"] for r in self.result["input_binding"]
            } | {r["path"] for r in self.result["unreadable_meshes"]}:
                raise ValueError("Cohort changed; request a new suggestion")
            if sha256_file(Path(row["path"])) != row["sha256"]:
                raise ValueError("Candidate changed; request a new suggestion")
        except (OSError, ValueError) as error:
            self._failed(str(error))
            return
        accepted = dict(row)
        self._owner.template_edit.setText(row["path"])
        self._owner._adopt_template_format_pattern(Path(row["path"]))
        self._owner._template_suggestion_accepted = accepted
        self.status.setText("Starting template selected. Continue with alignment and pilot design.")

    def _preview(self):
        if self.result is None:
            return
        row = self.alternatives.currentData()
        self.loader.request_paths(
            ("preview", row["path"]), (Path(row["path"]),), expected=(row["sha256"],)
        )

    def _failed(self, error):
        self.status.setText("Template suggestion: " + error)
        self.suggest.setEnabled(True)

    def closeEvent(self, event):
        self.cancelled.set()
        self.loader.cancel()
        super().closeEvent(event)
