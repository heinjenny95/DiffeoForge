"""Atomic media exports with byte/decode checks, away from the GUI thread."""

from __future__ import annotations

import os
import shutil
import uuid
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage
from shiboken6 import isValid

from diffeoforge.desktop.activity import ActivityIndicator
from diffeoforge.mesh import sha256_file

_EXPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="method-media-export")


class MediaExportController(QObject):
    """Keep file I/O off Qt; one accepted export per controller at a time."""

    active_changed = Signal(bool)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.future = None
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self._activity = None
        owner = parent
        while owner is not None:
            self._activity = owner.findChild(ActivityIndicator)
            if self._activity is not None:
                break
            owner = owner.parentWidget()
        self._activity_key = ("media-export", id(self))
        if self._activity is not None:
            reference, key = weakref.ref(self._activity), self._activity_key

            def clear_activity():
                indicator = reference()
                if indicator is not None and isValid(indicator):
                    indicator.set_task(key, None)

            self.destroyed.connect(clear_activity)

    def start(self, target, **options):
        if self.future is not None:
            return False
        self.future = _EXPORTS.submit(export_media, target, **options)
        if self._activity is not None:
            self._activity.set_task(self._activity_key, "Saving media")
        self.active_changed.emit(True)
        self.timer.start()
        return True

    def _poll(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        if self._activity is not None:
            self._activity.set_task(self._activity_key, None)
        self.active_changed.emit(False)
        try:
            self.finished.emit(future.result())
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            self.failed.emit(str(error))


def export_media(target: Path, *, source=None, image=None, expected=None, protected=()):
    target = target.expanduser()
    if target.is_symlink():
        raise ValueError("Export destination must be a regular file")
    target = target.resolve()
    if any(target.is_relative_to(Path(root).resolve()) for root in protected):
        raise ValueError("Choose an export folder outside the saved result and media cache.")
    if target.is_symlink():
        raise ValueError("Export destination must be a regular file")
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        if source is not None:
            source = Path(source)
            if (
                expected is None
                or source.is_symlink()
                or source.stat().st_size != expected["bytes"]
                or sha256_file(source) != expected["sha256"]
            ):
                raise ValueError("Prepared media changed since verification")
            if target.suffix.lower() in {".jpg", ".jpeg"} and source.suffix.lower() == ".png":
                converted = QImage(str(source))
                if converted.isNull() or not converted.save(str(stage), "JPEG", 95):
                    raise ValueError("Saved image could not be converted to JPEG")
                if QImage(str(stage)).size() != converted.size():
                    raise ValueError("Exported JPEG failed its dimension check")
                if sha256_file(source) != expected["sha256"]:
                    raise ValueError("Prepared image changed during conversion")
            else:
                if target.suffix.lower() != source.suffix.lower():
                    raise ValueError(f"Choose {source.suffix.upper()} for the selected medium")
                shutil.copyfile(source, stage)
                if sha256_file(stage) != expected["sha256"]:
                    raise ValueError("Exported media differs from the prepared file")
        else:
            kind = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(target.suffix.lower())
            if image is None or image.isNull() or kind is None:
                raise ValueError("Choose PNG or JPEG for an image export")
            if not image.save(str(stage), kind, 95):
                raise ValueError("Image encoder could not save the export")
            decoded = QImage(str(stage))
            if decoded.isNull() or decoded.size() != image.size():
                raise ValueError("Exported image failed its decode/dimension check")
        os.replace(stage, target)
        return target
    finally:
        stage.unlink(missing_ok=True)
