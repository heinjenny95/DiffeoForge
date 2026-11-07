"""Optional background starting-template recommendation in the input step."""

import hashlib
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
from diffeoforge.desktop.workflow_guidance import TEMPLATE_GUIDE, TEMPLATE_SUMMARY
from diffeoforge.pilot_design import suggest_templates


def _identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _verify_selection(bindings, row, cancelled):
    """Hash the ranking's complete input cohort in a worker, without loading meshes."""
    expected = {record["path"]: record["sha256"] for record in bindings}
    if expected.get(row["path"]) != row["sha256"]:
        raise ValueError("Candidate changed; analyze the meshes again")
    signatures = []
    for name, digest in expected.items():
        if not digest:
            raise ValueError(
                "An unreadable input has no verified source. Inspect it and reanalyze."
            )
        path = Path(name)
        before = _identity(path)
        actual = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if cancelled.is_set():
                    raise InterruptedError("Template selection cancelled")
                actual.update(chunk)
        if actual.hexdigest() != digest or _identity(path) != before:
            raise ValueError(f"Input changed: {path.name}. Analyze the meshes again.")
        signatures.append((name, before))
    return row, signatures


class TemplateSuggestionPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self._owner = window
        self.result = None
        self._busy = False
        self.cancelled = Event()
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(lambda _key, error: self._failed(error))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        guidance = QLabel(TEMPLATE_SUMMARY)
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        row = QHBoxLayout()
        self.suggest = QPushButton("Analyze meshes & suggest template")
        self.suggest.setObjectName("secondary")
        self.suggest.setToolTip("Compare this mesh folder in the background; no fitting.")
        self.suggest.clicked.connect(self._suggest)
        row.addWidget(self.suggest)
        self.preview = QPushButton("Preview candidate")
        self.preview.setObjectName("secondary")
        self.preview.clicked.connect(self._preview)
        self.use = QPushButton("Use selected template")
        self.use.setObjectName("primary")
        self.use.clicked.connect(self._apply)
        row.addWidget(self.preview)
        row.addWidget(self.use)
        self.cancel = QPushButton("Cancel check")
        self.cancel.setObjectName("secondary")
        self.cancel.clicked.connect(self._cancel)
        self.cancel.hide()
        row.addWidget(self.cancel)
        row.addStretch()
        layout.addLayout(row)
        self.status = QLabel("Optional: recommend a representative starting form before alignment.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(InfoDisclosure("How to choose an initial template", TEMPLATE_GUIDE))
        self.alternatives = QComboBox()
        self.alternatives.setAccessibleName("Alternative initial templates")
        layout.addWidget(self.alternatives)
        self.alternatives.hide()
        details = QWidget(self)
        details_layout = QVBoxLayout(details)
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
        for name in ("mesh_edit", "template_edit", "pattern_edit", "project_edit"):
            edit = getattr(window, name, None)
            if edit is not None:
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
        self._busy = False
        self.alternatives.hide()
        self.use.hide()
        self.preview.hide()
        self.more.hide()
        self.suggest.setEnabled(True)
        self.use.setEnabled(False)
        self.preview.setEnabled(False)
        self.cancel.hide()
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
        self.invalidate()
        self.cancelled = Event()
        cancelled = self.cancelled
        cache = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "mesh-measurements"
        )
        self._set_busy(True)
        self.cancel.setText("Cancel analysis")
        self.status.setText(f"Comparing {len(paths)} surfaces in background; no fitting…")
        project_edit = getattr(self._owner, "project_edit", None)
        project = project_edit.text().strip() if project_edit else None
        self.loader.request_operation(
            paths,
            lambda: self._measure(paths, cache, cancelled, project),
        )

    def _set_busy(self, busy):
        self._busy = busy
        self.suggest.setEnabled(not busy)
        self.alternatives.setEnabled(not busy)
        self.use.setEnabled(not busy and self.result is not None)
        self.preview.setEnabled(not busy and self.result is not None)
        self.cancel.setVisible(busy)

    def _cancel(self):
        self.invalidate()
        self.status.setText("Check cancelled. Your selected template has not changed.")

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
        if not self._busy:
            self.status.setText(row["filename"] + ": " + (
                "Contrasting alternative to the central suggestion; inspect its features."
                if row.get("contrasting_alternative") else row["reason"]
            ))
            if self.result and self.result["uncertain"]:
                self.status.setText(self.status.text() + " Similar scores: inspect alternatives.")
            if self.result and self.result["unreadable_meshes"]:
                self.status.setText(self.status.text() +
                    f" {len(self.result['unreadable_meshes'])} meshes still need inspection; "
                    "they are not excluded from the atlas.")
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
        if paths and paths[0] == "apply":
            row, signatures = result
            selected = self.alternatives.currentData()
            try:
                if self.cancelled.is_set():
                    return
                if not selected or selected["path"] != row["path"]:
                    raise ValueError("Candidate selection changed; choose it again")
                if self._owner._worker is not None:
                    raise ValueError("Preparation started; the recommendation was not applied.")
                if {str(p) for p in self._paths()} != {name for name, _ in signatures}:
                    raise ValueError("Cohort changed; analyze the meshes again")
                if any(_identity(Path(name)) != identity for name, identity in signatures):
                    raise ValueError("Input changed during selection; analyze the meshes again")
            except (OSError, ValueError) as error:
                self._failed(str(error))
                return
            self._set_busy(False)
            self._owner.template_edit.setText(row["path"])
            self._owner._adopt_template_format_pattern(Path(row["path"]))
            self._owner._template_suggestion_accepted = dict(row)
            self.status.setText(
                "Starting template selected. Continue with alignment and pilot design."
            )
            return
        if paths and paths[0] == "preview":
            from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D

            self._set_busy(False)
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
            close.setObjectName("secondary")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            try:
                dialog.exec()
            finally:
                canvas.close()
                dialog.deleteLater()
            return
        try:
            current = self._paths()
        except (OSError, ValueError):
            return
        if paths != current or self.cancelled.is_set():
            return
        self.result = result
        self._set_busy(False)
        self.alternatives.blockSignals(True)
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
        self.alternatives.blockSignals(False)
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
        self.alternatives.show()
        self.more.show()
        self.suggest.setEnabled(True)

    def _apply(self):
        if self._busy or self._owner._worker is not None or self.result is None:
            return
        row = self.alternatives.currentData()
        try:
            if {str(p) for p in self._paths()} != {
                r["path"] for r in self.result["input_binding"]
            } | {r["path"] for r in self.result["unreadable_meshes"]}:
                raise ValueError("Cohort changed; request a new suggestion")
        except (OSError, ValueError) as error:
            self._failed(str(error))
            return
        bindings = tuple(self.result["input_binding"]) + tuple(
            self.result["unreadable_meshes"])
        self._set_busy(True)
        self.cancel.setText("Cancel check")
        self.status.setText("Checking the recommendation's input files in the background…")
        cancelled = self.cancelled
        self.loader.request_operation(
            ("apply", row["path"]),
            lambda: _verify_selection(bindings, dict(row), cancelled),
        )

    def _preview(self):
        if self._busy or self.result is None:
            return
        row = self.alternatives.currentData()
        self._set_busy(True)
        self.cancel.setText("Cancel preview")
        self.loader.request_paths(
            ("preview", row["path"]), (Path(row["path"]),), expected=(row["sha256"],)
        )

    def _failed(self, error):
        self.invalidate()
        self.status.setText("Template suggestion: " + error)
        self.suggest.setEnabled(True)

    def closeEvent(self, event):
        self.cancelled.set()
        self.loader.cancel()
        super().closeEvent(event)
