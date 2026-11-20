from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.desktop.remote_atlas_controller import (  # noqa: E402
    DesktopRemoteAtlasController,
    DesktopRemoteAtlasDeletionController,
    DesktopRemoteAtlasError,
    create_desktop_remote_atlas_session,
    verify_desktop_remote_atlas_session,
)
from diffeoforge.desktop.worker_protocol import (  # noqa: E402
    DesktopWorkerRequest,
    sha256_file,
)
from diffeoforge.remote_atlas_job import verify_remote_atlas_result  # noqa: E402
from diffeoforge.remote_atlas_server import (  # noqa: E402
    RemoteAtlasJobManager,
    create_remote_atlas_http_server,
)
from diffeoforge.remote_atlas_transport import (  # noqa: E402
    create_remote_token_file,
    load_remote_token,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _request(tmp_path: Path) -> DesktopWorkerRequest:
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    config["project"]["name"] = "desktop-remote-test"
    config["input"]["directory"] = str(MESH_DIRECTORY)
    config["input"]["template"] = str(MESH_DIRECTORY / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = str(tmp_path / "downloaded-result")
    config_path = tmp_path / "modern-atlas.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    return DesktopWorkerRequest(
        request_id="desktop-reviewed",
        config_path=config_path.resolve(),
        destination=(tmp_path / "downloaded-result").resolve(),
        expected_config_sha256=sha256_file(config_path),
        runtime_device=config["runtime"]["device"],
    )


def test_desktop_remote_session_packages_without_network_or_secret(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url="http://127.0.0.1:8787",
        submission_id="a" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )

    state = verify_desktop_remote_atlas_session(session)
    assert state["submission_id"] == "a" * 32
    assert state["remote"]["status"] == "prepared"
    assert state["request"]["subjects"] == 5
    assert state["request"]["result_destination"] == str(request.destination)
    serialized = (session / "session.json").read_text(encoding="utf-8")
    assert "token" not in serialized.lower()
    assert not request.destination.exists()


def test_desktop_remote_session_accepts_pre_deletion_field_state(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url="http://127.0.0.1:8787",
        submission_id="0" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )
    state_path = session / "session.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["remote"].pop("server_deleted_at")
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    verified = verify_desktop_remote_atlas_session(session)

    assert "server_deleted_at" not in verified["remote"]


def test_desktop_remote_controller_executes_reconnectable_download(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    token_file = create_remote_token_file(tmp_path / "server.token")
    token = load_remote_token(token_file)
    manager = RemoteAtlasJobManager(tmp_path / "server")
    server = create_remote_atlas_http_server(manager, token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url=f"http://{host}:{port}",
        submission_id="b" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )
    events: list[dict[str, object]] = []
    try:
        result = DesktopRemoteAtlasController(
            session,
            token_file=token_file,
            poll_seconds=0.1,
        ).run(event_callback=events.append)

        assert result.completed
        assert result.destination == request.destination
        assert result.remote_state is not None
        assert result.remote_state["status"] == "completed"
        assert any(event["kind"] == "modern_progress" for event in events)
        verify_remote_atlas_result(session / "request", request.destination)
        state = verify_desktop_remote_atlas_session(session)
        assert state["remote"]["status"] == "downloaded"
        assert state["remote"]["event_cursor"] >= 0
        assert manager.get_state("b" * 32)["status"] == "completed"

        deletion = DesktopRemoteAtlasDeletionController(
            session,
            token_file=token_file,
        ).run()
        assert deletion.submission_id == "b" * 32
        assert deletion.already_recorded is False
        deleted_state = verify_desktop_remote_atlas_session(session)
        assert deleted_state["remote"]["status"] == "downloaded"
        assert deleted_state["remote"]["server_deleted_at"] == deletion.deleted_at

        repeated = DesktopRemoteAtlasDeletionController(
            session,
            token_file=tmp_path / "no-longer-needed.token",
        ).run()
        assert repeated.already_recorded is True
        assert repeated.deleted_at == deletion.deleted_at
    finally:
        server.shutdown()
        server.server_close()
        manager.close(wait=True)
        thread.join(timeout=10)


def test_desktop_remote_controller_can_cancel_before_upload(tmp_path: Path) -> None:
    request = _request(tmp_path)
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url="http://127.0.0.1:8787",
        submission_id="c" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )
    controller = DesktopRemoteAtlasController(
        session,
        token_file=tmp_path / "not-needed.token",
        poll_seconds=0.1,
    )

    assert controller.request_cancel() is True
    assert controller.request_cancel() is False
    result = controller.run()

    assert result.cancelled
    state = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert state["remote"]["status"] == "cancelled_before_submit"
    assert not request.destination.exists()


def test_desktop_remote_controller_can_detach_without_network_or_cancel(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url="http://127.0.0.1:8787",
        submission_id="d" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )
    controller = DesktopRemoteAtlasController(
        session,
        token_file=tmp_path / "not-needed.token",
        poll_seconds=0.1,
    )

    assert controller.request_detach() is True
    assert controller.request_detach() is False
    result = controller.run()

    assert result.detached
    assert result.status == "prepared"
    assert result.cancelled is False
    assert verify_desktop_remote_atlas_session(session)["remote"]["status"] == "prepared"
    assert not request.destination.exists()


def test_desktop_remote_deletion_rejects_unsubmitted_session(tmp_path: Path) -> None:
    request = _request(tmp_path)
    session = create_desktop_remote_atlas_session(
        request,
        tmp_path / "remote-session",
        server_url="http://127.0.0.1:8787",
        submission_id="e" * 32,
        created_at="2026-08-26T12:00:00+00:00",
    )

    with pytest.raises(DesktopRemoteAtlasError, match="terminal submitted"):
        DesktopRemoteAtlasDeletionController(
            session,
            token_file=tmp_path / "not-needed.token",
        ).run()

    state = verify_desktop_remote_atlas_session(session)
    assert state["remote"]["status"] == "prepared"
    assert state["remote"]["server_deleted_at"] is None
