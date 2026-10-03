"""Bounded event-loop waits and nonoverdrawn geometry for real-pixel tests."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer


def wait_for_frame(app, condition, canvas=None):
    # Native event-loop waiting releases the GIL for the Python render worker.
    # A tight qWait/repaint loop can instead starve it on some platforms.
    del app
    loop = QEventLoop()
    timer, timeout = QTimer(), QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)

    def poll():
        if canvas is not None:
            canvas.grab()
        if condition():
            loop.quit()

    if canvas is not None:
        canvas.grab()
    if condition():
        return
    timer.timeout.connect(poll)
    timer.start(20)
    timeout.start(10000)
    loop.exec()
    timer.stop()
    timeout.stop()
    assert condition()


def tessellated_triangle(base, subdivisions=91):
    # Exceed the proxy threshold with a real tiling, not thousands of identical
    # screen-filling faces (which made synchronization tests overdraw tests).
    points = [(i, j) for i in range(subdivisions + 1)
              for j in range(subdivisions + 1 - i)]
    lookup = {point: index for index, point in enumerate(points)}
    vertices = np.array([
        base[0] + (i * (base[1] - base[0]) + j * (base[2] - base[0])) / subdivisions
        for i, j in points
    ])
    faces = []
    for i in range(subdivisions):
        for j in range(subdivisions - i):
            faces.append((lookup[i, j], lookup[i + 1, j], lookup[i, j + 1]))
            if i + j < subdivisions - 1:
                faces.append((lookup[i + 1, j], lookup[i + 1, j + 1], lookup[i, j + 1]))
    triangles = np.array(faces)
    edges = np.unique(np.sort(np.concatenate((
        triangles[:, (0, 1)], triangles[:, (1, 2)], triangles[:, (2, 0)],
    )), axis=1), axis=0)
    return vertices, triangles, edges
