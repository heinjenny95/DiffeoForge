from __future__ import annotations

import hashlib
import http.client
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge import remote_atlas_server as remote_server_module  # noqa: E402
from diffeoforge.cli import build_parser, main  # noqa: E402
from diffeoforge.modern_workflow import ModernWorkflowCancelled  # noqa: E402
from diffeoforge.remote_atlas_job import (  # noqa: E402
    create_remote_atlas_job,
    verify_remote_atlas_job,
    verify_remote_atlas_result,
)
from diffeoforge.remote_atlas_server import (  # noqa: E402
    RemoteAtlasJobManager,
    RemoteAtlasServerCapacity,
    RemoteAtlasServerConflict,
    RemoteAtlasServerError,
    create_remote_atlas_http_server,
)
from diffeoforge.remote_atlas_transport import (  # noqa: E402
    REQUEST_MEDIA_TYPE,
    RemoteAtlasClient,
    RemoteAtlasTransportError,
    create_remote_atlas_job_archive,
    create_remote_token_file,
    extract_remote_atlas_job_archive,
    load_remote_token,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _write_config(path: Path) -> Path:
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    config["project"]["name"] = "remote-server-test"
    config["input"]["directory"] = str(MESH_DIRECTORY)
    config["input"]["template"] = str(MESH_DIRECTORY / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = "unused-local-result"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _wait_for_terminal(client: RemoteAtlasClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = client.status(job_id)
        if state["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return state
        time.sleep(0.05)
    raise AssertionError("Remote atlas test job did not reach a terminal state")


def test_remote_archive_is_deterministic_safe_and_round_trips(tmp_path: Path) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    first = create_remote_atlas_job_archive(job, tmp_path / "first.zip")
    second = create_remote_atlas_job_archive(job, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    extracted = extract_remote_atlas_job_archive(first, tmp_path / "extracted")
    assert verify_remote_atlas_job(extracted) == verify_remote_atlas_job(job)
    with pytest.raises(RemoteAtlasTransportError, match="outside"):
        create_remote_atlas_job_archive(job, job / "nested.zip")


def test_remote_archive_rejects_parent_traversal_without_escape(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "x") as output:
        output.writestr("../escaped.txt", "unsafe")

    with pytest.raises(RemoteAtlasTransportError, match="Unsafe archive entry"):
        extract_remote_atlas_job_archive(archive, tmp_path / "request")

    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "request").exists()


@pytest.mark.parametrize(
    "entries",
    [
        {"folder/file:stream": "unsafe"},
        {"CON.txt": "unsafe"},
        {"inputs/Subject.vtk": "one", "inputs/subject.vtk": "two"},
    ],
)
def test_remote_archive_rejects_nonportable_names(
    tmp_path: Path,
    entries: dict[str, str],
) -> None:
    archive = tmp_path / "nonportable.zip"
    with zipfile.ZipFile(archive, "x") as output:
        for name, content in entries.items():
            output.writestr(name, content)

    with pytest.raises(RemoteAtlasTransportError, match="portable|colliding"):
        extract_remote_atlas_job_archive(archive, tmp_path / "request")

    assert not (tmp_path / "request").exists()


def test_remote_token_file_and_client_transport_policy(tmp_path: Path) -> None:
    token_file = create_remote_token_file(tmp_path / "secrets" / "server.token")
    token = load_remote_token(token_file)

    assert len(token) >= 32
    assert token not in token_file.name
    with pytest.raises(FileExistsError):
        create_remote_token_file(token_file)
    with pytest.raises(RemoteAtlasTransportError, match="Plain HTTP"):
        RemoteAtlasClient("http://example.org:8787", token)


def test_nonloopback_server_requires_tls(tmp_path: Path) -> None:
    manager = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    try:
        with pytest.raises(RemoteAtlasServerError, match="requires an explicit TLS"):
            create_remote_atlas_http_server(
                manager,
                "x" * 32,
                host="0.0.0.0",
                port=0,
            )
    finally:
        manager.close()


def test_remote_http_server_executes_and_returns_request_bound_result(
    tmp_path: Path,
) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    token = "test-token-" + "a" * 32
    manager = RemoteAtlasJobManager(tmp_path / "server")
    server = create_remote_atlas_http_server(manager, token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    client = RemoteAtlasClient(f"http://{host}:{port}", token)
    try:
        assert client.health()["status"] == "ready"
        with pytest.raises(RemoteAtlasTransportError, match="HTTP 401"):
            RemoteAtlasClient(f"http://{host}:{port}", "wrong-" + "b" * 32).status(
                "0" * 32
            )

        submission_id = "1" * 32
        accepted = client.submit(job, submission_id=submission_id)
        job_id = accepted["job_id"]
        assert job_id == submission_id
        assert accepted["status"] in {"queued", "running"}
        terminal = _wait_for_terminal(client, job_id)
        assert terminal["status"] == "completed", terminal
        first_page = client.events(job_id, limit=1)
        assert first_page["has_more"] is True
        assert first_page["next_after"] == 0
        second_page = client.events(job_id, after=first_page["next_after"], limit=1)
        assert second_page["events"][0]["index"] == 1
        events = client.events(job_id)
        assert events["events"][0]["status"] == "queued"
        assert events["events"][-1]["status"] == "completed"
        assert any(event["kind"] == "modern_progress" for event in events["events"])

        repeated = client.submit(job, submission_id=submission_id)
        assert repeated["job_id"] == job_id
        assert repeated["status"] == "completed"
        assert len(list(manager.jobs_root.iterdir())) == 1

        downloaded = client.download(job_id, job, tmp_path / "downloaded-result")
        verify_remote_atlas_result(job, downloaded)
        assert client.delete(job_id) == {"job_id": job_id, "status": "deleted"}
        with pytest.raises(RemoteAtlasTransportError, match="HTTP 404"):
            client.status(job_id)
    finally:
        server.shutdown()
        server.server_close()
        manager.close(wait=True)
        thread.join(timeout=10)


def test_remote_http_server_rejects_unsafe_archive_as_json(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "x") as output:
        output.writestr("../escaped.txt", "unsafe")
    payload = archive.read_bytes()
    token = "test-token-" + "a" * 32
    manager = RemoteAtlasJobManager(tmp_path / "server")
    server = create_remote_atlas_http_server(manager, token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(
            "POST",
            "/v1/jobs",
            body=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": REQUEST_MEDIA_TYPE,
                "Content-Length": str(len(payload)),
                "X-DiffeoForge-Archive-SHA256": hashlib.sha256(payload).hexdigest(),
                "X-DiffeoForge-Submission-ID": "2" * 32,
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 400
        assert "Unsafe archive entry" in body["error"]
        assert not (tmp_path / "escaped.txt").exists()
        assert not list(manager.jobs_root.iterdir())
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        manager.close(wait=True)
        thread.join(timeout=10)


def test_running_remote_job_can_be_cancelled_cooperatively(tmp_path: Path) -> None:
    started = threading.Event()

    def blocking_runner(
        request: Path,
        result: Path,
        *,
        progress_callback,
        cancel_requested,
    ) -> Path:
        del request, result, progress_callback
        started.set()
        while not cancel_requested():
            time.sleep(0.01)
        raise ModernWorkflowCancelled("cancelled by test")

    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    archive = create_remote_atlas_job_archive(job, tmp_path / "request.zip")
    manager = RemoteAtlasJobManager(tmp_path / "server", runner=blocking_runner)
    try:
        accepted = manager.submit_archive(
            archive,
            submission_id="3" * 32,
            archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )
        assert started.wait(timeout=10)
        requested = manager.cancel(accepted["job_id"])
        assert requested["status"] == "cancel_requested"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = manager.get_state(accepted["job_id"])
            if state["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert state["status"] == "cancelled"
        assert not (manager.jobs_root / accepted["job_id"] / "result").exists()
    finally:
        manager.close(wait=True)


def test_remote_cli_contract_includes_server_and_client_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    parsed = parser.parse_args(
        [
            "modern-remote-server",
            "--root",
            str(tmp_path / "server"),
            "--token-file",
            str(tmp_path / "token"),
        ]
    )
    assert parsed.command == "modern-remote-server"
    token = tmp_path / "created.token"
    assert main(["modern-remote-token-init", str(token)]) == 0
    secret = load_remote_token(token)
    assert secret
    assert secret not in capsys.readouterr().out


def test_server_state_is_persistent_for_queued_jobs(tmp_path: Path) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    archive = create_remote_atlas_job_archive(job, tmp_path / "request.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    first = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    accepted = first.submit_archive(
        archive,
        submission_id="4" * 32,
        archive_bytes=archive.stat().st_size,
        archive_sha256=digest,
    )
    first.close()

    observed = json.loads(
        (
            tmp_path / "server" / "jobs" / accepted["job_id"] / "state.json"
        ).read_text(encoding="utf-8")
    )
    assert observed["status"] == "queued"
    assert observed["request"]["archive_sha256"] == digest

    started = threading.Event()

    def recovered_runner(
        request: Path,
        result: Path,
        *,
        progress_callback,
        cancel_requested,
    ) -> Path:
        del request, result, progress_callback
        started.set()
        while not cancel_requested():
            time.sleep(0.01)
        raise ModernWorkflowCancelled("cancel recovered queued job")

    second = RemoteAtlasJobManager(tmp_path / "server", runner=recovered_runner)
    try:
        assert started.wait(timeout=10)
        assert second.get_state(accepted["job_id"])["status"] == "running"
        second.cancel(accepted["job_id"])
    finally:
        second.close(wait=True)
    assert second.get_state(accepted["job_id"])["status"] == "cancelled"


def test_submission_id_is_idempotent_and_request_bound(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    first_job = create_remote_atlas_job(
        config,
        tmp_path / "first-job",
        created_at="2026-08-26T12:00:00+00:00",
    )
    second_job = create_remote_atlas_job(
        config,
        tmp_path / "second-job",
        created_at="2026-08-26T12:00:01+00:00",
    )
    first_archive = create_remote_atlas_job_archive(first_job, tmp_path / "first.zip")
    second_archive = create_remote_atlas_job_archive(second_job, tmp_path / "second.zip")
    first_digest = hashlib.sha256(first_archive.read_bytes()).hexdigest()
    second_digest = hashlib.sha256(second_archive.read_bytes()).hexdigest()
    submission_id = "9" * 32
    manager = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    try:
        accepted = manager.submit_archive(
            first_archive,
            submission_id=submission_id,
            archive_bytes=first_archive.stat().st_size,
            archive_sha256=first_digest,
        )
        repeated = manager.submit_archive(
            first_archive,
            submission_id=submission_id,
            archive_bytes=first_archive.stat().st_size,
            archive_sha256=first_digest,
        )
        assert repeated == accepted
        assert accepted["job_id"] == submission_id
        with pytest.raises(RemoteAtlasServerConflict, match="different request"):
            manager.submit_archive(
                second_archive,
                submission_id=submission_id,
                archive_bytes=second_archive.stat().st_size,
                archive_sha256=second_digest,
            )
        assert len(list(manager.jobs_root.iterdir())) == 1
    finally:
        manager.close()


def test_parallel_submission_reserves_bounded_queue_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    archive = create_remote_atlas_job_archive(job, tmp_path / "request.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    entered = threading.Event()
    release = threading.Event()
    original_extract = remote_server_module.extract_remote_atlas_job_archive

    def delayed_extract(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(
        remote_server_module,
        "extract_remote_atlas_job_archive",
        delayed_extract,
    )
    manager = RemoteAtlasJobManager(
        tmp_path / "server",
        max_active_jobs=1,
        autostart=False,
    )
    accepted: list[dict[str, object]] = []

    def submit_first() -> None:
        accepted.append(
            manager.submit_archive(
                archive,
                submission_id="5" * 32,
                archive_bytes=archive.stat().st_size,
                archive_sha256=digest,
            )
        )

    thread = threading.Thread(target=submit_first)
    thread.start()
    try:
        assert entered.wait(timeout=10)
        with pytest.raises(RemoteAtlasServerCapacity, match="capacity"):
            manager.submit_archive(
                archive,
                submission_id="6" * 32,
                archive_bytes=archive.stat().st_size,
                archive_sha256=digest,
            )
        release.set()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert len(accepted) == 1
    finally:
        release.set()
        thread.join(timeout=10)
        manager.close()


def test_server_restart_discards_only_uncommitted_event_tail(tmp_path: Path) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    archive = create_remote_atlas_job_archive(job, tmp_path / "request.zip")
    first = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    accepted = first.submit_archive(
        archive,
        submission_id="7" * 32,
        archive_bytes=archive.stat().st_size,
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    events_path = first.jobs_root / accepted["job_id"] / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"index": 1, "incomplete": true')
    first.close()

    second = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    try:
        events = second.get_events(accepted["job_id"])
        assert len(events["events"]) == 1
        assert events["events"][0]["status"] == "queued"
        assert not events_path.read_bytes().endswith(b"incomplete\": true")
    finally:
        second.close()


def test_server_restart_marks_nonterminal_running_job_interrupted(tmp_path: Path) -> None:
    job = create_remote_atlas_job(_write_config(tmp_path / "modern.yaml"), tmp_path / "job")
    archive = create_remote_atlas_job_archive(job, tmp_path / "request.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    first = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    accepted = first.submit_archive(
        archive,
        submission_id="8" * 32,
        archive_bytes=archive.stat().st_size,
        archive_sha256=digest,
    )
    state_path = first.jobs_root / accepted["job_id"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "running"
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    first.close()

    second = RemoteAtlasJobManager(tmp_path / "server", autostart=False)
    try:
        recovered = second.get_state(accepted["job_id"])
        assert recovered["status"] == "interrupted"
        assert recovered["error"]["type"] == "ServerRestart"
        assert second.get_events(accepted["job_id"])["events"][-1]["status"] == (
            "interrupted"
        )
    finally:
        second.close()
