"""Presentation isolation and actual interactive control regression checks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from diffeoforge.desktop.demo_fixture import demo_mesh, load_demo_fixture  # noqa: E402
from diffeoforge.desktop.demo_window import STATIONS, DemoWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application):
    view = DemoWindow()
    view.show()
    application.processEvents()
    yield view
    view.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_fixture_matches_public_sources_and_pca():
    from diffeoforge.analysis.pca import momenta_pca
    from diffeoforge.reference_pca import read_deformetrica_momenta

    fixture = load_demo_fixture()
    assert fixture["license"] == "CC0-1.0"
    for name, expected in fixture["sources"].items():
        assert not Path(name).is_absolute()
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    pca = momenta_pca(
        read_deformetrica_momenta(ROOT / "reference/synthetic-v1/artifacts/momenta.txt")
    )
    np.testing.assert_allclose(fixture["pca"]["scores"], pca.scores, rtol=1e-12, atol=1e-12)
    assert len(fixture["convergence"]) == 23
    assert fixture["convergence"][-1]["iteration"] == 22
    assert fixture["convergence"][-1]["log_likelihood"] == -0.4679
    assert len(fixture["residuals"]) == 5
    for subject in fixture["subjects"]:
        for kind in ("original", "aligned", "reconstruction"):
            mesh = demo_mesh(subject[kind], "test")
            assert mesh.point_count == 162 and mesh.triangle_count == 320
            assert np.isfinite(mesh.vertices).all()
    assert len(json.dumps(fixture)) < 250_000


def test_fixture_hash_and_size_fail_closed(tmp_path, monkeypatch):
    import diffeoforge.desktop.demo_fixture as module

    source = ROOT / "src/diffeoforge/desktop/demo_data"
    demo = tmp_path / "demo_data"
    demo.mkdir()
    expected = (source / "presentation.sha256").read_text()
    (demo / "presentation.sha256").write_text(expected)
    monkeypatch.setattr(module, "files", lambda _name: tmp_path)
    for payload in (b'{"altered":true}', b" " * 500_001):
        (demo / "presentation.json").write_bytes(payload)
        with pytest.raises(ValueError, match="size/hash"):
            module.load_demo_fixture()


def test_windows_bundle_declares_demo_data_and_shortcut():
    spec = (ROOT / "distribution/windows/DiffeoForge.spec").read_text()
    installer = (ROOT / "distribution/windows/DiffeoForge.iss").read_text()
    assert "datas=schema_data + demo_data" in spec
    assert 'Parameters: "--demo"' in installer
    for name in ("presentation.json", "presentation.sha256", "LICENSE.md", "SOFTWARE-LICENSE.txt"):
        assert (ROOT / "src/diffeoforge/desktop/demo_data" / name).is_file()


@pytest.mark.parametrize(
    "bad",
    [
        {"vertices": [[float("nan"), 0, 0]], "triangles": []},
        {"vertices": [[0, 0, 0]], "triangles": [[0, 1, 2]]},
    ],
)
def test_invalid_display_mesh_rejected(bad):
    with pytest.raises(ValueError):
        demo_mesh(bad, "invalid")


def test_all_stations_are_immediately_accessible(window, application):
    assert len(window.nav_buttons) == len(STATIONS) == 8
    assert "DEMO" in window.windowTitle()
    for index in (7, 5, 4, 3, 2, 6, 1, 0):
        assert window.nav_buttons[index].isEnabled()
        window.nav_buttons[index].click()
        application.processEvents()
        assert window.pages.currentIndex() == index
        assert sum(button.isChecked() for button in window.nav_buttons) == 1
    with pytest.raises(ValueError):
        window.show_station(8)


def test_replay_uses_recorded_samples_and_pauses_on_navigation(window):
    window.show_station(3)
    window.play_button.click()
    assert window.replay_timer.isActive()
    window._advance_replay()
    assert window.optimizer_plot.samples[-1].iteration == 1
    window.replay_slider.setValue(22)
    assert len(window.optimizer_plot.samples) == 23
    assert window.optimizer_plot.samples[-1].objective == -0.4679
    assert not window.replay_timer.isActive()
    window.play_button.click()
    assert window.replay_slider.value() == 0
    assert window.replay_timer.isActive()
    window.show_station(7)
    assert not window.replay_timer.isActive()
    window.replay_slider.setValue(5)
    assert [sample.iteration for sample in window.optimizer_plot.samples] == list(range(6))


def test_landmark_picking_uses_the_displayed_surface(window, application):
    window.show_station(1)
    window._clear_landmarks()
    deadline = time.monotonic() + 5
    while not window.landmark_canvas.picking_ready and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(20)
    assert window.landmark_canvas.picking_ready
    QTest.mouseClick(
        window.landmark_canvas,
        Qt.MouseButton.LeftButton,
        pos=window.landmark_canvas.rect().center(),
    )
    application.processEvents()
    assert list(window.landmarks[0]) == ["a"]
    assert np.isfinite(window.landmarks[0]["a"]).all()
    window.landmark_subject.setCurrentIndex(1)
    assert len(window.landmarks[1]) == 4
    window.landmark_subject.setCurrentIndex(0)
    assert len(window.landmarks[0]) == 1
    window._restore_landmarks()
    assert window.landmarks[0] == window.fixture["subjects"][0]["landmarks"]


def test_qc_scores_morph_and_reset_are_in_memory(window, application):
    fixture = deepcopy(window.fixture)
    window.qc_subject.setCurrentIndex(3)
    window._demo_decision("Needs review (demo)")
    assert window.decisions == {3: "Needs review (demo)"}
    window.show_original.setChecked(False)
    window.pca_subject.setCurrentIndex(2)
    window.morph_slider.setValue(0)
    np.testing.assert_allclose(
        window.pca_canvas.reconstruction_model.vertices, window.template.vertices
    )
    window.morph_slider.setValue(100)
    np.testing.assert_allclose(
        window.pca_canvas.reconstruction_model.vertices,
        window.models[2]["reconstruction"].vertices,
        atol=1e-15,
    )
    window.x_axis.setCurrentIndex(2)
    window.y_axis.setCurrentIndex(2)
    assert window.x_axis.currentIndex() != window.y_axis.currentIndex()
    window.group_checkbox.setChecked(True)
    window.parameter_fields[0].setValue(4)
    window._clear_landmarks()
    window._advance_pilot()
    window.replay_slider.setValue(22)
    window.reset_button.click()
    application.processEvents()
    assert window.fixture == fixture
    assert not window.decisions
    assert window.landmarks[0] == fixture["subjects"][0]["landmarks"]
    assert window.pca_subject.currentIndex() == 0
    assert window.show_original.isChecked() and window.show_reconstruction.isChecked()
    assert not window.group_checkbox.isChecked()
    assert window.parameter_fields[0].value() == 0.6
    assert window.replay_slider.value() == 0 and not window.replay_timer.isActive()
    assert window.pages.currentIndex() == 0


def test_camera_buttons_and_report_previews_work(window, application):
    for index in (0, 4):
        window.show_station(index)
        for button in window.pages.currentWidget().findChildren(QPushButton):
            if button.text() in ("Front", "Left", "Top", "Reset view"):
                button.click()
    window.show_station(7)
    for index in range(4):
        window.report_kind.setCurrentIndex(index)
        assert "DEMO" in window.report_browser.toPlainText()
    application.processEvents()


def test_demo_entry_does_not_import_production_or_launch_processes(tmp_path):
    # Fresh interpreter: imports are part of the boundary, not hidden by test caches.
    code = r"""
