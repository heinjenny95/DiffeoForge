"""Bounded native CPU coarse-to-full experiment on generated public surfaces.

No private inputs, installed-runtime changes, GPU or atlas. Both arms have the
same frozen field, numerical settings and total iteration allowance. The coarse
arm explicitly changes working geometry and then fits/inspects the full surface.
This is a feasibility rejection gate, never anatomical production qualification.
Compatible with the separate Python 3.8 reference runtime.
"""

# ruff: noqa: B905 -- the separate reference runtime is Python 3.8.

import argparse
import hashlib
import json
import logging
import os
import statistics
import time
from importlib.metadata import version
from pathlib import Path


def sphere(level):
    import numpy as np

    points = np.array(((1., 0., 0.), (-1., 0., 0.), (0., 1., 0.),
                       (0., -1., 0.), (0., 0., 1.), (0., 0., -1.)))
    faces = np.array(((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                      (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)))
    for _ in range(level):
        vertices, edges, triangles = points.tolist(), {}, []
        for a, b, c in faces:
            mids = []
            for left, right in ((a, b), (b, c), (c, a)):
                key = tuple(sorted((int(left), int(right))))
                if key not in edges:
                    midpoint = (points[left] + points[right]) / 2
                    midpoint /= np.linalg.norm(midpoint)
                    edges[key] = len(vertices)
                    vertices.append(midpoint.tolist())
                mids.append(edges[key])
            ab, bc, ca = mids
            triangles.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        points, faces = np.asarray(vertices), np.asarray(triangles)
    return points, faces


def point_triangle_distances(queries, vertices, faces):
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk

    points, cells, poly = vtk.vtkPoints(), vtk.vtkCellArray(), vtk.vtkPolyData()
    points.SetData(numpy_to_vtk(vertices, deep=True))
    for face in faces:
        cells.InsertNextCell(3)
        for index in face:
            cells.InsertCellPoint(int(index))
    poly.SetPoints(points)
    poly.SetPolys(cells)
    distance = vtk.vtkImplicitPolyDataDistance()
    distance.SetInput(poly)
    return [abs(distance.EvaluateFunction(point)) for point in queries]


def sample_surface(points, faces):
    import numpy as np

    rng = np.random.RandomState(41)
    triangles = points[faces]
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                   triangles[:, 2] - triangles[:, 0]), axis=1)
    selected = rng.choice(len(faces), 512, p=area / area.sum())
    uv = rng.rand(512, 2)
    reflected = uv.sum(axis=1) > 1
    uv[reflected] = 1 - uv[reflected]
    chosen = triangles[selected]
    return chosen[:, 0] + uv[:, :1] * (chosen[:, 1] - chosen[:, 0]) + uv[:, 1:] * (
        chosen[:, 2] - chosen[:, 0])


