"""Explicitly recover a finished native fit after losing the pilot worker."""

from contextlib import contextmanager
from pathlib import Path
from platform import node
from uuid import uuid4

from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_projection_worker import active, stage_lock
from diffeoforge.reference_qualification_resume import binding

# Old DiffeoForge versions exclude other method runners using this directory.
LOCK = "method-comparison-active.lock"
LEASE = "method-comparison-worker-v1"
BUSY = ("This pilot still has an execution lock. Check the original Pilot window, "
        "then refresh the saved pilot to see the latest attempt.")


def _release_marker(root, owner):
    lock = root / LOCK
    if (set(lock.iterdir()) != {lock / "owner.json"}
            or study._read_json(lock / "owner.json", "pilot writer") != owner):
        raise ValueError("The stored pilot writer changed")
    # Remove this exact directory atomically from the well-known name. An old
    # application may acquire that name immediately, even before our cleanup.
    retired = root / (".released-pilot-lock-" + owner["token"])
    lock.rename(retired)
    (retired / "owner.json").unlink()
    retired.rmdir()


@contextmanager
def writer(root):
    lock = root / LOCK
    if lock.exists() or (root / (LEASE + ".lease")).is_symlink():
        raise study.ReferenceCalibrationStudyError(BUSY)
    with stage_lock(root, LEASE, busy_message=BUSY):
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise study.ReferenceCalibrationStudyError(BUSY) from error
        try:
            lease = (root / (LEASE + ".lease")).stat()
            owner = dict(version=1, token=uuid4().hex, host=node(),
                         lease_identity=[lease.st_dev, lease.st_ino],
                         manifest=sha256_file(root / study.STUDY_MANIFEST),
                         journal_head=study._load_events(root)[-1]["event_hash"])
            study._write_json(lock / "owner.json", owner, overwrite=False)
        except Exception:
            if not any(lock.iterdir()):
                lock.rmdir()
            raise
        try:
            yield
        except BaseException:
            # The controller or its notification pipe can exit before journaling
            # the end of a native attempt. Its fit may still be running.
            latest = _attempts(root, owner)
            if not latest or latest[-1]["event"] != "candidate_started":
                _release_marker(root, owner)
            raise
        else:
            _release_marker(root, owner)


def _attempts(root, owner):
    events = study._load_events(root)
    boundary = next((i for i, e in enumerate(events) if e["event_hash"] == owner["journal_head"]),
                    None)
    if boundary is None:
        raise ValueError("Pilot writer does not match the saved journal")
    return [e for e in events[boundary + 1:] if e["event"] in {
        "candidate_started", "candidate_completed", "candidate_failed", "candidate_interrupted"
    }]


def _evidence(snapshot, owner):
    from diffeoforge.pilot_adaptive_run import marker as adaptive
    from diffeoforge.pilot_multiscale_study import marker as multiscale

    root = snapshot.study_directory
    if adaptive(snapshot.attachment_comparison) or multiscale(snapshot.attachment_comparison):
        raise ValueError("This attempt also requires recovery of its multistage controller")
    lease_path = root / (LEASE + ".lease")
    lease = lease_path.stat()
    if (lease_path.is_symlink() or not lease.st_ino or owner.get("host") != node()
            or owner.get("lease_identity") != [lease.st_dev, lease.st_ino]
            or owner.get("version") != 1 or not isinstance(owner.get("token"), str)
            or len(owner["token"]) != 32 or any(c not in "0123456789abcdef" for c in owner["token"])
            or owner.get("manifest") != sha256_file(root / study.STUDY_MANIFEST)):
        raise ValueError("Pilot writer identity changed")
    attempts = _attempts(root, owner)
    latest = attempts[-1] if attempts else {}
    reconciled = latest.get("recovered_writer") == owner["token"]
    if reconciled:
        if latest.get("event") != "candidate_interrupted" or len(attempts) < 2:
            raise ValueError("Recovered attempt changed")
        start = attempts[-2]
    else:
        start = latest
    if (start.get("event") != "candidate_started" or not snapshot.current_stage
            or start["stage_id"] != snapshot.current_stage.stage_id):
        raise ValueError("No unfinished start belongs to this pilot writer")
    candidate = next(c for c in snapshot.candidates if c.candidate_id == start["candidate_id"])
    run = candidate.run_directory
    if (candidate.status != ("interrupted" if reconciled else "orphaned")
            or any(c.status == "orphaned" and c != candidate for c in snapshot.candidates)
            or candidate.attempts != start["attempt"] or not run
            or run != study._safe_study_path(root, start["run_directory"])):
        raise ValueError("Saved attempt or run directory changed")
    native = binding(run, candidate.config_path)
    expected = start.get("completed_native_fit")
    if ((expected is not None and expected != native)
            or (reconciled and (latest.get("recovered_start") != start["event_hash"]
                                or latest.get("completed_native_fit") != native))):
        raise ValueError("Saved native fit changed")
    return dict(candidate=candidate.candidate_id, start=start["event_hash"],
                writer=owner["token"], native=native), start, reconciled


