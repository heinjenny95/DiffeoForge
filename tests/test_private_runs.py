from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from diffeoforge.cli import main
from diffeoforge.private_runs import (
    LEASE_NAME,
    MARKER_NAME,
    PrivateRunError,
    acquire_private_run_lease,
    discover_private_runs,
)


def _private_directory(destination: Path, token: str | None = None) -> Path:
    suffix = uuid.uuid4().hex if token is None else token
    private = destination.parent / f".{destination.name}.tmp-{suffix}"
    private.mkdir()
    return private


def test_discovery_transitions_real_lease_from_active_to_abandoned_without_rewrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "Atlas result Käfer"
    private = _private_directory(destination)
    lease = acquire_private_run_lease(
        private,
        destination,
        operation="modern_workflow",
    )
    marker_before = (private / MARKER_NAME).read_bytes()
    lease_size_before = (private / LEASE_NAME).stat().st_size

    active = discover_private_runs(destination)

    assert active.status == "attention_required"
    assert active.ready_for_new_run is False
    assert active.as_dict()["mutation_performed"] is False
    assert [candidate.status for candidate in active.candidates] == ["active"]
    assert active.candidates[0].marker is not None
    assert active.candidates[0].marker["pid"] == os.getpid()
    assert (private / MARKER_NAME).read_bytes() == marker_before
    assert (private / LEASE_NAME).stat().st_size == lease_size_before

    lease.close()
    abandoned = discover_private_runs(destination)

    assert [candidate.status for candidate in abandoned.candidates] == ["abandoned"]
    assert (private / MARKER_NAME).read_bytes() == marker_before
    assert (private / LEASE_NAME).stat().st_size == lease_size_before


def test_hard_process_exit_releases_private_run_lease(tmp_path: Path) -> None:
    destination = tmp_path / "hard-exit result"
    private = _private_directory(destination)
    code = "\n".join(
        (
            "import sys,time",
            "from diffeoforge.private_runs import acquire_private_run_lease",
            "lease=acquire_private_run_lease(sys.argv[1],sys.argv[2],operation='modern_workflow')",
            "time.sleep(300)",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(private), str(destination)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 10
        while not (private / MARKER_NAME).is_file() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        diagnostic = ""
        if process.poll() is not None and process.stderr is not None:
            diagnostic = process.stderr.read()
        assert (private / MARKER_NAME).is_file(), diagnostic
        active = discover_private_runs(destination)
        assert [candidate.status for candidate in active.candidates] == ["active"]
        process.terminate()
        process.wait(timeout=10)
        abandoned = discover_private_runs(destination)
        assert [candidate.status for candidate in abandoned.candidates] == ["abandoned"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_publication_removal_keeps_private_directory_unpublished_until_atomic_rename(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "run"
    private = _private_directory(destination)
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")

    lease.remove_for_publication()
    discovery = discover_private_runs(destination)

    assert lease.open is False
    assert not (private / MARKER_NAME).exists()
    assert not (private / LEASE_NAME).exists()
    assert [candidate.status for candidate in discovery.candidates] == ["unattributed"]

    private.rename(destination)
    published = discover_private_runs(destination)
    assert published.status == "destination_exists"
    assert published.candidates == ()


def test_discovery_classifies_unattributed_invalid_and_non_directory_candidates(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "run"
    unattributed = _private_directory(destination, "1" * 32)
    invalid = _private_directory(destination, "2" * 32)
    (invalid / MARKER_NAME).write_text("{not json", encoding="utf-8")
    matching_file = destination.parent / f".{destination.name}.tmp-{'3' * 32}"
    matching_file.write_text("not a directory", encoding="utf-8")
    (destination.parent / f".{destination.name}.tmp-not-a-uuid").mkdir()
    (destination.parent / f".other.tmp-{'4' * 32}").mkdir()

    discovery = discover_private_runs(destination)

    assert [candidate.path.name for candidate in discovery.candidates] == sorted(
        (unattributed.name, invalid.name, matching_file.name)
    )
    assert [candidate.status for candidate in discovery.candidates] == [
        "unattributed",
        "invalid_metadata",
        "invalid_metadata",
    ]


def test_discovery_never_follows_matching_symbolic_link(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    target = tmp_path / "unrelated"
    target.mkdir()
    candidate = destination.parent / f".{destination.name}.tmp-{'a' * 32}"
    try:
        candidate.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic-link creation is unavailable on this runner: {error}")

    discovery = discover_private_runs(destination)

    assert len(discovery.candidates) == 1
    assert discovery.candidates[0].status == "unsafe_link"
    assert target.is_dir()


def test_existing_destination_is_not_ready_but_is_not_a_private_candidate(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "published"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("published user evidence", encoding="utf-8")

    discovery = discover_private_runs(destination)

    assert discovery.status == "destination_exists"
    assert discovery.destination_exists is True
    assert discovery.ready_for_new_run is False
    assert discovery.candidates == ()
    assert sentinel.read_text(encoding="utf-8") == "published user evidence"


def test_lease_refuses_wrong_private_directory_contract(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    wrong = tmp_path / f".other.tmp-{'b' * 32}"
    wrong.mkdir()

    with pytest.raises(PrivateRunError, match="exact destination contract"):
        acquire_private_run_lease(wrong, destination, operation="modern_workflow")


def test_cli_private_status_has_distinct_clear_and_attention_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "run with spaces"

    assert main(["modern-private-status", str(destination), "--json"]) == 0
    clear_output = json.loads(capsys.readouterr().out)
    assert clear_output["status"] == "clear"
    assert clear_output["mutation_performed"] is False

    private = _private_directory(destination)
    lease = acquire_private_run_lease(private, destination, operation="modern_workflow")
    try:
        assert main(["modern-private-status", str(destination)]) == 1
        human = capsys.readouterr()
        assert "[active]" in human.out
        assert "No files were deleted, renamed, resumed, published, or rewritten." in human.out
        assert human.err == ""
    finally:
        lease.close()


def test_private_run_module_imports_without_optional_numerical_or_qt_modules(
    tmp_path: Path,
) -> None:
    code = (
        "import sys; import diffeoforge.private_runs; "
        "assert 'torch' not in sys.modules; assert 'PySide6' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
