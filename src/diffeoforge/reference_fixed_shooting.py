"""Endpoint-only reference Shooting of one immutable, ordered learned model.

The run-local adapter changes output scheduling and the explicit temporal grid,
never the installed runtime, learned fields or integration equations.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from diffeoforge.backends.deformetrica_reference import build_shooting_command
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.reference_pca_deformations import _render_shooting_model
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs

# Deformetrica 4.3's Shooting accepts number_of_time_points but constructs a
# Geodesic using concentration_of_time_points instead. Verify the effective grid.
ADAPTER = """import importlib, json, os, threading
def watch_parent():
    try:
        os.read(0, 1)
    finally:
        os._exit(130)
threading.Thread(target=watch_parent, daemon=True).start()
try:
    module = importlib.import_module("deformetrica.launch.compute_shooting")
    Base = module.Geodesic
    count = int(os.environ["DF_PILOT_TIMEPOINTS"])
    class EndpointGeodesic(Base):
        def __init__(self, *args, **kwargs):
            kwargs["concentration_of_time_points"] = count - 1
            super().__init__(*args, **kwargs)
        def write(self, root_name, objects_name, objects_extension, template,
                  template_data, output_dir, write_adjoint_parameters=False):
            times = self.get_times()
            if len(times) != count or times[0] != 0 or times[-1] != 1:
                raise RuntimeError("Fixed-model Shooting grid differs from declaration")
            if len(objects_name) != 1:
                raise RuntimeError("Pilot qualification requires one surface")
            data = template.get_deformed_data(self.get_template_points(1), template_data)
            names = [root_name + "__endpoint" + objects_extension[0]]
            template.write(output_dir, names,
                {key: value.detach().cpu().numpy() for key, value in data.items()})
            with open(os.path.join(output_dir, root_name + "__grid.json"), "w") as out:
                json.dump({"root": root_name, "timepoints": len(times),
                           "tmin": times[0], "tmax": times[-1]}, out)
    module.Geodesic = EndpointGeodesic
except BaseException:
    import traceback
    traceback.print_exc()
    os._exit(1)
"""


def movement(left: Path, right: Path, scale: float) -> dict[str, float]:
    """Corresponding-vertex movement; reject changed topology/order, not NN fit."""
    a, b = read_vtk_polydata(left), read_vtk_polydata(right)
    if a.triangles != b.triangles or len(a.vertices) != len(b.vertices):
        raise ValueError("Qualification endpoint topology/order changed")
    distances = np.linalg.norm(np.asarray(a.vertices) - np.asarray(b.vertices), axis=1)
    if not np.isfinite(distances).all() or not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid qualification geometry or scale")
    return dict(
        rms=float(np.sqrt(np.mean(distances**2))) / scale,
        p95=float(np.quantile(distances, 0.95)) / scale,
        maximum=float(distances.max()) / scale,
    )


def shoot(
    config,
    seed_root: Path,
    seed,
    destination: Path,
    count: int,
    *,
    cancelled=lambda: False,
    event_callback=None,
):
    if type(count) is not int or count < 2:
        raise ValueError("Shooting needs at least two timepoints")
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "source"
    engine = destination / "engine"
    source.mkdir()
    engine.mkdir()
    (destination / "output").mkdir()
    names = {
        "template": "estimated-template.vtk",
        "control_points": "control-points.txt",
        "momenta": "endpoint-momenta.txt",
    }
    for role, name in names.items():
        bound = seed["files"][role]
        path = seed_root / bound["copy"]
        if sha256_file(path) != bound["sha256"]:
            raise ValueError("Fixed Shooting source changed")
        shutil.copyfile(path, source / name)
    run = Path(seed["source_run_directory"])
    (engine / "model.xml").write_bytes(
        _render_shooting_model((run / "engine/model.xml").read_bytes())
    )
    shutil.copyfile(
        run / "engine/optimization_parameters.xml", engine / "optimization_parameters.xml"
    )
    (engine / "sitecustomize.py").write_text(ADAPTER, encoding="utf-8")
    artifacts = {
        str(p.relative_to(destination)): sha256_file(p)
        for p in destination.rglob("*")
        if p.is_file()
    }
    command = build_shooting_command(config, destination)
    argv = list(command.argv)
    env = {**os.environ, **command.environment}
    if argv[0].lower().endswith("wsl.exe"):
        from diffeoforge.backends.deformetrica_reference import _windows_to_wsl

        # env options (including GPU-related -u) must precede assignments.
        pos = argv.index(config["runtime"]["launcher"]["executable"])
        argv[pos:pos] = ["PYTHONPATH=" + _windows_to_wsl(engine), f"DF_PILOT_TIMEPOINTS={count}"]
    elif config["runtime"]["launcher"]["type"] == "native":
        env.update(PYTHONPATH=str(engine), DF_PILOT_TIMEPOINTS=str(count))
    else:
        raise ValueError("Fixed-model qualification currently supports native and WSL launchers")
    from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

    job = WindowsKillOnCloseJob() if os.name == "nt" else None
    started = time.monotonic()
    process = None
    try:
        with (
            (destination / "stdout.log").open("wb") as out,
            (destination / "stderr.log").open("wb") as err,
        ):
            process = subprocess.Popen(
                argv,
                cwd=command.working_directory,
                env=env,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                **hidden_windows_process_kwargs(),
            )
            if job:
                job.assign(process)
            while process.poll() is None:
                if cancelled():
                    process.stdin.close()  # Runtime watcher ends even a Linux process behind WSL.
                    process.wait(timeout=30)
                    raise InterruptedError(
                        "Fixed-model qualification cancelled; saved fits retained"
                    )
                if event_callback:
                    event_callback(
                        dict(
                            event="qualification_progress",
                            phase="fixed_shooting",
                            timepoints=count,
                            completed_subjects=len(
                                list((destination / "output").glob("*__grid.json"))
                            ),
                            total_subjects=len(seed["subject_labels"]),
                            elapsed_seconds=time.monotonic() - started,
                        )
                    )
                time.sleep(1)
            if process.returncode:
                raise ValueError(
                    f"Fixed-model Shooting failed ({process.returncode}); "
                    f"see {destination / 'stderr.log'}"
                )
    finally:
        if process and process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
        if job:
            job.close()
    for path, digest in artifacts.items():
        if sha256_file(destination / path) != digest:
            raise ValueError("Fixed Shooting input changed during computation")
    labels = seed["subject_labels"]
    result = {}
    for index, label in enumerate(labels):
        prefix = "Shooting" if len(labels) == 1 else f"Shooting_{index}"
        grid = json.loads((destination / "output" / (prefix + "__grid.json")).read_text())
        if grid != dict(root=prefix, timepoints=count, tmin=0, tmax=1):
            raise ValueError("Runtime grid receipt differs from declaration")
        endpoint = destination / "output" / (prefix + "__endpoint.vtk")
        read_vtk_polydata(endpoint)
        result[label] = endpoint
    expected = {p.name for p in result.values()}
    if {p.name for p in (destination / "output").glob("*.vtk")} != expected:
        raise ValueError("Unexpected or missing fixed-model endpoints")
    return result, artifacts
