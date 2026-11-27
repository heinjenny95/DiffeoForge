"""No numerical backend: truthful lifecycle when supervised shutdown is unknown."""

import hashlib
import json
import sys

import pytest
from test_runs import write_run_config

import diffeoforge.runs as runs
from diffeoforge.backends import CommandSpec


@pytest.mark.parametrize("acknowledge", [False, True])
def test_no_terminal_inventory_without_current_session_shutdown(tmp_path, monkeypatch, acknowledge):
    run = runs.prepare_run(write_run_config(tmp_path), run_id="supervised-process-only")
    script = run / "engine/backend_control.py"
    script.write_text(
        "from pathlib import Path\nimport hashlib,json,time\n"
        "root=Path.cwd()\n"
        "while not (root/'logs/backend-cancel.json').exists(): time.sleep(.01)\n"
        + (
            "token=(root/'logs/backend-control-token').read_text()\n"
            "(root/'logs/backend-control.json').write_text(json.dumps({"
            "'state':'stopped','session_empty':True,'command_received':True,"
            "'boot_id':'synthetic-process-only','identity':{'start_ticks':1},"
            "'token_sha256':hashlib.sha256(token.encode()).hexdigest()}))\n"
            if acknowledge
            else ""
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runs, "ensure_launcher_available", lambda _: None)
    monkeypatch.setattr(runs, "_probe_backend_environment", lambda _: {"probe_status": "verified"})
    monkeypatch.setattr(
        runs,
        "build_command",
        lambda _config, path: CommandSpec(
            argv=(sys.executable, "engine/backend_control.py"),
            working_directory=str(path),
            environment={},
        ),
    )
    if acknowledge:
        assert runs.execute_run(run, cancel_requested=lambda: True) == 130
        assert runs.run_status(run)["status"] == "interrupted"
    else:
        with pytest.raises(runs.BackendShutdownUnverified):
            runs.execute_run(run, cancel_requested=lambda: True)
        assert not (run / "result.json").exists()
        assert not (run / "output-inventory.json").exists()
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        assert events[-1]["event"] == "started"


def test_stale_or_incomplete_receipts_cannot_confirm_backend_shutdown(tmp_path):
    (tmp_path / "logs").mkdir()
    token = "a" * 64
    receipt = {
        "state": "stopped",
        "session_empty": True,
        "command_received": True,
        "boot_id": "synthetic",
        "identity": {"start_ticks": 1},
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }
    for key, invalid in (
        ("token_sha256", "b" * 64),
        ("session_empty", False),
        ("command_received", False),
        ("identity", None),
    ):
        (tmp_path / "logs/backend-control.json").write_text(json.dumps({**receipt, key: invalid}))
        with pytest.raises(runs.BackendShutdownUnverified):
            runs._control_receipt(tmp_path, token)
