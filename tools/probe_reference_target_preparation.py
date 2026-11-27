"""Bounded offline native CPU cache probe; Python 3.8 compatible.

Uses generated public octahedra, one CPU thread, no scientific run or GPU.
The real Deformetrica flow/attachment/backward are compared exactly across four
identical fixed-budget gradient steps. This is NOT full-fit qualification.
"""

# ruff: noqa: B905 -- this isolated reference tool must run on Python 3.8.

import argparse
import hashlib
import importlib.util
import json
import logging
import os
import statistics
import sys
import time
from contextlib import nullcontext
from pathlib import Path


def run(repo, kernel_name, repeats):
    from importlib.metadata import version

    import numpy as np
    import torch
    from deformetrica.core import GpuMode, default
    from deformetrica.core.model_tools.attachments.multi_object_attachment import (
        MultiObjectAttachment,
    )
    from deformetrica.core.model_tools.deformations.exponential import Exponential
    from deformetrica.core.observations.deformable_objects.landmarks.surface_mesh import (
        SurfaceMesh,
    )
    from deformetrica.support.kernels.torch_kernel import TorchKernel

    native_version = version("deformetrica")
    if native_version != "4.3.0":
        raise RuntimeError("This probe requires Deformetrica 4.3.0")
    spec = importlib.util.spec_from_file_location(
        "offline_reference_target_cache",
        repo / "src/diffeoforge/reference_attachment_performance.py",
    )
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    logging.disable(logging.CRITICAL)
    torch.set_num_threads(1)
    default.update_dtype("float64")
    vertices = np.array(((1., 0., 0.), (-1., 0., 0.), (0., 1., 0.),
                         (0., -1., 0.), (0., 0., 1.), (0., 0., -1.)))
    faces = np.array(((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                      (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)))
    target_vertices = vertices * np.array((1.08, 0.95, 1.03)) + (0.03, -0.02, 0.01)

    class CpuReduction:
        def __init__(self, operation):
            self.operation = operation

        def __call__(self, *args, **kwargs):
            kwargs["backend"] = "CPU"
            return self.operation(*args, **kwargs)

    def kernel(width):
        if kernel_name == "torch":
            return TorchKernel(gpu_mode=GpuMode.NONE, kernel_width=width)
        from deformetrica.support.kernels.keops_kernel import KeopsKernel
        value = KeopsKernel(gpu_mode=GpuMode.NONE, kernel_width=width,
                            cuda_type="float64")
        for name in ("gaussian_convolve", "point_cloud_convolve", "varifold_convolve",
                     "gaussian_convolve_gradient_x"):
            setattr(value, name, [CpuReduction(op) for op in getattr(value, name)])
        return value

    def arm(cache):
        source, target = SurfaceMesh(vertices, faces), SurfaceMesh(target_vertices, faces)
        deformation, attachment = kernel(1.0), kernel(0.6)
        template = torch.tensor(vertices, dtype=torch.float64)
        controls = torch.tensor(vertices * 1.1, dtype=torch.float64)
        initial = np.arange(18, dtype=np.float64).reshape(6, 3) * 0.00003
        momentum = torch.tensor(initial, dtype=torch.float64, requires_grad=True)
        records, times, phases = [], [], []
        with candidate.isolated_native_cache_probe() if cache else nullcontext():
            for _ in range(4):
                start = time.perf_counter()
                flow = Exponential(
                    dense_mode=False, kernel=deformation, number_of_time_points=5,
                    initial_control_points=controls, initial_momenta=momentum,
                    initial_template_points={"landmark_points": template},
                    use_rk2_for_shoot=True, use_rk2_for_flow=True,
                )
                flow.update()
                endpoint = flow.get_template_points()["landmark_points"]
                flow_end = time.perf_counter()
                distance = MultiObjectAttachment.varifold_distance(
                    endpoint, source, target, attachment)
                objective = -distance / 0.25 - flow.get_norm_squared()
                attachment_end = time.perf_counter()
                gradient, = torch.autograd.grad(objective, momentum)
                backward_end = time.perf_counter()
                times.append(backward_end - start)
                phases.append(dict(integration=flow_end - start,
                                   attachment_and_regularity=attachment_end - flow_end,
                                   gradient_backward=backward_end - attachment_end))
                arrays = [value.detach().numpy().copy()
                          for value in (objective, endpoint, gradient, momentum)]
                records.append(arrays)
                momentum = (momentum + 0.0001 * gradient).detach().requires_grad_(True)
        return records, times, phases

    # Compilation/setup are outside measured warm repeats, identically for both arms.
    reference, _, _ = arm(False)
    repeated_reference, _, _ = arm(False)
    if not all(np.array_equal(a, b) for left, right in zip(reference, repeated_reference)
               for a, b in zip(left, right)):
        raise RuntimeError("Uncached native CPU path itself is not bitwise repeatable")
    cached, _, _ = arm(True)
    exact = all(np.array_equal(a, b) for left, right in zip(reference, cached)
                for a, b in zip(left, right))
    differences = [(step, name, float(np.max(np.abs(a - b))))
                   for step, (left, right) in enumerate(zip(reference, cached))
                   for name, a, b in zip(("objective", "endpoint", "gradient", "field"),
                                          left, right) if not np.array_equal(a, b)]
    timings = {"reference": [], "candidate": []}
    phase_timings = {name: {phase: [] for phase in (
        "integration", "attachment_and_regularity", "gradient_backward")}
        for name in timings}
    for repetition in range(repeats):
        # Reverse order on alternate repeats to reduce order bias.
        for enabled in ((False, True) if repetition % 2 == 0 else (True, False)):
            records, times, phases = arm(enabled)
            # Only identical-arm repeatability is required for measuring a rejection.
            expected = cached if enabled else reference
            if not all(np.array_equal(a, b) for left, right in zip(expected, records)
                       for a, b in zip(left, right)):
                raise RuntimeError("Native CPU repeated gradient path is not exact")
            name = "candidate" if enabled else "reference"
            timings[name].append(sum(times))
            for phase in phase_timings[name]:
                phase_timings[name][phase].append(sum(step[phase] for step in phases))

    # Isolate remaining target-only preparation work at a bounded public size.
    class Target:
        pass

    normals = torch.tensor(np.random.RandomState(7).normal(size=(32768, 3)),
                           dtype=torch.float64)
    target = Target()
    candidate.cached_target_normals(target, normals, torch)
    preparation = {"reference": [], "candidate": []}
    for _ in range(20):
        start = time.perf_counter()
        expected = candidate.prepare_target_normals(normals, torch)
        preparation["reference"].append(time.perf_counter() - start)
        start = time.perf_counter()
        observed = candidate.cached_target_normals(target, normals, torch)
        preparation["candidate"].append(time.perf_counter() - start)
        if not all(torch.equal(a, b) for a, b in zip(expected, observed)):
            raise RuntimeError("Target preparation cache changed values")

    def digest(arrays):
        return hashlib.sha256(b"".join(x.tobytes() for x in arrays)).hexdigest()

    return {
        "protocol": candidate.VERSION,
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidate_source_sha256": hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest(),
        "kernel": kernel_name + "-cpu", "threads": 1,
        "native_version": native_version, "torch_version": torch.__version__,
        "cpu_environment": {name: os.environ.get(name) for name in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_CBWR", "CUDA_VISIBLE_DEVICES")},
        "steps": 4, "timepoints": 5, "faces_per_surface": 8,
        "same_initial_field_and_budget": True,
        "exact_objective_endpoint_gradient_and_step_fields": exact,
        "cache_qualification": "passed_tiny_cpu_only" if exact else "rejected_exact_path_changed",
        "path_differences": differences,
        "step_evidence_sha256": [digest(arrays) for arrays in reference],
        "four_step_median_seconds": {
            name: statistics.median(values) for name, values in timings.items()},
        "four_step_phase_median_seconds": {
            name: {phase: statistics.median(values) for phase, values in parts.items()}
            for name, parts in phase_timings.items()},
        "line_search_and_scientific_qc": "Not measured by this fixed-step objective probe",
        "target_preparation_32768_faces_median_seconds": {
            name: statistics.median(values) for name, values in preparation.items()},
        "production_enabled": False,
        "qualification": "Synthetic native CPU flow/objective/gradient probe only",
        "pending": ["Full-resolution paired native fit and all original-surface QC",
                    "GPU timing/equivalence and independent anatomical review"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--kernel", choices=("torch", "keops"), default="torch")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Retain existing evidence; choose a new output path")
    # Every kernel is explicitly CPU; hiding CUDA also prevents accidental discovery.
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        parser.error("Run the isolated probe with CUDA_VISIBLE_DEVICES empty")
    if args.kernel == "keops":
        # Compiled experimental kernels must not enter the owner's live cache.
        import pykeops
        cache = args.output.parent / (args.output.stem + "-keops-cache")
        pykeops.set_bin_folder(str(cache))
        sys.path.insert(0, pykeops.bin_folder)
    payload = run(args.repo, args.kernel, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
