"""Generate the v0.2 objective fixture inside the frozen Deformetrica 4.3 environment.

This script is intentionally not imported by DiffeoForge. Run it with the Python 3.8
interpreter from the frozen reference environment and capture standard output as JSON.
"""

from __future__ import annotations

import json
import logging
import platform
import sys

import numpy as np
import torch
from deformetrica.core.model_tools.attachments.multi_object_attachment import (
    MultiObjectAttachment,
)
from deformetrica.core.model_tools.deformations.exponential import Exponential
from deformetrica.core.observations.deformable_objects.landmarks.surface_mesh import SurfaceMesh
from deformetrica.support.kernels.torch_kernel import TorchKernel

DTYPE = torch.float64
logging.disable(logging.CRITICAL)
TEMPLATE_VERTICES = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [0.2, 0.9, 0.0],
    [0.15, 0.25, 0.8],
]
TARGET_VERTICES = [
    [0.05, -0.02, 0.03],
    [1.08, 0.04, -0.01],
    [0.15, 0.95, 0.07],
    [0.2, 0.2, 0.88],
]
TRIANGLES = [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
CONTROL_POINTS = [[0.0, 0.0, 0.0], [1.0, 0.4, 0.2], [0.2, 0.9, 0.3]]
MOMENTA = [[0.04, -0.02, 0.01], [-0.03, 0.05, 0.015], [0.02, 0.01, -0.025]]
DEFORMATION_WIDTH = 1.1
ATTACHMENT_WIDTH = 0.75
NOISE_VARIANCE = 0.04
NUMBER_OF_TIME_POINTS = 4


def _tensor(values, *, requires_grad=False):
    return torch.tensor(values, dtype=DTYPE, requires_grad=requires_grad)


def _surface(vertices):
    surface = SurfaceMesh(
        np.asarray(vertices, dtype=np.float64),
        np.asarray(TRIANGLES, dtype=np.int64),
    )
    # Deformetrica 4.3 constructs and caches SurfaceMesh geometry in its global
    # float32 default even when the model tensors are float64. Marking the object
    # modified makes get_centers_and_normals recompute in the calling tensor's
    # dtype. The fixture therefore isolates the mathematical implementation from
    # that constructor-cache precision bug; the policy is recorded in metadata.
    surface.set_points(surface.points.copy())
    return surface


def _distance(kind, points, source, target):
    kernel = TorchKernel(kernel_width=ATTACHMENT_WIDTH)
    if kind == "current":
        return MultiObjectAttachment.current_distance(points, source, target, kernel)
    return MultiObjectAttachment.varifold_distance(points, source, target, kernel)


def _static_attachment(kind):
    points = _tensor(TEMPLATE_VERTICES, requires_grad=True)
    distance = _distance(kind, points, _surface(TEMPLATE_VERTICES), _surface(TARGET_VERTICES))
    (gradient,) = torch.autograd.grad(distance, points)
    return {
        "distance": distance.item(),
        "source_gradient": gradient.tolist(),
    }


def _subject(kind):
    template = _tensor(TEMPLATE_VERTICES, requires_grad=True)
    control_points = _tensor(CONTROL_POINTS, requires_grad=True)
    momenta = _tensor(MOMENTA, requires_grad=True)
    exponential = Exponential(
        dense_mode=False,
        kernel=TorchKernel(kernel_width=DEFORMATION_WIDTH),
        number_of_time_points=NUMBER_OF_TIME_POINTS,
        initial_control_points=control_points,
        initial_momenta=momenta,
        initial_template_points={"landmark_points": template},
        use_rk2_for_shoot=True,
        use_rk2_for_flow=True,
    )
    exponential.update()
    endpoint = exponential.get_template_points()["landmark_points"]
    residual = _distance(
        kind,
        endpoint,
        _surface(TEMPLATE_VERTICES),
        _surface(TARGET_VERTICES),
    )
    attachment = -residual / NOISE_VARIANCE
    regularity = -exponential.get_norm_squared()
    total = attachment + regularity
    template_gradient, control_points_gradient, momenta_gradient = torch.autograd.grad(
        total,
        (template, control_points, momenta),
    )
    return {
        "control_points_path": [value.tolist() for value in exponential.control_points_t],
        "momenta_path": [value.tolist() for value in exponential.momenta_t],
        "endpoint": endpoint.tolist(),
        "residual": residual.item(),
        "attachment": attachment.item(),
        "regularity": regularity.item(),
        "total": total.item(),
        "template_gradient": template_gradient.tolist(),
        "control_points_gradient": control_points_gradient.tolist(),
        "momenta_gradient": momenta_gradient.tolist(),
    }


def main():
    fixture = {
        "schema_version": "0.2",
        "description": (
            "Surface attachments and full deterministic subject-objective values generated "
            "with the frozen Deformetrica 4.3.0 CPU/float64 environment."
        ),
        "baseline": {
            "engine": "Deformetrica",
            "engine_version": "4.3.0",
            "pytorch": torch.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "target_geometry_precision": (
                "recomputed from float64 points; bypasses Deformetrica 4.3's "
                "float32 SurfaceMesh constructor cache"
            ),
            "source_components": [
                "deformetrica/support/kernels/torch_kernel.py",
                "deformetrica/core/model_tools/deformations/exponential.py",
                "deformetrica/core/model_tools/attachments/multi_object_attachment.py",
                "deformetrica/core/observations/deformable_objects/landmarks/surface_mesh.py",
                "deformetrica/core/models/deterministic_atlas.py",
            ],
        },
        "device": "cpu",
        "dtype": "float64",
        "tolerance": {
            "relative": 1e-10,
            "absolute": 1e-12,
            "status": "full-chain feasibility threshold; not a final release tolerance",
        },
        "inputs": {
            "template_vertices": TEMPLATE_VERTICES,
            "target_vertices": TARGET_VERTICES,
            "triangles": TRIANGLES,
            "control_points": CONTROL_POINTS,
            "momenta": MOMENTA,
            "deformation_width": DEFORMATION_WIDTH,
            "attachment_width": ATTACHMENT_WIDTH,
            "noise_variance": NOISE_VARIANCE,
            "number_of_time_points": NUMBER_OF_TIME_POINTS,
            "shooting_integrator": "rk2",
            "flow_integrator": "deformetrica_heun",
        },
        "expected": {
            "static": {
                "current": _static_attachment("current"),
                "varifold": _static_attachment("varifold"),
            },
            "subject": {
                "current": _subject("current"),
                "varifold": _subject("varifold"),
            },
        },
    }
    json.dump(fixture, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
