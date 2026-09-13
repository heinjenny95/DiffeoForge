from __future__ import annotations

import threading
from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from diffeoforge.desktop import surface_rendering as rendering


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(["background-render-test"])
    yield application
    QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()


def scene(faces=1):
    vertices = np.array([[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [0.0, 1.0, 0.0]])
    triangles = np.tile(np.array([[0, 1, 2]]), (faces, 1))
    return rendering.SurfaceScene(
        200,
        200,
        np.zeros(3),
        2.0,
        np.eye(3),
        1.0,
        (0.0, 0.0),
        (rendering.SurfaceLayer(vertices, triangles),),
    )


def wait_until(app, predicate):
    for _ in range(500):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    pytest.fail("Background operation did not finish")


def test_settled_render_uses_every_face_navigation_alone_is_bounded(app, monkeypatch):
    calls = []
    original = rendering.QPainter

    class CountingPainter(original):
        def drawPolygon(self, polygon):
            calls.append(1)
            return super().drawPolygon(polygon)

    monkeypatch.setattr(rendering, "QPainter", CountingPainter)
    full = scene(rendering.NAVIGATION_FACES + 19)
    assert rendering.render_surface_scene(full, threading.Event()) is not None
    assert len(calls) == rendering.NAVIGATION_FACES + 19
    calls.clear()
    assert rendering.render_surface_scene(replace(full, navigation=True), threading.Event())
    assert len(calls) == rendering.NAVIGATION_FACES
    assert len(full.layers[0].indices) == rendering.NAVIGATION_FACES + 19


def test_identical_frame_is_cached_and_cancelled_scene_never_presents(app):
    cache = rendering.SurfaceFrameCache()
    first = scene()
    cache.request((1,), first)
    wait_until(app, lambda: cache.ready((1,)))
    for _ in range(20):
        assert cache.request((1,), first) is not None
    assert cache.render_count == 1
    cache.clear()
    assert not cache.ready((1,))
    cancelled = threading.Event()
    cancelled.set()
    assert rendering.render_surface_scene(first, cancelled) is None


def test_settled_wireframe_uses_every_edge(app, monkeypatch):
    counts = []
    original = rendering.QPainter

    class CountingPainter(original):
        def drawPath(self, path):
            counts.append(path.elementCount() // 2)
            return super().drawPath(path)

    monkeypatch.setattr(rendering, "QPainter", CountingPainter)
    base = scene()
    edges = np.tile(np.array([[0, 1]]), (rendering.NAVIGATION_EDGES + 21, 1))
    wire = replace(
        base, layers=(rendering.SurfaceLayer(base.layers[0].vertices, edges, wireframe=True),)
    )
    assert rendering.render_surface_scene(wire, threading.Event()) is not None
    assert sum(counts) == len(edges)
    counts.clear()
    assert rendering.render_surface_scene(replace(wire, navigation=True), threading.Event())
    assert sum(counts) == rendering.NAVIGATION_EDGES


def test_new_camera_request_cancels_old_job_and_keeps_only_latest(app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    real = rendering.render_surface_scene

    def slow(snapshot, cancelled):
        calls.append(snapshot.zoom)
        if len(calls) == 1:
            entered.set()
            release.wait(3)
        return real(snapshot, cancelled)

    monkeypatch.setattr(rendering, "render_surface_scene", slow)
    cache = rendering.SurfaceFrameCache()
    cache.request((1,), scene())
    wait_until(app, entered.is_set)
    try:
        for index in range(2, 30):
            cache.request((index,), replace(scene(), zoom=float(index)))
        assert cache._active.cancelled.is_set()
        assert cache._pending[0] == (29,)
        assert not cache.ready((1,))
    finally:
        release.set()
    wait_until(app, lambda: cache.ready((29,)))
    assert calls == [1.0, 29.0]
    assert not cache.ready((1,))


def test_failed_render_never_becomes_ready_and_does_not_retry_each_repaint(app, monkeypatch):
    def fail(*_args):
        raise ValueError("render failure")

    monkeypatch.setattr(rendering, "render_surface_scene", fail)
    cache = rendering.SurfaceFrameCache()
    cache.request((1,), scene())
    wait_until(app, lambda: bool(cache.error))
    assert cache.error == "render failure"
    assert not cache.ready((1,))
    for _ in range(10):
        cache.request((1,), scene())
    assert cache.render_count == 1
