"""Launch-bound interruption observer; qualified C5 mathematics stay unchanged."""

SOURCE = rb'''
import datetime as _df_oi_datetime
import hashlib as _df_oi_hashlib
import hmac as _df_oi_hmac
import json as _df_oi_json
import os as _df_oi_os
import stat as _df_oi_stat
from pathlib import Path as _df_oi_Path


def _df_owner_current_identity():
    p = _df_oi_Path('/proc/self')
    st = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    pid = _df_oi_os.getpid()
    return dict(boot_id=_df_oi_Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        identity=dict(pid=pid, parent=_df_oi_os.getppid(), start_ticks=int(st[19]),
            session=_df_oi_os.getsid(0), group=_df_oi_os.getpgrp(),
            argv=[v.decode() for v in (p / 'cmdline').read_bytes().split(b'\0') if v],
            cwd=str(_df_oi_Path.cwd().resolve())))


def _df_owner_read(path, limit=65536):
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Cancellation evidence is not run-local regular data')
    with path.open('rb') as f:
        if not _df_oi_stat.S_ISREG(_df_oi_os.fstat(f.fileno()).st_mode):
            raise ValueError('Cancellation evidence is not regular')
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized cancellation evidence')
    return raw


def _df_owner_cancel_evidence(context):
    try:
        root = context.root
        manifest = context.manifest
        mode = manifest['effective_config']['output'].get('process_control')
        if manifest['run_id'] != root.name or mode != 'linux_session_v1':
            return None
        logs = root / 'logs'
        if logs.resolve() != logs or logs.is_symlink():
            return None
        token = _df_owner_read(logs / 'backend-control-token', 128).decode('ascii').strip()
        if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
            return None
        command = _df_oi_json.loads(_df_owner_read(logs / 'backend-cancel.json'))
        control = _df_oi_json.loads(_df_owner_read(logs / 'backend-control.json'))
        digest = _df_oi_hashlib.sha256(token.encode()).hexdigest()
        if (command.get('operation') != 'cancel' or not isinstance(command.get('token'), str)
                or not _df_oi_hmac.compare_digest(command['token'], token)
                or control.get('state') not in ('running', 'cancelling')
                or control.get('token_sha256') != digest):
            return None
        actual = _df_owner_current_identity()
        identity = actual['identity']
        if (control.get('boot_id') != actual['boot_id'] or control.get('identity') != identity
                or identity['cwd'] != str(root)
                or identity['pid'] != identity['session'] or identity['pid'] != identity['group']):
            return None
        # The supervisor publishes 'cancelling' after sending SIGINT. The signed
        # command plus exact current identity also covers that publication race.
        context.verify_content()
        return dict(run_id=manifest['run_id'],
            source_config_sha256=manifest['source_config']['sha256'],
            boot_id=actual['boot_id'], native_identity=identity,
            token_sha256=control['token_sha256'])
    except Exception:
        return None


def _df_bind_owner_interruption(guard, context):
    original_fail, original_active = guard.fail, guard._active
    interrupted = [False]

    def active():
        if interrupted[0]:
            raise KeyboardInterrupt('Verified owner interruption is terminal')
        return original_active()

    def fail(reason, **details):
        error = details.get('error')
        is_interrupt = isinstance(error, str) and error.partition(':')[0] == 'KeyboardInterrupt'
        if interrupted[0] and is_interrupt:
            raise KeyboardInterrupt('Verified owner interruption is terminal')
        already_failed = guard.status == 'failed' or (guard.root / 'violation.json').exists()
        if is_interrupt and not already_failed:
            evidence = _df_owner_cancel_evidence(context)
            if evidence is not None:
                accepted = guard.accepted or {}
                payload = dict(version='verified-owner-interruption-v1',
                    interrupted_at=_df_oi_datetime.datetime.now(_df_oi_datetime.timezone.utc).isoformat(),
                    evidence=evidence, source_exception=error, observer_boundary=reason,
                    last_accepted_parameter_sha256=accepted.get('key'),
                    numerical_convergence=False, original_update_returned_normally=False,
                    automatic_restore=False, anatomical_approval=False,
                    accepted_checkpoint_requires_separate_verification=True)
                try:
                    with (guard.root / 'owner-interruption.json').open('x', encoding='utf-8') as f:
                        _df_oi_json.dump(payload, f, indent=2, allow_nan=False)
                        f.flush()
                        _df_oi_os.fsync(f.fileno())
                    guard._event('verified_owner_interruption', **payload)
                except Exception as e:
                    return original_fail('owner_interruption_receipt_failed',
                        error=type(e).__name__ + ': ' + str(e))
                interrupted[0] = True
                guard.status = 'interrupted'
                raise KeyboardInterrupt('Verified owner cancellation; accepted states unchanged')
        return original_fail(reason, **details)

    guard.fail, guard._active = fail, active
'''


def bind_runtime_owner_interruption(runtime: bytes) -> bytes:
    """Append a protected observer around C5 error reporting, never its f/g."""
    needle = b"        c5_write = self.write\n"
    if runtime.count(needle) != 1 or b"_df_bind_owner_interruption" in runtime:
        raise ValueError("Unexpected finite-guard runtime composition")
    return runtime.replace(
        needle, b"        _df_bind_owner_interruption(guard, context)\n" + needle
    ) + b"\n" + SOURCE
