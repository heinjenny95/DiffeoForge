"""Protected Linux process supervision; native numerical code is unchanged."""

# Python 3.8 compatible: runs under the WSL system interpreter without importing
# Deformetrica or sitecustomize. The child retains the original runtime/env/cwd.
CONTROL_SOURCE = r"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_child = None


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
    os.replace(str(temporary), str(path))


def identity(pid):
    root = Path('/proc') / str(pid)
    fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'parent': int(fields[1]), 'group': int(fields[2]),
            'session': int(fields[3]), 'start_ticks': int(fields[19]),
            'argv': (root / 'cmdline').read_bytes().split(b'\0')[:-1],
            'cwd': os.readlink(str(root / 'cwd'))}


def session_members(session):
    members = []
    for root in Path('/proc').iterdir():
        if not root.name.isdigit():
            continue
        try:
            fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[3]) == session and fields[0] != 'Z':
                members.append(int(root.name))
        except FileNotFoundError:
            pass
    return members


def main():
    global _child
    command = sys.argv[1:]
    if not command:
        raise RuntimeError('Missing supervised command')
    root = Path.cwd()
    request = root / 'logs/backend-cancel.json'
    receipt = root / 'logs/backend-control.json'
    token = (root / 'logs/backend-control-token').read_text().strip()
    if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise RuntimeError('Invalid launch-bound cancellation token')
    child = _child = subprocess.Popen(command, start_new_session=True)
    initial = identity(child.pid)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if (initial['parent'] != os.getpid() or initial['group'] != child.pid
            or initial['session'] != child.pid):
        child.kill()
        raise RuntimeError('Backend is not contained in its own session')
    public = dict(initial, argv=[v.decode('utf-8', 'replace') for v in initial['argv']])
    write(receipt, {'state': 'running', 'identity': public, 'boot_id': boot,
                    'token_sha256': hashlib.sha256(token.encode()).hexdigest()})
    cancelling = None
    signals_sent = []
    while child.poll() is None:
        if cancelling is None and request.is_file():
            value = json.loads(request.read_text())
            if value != {'token': token, 'operation': 'cancel'}:
                raise RuntimeError('Cancellation does not match this launch')
            current = identity(child.pid)
            # argv can legitimately change during exec, but parent/session/start,
            # cwd and boot bind the live child beyond its numerical PID.
            for key in ('pid', 'parent', 'group', 'session', 'start_ticks', 'cwd'):
                if current[key] != initial[key]:
                    raise RuntimeError('Backend identity changed before cancellation')
            if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
                raise RuntimeError('Boot identity changed')
            os.killpg(child.pid, signal.SIGINT)
            signals_sent.append('SIGINT')
            cancelling = time.monotonic()
            write(receipt, {'state': 'cancelling', 'identity': public,
                            'signals': signals_sent, 'command_received': True})
        if cancelling is not None:
            elapsed = time.monotonic() - cancelling
            if elapsed >= 10 and 'SIGTERM' not in signals_sent:
                os.killpg(child.pid, signal.SIGTERM)
                signals_sent.append('SIGTERM')
            if elapsed >= 15 and 'SIGKILL' not in signals_sent:
                os.killpg(child.pid, signal.SIGKILL)
                signals_sent.append('SIGKILL')
            if elapsed >= 20:
                raise RuntimeError('Backend shutdown could not be confirmed within 20 seconds')
        time.sleep(.1)
    code = child.wait()
    if cancelling is not None:
        # Stop any remaining members of this owned session before acknowledging.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5
        while session_members(child.pid):
            if time.monotonic() >= deadline:
                raise RuntimeError('Backend session still has active processes')
            time.sleep(.1)
        write(receipt, {'state': 'stopped', 'identity': public, 'signals': signals_sent,
                        'command_received': True, 'backend_return_code': code,
                        'boot_id': boot, 'session_empty': True,
                        'token_sha256': hashlib.sha256(token.encode()).hexdigest()})
        return 130
    if session_members(child.pid):
        raise RuntimeError('Backend left active processes after its parent exited')
    write(receipt, {'state': 'completed', 'identity': public, 'backend_return_code': code,
                    'boot_id': boot, 'session_empty': True,
                    'token_sha256': hashlib.sha256(token.encode()).hexdigest()})
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        if _child is not None:
            # A malformed control message or identity failure is terminal. It
            # must not leave the child running after supervision disappears.
            try:
                os.killpg(_child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if _child.poll() is None:
                _child.wait(timeout=5)
"""
