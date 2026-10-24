"""Isolate native MeshLab filters from the desktop heap and Qt event loop."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


def _worker_command():
    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).with_name("DiffeoForgeWorker.exe")
        if not worker.is_file():
            raise RuntimeError("The installed mesh worker is missing; reinstall DiffeoForge")
        return [str(worker), "--mesh-filter-worker"]
    return [sys.executable, "-m", "diffeoforge.mesh_filter_worker"]


def run_mesh_filter(operation: str, *, timeout: float = 300, **arrays) -> dict:
    """Run one filter in a fresh hidden process; native faults become Python errors."""
    command = _worker_command()
    with tempfile.TemporaryDirectory(prefix="diffeoforge-mesh-filter-") as temporary:
        root = Path(temporary)
        source, output = root / "input.npz", root / "output.npz"
        np.savez(source, **arrays)
        job = process = None
        try:
            if os.name == "nt":
                from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

                job = WindowsKillOnCloseJob()
            with (root / "error.txt").open("w+", encoding="utf-8") as error:
                process = subprocess.Popen(
                    [*command, operation, str(source), str(output)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=error,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if job is not None:
                    job.assign(process)
                # The child waits before importing native plugins: supervision first.
                try:
                    process.communicate("start\n", timeout=timeout)
                except subprocess.TimeoutExpired as exception:
                    raise RuntimeError(
                        "Mesh preparation timed out; the saved pilot is retained"
                    ) from exception
                if process.returncode != 0 or not output.is_file():
                    error.seek(0)
                    detail = error.read()[-2000:].strip()
                    code = f"0x{process.returncode & 0xFFFFFFFF:08x}"
                    raise RuntimeError(
                        f"Mesh filter stopped ({code}); the saved pilot is retained. {detail}"
                    )
            with np.load(output, allow_pickle=False) as result:
                return {key: result[key].copy() for key in result.files}
        finally:
            if job is not None:
                job.close()
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            # A Windows venv launcher can have a still-closing interpreter child.
            # Kill-on-close covers the whole tree; wait for its file handle release.
            if os.name == "nt":
                for _ in range(100):
                    try:
                        (root / "error.txt").unlink(missing_ok=True)
                        break
                    except PermissionError:
                        time.sleep(0.05)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("decimate", "distances"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if sys.stdin.readline().strip() != "start":
        return 2
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    try:
        import faulthandler

        faulthandler.enable(file=sys.stderr)
        import pymeshlab as pm

        with np.load(args.source, allow_pickle=False) as data:
            vertices, faces = data["vertices"], data["faces"]
            ms = pm.MeshSet()
            ms.add_mesh(pm.Mesh(vertex_matrix=vertices, face_matrix=faces))
            if args.operation == "decimate":
                budget = int(data["budget"])
                if ms.current_mesh().face_number() > budget:
                    ms.apply_filter(
                        "meshing_decimation_quadric_edge_collapse",
                        targetfacenum=budget, preservetopology=True,
                        preservenormal=True, preserveboundary=True,
                    )
                mesh = ms.current_mesh()
                result = dict(vertices=mesh.vertex_matrix(), faces=mesh.face_matrix())
            else:
                points = data["points"]
                ms.add_mesh(pm.Mesh(vertex_matrix=points))
                combined = np.concatenate((points, vertices))
                limit = float(np.linalg.norm(np.ptp(combined, axis=0))) * 2 + 1e-12
                ms.apply_filter(
                    "compute_scalar_by_distance_from_another_mesh_per_vertex",
                    measuremesh=1, refmesh=0, signeddist=False,
                    maxdist=pm.PureValue(limit),
                )
                result = dict(distances=ms.mesh(1).vertex_scalar_array().copy())
            np.savez(args.output, **result)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
