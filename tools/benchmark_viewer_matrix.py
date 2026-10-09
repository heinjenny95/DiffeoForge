"""Opt-in synthetic, offscreen native-event-loop viewer observation (no atlas).

Exercises the production landmark/result/PC, calibration/registration-QC and GPA
canvases, not complete result-bundle opening or an installed executable. Timings
are observations, not FPS guarantees. Each size/family runs in a fresh process.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

SIZES = {10_000: (100, 50), 100_000: (250, 200), 200_000: (400, 250)}
FAMILIES = ("landmark-result-pc", "calibration-registration-qc", "gpa")


def synthetic_surface(segments: int, rings: int, variant: int = 0) -> tuple:
    """Closed ellipsoid with a local bump; exactly 2 * segments * rings faces."""
    if segments < 3 or rings < 2:
        raise ValueError("Need at least three segments and two rings")
    theta, phi = np.meshgrid(
        np.arange(1, rings + 1) * np.pi / (rings + 1),
        np.arange(segments) * 2 * np.pi / segments, indexing="ij",
    )
    vertices = np.column_stack((
        (np.sin(theta) * np.cos(phi)).ravel(),
        (np.sin(theta) * np.sin(phi)).ravel(), np.cos(theta).ravel(),
    ))
    vertices = np.vstack(([0., 0., 1.], vertices, [0., 0., -1.]))
    bump = np.exp(-12 * ((vertices[:, 0] - .7) ** 2 + vertices[:, 2] ** 2))
    vertices[:, 0] *= 1.4 + .12 * bump + .04 * variant
    vertices[:, 1] *= .7
    j = np.arange(segments)
    top = np.column_stack((np.zeros(segments, dtype=int), 1 + j, 1 + (j + 1) % segments))
    a = (1 + np.arange(rings - 1)[:, None] * segments + j).ravel()
    b = (1 + np.arange(rings - 1)[:, None] * segments + (j + 1) % segments).ravel()
    side = np.vstack((np.column_stack((a, a + segments, b)),
                      np.column_stack((b, a + segments, b + segments))))
    bottom = np.column_stack((np.full(segments, len(vertices) - 1),
                              1 + (rings - 1) * segments + (j + 1) % segments,
                              1 + (rings - 1) * segments + j))
    return vertices, np.vstack((top, side, bottom))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_plan(output: Path) -> dict:
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    if plan["script_sha256"] != digest(Path(__file__)):
        raise ValueError("Benchmark script changed after planning; prepare a new matrix")
    source_root = Path(__file__).resolve().parents[1] / "src/diffeoforge/desktop"
    for name, expected in plan["viewer_module_sha256"].items():
        if Path(name).name != name or digest(source_root / name) != expected:
            raise ValueError("Viewer implementation changed after planning")
    return plan


def prepare(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    sources = {}
    for faces, (segments, rings) in SIZES.items():
        folder = output / str(faces) / "meshes"
        folder.mkdir(parents=True)
        landmarks = []
        for index, name in enumerate(("template.vtk", "subject-01.vtk", "subject-02.vtk")):
            vertices, triangles = synthetic_surface(segments, rings, index)
            path = folder / name
            with path.open("w", encoding="ascii", newline="\n") as handle:
                handle.write("# vtk DataFile Version 3.0\nSynthetic viewer-only fixture\n")
                handle.write(f"ASCII\nDATASET POLYDATA\nPOINTS {len(vertices)} double\n")
                np.savetxt(handle, vertices, fmt="%.17g")
                handle.write(f"POLYGONS {len(triangles)} {4 * len(triangles)}\n")
                np.savetxt(handle, np.column_stack((np.full(len(triangles), 3), triangles)),
                           fmt="%d")
            sources[str(path.relative_to(output))] = digest(path)
            indices = (0, 1 + (rings // 2) * segments, 1 + (rings // 2) * segments + segments // 4)
            for label, point in zip(("top", "front", "side"), indices, strict=True):
                landmarks.append((name, label, *vertices[point]))
        csv_path = folder.parent / "landmarks.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("mesh_file", "landmark", "x", "y", "z"))
            writer.writerows(landmarks)
        sources[str(csv_path.relative_to(output))] = digest(csv_path)
    source_root = Path(__file__).resolve().parents[1]
    modules = ["gpa_visualization_widget.py", "gpa_visualization.py", "landmark_3d_widget.py",
               "calibration_comparison_widget.py", "surface_rendering.py", "mesh_preview.py",
               "preview_mesh_loader.py", "display_proxy.py"]
    plan = {
        "schema_version": "0.1", "sizes": list(SIZES), "families": list(FAMILIES),
        "viewport": [900, 650], "source_hashes": sources,
        "script_sha256": digest(Path(__file__)), "python": sys.version,
        "viewer_module_sha256": {
            name: digest(source_root / "src/diffeoforge/desktop" / name) for name in modules
        },
        "platform": platform.platform(), "camera_samples": 5, "reopen_cycles": 3,
        "scope": "synthetic canvas/preview-loader engineering only; no atlas or result approval",
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def observe(output: Path, faces: int, family: str) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import psutil
    from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete

    from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
    from diffeoforge.desktop.gpa_visualization import build_gpa_alignment_visual
    from diffeoforge.desktop.gpa_visualization_widget import GpaAlignmentCanvas3D
    from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
    from diffeoforge.preprocessing import preview_landmark_alignment

    app = QApplication.instance() or QApplication(["synthetic-viewer-observation"])
    app.setQuitOnLastWindowClosed(False)
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Arial", 10))
    proc, stop = psutil.Process(), threading.Event()
    rss = [proc.memory_info().rss]

    def sample_memory():
        while not stop.wait(.02):
            rss.append(proc.memory_info().rss)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    phases = []

    def measure(name, action, ready=lambda: True):
        loop, pulse, deadline = QEventLoop(), QTimer(), QTimer()
        ticks, error = [time.perf_counter()], []
        start = ticks[0]
        deadline.setSingleShot(True)

        def poll():
            ticks.append(time.perf_counter())
            try:
                if ready():
                    loop.quit()
            except Exception as exc:
                error.append(exc)
                loop.quit()

        pulse.timeout.connect(poll)
        deadline.timeout.connect(loop.quit)
        pulse.start(10)
        deadline.start(60_000)
        try:
            action()
            loop.exec()
            if error:
                raise error[0]
            if not ready():
                raise TimeoutError(f"{name}: did not complete within 60 seconds")
            phases.append({"phase": name, "seconds": time.perf_counter() - start,
                           "gui_timer_count": len(ticks) - 1,
                           "max_gui_timer_gap_seconds": max(np.diff(ticks), default=0.),
                           "sampled_rss_bytes": proc.memory_info().rss})
        finally:
            pulse.stop()
            deadline.stop()

    loader, loaded, failures = PreviewMeshLoader(), [], []
    loader.loaded.connect(lambda _key, value: loaded.append(value))
    loader.failed.connect(lambda _key, error: failures.append(error))
    folder = output / str(faces)
    paths = (folder / "meshes/template.vtk", folder / "meshes/subject-01.vtk")
    plan = verify_plan(output)
    before = {str(p.relative_to(output)): digest(p) for p in
              (*sorted((folder / "meshes").glob("*.vtk")), folder / "landmarks.csv")}
    if any(plan["source_hashes"][key] != value for key, value in before.items()):
        raise ValueError("Synthetic inputs drifted after planning")
    try:
        if family == "gpa":
            def operation():
                preview = preview_landmark_alignment(paths[0].parent,
                                                     landmarks_file=folder / "landmarks.csv")
                return build_gpa_alignment_visual(preview)
            def request():
                loader.request_operation("gpa", operation)
        else:
            def request():
                loader.request_paths("pair", paths)
        measure("cold_background_load", request, lambda: bool(loaded or failures))
        if failures:
            raise RuntimeError(failures[0])
        models = loaded.pop()

        def create():
            if family == "gpa":
                widget = GpaAlignmentCanvas3D()
                widget.set_visual(models)
                widget.set_selected_proxy(0)
                widget.set_show_selected_surface(True)
            elif family == "calibration-registration-qc":
                widget = CalibrationComparisonCanvas3D()
                widget.set_models(*models)
            else:
                widget = InteractiveMeshCanvas3D()
                widget.set_picking_enabled(False)
                widget.set_model(models[0])
            widget.resize(900, 650)
            widget.show()
            return widget

        holder = []

        def frame_ready():
            if not holder:
                return False
            widget = holder[0]
            cache = widget._frames
            if cache.error:
                raise RuntimeError(cache.error)
            return cache._wanted is not None and cache.ready(cache._wanted)

        measure("install_and_first_frame", lambda: holder.append(create()), frame_ready)
        canvas = holder[0]
        canvas.grab().save(str(folder / f"{family}.png"))
        if family != "gpa":
            assert not canvas.full_resolution_ready, "Proxy cannot authorize original-detail QC"
        for index in range(5):
            def camera(index=index):
                canvas._interacting = True
                canvas._yaw += .21 + .01 * index
                canvas.repaint()
            measure(f"navigation_{index}", camera, frame_ready)
        measure("settled_after_navigation",
                lambda: (setattr(canvas, "_interacting", False), canvas.repaint()), frame_ready)

        def switch():
            if family == "gpa":
                canvas.set_selected_proxy(1)
                canvas.set_show_cohort(False)
            elif family == "calibration-registration-qc":
                canvas.set_models(models[1], models[0])
            else:
                canvas.set_model(models[1])
            canvas.repaint()
        measure("switch_loaded_specimen", switch, frame_ready)
        proxy_faces = ([len(m.triangles) for m in models.meshes] if family == "gpa"
                       else [len(m.display_proxy.triangles) for m in models])
        assert max(proxy_faces) <= 8_000
        original_detail_verified = None
        if family != "gpa":
            measure("explicit_original_detail",
                    lambda: (canvas.original_detail.setChecked(True), canvas.repaint()),
                    lambda: frame_ready() and canvas.full_resolution_ready)
            original_detail_verified = True
            if family == "calibration-registration-qc":
                canvas.set_show_original(False)
                assert not canvas.full_resolution_ready
                canvas.set_show_original(True)
            measure("back_to_proxy",
                    lambda: (canvas.original_detail.setChecked(False), canvas.repaint()),
                    frame_ready)
            assert not canvas.full_resolution_ready
        for cycle in range(3):
            canvas.close()
            delete(canvas)
            holder.clear()
            measure(f"reopen_{cycle}", lambda: holder.append(create()), frame_ready)
            canvas = holder[0]
        # Destruction while a new render is outstanding, without waiting for it.
        canvas._yaw += .7
        canvas.repaint()
        active_at_destroy = canvas._frames._active is not None
        assert active_at_destroy
        canvas.close()
        delete(canvas)
        holder.clear()
        measure("drain_after_active_owner_destruction", lambda: None,
                lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
        assert {key: digest(output / key) for key in before} == before
        return {"faces_per_mesh": faces, "family": family, "phases": phases,
                "display_faces": proxy_faces, "source_unchanged": True,
                "proxy_cannot_approve_original_detail": family != "gpa",
                "explicit_original_detail_verified": original_detail_verified,
                "active_render_at_owner_destruction": active_at_destroy,
                "baseline_rss_bytes": rss[0], "sampled_peak_rss_bytes": max(rss),
                "rss_after_close_bytes": proc.memory_info().rss,
                "scope": "fresh offscreen process; production canvases, not whole installed app"}
    finally:
        stop.set()
        sampler.join(1)
        QThreadPool.globalInstance().waitForDone(60_000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-existing", action="store_true")
    parser.add_argument("--faces", type=int, choices=SIZES)
    parser.add_argument("--family", choices=FAMILIES)
    args = parser.parse_args()
    if args.family:
        if args.faces is None:
            parser.error("--family requires --faces")
        path = args.output / str(args.faces) / f"{args.family}.json"
        if path.exists() or path.with_suffix(".png").exists():
            raise FileExistsError("Observation already exists; use a fresh output directory")
        report = observe(args.output, args.faces, args.family)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(json.dumps(report), flush=True)
        return
    if not args.run_existing:
        prepare(args.output)
    if args.prepare_only:
        print(f"Prepared synthetic matrix in {args.output}")
        return
    verify_plan(args.output)
    for faces in SIZES:
        for family in FAMILIES:
            subprocess.run([sys.executable, __file__, "--output", str(args.output),
                            "--faces", str(faces), "--family", family], check=True)


if __name__ == "__main__":
    main()
