"""Cancel only the supervised check child, including nested/thread-local callers."""
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from diffeoforge import mesh_filter_worker as worker


def test_cancel_during_native_check_is_prompt_and_reaps_only_its_child(monkeypatch):
    cancel = threading.Event()
    children = []
    popen = subprocess.Popen
    outside = popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    monkeypatch.setattr(worker, '_worker_command', lambda: [sys.executable, '-c',
        'import sys,time;sys.stdin.readline();time.sleep(30)'])

    def capture(*a, **kw):
        child = popen(*a, **kw)
        children.append(child)
        return child

    monkeypatch.setattr(worker.subprocess, 'Popen', capture)
    timer = threading.Timer(.4, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with worker.mesh_filter_cancellation(cancel.is_set):
            with pytest.raises(InterruptedError, match='saved fit retained'):
                worker.run_mesh_filter('distances', timeout=20, vertices=np.zeros((3, 3)))
        assert time.monotonic()-started < 3
        assert len(children) == 1 and children[0].poll() is not None
        assert outside.poll() is None
    finally:
        timer.cancel()
        outside.terminate()
        outside.wait(timeout=5)
    assert worker._CANCELLATION.get() is None


def test_pre_cancel_starts_no_process_and_nested_scope_restores_outer(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, '_worker_command', lambda: calls.append(True))
    def outer():
        return False
    with worker.mesh_filter_cancellation(outer):
        with worker.mesh_filter_cancellation(lambda: True):
            with pytest.raises(InterruptedError):
                worker.run_mesh_filter('intersections', vertices=np.zeros((3, 3)))
        assert worker._CANCELLATION.get() is outer
    assert not calls and worker._CANCELLATION.get() is None


def test_check_cancellation_does_not_leak_to_another_thread():
    observed = []
    with worker.mesh_filter_cancellation(lambda: True):
        other = threading.Thread(target=lambda: observed.append(worker._CANCELLATION.get()))
        other.start()
        other.join(timeout=5)
    assert observed == [None]
