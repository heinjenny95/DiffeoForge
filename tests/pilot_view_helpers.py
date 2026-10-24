"""Wait explicitly for the pilot's asynchronous evidence presentation."""

import time


def wait_pilot_view(dialog, timeout=20):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while dialog._view_loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    assert not dialog._view_loading, dialog.status.text()
    assert dialog._prepared_view is not None, dialog.status.text()
