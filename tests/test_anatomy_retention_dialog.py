from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from diffeoforge.anatomy_retention import (
    AnatomyRetentionReport,
    RetentionRow,
    RetentionStage,
    SurfaceEvidence,
)
from diffeoforge.desktop.anatomy_retention_dialog import AnatomyRetentionDialog
from diffeoforge.desktop.common_projection_dialog import CommonProjectionDialog
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader


def test_stage_trace_opens_first_lost_saved_area_and_clears_missing_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    pending = []
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, key, fn: pending.append((key, fn))
    )
    source = SurfaceEvidence(tmp_path / "original.vtk", "test")
    stages = tuple(
        RetentionStage(key, key, source if key != "atlas" else None, reason)
        for key, reason in (
            ("approved", ""),
            ("transfer", ""),
            ("common", ""),
            ("atlas", "No final atlas is available."),
        )
    )
    marks = (
        dict(center=[1, 1, 1], radius=1, purpose="fixed"),
        dict(center=[2, 2, 2], radius=1, purpose="problem"),
    )
    rows = (
        RetentionRow("transfer", 1, "original_to_fit_p99", (0.9, 1), (13.0, 14.0), "worse"),
        RetentionRow("transfer", None, "p99", (1.0, 1.1), (2.0, 2.1), "worse"),
        RetentionRow("common", 0, "original_to_fit_p99", (0.5, 0.6), (18.0, 19.0), "worse"),
    )
    report = AnatomyRetentionReport(
        "specimen.vtk", source, marks, stages, rows, "Area B regressed."
    )
    dialog = AnatomyRetentionDialog(None, report.target, lambda *, cancelled: report)
    try:
        dialog._loaded("report", pending.pop()[1]())
        assert dialog.stage.currentData() == "transfer" and dialog.area.currentData() == 1
        assert dialog.table.item(0, 3).text() == "Farther"
        dialog.stage.setCurrentIndex(dialog.stage.findData("atlas"))
        assert "No final atlas" in dialog.stage_note.text() and not dialog.models
        dialog._loaded("transfer", ("stale",))
        assert not dialog.models and dialog.table.rowCount() == 0
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize(
    "status,expected",
    [
        ({}, "prepare"),
        ({"projection": "pending", "original": "pending"}, "projection"),
        (
            {
                "projection": "completed",
                "original": "pending",
                "projection_retention": {"status": "regression", "summary": "Area C is farther."},
            },
            None,
        ),
        (
            {
                "projection": "completed",
                "original": "pending",
                "projection_retention": {"status": "comparable"},
                "can_fit_original": True,
            },
            "original",
        ),
        (
            {
                "projection": "completed",
                "original": "pending",
                "projection_retention": {"status": "comparable"},
            },
            None,
        ),
        (
            {
                "projection": "completed",
                "original": "completed",
                "approved": True,
                "original_retention": {"status": "unmeasured"},
            },
            None,
        ),
        (
            {
                "projection": "completed",
                "original": "completed",
                "approved": True,
                "original_retention": {"status": "comparable"},
                "original_numerical": {"passed": True},
                "can_attach": True,
            },
            "attach",
        ),
        (
            {
                "projection": "completed",
                "original": "completed",
                "approved": False,
                "original_retention": {"status": "comparable"},
                "original_numerical": {"passed": True},
            },
            None,
        ),
        (
            {
                "projection": "completed",
                "original": "completed",
                "original_retention": {"status": "comparable"},
                "original_numerical": {"passed": True},
            },
            "review",
        ),
    ],
)
def test_transfer_requires_explicit_steps_and_reliable_evidence(
    monkeypatch, tmp_path, status, expected
):
    from diffeoforge import pilot_common_projection as transfer

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    operations = []
    monkeypatch.setattr(transfer, "default_directory", lambda snap, choice: tmp_path / "transfer")
    monkeypatch.setattr(
        PreviewMeshLoader, "request_operation", lambda self, key, fn: operations.append(key)
    )
    notices = []
    monkeypatch.setattr("diffeoforge.desktop.common_projection_dialog.notify",
                        lambda _w, title, note: notices.append((title, note)))
    dialog = CommonProjectionDialog(None, object(), {"target": "subject.vtk"})
    try:
        dialog._loaded("status", status)
        assert notices == []  # Reopening saved status is not a new completion.
        dialog._loaded("projection", None)
        dialog._loaded("status", status)
        dialog._loaded("status", status)
        assert len(notices) == 1 and notices[0][0] == "Common-fit step finished"
        assert operations == ["status", "status"] and dialog.next_action == expected
        assert dialog.primary.isEnabled() is bool(expected)
        if expected is None:
            assert dialog.close_button.text() == "Return to pilot" and dialog.inspect.isEnabled()
            assert "next common fit" in dialog.status.text()
            if status.get("projection_retention", {}).get("status") == "regression":
                assert "Area C" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()


def test_transfer_primary_action_passes_the_exact_choice(tmp_path):
    from diffeoforge.desktop.pilot_common_model import pin_recovery

    app = QApplication.instance() or QApplication([])
    button = QPushButton()
    snapshot = SimpleNamespace(study_directory=Path(tmp_path), candidates=())
    window = SimpleNamespace(next_step_button=button, _guided_footer_action=None)
    choice = dict(
        mode="project_approved",
        available=True,
        label="Test transfer",
        reason="Approved shape differs",
        target="same.vtk",
    )
    try:
        pin_recovery(window, snapshot, choice)
        assert window._guided_footer_action == (tmp_path, "project_approved", choice)
        assert button.text() == choice["label"]
    finally:
        button.close()
        app.processEvents()