import os, subprocess, pathlib, sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
app = QApplication([])
def forbidden(*args, **kwargs):
    raise AssertionError("Demo attempted a persistent write/process/settings operation")
subprocess.Popen = forbidden
os.system = forbidden
pathlib.Path.write_text = forbidden
pathlib.Path.write_bytes = forbidden
pathlib.Path.mkdir = forbidden
QSettings.setValue = forbidden
from diffeoforge.desktop.demo_window import DemoWindow
w = DemoWindow()
w.show()
for i in range(8):
    w.show_station(i)
    app.processEvents()
w._demo_decision("Looks good (demo)")
w.reset_session()
w.close()
app.processEvents()
for name in ("diffeoforge.desktop.widgets", "diffeoforge.desktop.controller",
             "diffeoforge.reference_pca", "diffeoforge.analysis.pca"):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not list(tmp_path.iterdir())


def test_launcher_demo_smoke_from_arbitrary_directory(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "diffeoforge.desktop", "--demo", "--smoke"],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_real_window_entry_preserves_real_gates(application, monkeypatch):
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    monkeypatch.setattr(DiffeoForgeWindow, "_restore_recent_project_inputs", lambda self: None)
    real = DiffeoForgeWindow()
    before = [real._step_is_unlocked(index) for index in range(6)]
    real.open_demo_button.click()
    demo = real._demo_window
    demo.show_station(5)
    demo._demo_decision("Looks good (demo)")
    assert [real._step_is_unlocked(index) for index in range(6)] == before
    assert real._worker is None
    demo.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert real._demo_window is None
    real.close()
