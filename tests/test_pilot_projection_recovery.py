"""Recovery of interrupted transfers from the normal pilot window, without a backend."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_runs import abandon_prepared_run, write_run_config

from diffeoforge import pilot_common_projection as transfer
from diffeoforge import pilot_projection_worker as worker
from diffeoforge import reference_calibration_study as study
from diffeoforge.desktop.common_projection_dialog import CommonProjectionDialog
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.runs import prepare_run, run_status


def test_reopen_after_hard_stop_reuses_guarded_recovery(tmp_path, monkeypatch):
    config = write_run_config(tmp_path)
    run = prepare_run(
        config, run_id="projection-synthetic", output_directory=tmp_path / "projection-runs"
    )
    abandon_prepared_run(run, checkpoint=b"saved transfer checkpoint")
    study._write_json(
        tmp_path / "last-projection-attempt.json", dict(name=run.name), overwrite=False
    )
    monkeypatch.setattr(
        transfer,
        "contract",
        lambda root: {
            "choice": dict(target="subject.vtk", approved_reference={}, basis_reference={}),
        },
    )
    assert transfer.status(tmp_path)["projection"] == "recovery"
    assert transfer.status(tmp_path)["previous_run"] == str(run)
    with pytest.raises(ValueError, match="confirm-process-stopped"):
        worker.recover_projection(tmp_path, run)
    with pytest.raises(ValueError, match="changed"):
        worker.recover_projection(tmp_path, tmp_path / "another-run", confirm_process_stopped=True)
    with worker.stage_lock(tmp_path, "projection"):
        assert transfer.status(tmp_path)["projection"] == "running"
        with pytest.raises(ValueError, match="already running"):
            worker.recover_projection(tmp_path, run, confirm_process_stopped=True)
    assert run_status(run)["status"] == "started" and not (run / "result.json").exists()
    result = worker.recover_projection(tmp_path, run, confirm_process_stopped=True)
    assert result["checkpoint"]["available"] and result["status"] == "interrupted"
    assert transfer.status(tmp_path)["projection"] == "interrupted"
    assert list(run.parent.iterdir()) == [run]

    # A retained result can predate its lifecycle event after a power loss.
    events = run / "events.jsonl"
    events.write_bytes(b"".join(events.read_bytes().splitlines(keepends=True)[:-1]))
    retained = (run / "result.json").read_bytes()
    assert transfer.status(tmp_path)["projection"] == "recovery"
    with pytest.raises(ValueError, match="no terminal result"):
        worker._native_run(tmp_path, None, {}, None)
    worker.recover_projection(tmp_path, run, confirm_process_stopped=True)
    assert (run / "result.json").read_bytes() == retained
    assert transfer.status(tmp_path)["projection"] == "interrupted"


def test_running_transfer_shows_native_iterations_then_check_and_return(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(transfer, "default_directory", lambda *_: tmp_path)
    monkeypatch.setattr(PreviewMeshLoader, "request_operation", lambda *_: None)
    dialog = CommonProjectionDialog(None, object(), {"target": "subject.vtk"})
    try:
        dialog._loaded("status", {"projection": "pending"})
        dialog.primary.click()
        assert dialog.operation == "projection" and dialog.primary.isHidden()
        assert dialog.cancel_run.isEnabled() and not dialog.progress_bar.isHidden()
        assert dialog.progress_bar.maximum() == 0
        dialog._progress({"worker_event": {"kind": "progress", "payload": {"iteration": 37}}})
        assert dialog.progress_bar.maximum() == transfer.BUDGET
        assert dialog.progress_bar.value() == 37
        dialog._progress({"event": "qualification_phase", "message": "Checking saved anatomy"})
        assert dialog.status.text() == "Checking saved anatomy"
        assert dialog.progress_bar.maximum() == 0
        dialog._loaded("projection", {})
        dialog._loaded("status", {"projection": "completed", "can_fit_original": False})
        assert dialog.progress_bar.isHidden() and dialog.primary.isHidden()
        assert dialog.next_action is None and dialog.close_button.text() == "Return to pilot"
        assert dialog.close_button.isEnabled() and dialog.cancel_run.isHidden()
    finally:
        dialog.close()
        app.processEvents()


def test_transfer_recovery_requires_confirmation_and_only_refreshes(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(transfer, "default_directory", lambda *_: tmp_path)
    operations = []
    monkeypatch.setattr(
        PreviewMeshLoader,
        "request_operation",
        lambda self, key, operation: operations.append((key, operation)),
    )
    calls = []
    monkeypatch.setattr(worker, "recover_projection", lambda *args, **kw: calls.append((args, kw)))
    run = tmp_path / "projection-runs" / "projection-synthetic"
    dialog = CommonProjectionDialog(None, object(), {"target": "subject.vtk"})
    try:
        dialog._loaded(
            "status", dict(projection="recovery", original="pending", previous_run=str(run))
        )
        assert dialog.next_action == "recover" and str(run) in dialog.status.text()
        assert not dialog.refresh_status.isHidden()
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
        dialog.primary.click()
        assert [key for key, _ in operations] == ["status"] and not calls
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
        dialog.primary.click()
        key, operation = operations[-1]
        assert key == "recover"
        dialog._loaded(key, operation())
        assert calls == [((tmp_path, run), {"confirm_process_stopped": True})]
        assert [key for key, _ in operations] == ["status", "recover", "status"]
        dialog._loaded("status", dict(projection="interrupted", original="pending"))
        assert dialog.next_action == "projection" and "Retry" in dialog.primary.text()
        dialog._loaded("status", dict(projection="verify_saved", original="pending"))
        assert dialog.next_action == "projection" and "Check saved" in dialog.primary.text()
    finally:
        dialog.close()
        app.processEvents()
