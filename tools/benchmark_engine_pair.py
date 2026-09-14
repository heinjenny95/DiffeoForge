"""Bounded public CPU objective/gradient comparison; compatible with Python 3.8.

This is a single-subject kernel/gradient benchmark, NOT atlas qualification.
Both runtimes must execute sequentially on the same Linux host. It neither
changes an installed runtime nor accepts private meshes or arbitrary sizes.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import itertools
import json
import logging
import math
import os
import platform
import statistics
import time
from pathlib import Path

from probe_reference_cpu import checked_meshes

PROTOCOL = "public-engine-pair-v1"
ENGINES = ("reference-keops", "modern-dense", "modern-blockwise")
RTOL, ATOL = 1e-8, 1e-10
VALUE_NAMES = (
    "total",
    "residual",
    "attachment",
    "regularity",
    "endpoint",
    "control_path",
    "momenta_path",
    "template_gradient",
    "control_gradient",
    "momenta_gradient",
)


def read_mesh(path):
    """Read only the already hash-verified public ASCII VTK fixture."""
    import numpy as np

    tokens = path.read_text().split()
    index = tokens.index("POINTS")
    count = int(tokens[index + 1])
    points = np.array(tokens[index + 3 : index + 3 + 3 * count], dtype=np.float64).reshape(-1, 3)
    index = tokens.index("POLYGONS")
    count = int(tokens[index + 1])
    cells = np.array(tokens[index + 3 : index + 3 + 4 * count], dtype=np.int64).reshape(-1, 4)
    if not (cells[:, 0] == 3).all():
        raise ValueError("Expected triangular fixture")
    return points, cells[:, 1:].copy()


def subdivide(points, faces):
    """Deterministic edge-midpoint subdivision, without smoothing or projection."""
    import numpy as np

    vertices = points.tolist()
    edges, triangles = {}, []
    for a, b, c in faces.tolist():
        mids = []
        for left, right in ((a, b), (b, c), (c, a)):
            key = tuple(sorted((left, right)))
            if key not in edges:
                edges[key] = len(vertices)
                vertices.append(((points[left] + points[right]) * 0.5).tolist())
            mids.append(edges[key])
        ab, bc, ca = mids
        triangles.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
    return np.asarray(vertices), np.asarray(triangles)


def observe(repo, engine, attachment, level, repeat):
    import importlib.metadata as metadata
    import resource

    import numpy as np
    import torch

    if platform.system() != "Linux":
        raise ValueError("Use one Linux host for both engines and Linux ru_maxrss units")
    if any(os.environ.get(k) != "1" for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("Set OMP_NUM_THREADS=MKL_NUM_THREADS=1 before process startup")
    logging.disable(logging.CRITICAL)
    meshes = checked_meshes(repo)
    vertices, faces = read_mesh(meshes["template.vtk"])
    target_vertices, target_faces = read_mesh(meshes["subject-01.vtk"])
    for _ in range(level):
        vertices, faces = subdivide(vertices, faces)
        target_vertices, target_faces = subdivide(target_vertices, target_faces)
    q = np.asarray(list(itertools.product((-0.6, 0.0, 0.6), repeat=3)))
    p = np.sin(np.arange(q.size).reshape(q.shape) + 0.5) * 0.002
    arrays = (vertices, faces, target_vertices, target_faces, q, p)
    inputs_hash = hashlib.sha256(b"".join(a.tobytes() for a in arrays)).hexdigest()
    template = torch.tensor(vertices, dtype=torch.float64, requires_grad=True)
    control = torch.tensor(q, dtype=torch.float64, requires_grad=True)
    momenta = torch.tensor(p, dtype=torch.float64, requires_grad=True)
    target = torch.tensor(target_vertices, dtype=torch.float64)
    triangles = torch.tensor(faces, dtype=torch.int64)
    target_triangles = torch.tensor(target_faces, dtype=torch.int64)

    if engine == "reference-keops":
        from deformetrica.core import GpuMode
        from deformetrica.core.model_tools.attachments.multi_object_attachment import (
            MultiObjectAttachment,
        )
        from deformetrica.core.model_tools.deformations.exponential import Exponential
        from deformetrica.core.observations.deformable_objects.landmarks.surface_mesh import (
            SurfaceMesh,
        )
        from deformetrica.support.kernels.keops_kernel import KeopsKernel

        if metadata.version("deformetrica") != "4.3.0" or torch.__version__ != "1.6.0+cpu":
            raise ValueError("Use the frozen Deformetrica 4.3.0 / Torch 1.6.0+cpu runtime")
        source_mesh = SurfaceMesh(vertices, faces)
        target_mesh = SurfaceMesh(target_vertices, target_faces)
        # Same explicit precision policy as the existing v0.2 objective fixture:
        # discard only the constructor's float32 geometry cache for this float64 probe.
        source_mesh.set_points(source_mesh.points.copy())
        target_mesh.set_points(target_mesh.points.copy())
        deformation = KeopsKernel(kernel_width=1.0, gpu_mode=GpuMode.NONE, cuda_type="float64")
        distance_kernel = KeopsKernel(kernel_width=0.5, gpu_mode=GpuMode.NONE, cuda_type="float64")

        def forward():
            flow = Exponential(
                dense_mode=False,
                kernel=deformation,
                number_of_time_points=5,
                initial_control_points=control,
                initial_momenta=momenta,
                initial_template_points={"landmark_points": template},
                use_rk2_for_shoot=True,
                use_rk2_for_flow=True,
            )
            flow.update()
            endpoint = flow.get_template_points()["landmark_points"]
            distance = getattr(MultiObjectAttachment, attachment + "_distance")(
                endpoint,
                source_mesh,
                target_mesh,
                distance_kernel,
            )
            weighted = -distance / 0.25
            regularity = -flow.get_norm_squared()
            return (
                weighted + regularity,
                distance,
                weighted,
                regularity,
                endpoint,
                torch.stack(flow.control_points_t),
                torch.stack(flow.momenta_t),
            )
    else:
        from diffeoforge.engine.dense import GaussianTilePlan, prepare_surface_attachment_target
        from diffeoforge.engine.objective import subject_objective

        if torch.__version__.split("+")[0] != "2.13.0":
            raise ValueError("Use the declared Modern Torch 2.13.0 CPU runtime")
        plan = GaussianTilePlan(128, 128, "recompute") if engine == "modern-blockwise" else None
        prepared = prepare_surface_attachment_target(
            target,
            target_triangles,
            0.5,
            attachment_type=attachment,
            gaussian_tile_plan=plan,
        )

        def forward():
            result = subject_objective(
                template,
                triangles,
                target,
                target_triangles,
                control,
                momenta,
                deformation_kernel_width=1.0,
                attachment_kernel_width=0.5,
                noise_variance=0.25,
                number_of_time_points=5,
                attachment_type=attachment,
                shooting_integrator="rk2",
                flow_integrator="deformetrica_heun",
                gaussian_tile_plan=plan,
                prepared_target=prepared,
            )
            return (
                result.total,
                result.residual,
                result.attachment,
                result.regularity,
                result.endpoint_vertices,
                result.trajectory.control_points,
                result.trajectory.momenta,
            )

    torch.set_num_threads(1)  # Deformetrica imports can reset the Torch thread count.

    def evaluate():
        result = forward()
        gradients = torch.autograd.grad(result[0], (template, control, momenta))
        return result + gradients

    warm = evaluate()  # Compile KeOps and populate invariant target caches outside timing.
    del warm
    gc.collect()
    observations, seconds = [], []
    for _ in range(3):
        start = time.perf_counter()
        result = evaluate()
        seconds.append(time.perf_counter() - start)
        observations.append(
            {name: result[i].detach().tolist() for i, name in enumerate(VALUE_NAMES)}
        )
        del result
        gc.collect()
    if any(item != observations[0] for item in observations[1:]):
        raise ValueError("Repeated objective/gradient values were not exactly repeatable")
    cpu = next(
        line.split(":", 1)[1].strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines()
        if line.startswith("model name")
    )
    return {
        "protocol": PROTOCOL,
        "engine": engine,
        "attachment": attachment,
        "subdivision": level,
        "repeat": repeat,
        "vertices": len(vertices),
        "faces": len(faces),
        "input_sha256": inputs_hash,
        "cpu_model": cpu,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "threads": torch.get_num_threads(),
        "dtype": "float64",
        "device": "cpu",
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": {
            k: os.environ.get(k)
            for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "MKL_CBWR", "MKL_DEBUG_CPU_TYPE")
        },
        "timed_evaluations_seconds": seconds,
        "median_seconds": statistics.median(seconds),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "memory_scope": (
            "whole fresh worker including imports and untimed warmup; excludes children"
        ),
        "values": observations[0],
    }


def write_report(path, report):
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    sidecar = path.with_suffix(".sha256")
    if path.exists() or sidecar.exists():
        raise FileExistsError("Evidence is never overwritten")
    with path.open("xb") as stream:
        stream.write(payload)
    with sidecar.open("x", encoding="ascii") as stream:
        stream.write(hashlib.sha256(payload).hexdigest() + "\n")


def differences(left, right):
    if isinstance(left, list):
        if not isinstance(right, list) or not left or len(left) != len(right):
            raise ValueError("Numeric shape mismatch")
        return [item for i, value in enumerate(left) for item in differences(value, right[i])]
    if any(
        isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
        for x in (left, right)
    ):
        raise ValueError("Invalid or non-finite numeric observation")
    delta = abs(left - right)
    return [(delta, delta <= ATOL + RTOL * max(abs(left), abs(right)))]


def compare_reports(reports):
    wanted = set(itertools.product(ENGINES, ("current", "varifold"), (0, 1), (1, 2, 3)))
    indexed = {}
    for report in reports:
        key = tuple(report[k] for k in ("engine", "attachment", "subdivision", "repeat"))
        if key not in wanted or key in indexed:
            raise ValueError("Unexpected or duplicate comparison condition")
        if (
            report["protocol"] != PROTOCOL
            or report["threads"] != 1
            or report["dtype"] != "float64"
            or report["device"] != "cpu"
            or set(report["values"]) != set(VALUE_NAMES)
        ):
            raise ValueError("Incompatible comparison protocol")
        expected_torch = "1.6.0+cpu" if key[0] == "reference-keops" else "2.13.0+cpu"
        if report["torch"] != expected_torch:
            raise ValueError("Unexpected Torch runtime")
        if (
            report["environment"].get("OMP_NUM_THREADS") != "1"
            or report["environment"].get("MKL_NUM_THREADS") != "1"
            or report["environment"].get("MKL_DEBUG_CPU_TYPE") is not None
        ):
            raise ValueError("Unexpected thread or diagnostic environment override")
        if report["faces"] != 320 * 4 ** key[2] or report["vertices"] != (162, 642)[key[2]]:
            raise ValueError("Unexpected public fixture dimensions")
        times = report["timed_evaluations_seconds"]
        if (
            len(times) != 3
            or any(not math.isfinite(t) or t <= 0 for t in times)
            or report["median_seconds"] != statistics.median(times)
            or report["process_peak_rss_bytes"] <= 0
        ):
            raise ValueError("Invalid time or memory observation")
        for value in report["values"].values():
            differences(value, value)
        indexed[key] = report
    if set(indexed) != wanted:
        raise ValueError("Require all 36 predeclared fresh-process observations")
    for field in ("cpu_model", "platform", "worker_sha256"):
        if len({r[field] for r in reports}) != 1:
            raise ValueError("Mixed host/platform/worker provenance")
    cases = []
    for attachment, level in itertools.product(("current", "varifold"), (0, 1)):
        group = [r for r in reports if r["attachment"] == attachment and r["subdivision"] == level]
        if len({r["input_sha256"] for r in group}) != 1:
            raise ValueError("Input fingerprints differ between engines")
        reference = indexed[("reference-keops", attachment, level, 1)]
        for engine in ENGINES:
            observations = [indexed[(engine, attachment, level, i)] for i in (1, 2, 3)]
            if any(r["values"] != observations[0]["values"] for r in observations[1:]):
                raise ValueError("Fresh-process numerical repeatability failed")
            agreement = {}
            for name in VALUE_NAMES:
                pairs = differences(reference["values"][name], observations[0]["values"][name])
                agreement[name] = {
                    "pass": all(p[1] for p in pairs),
                    "max_absolute": max(p[0] for p in pairs),
                }
            cases.append(
                {
                    "engine": engine,
                    "attachment": attachment,
                    "faces": 320 * 4**level,
                    "agreement": agreement,
                    "numerical_pass": all(a["pass"] for a in agreement.values()),
                    "median_seconds": statistics.median(r["median_seconds"] for r in observations),
                    "min_seconds": min(r["median_seconds"] for r in observations),
                    "max_seconds": max(r["median_seconds"] for r in observations),
                    "max_process_peak_rss_bytes": max(
                        r["process_peak_rss_bytes"] for r in observations
                    ),
                }
            )
    return {
        "protocol": PROTOCOL,
        "rtol": RTOL,
        "atol": ATOL,
        "observation_count": len(reports),
        "cpu_model": reports[0]["cpu_model"],
        "platform": reports[0]["platform"],
        "cases": cases,
        "numerical_pass": all(c["numerical_pass"] for c in cases),
        "limits": (
            "Single-subject float64 objective plus gradients; not atlas convergence, "
            "biological validation or a large-mesh performance claim."
        ),
    }


def compare_directory(directory):
    reports = []
    for path in sorted(directory.glob("*.json")):
        if path.stat().st_size > 2_000_000:
            raise ValueError("Unexpected observation size")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != path.with_suffix(".sha256").read_text().strip():
            raise ValueError("Observation checksum mismatch")
        reports.append(json.loads(payload))
    return compare_reports(reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    observe_parser = commands.add_parser("observe")
    observe_parser.add_argument("--repository", type=Path, required=True)
    observe_parser.add_argument("--engine", choices=ENGINES, required=True)
    observe_parser.add_argument("--attachment", choices=("current", "varifold"), required=True)
    observe_parser.add_argument("--subdivision", type=int, choices=(0, 1), required=True)
    observe_parser.add_argument("--repeat", type=int, choices=(1, 2, 3), required=True)
    observe_parser.add_argument("--output", type=Path, required=True)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("--directory", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".sha256").exists():
        parser.error("Output already exists")
    report = (
        compare_directory(args.directory)
        if args.command == "compare"
        else observe(args.repository, args.engine, args.attachment, args.subdivision, args.repeat)
    )
    write_report(args.output, report)
    if args.command == "compare" and not report["numerical_pass"]:
        raise SystemExit(4)


if __name__ == "__main__":
    main()
