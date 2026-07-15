"""Machine-readable comparison against a frozen Deformetrica primitive fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import torch

from diffeoforge.engine.dense import (
    current_squared_distance,
    deformation_energy,
    gaussian_convolve,
    gaussian_convolve_gradient,
    gaussian_kernel,
    shoot,
    varifold_squared_distance,
)
from diffeoforge.engine.objective import subject_objective


def _maximum(values: torch.Tensor) -> float:
    return float(torch.max(values.detach())) if values.numel() else 0.0


def _comparison(
    actual: torch.Tensor,
    expected: Any,
    *,
    relative_tolerance: float,
    absolute_tolerance: float,
    name: str,
) -> dict[str, float | bool]:
    reference = torch.as_tensor(expected, dtype=torch.float64)
    if actual.shape != reference.shape:
        raise ValueError(f"reference shape mismatch for {name}")
    absolute_error = torch.abs(actual - reference)
    denominator = torch.maximum(
        torch.abs(reference), torch.full_like(reference, absolute_tolerance)
    )
    relative_error = absolute_error / denominator
    return {
        "pass": bool(
            torch.allclose(
                actual,
                reference,
                rtol=relative_tolerance,
                atol=absolute_tolerance,
            )
        ),
        "max_absolute_error": _maximum(absolute_error),
        "max_relative_error": _maximum(relative_error),
    }


def _report(
    path: Path,
    fixture_bytes: bytes,
    fixture: dict[str, Any],
    comparisons: dict[str, dict[str, float | bool]],
) -> dict[str, Any]:
    return {
        "schema_version": fixture["schema_version"],
        "fixture": {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
            "baseline": fixture["baseline"],
        },
        "runtime": {
            "python": platform.python_version(),
            "pytorch": torch.__version__,
            "platform": platform.platform(),
            "device": "cpu",
            "dtype": "float64",
            "python_executable": sys.executable,
        },
        "tolerance": fixture["tolerance"],
        "comparisons": comparisons,
        "overall_pass": all(item["pass"] for item in comparisons.values()),
    }


def _compare_objective_fixture(
    path: Path,
    fixture_bytes: bytes,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    inputs = fixture["inputs"]
    expected = fixture["expected"]
    tolerance = fixture["tolerance"]
    relative_tolerance = float(tolerance["relative"])
    absolute_tolerance = float(tolerance["absolute"])
    triangles = torch.tensor(inputs["triangles"], dtype=torch.int64)
    target = torch.tensor(inputs["target_vertices"], dtype=torch.float64)
    comparisons: dict[str, dict[str, float | bool]] = {}

    for attachment_type, distance_function in (
        ("current", current_squared_distance),
        ("varifold", varifold_squared_distance),
    ):
        source = torch.tensor(
            inputs["template_vertices"], dtype=torch.float64, requires_grad=True
        )
        distance = distance_function(
            source,
            triangles,
            target,
            triangles,
            float(inputs["attachment_width"]),
        )
        (source_gradient,) = torch.autograd.grad(distance, source)
        static_expected = expected["static"][attachment_type]
        for suffix, actual, reference in (
            ("distance", distance, static_expected["distance"]),
            ("source_gradient", source_gradient, static_expected["source_gradient"]),
        ):
            name = f"static.{attachment_type}.{suffix}"
            comparisons[name] = _comparison(
                actual,
                reference,
                relative_tolerance=relative_tolerance,
                absolute_tolerance=absolute_tolerance,
                name=name,
            )

        template = torch.tensor(
            inputs["template_vertices"], dtype=torch.float64, requires_grad=True
        )
        control_points = torch.tensor(
            inputs["control_points"], dtype=torch.float64, requires_grad=True
        )
        momenta = torch.tensor(inputs["momenta"], dtype=torch.float64, requires_grad=True)
        subject = subject_objective(
            template,
            triangles,
            target,
            triangles,
            control_points,
            momenta,
            deformation_kernel_width=float(inputs["deformation_width"]),
            attachment_kernel_width=float(inputs["attachment_width"]),
            noise_variance=float(inputs["noise_variance"]),
            number_of_time_points=int(inputs["number_of_time_points"]),
            attachment_type=attachment_type,
            shooting_integrator=inputs["shooting_integrator"],
            flow_integrator=inputs["flow_integrator"],
        )
        gradients = torch.autograd.grad(
            subject.total,
            (template, control_points, momenta),
        )
        subject_expected = expected["subject"][attachment_type]
        observed = {
            "endpoint": subject.endpoint_vertices,
            "residual": subject.residual,
            "attachment": subject.attachment,
            "regularity": subject.regularity,
            "total": subject.total,
            "template_gradient": gradients[0],
            "control_points_gradient": gradients[1],
            "momenta_gradient": gradients[2],
        }
        for suffix, actual in observed.items():
            name = f"subject.{attachment_type}.{suffix}"
            comparisons[name] = _comparison(
                actual,
                subject_expected[suffix],
                relative_tolerance=relative_tolerance,
                absolute_tolerance=absolute_tolerance,
                name=name,
            )

    return _report(path, fixture_bytes, fixture, comparisons)


def compare_reference_fixture(path: Path) -> dict[str, Any]:
    """Evaluate and compare every operation declared by a reference JSON fixture."""

    fixture_bytes = path.read_bytes()
    fixture = json.loads(fixture_bytes)
    if fixture.get("schema_version") == "0.2":
        if fixture.get("dtype") != "float64" or fixture.get("device") != "cpu":
            raise ValueError("the v0.2 comparison harness supports only CPU float64 fixtures")
        return _compare_objective_fixture(path, fixture_bytes, fixture)
    if fixture.get("schema_version") != "0.1":
        raise ValueError("unsupported modern-engine reference schema_version")
    if fixture.get("dtype") != "float64" or fixture.get("device") != "cpu":
        raise ValueError("the v0.1 comparison harness supports only CPU float64 fixtures")

    inputs = fixture["inputs"]
    expected = fixture["expected"]
    tolerance = fixture["tolerance"]
    relative_tolerance = float(tolerance["relative"])
    absolute_tolerance = float(tolerance["absolute"])
    control_points = torch.tensor(inputs["control_points"], dtype=torch.float64)
    momenta = torch.tensor(inputs["momenta"], dtype=torch.float64)
    kernel_width = float(inputs["kernel_width"])
    number_of_time_points = int(inputs["number_of_time_points"])
    trajectory = shoot(
        control_points,
        momenta,
        kernel_width,
        number_of_time_points,
        integrator="rk2",
    )
    observed = {
        "kernel": gaussian_kernel(control_points, control_points, kernel_width),
        "convolution": gaussian_convolve(
            control_points, control_points, momenta, kernel_width
        ),
        "gradient": gaussian_convolve_gradient(
            momenta, control_points, kernel_width=kernel_width
        ),
        "norm_squared": deformation_energy(control_points, momenta, kernel_width),
        "rk2_q_step": trajectory.control_points[1],
        "rk2_p_step": trajectory.momenta[1],
    }

    comparisons: dict[str, dict[str, float | bool]] = {}
    for name, actual in observed.items():
        comparisons[name] = _comparison(
            actual,
            expected[name],
            relative_tolerance=relative_tolerance,
            absolute_tolerance=absolute_tolerance,
            name=name,
        )

    return _report(path, fixture_bytes, fixture, comparisons)


def main(argv: list[str] | None = None) -> int:
    """Run the reference comparison and print a JSON report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Path to a modern-engine reference JSON file")
    parser.add_argument("--output", type=Path, help="Optional path for the comparison report")
    arguments = parser.parse_args(argv)
    report = compare_reference_fixture(arguments.fixture)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the command line
    raise SystemExit(main())
