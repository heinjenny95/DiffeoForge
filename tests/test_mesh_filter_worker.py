"""Native-plugin lifetime faults must not terminate the host Qt application."""

import subprocess
import sys

import numpy as np
import pytest

from diffeoforge import mesh_filter_worker as worker


def test_repeated_native_filters_from_qt_workers_keep_gui_alive():
    from concurrent.futures import ThreadPoolExecutor

    from PySide6.QtWidgets import QApplication, QLabel

    from diffeoforge.reference_fit_search import distances_to_surface

    app = QApplication.instance() or QApplication([])
    label = QLabel("Before native filters")
    label.show()
    for _ in range(3):
        # Separate worker lifetimes model rejection followed by a new attempt.
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                distances_to_surface, [[2, 2, 0], [2, 2, 1]],
                [[0, 0, 0], [10, 0, 0], [0, 10, 0]], [[0, 1, 2]],
            ).result(timeout=30)
        np.testing.assert_allclose(result, [0, 1], atol=1e-6)
        app.processEvents()
        label.setText("Still responsive")
    assert label.text() == "Still responsive"
    assert "pymeshlab" not in sys.modules
    label.close()


@pytest.mark.parametrize("fail", ["exit", "timeout"])
def test_child_failure_is_visible_and_child_reaped(monkeypatch, fail):
    code = (
        "import sys,os;sys.stdin.readline();os._exit(7)"
        if fail == "exit"
        else "import sys,time;sys.stdin.readline();time.sleep(30)"
    )
    monkeypatch.setattr(worker, "_worker_command", lambda: [sys.executable, "-c", code])
    actual_popen = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        result = actual_popen(*args, **kwargs)
        children.append(result)
        return result

    monkeypatch.setattr(worker.subprocess, "Popen", capture)
    with pytest.raises(RuntimeError, match="stopped|timed out"):
        worker.run_mesh_filter("distances", timeout=0.1 if fail == "timeout" else 10,
                               vertices=np.zeros((3, 3)))
    assert children[0].poll() is not None


def test_native_decimation_returns_valid_closed_geometry():
    # Public synthetic octahedron, no private geometry or engine run.
    vertices = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                         [0, -1, 0], [0, 0, 1], [0, 0, -1]], float)
    faces = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
                      [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]], np.int32)
    result = worker.run_mesh_filter("decimate", vertices=vertices, faces=faces,
                                    budget=np.array(6))
    assert 0 < len(result["faces"]) <= len(faces)
    assert result["vertices"].shape[1] == result["faces"].shape[1] == 3
    assert np.isfinite(result["vertices"]).all()
    assert result["faces"].min() >= 0
    assert result["faces"].max() < len(result["vertices"])


def test_frozen_dispatch_does_not_construct_the_application(monkeypatch):
    import runpy
    from pathlib import Path

    calls = []
    monkeypatch.setattr(worker, "main", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(sys, "argv", ["DiffeoForgeWorker", "--mesh-filter-worker",
                                     "distances", "input.npz", "output.npz"])
    entry = Path(__file__).parents[1] / "distribution/windows/diffeoforge_worker.py"
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(entry), run_name="__main__")
    assert result.value.code == 0
    assert calls == [["distances", "input.npz", "output.npz"]]


def test_frozen_helper_uses_console_worker_hidden_by_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DiffeoForge.exe"))
    (tmp_path / "DiffeoForgeWorker.exe").write_bytes(b"synthetic fixture")
    assert worker._worker_command() == [str(tmp_path / "DiffeoForgeWorker.exe"),
                                        "--mesh-filter-worker"]
