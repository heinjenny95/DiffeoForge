"""Native worker supervision and resumable evidence for an approved geometry transfer."""

from contextlib import contextmanager
from uuid import uuid4

from diffeoforge import reference_calibration_study as study
from diffeoforge.private_runs import _acquire_nonblocking_lock, _LeaseHeld, _release_lock


@contextmanager
def stage_lock(root, stage):
    path = root / (stage + ".lease")
    with path.open("a+b", buffering=0) as handle:
        if not handle.tell():
            handle.write(b"0")
        try:
            _acquire_nonblocking_lock(handle)
        except _LeaseHeld as exc:
            raise ValueError("This approved anatomy step is already running") from exc
        try:
            yield
        finally:
            _release_lock(handle)


def active(root, stage):
    path = root / (stage + ".lease")
    if not path.is_file():
        return False
    with path.open("r+b", buffering=0) as handle:
        try:
            _acquire_nonblocking_lock(handle)
        except _LeaseHeld:
            return True
        _release_lock(handle)
        return False


def previous_projection(root):
    """Bind recovery and retry to the same recorded attempt and terminal lifecycle event."""
    from diffeoforge.runs import run_status

    previous = root / "last-projection-attempt.json"
    if not previous.is_file():
        return None, None
    attempt = study._read_json(previous, "previous transfer attempt")
    path = study._safe_study_path(root, "projection-runs/" + attempt["name"])
    if path.parent != root.resolve() / "projection-runs" or path.name != attempt["name"]:
        raise ValueError("The previous transfer run is outside its recorded directory")
    if not path.exists():
        return path, "missing"
    if (path / "result.json").is_file():
        state = run_status(path)
        terminal = (state["result"] or {}).get("status")
        if terminal in {"completed", "failed", "interrupted"} and state["status"] == terminal:
            return path, terminal
    return path, "unfinalized"


def recover_projection(root, expected_run, *, confirm_process_stopped=False):
    from diffeoforge.runs import recover_run

    with stage_lock(root, "projection"):
        path, state = previous_projection(root)
        if path != expected_run or state != "unfinalized":
            raise ValueError("The transfer run changed. Refresh its status before recovery.")
        return recover_run(
            path,
            reason="Manual pilot transfer recovery after an unclean stop.",
            confirm_process_stopped=confirm_process_stopped,
        )


def _native_run(root, runner, contract, callback):
    from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest

    path, state = previous_projection(root)
    if state == "completed":
        return path  # An interrupted check does not incur another optimization.
    if state == "unfinalized" or (
        state == "missing" and not (root / "projection-last-error.json").is_file()
    ):
        raise ValueError(f"The previous transfer has no terminal result. Check recovery for {path}")
    launcher = contract["launcher"]
    run = root / "projection-runs" / ("projection-" + uuid4().hex[:12])
    study._write_json(root / "last-projection-attempt.json", dict(name=run.name), overwrite=True)
    request = DesktopReferenceLaunchRequest(
        request_id="transfer-" + uuid4().hex,
        config_path=root / "projection.yaml",
        destination=run,
        run_id=run.name,
        expected_config_sha256=contract["config_sha256"],
        launcher_engine=launcher.get("engine"),
        launcher_image=launcher.get("image"),
        launcher_type=launcher["type"],
        launcher_distribution=launcher.get("distribution"),
        launcher_executable=launcher.get("executable"),
    )
    controller = runner._factory(request)
    runner._controller = controller
    if runner._cancel.is_set():
        controller.request_cancel()

    def forward(event):
        if callback:
            callback(
                dict(
                    event="projection_progress",
                    message=str(event.payload.get("message", event.kind)),
                    worker_event=event.as_dict(),
                )
            )

    result = controller.run(event_callback=forward)
    if result.interrupted:
        raise InterruptedError("Native transfer cancelled")
    if not result.completed:
        raise ValueError("Native transfer failed: " + str(result.terminal_event.payload))
    return run
