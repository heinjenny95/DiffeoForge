"""Process-only probes: no numerical backend, private inputs or GPU execution."""

import json
import os
import subprocess
import sys
import time

import pytest

from diffeoforge.reference_process_control import CONTROL_SOURCE


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
