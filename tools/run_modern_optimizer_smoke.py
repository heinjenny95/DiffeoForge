"""Run the momenta-only optimizer on the committed five-subject CC0 cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import runpy
from pathlib import Path

import torch

from diffeoforge.engine import optimize_momenta
from diffeoforge.mesh import read_vtk_points, sha256_file

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "examples" / "synthetic" / "generate_dataset.py"
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
CONTROL_POINT_STRIDE = 20


def _tensor(values) -> torch.Tensor:
    return torch.tensor(values, dtype=torch.float64)


def run_smoke() -> dict:
    """Return deterministic optimization evidence without writing files."""

    generator = runpy.run_path(str(GENERATOR))
    _, faces = generator["_icosphere"](generator["SUBDIVISION_LEVEL"])
    triangles = torch.tensor(faces, dtype=torch.int64)
    template_path = MESH_DIRECTORY / "template.vtk"
    subject_paths = tuple(sorted(MESH_DIRECTORY.glob("subject-*.vtk")))
    template = _tensor(read_vtk_points(template_path))
    targets = tuple(
        (_tensor(read_vtk_points(subject_path)), triangles) for subject_path in subject_paths
    )
    control_point_indices = tuple(range(0, template.shape[0], CONTROL_POINT_STRIDE))
    control_points = template[list(control_point_indices)].clone()
    initial_momenta = torch.zeros(
        (len(targets), control_points.shape[0], 3),
        dtype=torch.float64,
    )
    settings = {
        "deformation_kernel_width": 0.6,
        "attachment_kernel_width": 0.45,
        "noise_variance": 0.01,
        "number_of_time_points": 5,
        "attachment_type": "current",
        "shooting_integrator": "rk2",
        "flow_integrator": "deformetrica_heun",
        "max_iterations": 3,
        "initial_step_size": 0.01,
        "backtracking_factor": 0.5,
        "armijo_constant": 1e-4,
        "gradient_tolerance": 0.0,
        "minimum_step_size": 1e-12,
        "max_line_search_iterations": 20,
    }
    result = optimize_momenta(
        template,
        triangles,
        targets,
        control_points,
        initial_momenta,
        **settings,
    )
    history = [
        {
            "iteration": record.iteration,
            "objective": record.objective,
            "attachment": record.attachment,
            "regularity": record.regularity,
            "residuals": list(record.residuals),
            "gradient_norm": record.gradient_norm,
            "accepted_step_size": record.accepted_step_size,
            "line_search_evaluations": record.line_search_evaluations,
        }
        for record in result.history
    ]
    return {
        "schema_version": "0.3",
        "description": (
            "Deterministic momenta-only optimization smoke evidence on the committed "
            "five-subject CC0 synthetic cohort."
        ),
        "scientific_boundary": (
            "Template vertices and control points are fixed; this is not a complete atlas "
            "estimator or evidence of optimizer equivalence with Deformetrica."
        ),
        "runtime": {
            "python": platform.python_version(),
            "pytorch": torch.__version__,
            "platform": platform.platform(),
            "device": "cpu",
            "dtype": "float64",
        },
        "inputs": {
            "license": "CC0-1.0",
            "generator_sha256": sha256_file(GENERATOR),
            "template": {
                "path": str(template_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(template_path),
                "points": template.shape[0],
                "triangles": triangles.shape[0],
            },
            "subjects": [
                {
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": sha256_file(path),
                }
                for path in subject_paths
            ],
            "control_point_indices": list(control_point_indices),
        },
        "settings": settings,
        "result": {
            "termination_reason": result.termination_reason,
            "converged": result.converged,
            "total_line_search_evaluations": result.total_line_search_evaluations,
            "momenta_sha256": hashlib.sha256(
                result.momenta.numpy().tobytes(order="C")
            ).hexdigest(),
            "history": history,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    arguments = parser.parse_args(argv)
    report = run_smoke()
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