def inspect(snapshot):
    """Read-only readiness. A missing legacy owner or live writer cannot qualify."""
    root = snapshot.study_directory
    lock = root / LOCK
    if not lock.is_dir():
        return None
    owner_path = lock / "owner.json"
    try:
        if (lock.is_symlink() or not owner_path.is_file() or owner_path.is_symlink()
                or not (root / (LEASE + ".lease")).is_file() or active(root, LEASE)):
            return None
        owner = study._read_json(owner_path, "pilot writer")
        return _evidence(snapshot, owner)[0]
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None


def recover(directory, expected):
    root = Path(directory).resolve()
    lease = root / (LEASE + ".lease")
    if not isinstance(expected, dict) or lease.is_symlink() or not lease.is_file():
        raise ValueError("No verified completed fit is ready to recover")
    with stage_lock(root, LEASE, busy_message=BUSY):
        snapshot = study.load_reference_calibration_study(root)
        lock = root / LOCK
        if not lock.exists():
            # Retrying a delivered action after its reply was lost is harmless.
            event = next((e for e in reversed(study._load_events(root))
                          if e.get("candidate_id") == expected.get("candidate")
                          and e["event"] in {"candidate_started", "candidate_completed",
                                             "candidate_failed", "candidate_interrupted"}), {})
            if (event.get("event") == "candidate_interrupted"
                    and event.get("recovered_writer") == expected["writer"]
                    and event.get("recovered_start") == expected["start"]
                    and event.get("completed_native_fit") == expected["native"]):
                candidate = next((c for c in snapshot.candidates
                                  if c.candidate_id == expected["candidate"]), None)
                if (candidate and candidate.status == "interrupted" and candidate.run_directory
                        and binding(candidate.run_directory, candidate.config_path)
                        == expected["native"]):
                    return snapshot
            raise ValueError("Pilot recovery already changed; refresh the saved pilot")
        owner_path = lock / "owner.json"
        if lock.is_symlink() or owner_path.is_symlink() or not owner_path.is_file():
            raise ValueError("The existing execution lock has no verified pilot writer")
        owner = study._read_json(owner_path, "pilot writer")
        actual, start, reconciled = _evidence(snapshot, owner)
        if actual != expected:
            raise ValueError("The selected completed fit changed; refresh the saved pilot")
        if not reconciled:
            study._append_event(root, "candidate_interrupted", dict(
                stage_id=start["stage_id"], candidate_id=actual["candidate"],
                attempt=start["attempt"],
                run_directory=start["run_directory"], phase="qualification",
                completed_native_fit=actual["native"], recovered_start=actual["start"],
                recovered_writer=actual["writer"], error="Native fit recovered for surface checks.",
            ))
        _release_marker(root, owner)
        return study.load_reference_calibration_study(root)


def check_offer(snapshot, verified):
    """Choose just the recovered method even when other candidate fits are pending."""
    if not verified:
        return None
    from diffeoforge.reference_qualification_resume import _latest

    latest = _latest(snapshot)
    for identifier, native in verified.items():
        event = latest.get(identifier, {})
        if event.get("recovered_writer") and event.get("completed_native_fit") == native:
            return dict(candidate=identifier, event=event["event_hash"], native=native)
    return None


def resume_checks(runner, identifier, expected, event_callback=None):
    from diffeoforge.reference_qualification_resume import pending

    with writer(runner.study_directory):
        snapshot = study.load_reference_calibration_study(runner.study_directory)
        actual = check_offer(snapshot, pending(snapshot))
        if not actual or actual != expected or actual["candidate"] != identifier:
            raise ValueError("The recovered fit changed; refresh the saved pilot")
        # Run the existing immutable qualification pipeline for this candidate
        # under the writer lease. No method batch or follow-on capture is dispatched.
        runner._method_comparison_dispatch = True
        runner._recovered_checks_only = True
        try:
            return runner.run_current_stage(event_callback=event_callback,
                                            candidate_ids={identifier})
        finally:
            runner._method_comparison_dispatch = False
            runner._recovered_checks_only = False
