"""Process-only probes: no numerical backend, private inputs or GPU execution."""

import json
import os
import subprocess
import sys
import time

import pytest

from diffeoforge.reference_process_control import CONTROL_SOURCE, request_live_cancel


def live_attempt(root):
    import hashlib

    (root / "logs").mkdir()
    manifest = dict(run_id="owned", source_config=dict(sha256="f" * 64),
        effective_config=dict(output=dict(process_control="linux_session_v1")))
    raw = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(raw)
    (root / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest()+" manifest.json\n")
    token = "a" * 64
    (root / "logs/backend-control-token").write_text(token)
    receipt = dict(state="running", boot_id="synthetic-boot",
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        identity=dict(pid=123, parent=122, group=123, session=123,
                      start_ticks=456, cwd=str(root)))
    (root / "logs/backend-control.json").write_text(json.dumps(receipt))
    return receipt


def test_direct_cancel_is_bound_to_this_running_attempt_without_signalling(tmp_path):
    original = live_attempt(tmp_path)
    assert request_live_cancel(tmp_path, run_id="owned", config_sha256="f" * 64)
    command = json.loads((tmp_path / "logs/backend-cancel.json").read_text())
    assert command == dict(token="a" * 64, operation="cancel")
    assert json.loads((tmp_path / "logs/backend-control.json").read_text()) == original
    assert not list((tmp_path / "logs").glob(".backend-cancel-*.tmp"))


@pytest.mark.parametrize("change", ["config", "run", "manifest", "nonce", "cwd",
                                    "session", "completed", "missing"])
def test_direct_cancel_refuses_unbound_or_finished_attempts(tmp_path, change):
    receipt = live_attempt(tmp_path)
    run, config = "owned", "f" * 64
    if change == "config":
        config = "0" * 64
    if change == "run":
        run = "other"
    if change == "manifest":
        (tmp_path / "manifest.json").write_text("{}")
    if change == "nonce":
        receipt["token_sha256"] = "0" * 64
    if change == "cwd":
        receipt["identity"]["cwd"] = str(tmp_path.parent)
    if change == "session":
        receipt["identity"]["session"] += 1
    if change == "completed":
        receipt["state"] = "completed"
    if change == "missing":
        (tmp_path / "logs/backend-control-token").unlink()
    (tmp_path / "logs/backend-control.json").write_text(json.dumps(receipt))
    assert not request_live_cancel(tmp_path, run_id=run, config_sha256=config)
    assert not (tmp_path / "logs/backend-cancel.json").exists()


def test_control_source_is_standalone_and_native_math_is_not_imported():
    compile(CONTROL_SOURCE, "backend_control.py", "exec")
    assert "import numpy" not in CONTROL_SOURCE
    assert "from deformetrica" not in CONTROL_SOURCE


@pytest.mark.skipif(os.name != "posix", reason="Linux owned-session probe")
@pytest.mark.parametrize("wrong_token", [False, True])
def test_cancel_is_launch_bound_and_retains_checkpoint(tmp_path, wrong_token):
    (tmp_path / "logs").mkdir()
    token = "a" * 64
    (tmp_path / "logs/backend-control-token").write_text(token)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.write_bytes(b"last complete checkpoint")
    script = tmp_path / "control.py"
    script.write_text(CONTROL_SOURCE)
    outside = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(40)"])
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(script),
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(60)",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        receipt = tmp_path / "logs/backend-control.json"
        deadline = time.monotonic() + 5
        while not receipt.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert receipt.is_file()
        initial = json.loads(receipt.read_text())
        assert initial["identity"]["start_ticks"] > 0 and initial["boot_id"]
        (tmp_path / "logs/backend-cancel.json").write_text(
            json.dumps(
                {
                    "operation": "cancel",
                    "token": "b" * 64 if wrong_token else token,
                }
            )
        )
        process.communicate(timeout=25)
        assert process.returncode == (1 if wrong_token else 130)
        result = json.loads(receipt.read_text())
        if not wrong_token:
            assert result["state"] == "stopped" and result["command_received"] is True
            assert "SIGTERM" in result["signals"]
        else:
            assert result["state"] != "stopped"
        assert outside.poll() is None
        assert checkpoint.read_bytes() == b"last complete checkpoint"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        outside.terminate()
        outside.wait(timeout=5)