def run():
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
    from scipy.optimize import minimize

    if version("deformetrica") != "4.3.0":
        raise RuntimeError("Requires the separately verified Deformetrica 4.3.0 runtime")
    torch.set_num_threads(1)
    default.update_dtype("float64")
    logging.disable(logging.CRITICAL)
    full, full_faces = sphere(3)
    coarse, coarse_faces = sphere(2)
    assert np.array_equal(full[:len(coarse)], coarse)
    controls = coarse * 1.1
    control_tensor = torch.tensor(controls, dtype=torch.float64)
    initial = np.zeros_like(controls)
    deformation = TorchKernel(gpu_mode=GpuMode.NONE, kernel_width=0.7)
    attachment = TorchKernel(gpu_mode=GpuMode.NONE, kernel_width=0.3)

    def flow(points, momentum):
        value = Exponential(
            dense_mode=False, kernel=deformation, number_of_time_points=5,
            initial_control_points=control_tensor, initial_momenta=momentum,
            initial_template_points={"landmark_points": torch.tensor(points, dtype=torch.float64)},
            use_rk2_for_shoot=True, use_rk2_for_flow=True,
        )
        value.update()
        return value

    def solve(source_points, target_points, faces, start, cap):
        source, target = SurfaceMesh(source_points, faces), SurfaceMesh(target_points, faces)
        phase = dict(integration=0., attachment_and_regularity=0., gradient_backward=0.)
        evaluations = []

        def objective(flat):
            begin = time.perf_counter()
            momentum = torch.tensor(flat.reshape(controls.shape), dtype=torch.float64,
                                    requires_grad=True)
            current = flow(source_points, momentum)
            after_flow = time.perf_counter()
            endpoint = current.get_template_points()["landmark_points"]
            residual = MultiObjectAttachment.varifold_distance(endpoint, source, target, attachment)
            cost = residual / 0.0025 + current.get_norm_squared()
            after_attachment = time.perf_counter()
            gradient, = torch.autograd.grad(cost, momentum)
            after_gradient = time.perf_counter()
            for key, elapsed in zip(phase, (after_flow - begin,
                                           after_attachment - after_flow,
                                           after_gradient - after_attachment)):
                phase[key] += elapsed
            evaluations.append(float(cost))
            return float(cost), gradient.detach().numpy().ravel().copy()

        begin = time.perf_counter()
        result = minimize(objective, start.ravel(), jac=True, method="L-BFGS-B",
                          options=dict(maxiter=cap, maxls=5, ftol=1e-4, gtol=1e-5))
        return result.x.reshape(controls.shape).copy(), dict(
            cap=cap, iterations=int(result.nit), objective_evaluations=len(evaluations),
            # Accepted iterates + initial evaluation need at least nit+1 calls.
            additional_evaluations=max(0, len(evaluations) - int(result.nit) - 1),
            solver_wall_seconds=time.perf_counter() - begin,
            phase_seconds=phase, final_objective=float(result.fun),
            native_stop=str(result.message), success=bool(result.success),
        )

    def arm(target, multires):
        started = time.perf_counter()
        momentum = initial.copy()
        stages = []
        if multires:
            preparation = time.perf_counter()
            working_target = target[:len(coarse)].copy()
            reduction_seconds = time.perf_counter() - preparation
            momentum, report = solve(coarse.copy(), working_target, coarse_faces, momentum, 4)
            stages.append(report)
        else:
            reduction_seconds = 0.
        momentum, report = solve(full.copy(), target.copy(), full_faces, momentum,
                                 4 if multires else 8)
        stages.append(report)
        finalization = time.perf_counter()
        with torch.no_grad():
            final_flow = flow(full, torch.tensor(momentum, dtype=torch.float64))
            endpoint = final_flow.get_template_points()["landmark_points"].numpy().copy()
        forward = point_triangle_distances(sample_surface(target, full_faces), endpoint, full_faces)
        reverse = point_triangle_distances(sample_surface(endpoint, full_faces), target, full_faces)
        material_errors = np.linalg.norm(endpoint - target, axis=1)
        peak = int(np.argmax(target[:, 2] - full[:, 2]))
        qc = dict(
            original_to_reco_p95=float(np.percentile(forward, 95)),
            reco_to_original_p95=float(np.percentile(reverse, 95)),
            material_rms=float(np.sqrt(np.mean(material_errors ** 2))),
            known_local_peak_error=float(material_errors[peak]),
            recovered_peak_displacement=float(endpoint[peak, 2] - full[peak, 2]),
        )
        return dict(
            total_wall_seconds=time.perf_counter() - started,
            reduction_seconds=reduction_seconds,
            full_material_flow_and_qc_seconds=time.perf_counter() - finalization,
            stages=stages, qc=qc,
            final_momenta_sha256=hashlib.sha256(momentum.tobytes()).hexdigest(),
            full_endpoint_sha256=hashlib.sha256(endpoint.tobytes()).hexdigest(),
        )

    # Warm the same generated geometry/flow path before measuring either arm.
    with torch.no_grad():
        flow(full, torch.tensor(initial, dtype=torch.float64))
    point_triangle_distances(full[:1], full, full_faces)
    comparisons = []
    for dose in (0., 0.10, 0.20):
        target = full.copy()
        bump = np.exp(-((full[:, 0] / 0.35) ** 2 + (full[:, 1] / 0.35) ** 2))
        bump[full[:, 2] < 0] = 0
        target[:, 2] += dose * bump
        baseline = arm(target, False)
        candidate = arm(target, True)
        # Predeclared strict synthetic gate; it is not an anatomical tolerance.
        measurements = ("original_to_reco_p95", "reco_to_original_p95",
                        "material_rms", "known_local_peak_error")
        quality = all(candidate["qc"][key] <= baseline["qc"][key] + 1e-12
                      for key in measurements)
        comparisons.append(dict(dose=dose, full_reference=baseline,
                                coarse_to_full=candidate,
                                target_material_sha256=hashlib.sha256(
                                    target.tobytes() + full_faces.tobytes()).hexdigest(),
                                no_worse_on_all_declared_full_geometry_metrics=quality))
    quality = all(item["no_worse_on_all_declared_full_geometry_metrics"]
                  for item in comparisons)
    speed = statistics.median(item["coarse_to_full"]["total_wall_seconds"]
                              for item in comparisons[1:]) < statistics.median(
        item["full_reference"]["total_wall_seconds"] for item in comparisons[1:])
    return dict(
        protocol="public-native-multiresolution-feasibility-v1",
        probe_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        native_version=version("deformetrica"), torch_version=torch.__version__,
        execution="one CPU thread, native Torch kernels, no GPU",
        settings=dict(controls=len(controls), full_faces=len(full_faces),
                      coarse_faces=len(coarse_faces), timepoints=5, precision="float64",
                      total_iteration_cap=8, ftol=1e-4, gtol=1e-5, maxls=5,
                      attachment_width=0.3, deformation_width=0.7, noise_std=0.05),
        initial_field_sha256=hashlib.sha256(initial.tobytes()).hexdigest(),
        controls_sha256=hashlib.sha256(controls.tobytes()).hexdigest(),
        template_material_sha256=hashlib.sha256(
            full.tobytes() + full_faces.tobytes()).hexdigest(),
        coarse_material_sha256=hashlib.sha256(
            coarse.tobytes() + coarse_faces.tobytes()).hexdigest(),
        comparisons=comparisons, strict_synthetic_quality_gate=quality,
        faster_on_nonzero_doses=speed,
        feasibility="passed_tiny_cpu_only" if quality and speed else "rejected",
        production_enabled=False,
        limitations=["Generated smooth closed surfaces do not represent thin skull structures",
                     "Coarse geometry is known nested synthetic sampling, not real-mesh decimation",
                     "A capped fit remains capped; no anatomical approval is inferred",
                     "Full specimen/GPU/time-grid/intersection qualification remains required"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Retain previous evidence; choose a new output")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        parser.error("Run the isolated CPU probe with CUDA_VISIBLE_DEVICES empty")
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps({key: value for key, value in result.items() if key != "comparisons"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
