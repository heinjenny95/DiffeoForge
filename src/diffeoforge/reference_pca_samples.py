"""Native PC-path display samples on corresponding original template vertices.

The control points, momenta, precision, kernel and time grid are retained. Only
the displayed template vertex subset changes. Full native anchors qualify this
display approximation before any movie is published; it is never QC geometry.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from diffeoforge.analysis.pca_media_rendering import faces, points, read_mesh
from diffeoforge.backends.deformetrica_reference import build_shooting_command
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.reference_pca_deformations import (
    _number_of_time_points,
    _verify_grid,
    _write_momenta,
)
from diffeoforge.reference_shooting_grid import SITECUSTOMIZE
from diffeoforge.runs import _backend_process_working_directory
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs


def native_axis_samples(
    root: Path,
    *,
    endpoint_root: Path,
    pca,
    config,
    template_proxy,
    components,
    anchors,
    scale,
    progress=lambda _text: None,
    process_runner=subprocess.run,
):
    """Execute a protected display-only batch; verify every native grid/anchor."""
    root.mkdir()
    for name in ("source", "engine", "output", "logs"):
        (root / name).mkdir()
    source = root / "source/estimated-template.vtk"
    write_vtk_polydata(source, points(template_proxy), faces(template_proxy))
    shutil.copyfile(endpoint_root / "source/control-points.txt", root / "source/control-points.txt")
    shutil.copyfile(endpoint_root / "engine/model.xml", root / "engine/model.xml")
    shutil.copyfile(
        endpoint_root / "engine/optimization_parameters.xml",
        root / "engine/optimization_parameters.xml",
    )
    (root / "engine/sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    controls = int(pca.mean.size // 3)
    deviations = np.linspace(-2, 2, 17)
    fields = np.stack(
        [
            (
                pca.mean + sd * np.sqrt(pca.explained_variance[pc - 1]) * pca.components[pc - 1]
            ).reshape(controls, 3)
            for pc in components
            for sd in deviations
        ]
    )
    _write_momenta(root / "source/endpoint-momenta.txt", fields)
    protected = {
        str(path.relative_to(root)): sha256_file(path)
        for name in ("source", "engine")
        for path in (root / name).rglob("*")
        if path.is_file()
    }
    command = build_shooting_command(config, root, verified_grid=True)
    environment = os.environ.copy()
    environment.update(command.environment)
    progress(f"Shooting {len(fields)} native PC-path display samples")
    result = process_runner(
        command.argv,
        cwd=_backend_process_working_directory(config, command.working_directory),
        env=environment,
        capture_output=True,
        text=True,
        timeout=7_200,
        check=False,
        **hidden_windows_process_kwargs(),
    )
    for name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
        (root / f"logs/shooting.{name}.log").write_text(str(text or ""), encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"PC display Shooting returned {result.returncode}: "
            f"{str(result.stderr or result.stdout)[-1000:]}"
        )
    dtype = np.dtype(config["runtime"]["precision"])
    count = _number_of_time_points(root / "engine/model.xml")
    topology = faces(read_mesh(source))
    values = []
    grids = []
    for index, field in enumerate(fields):
        path = root / f"output/Shooting_{index}__grid.json"
        grid = json.loads(path.read_text())
        _verify_grid(grid, count, field.astype(dtype))
        grids.append(grid)
        mesh = read_mesh(root / f"output/Shooting_{index}__endpoint.vtk")
        if not np.array_equal(faces(mesh), topology):
            raise ValueError("PC display sample topology differs")
        values.append(points(mesh))
    samples = np.stack(values).reshape(len(components), 17, len(values[0]), 3)
    tolerance = float(100 * np.finfo(dtype).eps * max(float(scale), 1e-12))
    differences = []
    for j, pc in enumerate(components):
        for index, label in ((0, "minus"), (8, "mean"), (16, "plus")):
            error = float(np.linalg.norm(samples[j, index] - anchors[(pc, label)], axis=1).max())
            if error > tolerance:
                raise ValueError("PC display/native full-resolution anchor agreement failed")
            differences.append({"pc": pc, "sd": float(deviations[index]), "max_error": error})
    if any(sha256_file(root / path) != digest for path, digest in protected.items()):
        raise ValueError("PC display Shooting changed its declared inputs")
    receipt = {
        "version": "1",
        "return_code": 0,
        "samples_per_axis": 17,
        "sd_coordinates": deviations.tolist(),
        "components": components,
        "precision": str(dtype),
        "timepoints": count,
        "exported_time": 1,
        "protected_inputs": protected,
        "native_grids": grids,
        "anchor_errors": differences,
        "anchor_tolerance": tolerance,
        "boundary": "Display-only vertex subset; native PC samples, not optimizer iterations.",
    }
    (root / "samples.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8"
    )
    return samples
