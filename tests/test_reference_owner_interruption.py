"""Expected launch-bound SIGINT is distinct from a numerical violation."""

import ast
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from diffeoforge.reference_finite_accepted_guard import C5_SHA256
from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_SOURCE


class GuardFailure(Exception):
    pass


def fixture(tmp_path, monkeypatch):
    root = tmp_path / "attempt"
    logs = root / "logs"
    logs.mkdir(parents=True)
    output = root / "output/numerical-guard"
    output.mkdir(parents=True)
    identity = dict(pid=123, parent=122, start_ticks=345, session=123, group=123,
                    argv=["python", "native", "estimate"], cwd=str(root.resolve()))
    current_identity = deepcopy(identity)
    token = "a" * 64
    control = dict(state="running", identity=identity, boot_id="boot",
                   token_sha256=hashlib.sha256(token.encode()).hexdigest())
    (logs / "backend-control-token").write_text(token)
    (logs / "backend-cancel.json").write_text(json.dumps(dict(operation="cancel", token=token)))
    (logs / "backend-control.json").write_text(json.dumps(control))
    namespace = {}
    exec(compile(RUNTIME_SOURCE, "regional_guard_runtime.py", "exec"), namespace)
    monkeypatch.setitem(namespace, "_df_owner_current_identity", lambda: dict(
        boot_id="boot", identity=deepcopy(current_identity)))
    checks, failures, events = [], [], []
    context = SimpleNamespace(root=root.resolve(), manifest=dict(run_id=root.name,
        source_config=dict(sha256="f" * 64),
        effective_config=dict(output=dict(process_control="linux_session_v1"))),
        verify_content=lambda: checks.append("verified"))
    guard = SimpleNamespace(root=output, status="running", accepted=dict(key="accepted-hash"))

    def fail(reason, **details):
        failures.append((reason, details))
        guard.status = "failed"
        raise GuardFailure(reason)

    guard.fail = fail
    guard._active = lambda: "original active behavior"
    guard._event = lambda kind, **data: events.append((kind, data))
    namespace["_df_bind_owner_interruption"](guard, context)
    return guard, context, namespace, control, checks, failures, events


@pytest.mark.parametrize("boundary", ["native_evaluation_exception", "native_callback_exception",
                                     "native_update_exception", "verified_native_export_failed"])
@pytest.mark.parametrize("state", ["running", "cancelling"])
def test_matching_live_cancel_is_terminal_interruption_not_math_failure(
    tmp_path, monkeypatch, boundary, state
):
    guard, context, _, control, checks, failures, events = fixture(tmp_path, monkeypatch)
    control["state"] = state
    (context.root / "logs/backend-control.json").write_text(json.dumps(control))
    assert guard._active() == "original active behavior"
    with pytest.raises(KeyboardInterrupt, match="accepted states unchanged"):
        guard.fail(boundary, error="KeyboardInterrupt: ")
    row = json.loads((guard.root / "owner-interruption.json").read_text())
    assert row["evidence"]["source_config_sha256"] == context.manifest["source_config"]["sha256"]
    assert row["last_accepted_parameter_sha256"] == "accepted-hash"
    assert not row["numerical_convergence"] and not row["original_update_returned_normally"]
    assert "a" * 64 not in json.dumps(row) and row["automatic_restore"] is False
    assert checks == ["verified"] and not failures and guard.status == "interrupted"
    assert events[0][0] == "verified_owner_interruption"
    assert not (guard.root / "violation.json").exists()
    with pytest.raises(KeyboardInterrupt, match="terminal"):
        guard._active()
    with pytest.raises(KeyboardInterrupt, match="terminal"):
        guard.fail("native_update_exception", error="KeyboardInterrupt: outer unwind")
    assert len(events) == 1


@pytest.mark.parametrize("fault", ["missing_command", "wrong_token", "wrong_boot", "wrong_pid",
                                   "wrong_start", "wrong_argv", "terminal_receipt", "wrong_run",
                                   "wrong_mode", "wrong_parent", "wrong_session", "wrong_cwd",
                                   "wrong_token_hash", "changed_inputs"])
def test_unmatched_or_unverifiable_interrupt_stays_fail_closed(tmp_path, monkeypatch, fault):
    guard, context, _, control, _, failures, events = fixture(tmp_path, monkeypatch)
    logs = context.root / "logs"
    if fault == "missing_command":
        (logs / "backend-cancel.json").unlink()
    elif fault == "wrong_token":
        (logs / "backend-cancel.json").write_text(
            json.dumps(dict(operation="cancel", token="b" * 64)))
    elif fault == "wrong_boot":
        control["boot_id"] = "other"
    elif fault == "wrong_pid":
        control["identity"]["pid"] += 1
    elif fault == "wrong_start":
        control["identity"]["start_ticks"] += 1
    elif fault == "wrong_argv":
        control["identity"]["argv"] = ["other"]
    elif fault == "terminal_receipt":
        control["state"] = "stopped"
    elif fault == "wrong_run":
        context.manifest["run_id"] = "other"
    elif fault == "wrong_mode":
        context.manifest["effective_config"]["output"]["process_control"] = "none"
    elif fault == "wrong_parent":
        control["identity"]["parent"] += 1
    elif fault == "wrong_session":
        control["identity"]["session"] += 1
    elif fault == "wrong_cwd":
        control["identity"]["cwd"] += "/other"
    elif fault == "wrong_token_hash":
        control["token_sha256"] = "b" * 64
    else:
        context.verify_content = lambda: (_ for _ in ()).throw(ValueError("changed input"))
    (logs / "backend-control.json").write_text(json.dumps(control))
    with pytest.raises(GuardFailure):
        guard.fail("native_evaluation_exception", error="KeyboardInterrupt: ")
    assert failures and not events and not (guard.root / "owner-interruption.json").exists()


def test_true_errors_and_existing_violation_never_become_owner_success(tmp_path, monkeypatch):
    guard, _, _, _, _, failures, events = fixture(tmp_path, monkeypatch)
    with pytest.raises(GuardFailure):
        guard.fail("native_evaluation_exception", error="RuntimeError: CUDA failure")
    assert failures and not events
    with pytest.raises(GuardFailure):
        guard.fail("native_update_exception", error="KeyboardInterrupt: ")
    assert not (guard.root / "owner-interruption.json").exists()


def test_cannot_record_interruption_without_a_new_durable_receipt(tmp_path, monkeypatch):
    guard, _, _, _, _, failures, _ = fixture(tmp_path, monkeypatch)
    (guard.root / "owner-interruption.json").write_text("preserve old bytes")
    with pytest.raises(GuardFailure, match="receipt_failed"):
        guard.fail("native_evaluation_exception", error="KeyboardInterrupt: ")
    assert failures and (guard.root / "owner-interruption.json").read_text() == "preserve old bytes"


def test_core_c5_bytes_and_native_python38_contract_remain_unchanged():
    assert hashlib.sha256(C5_SOURCE).hexdigest() == C5_SHA256
    ast.parse(RUNTIME_SOURCE.decode(), feature_version=(3, 8))
    assert RUNTIME_SOURCE.count(b"_df_bind_owner_interruption(guard, context)\n") == 1
