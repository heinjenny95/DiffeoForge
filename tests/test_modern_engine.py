from __future__ import annotations

import math
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

ShootingTrajectory = engine.ShootingTrajectory
current_squared_distance = engine.current_squared_distance
deformation_energy = engine.deformation_energy
flow_points = engine.flow_points
gaussian_convolve = engine.gaussian_convolve
gaussian_convolve_gradient = engine.gaussian_convolve_gradient
gaussian_kernel = engine.gaussian_kernel
shoot = engine.shoot
triangle_centers_and_area_normals = engine.triangle_centers_and_area_normals
varifold_squared_distance = engine.varifold_squared_distance


DTYPE = torch.float64
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.1"
    / "deformetrica-4.3.0-primitives.json"
)


def _shooting_inputs() -> tuple[torch.Tensor, torch.Tensor]:
    control_points = torch.tensor(
        [[0.0, 0.0, 0.0], [1.0, 0.5, -0.25]],
        dtype=DTYPE,
    )
    momenta = torch.tensor(
        [[0.2, -0.1, 0.05], [-0.15, 0.3, 0.1]],
        dtype=DTYPE,
    )
    return control_points, momenta


def _square_surface(z: float = 0.0) -> tuple[torch.Tensor, torch.Tensor]:
    vertices = torch.tensor(
        [[0.0, 0.0, z], [1.0, 0.0, z], [1.0, 1.0, z], [0.0, 1.0, z]],
        dtype=DTYPE,
    )
    triangles = torch.tensor([[0, 1, 2], [0, 2, 3]], dtype=torch.int64)
    return vertices, triangles


def test_gaussian_kernel_and_convolution_match_hand_calculation() -> None:
    points = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=DTYPE)
    weights = torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=DTYPE)
    off_diagonal = math.exp(-0.25)
    expected = torch.tensor(
        [[1.0, off_diagonal], [off_diagonal, 1.0]],
        dtype=DTYPE,
    )

    actual = gaussian_kernel(points, points, kernel_width=2.0)

    torch.testing.assert_close(actual, expected, rtol=1e-14, atol=1e-14)
    torch.testing.assert_close(
        gaussian_convolve(points, points, weights, 2.0),
        expected @ weights,
        rtol=1e-14,
        atol=1e-14,
    )


def test_dense_primitives_match_deformetrica_4_3_golden_values() -> None:
    """Values generated with the frozen Deformetrica 4.3 TorchKernel on CPU/float64."""

    control_points, momenta = _shooting_inputs()
    expected_kernel = torch.tensor(
        [[1.0, 0.43171052342907973], [0.43171052342907973, 1.0]],
        dtype=DTYPE,
    )
    expected_gradient = torch.tensor(
        [
            [-0.030392420849407208, -0.015196210424703604, 0.007598105212351802],
            [0.030392420849407215, 0.015196210424703607, -0.007598105212351804],
        ],
        dtype=DTYPE,
    )
    expected_first_points = torch.tensor(
        [
            [0.04563391870475212, 0.011097790510133662, 0.03108276996121602],
            [0.9783590810051711, 0.5848742083295593, -0.20910377083144632],
        ],
        dtype=DTYPE,
    )
    expected_first_momenta = torch.tensor(
        [
            [0.21012888669000268, -0.09436501294990932, 0.04743056895542829],
            [-0.16012888669000266, 0.2943650129499093, 0.10256943104457172],
        ],
        dtype=DTYPE,
    )

    trajectory = shoot(control_points, momenta, 1.25, 4, integrator="rk2")

    torch.testing.assert_close(
        gaussian_kernel(control_points, control_points, 1.25),
        expected_kernel,
        rtol=1e-13,
        atol=1e-14,
    )
    torch.testing.assert_close(
        gaussian_convolve_gradient(momenta, control_points, kernel_width=1.25),
        expected_gradient,
        rtol=1e-13,
        atol=1e-14,
    )
    torch.testing.assert_close(
        deformation_energy(control_points, momenta, 1.25),
        torch.tensor(0.12751184242280125, dtype=DTYPE),
        rtol=1e-13,
        atol=1e-14,
    )
    torch.testing.assert_close(
        trajectory.control_points[1], expected_first_points, rtol=1e-13, atol=1e-14
    )
    torch.testing.assert_close(
        trajectory.momenta[1], expected_first_momenta, rtol=1e-13, atol=1e-14
    )


def test_machine_readable_reference_harness_passes() -> None:
    from diffeoforge.engine.reference import compare_reference_fixture

    report = compare_reference_fixture(REFERENCE_FIXTURE)

    assert report["overall_pass"] is True
    assert report["fixture"]["baseline"]["engine_version"] == "4.3.0"
    assert set(report["comparisons"]) == {
        "kernel",
        "convolution",
        "gradient",
        "norm_squared",
        "rk2_q_step",
        "rk2_p_step",
    }


def test_explicit_kernel_gradient_matches_autograd() -> None:
    control_points, momenta = _shooting_inputs()
    control_points.requires_grad_(True)

    half_energy = 0.5 * deformation_energy(control_points, momenta, 1.25)
    (autograd_gradient,) = torch.autograd.grad(half_energy, control_points)
    explicit_gradient = gaussian_convolve_gradient(
        momenta, control_points, kernel_width=1.25
    )

    torch.testing.assert_close(explicit_gradient, autograd_gradient, rtol=1e-12, atol=1e-13)


def test_shooting_is_differentiable_deterministic_and_does_not_mutate_inputs() -> None:
    control_points, momenta = _shooting_inputs()
    original_points = control_points.clone()
    original_momenta = momenta.clone()
    momenta.requires_grad_(True)

    first = shoot(control_points, momenta, 1.25, 5, integrator="rk2")
    second = shoot(control_points, momenta, 1.25, 5, integrator="rk2")
    loss = first.control_points[-1].square().sum()
    (gradient,) = torch.autograd.grad(loss, momenta)

    assert torch.equal(first.control_points, second.control_points)
    assert torch.equal(first.momenta, second.momenta)
    assert torch.equal(control_points, original_points)
    assert torch.equal(momenta.detach(), original_momenta)
    assert bool(torch.isfinite(gradient).all())
    assert torch.count_nonzero(gradient) > 0


@pytest.mark.parametrize("integrator", ["euler", "rk2"])
def test_zero_momenta_produce_stationary_shooting_and_flow(integrator: str) -> None:
    control_points, _ = _shooting_inputs()
    momenta = torch.zeros_like(control_points)
    landmarks = torch.tensor([[0.2, 0.3, 0.4], [1.5, -0.5, 0.25]], dtype=DTYPE)

    trajectory = shoot(control_points, momenta, 1.0, 4, integrator=integrator)
    flow_integrator = "euler" if integrator == "euler" else "heun"
    path = flow_points(landmarks, trajectory, 1.0, integrator=flow_integrator)

    assert torch.equal(trajectory.control_points, control_points.expand(4, -1, -1))
    assert torch.equal(trajectory.momenta, momenta.expand(4, -1, -1))
    assert torch.equal(path, landmarks.expand(4, -1, -1))


def test_deformation_energy_is_nonnegative_and_translation_invariant() -> None:
    control_points, momenta = _shooting_inputs()
    translation = torch.tensor([13.5, -7.0, 2.25], dtype=DTYPE)

    original = deformation_energy(control_points, momenta, 1.25)
    translated = deformation_energy(control_points + translation, momenta, 1.25)

    assert float(original) >= 0.0
    torch.testing.assert_close(original, translated, rtol=1e-13, atol=1e-14)


def test_surface_geometry_matches_triangle_centers_and_area() -> None:
    vertices, triangles = _square_surface()

    centers, normals = triangle_centers_and_area_normals(vertices, triangles)

    expected_centers = torch.tensor(
        [[2.0 / 3.0, 1.0 / 3.0, 0.0], [1.0 / 3.0, 2.0 / 3.0, 0.0]],
        dtype=DTYPE,
    )
    expected_normals = torch.tensor([[0.0, 0.0, 0.5], [0.0, 0.0, 0.5]], dtype=DTYPE)
    torch.testing.assert_close(centers, expected_centers, rtol=1e-14, atol=1e-14)
    torch.testing.assert_close(normals, expected_normals, rtol=1e-14, atol=1e-14)


def test_current_and_varifold_orientation_contracts() -> None:
    vertices, triangles = _square_surface()
    reversed_triangles = triangles[:, [0, 2, 1]]

    current_self = current_squared_distance(vertices, triangles, vertices, triangles, 0.8)
    varifold_self = varifold_squared_distance(vertices, triangles, vertices, triangles, 0.8)
    reversed_current = current_squared_distance(
        vertices, triangles, vertices, reversed_triangles, 0.8
    )
    reversed_varifold = varifold_squared_distance(
        vertices, triangles, vertices, reversed_triangles, 0.8
    )

    torch.testing.assert_close(current_self, torch.zeros((), dtype=DTYPE), atol=1e-14, rtol=0)
    torch.testing.assert_close(varifold_self, torch.zeros((), dtype=DTYPE), atol=1e-14, rtol=0)
    assert float(reversed_current) > 0.0
    torch.testing.assert_close(
        reversed_varifold, torch.zeros((), dtype=DTYPE), atol=1e-14, rtol=0
    )


def test_surface_distances_are_jointly_translation_invariant() -> None:
    source, triangles = _square_surface()
    target, _ = _square_surface(z=0.2)
    translation = torch.tensor([4.0, -3.0, 8.0], dtype=DTYPE)

    for distance in (current_squared_distance, varifold_squared_distance):
        original = distance(source, triangles, target, triangles, 0.8)
        translated = distance(
            source + translation,
            triangles,
            target + translation,
            triangles,
            0.8,
        )
        torch.testing.assert_close(original, translated, rtol=1e-12, atol=1e-13)


def test_varifold_distance_passes_double_precision_gradcheck() -> None:
    source, triangles = _square_surface()
    target, _ = _square_surface(z=0.2)
    source.requires_grad_(True)

    assert torch.autograd.gradcheck(
        lambda candidate: varifold_squared_distance(
            candidate, triangles, target, triangles, 0.8
        ),
        (source,),
        eps=1e-6,
        atol=1e-5,
        rtol=1e-4,
    )


@pytest.mark.parametrize("width", [0.0, -1.0, math.inf, math.nan])
def test_invalid_kernel_width_fails_explicitly(width: float) -> None:
    control_points, _ = _shooting_inputs()

    with pytest.raises(ValueError, match="kernel_width"):
        gaussian_kernel(control_points, control_points, width)


def test_invalid_shapes_dtypes_timepoints_and_integrators_fail_explicitly() -> None:
    control_points, momenta = _shooting_inputs()

    with pytest.raises(ValueError, match="shape"):
        gaussian_kernel(control_points[:, :2], control_points[:, :2], 1.0)
    with pytest.raises(TypeError, match="dtype"):
        gaussian_kernel(control_points.float(), control_points, 1.0)
    with pytest.raises(ValueError, match="at least 2"):
        shoot(control_points, momenta, 1.0, 1)
    with pytest.raises(ValueError, match="integrator"):
        shoot(control_points, momenta, 1.0, 2, integrator="bogus")


def test_invalid_triangle_connectivity_and_degenerate_faces_fail_explicitly() -> None:
    vertices, triangles = _square_surface()
    collinear = torch.tensor(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        dtype=DTYPE,
    )

    with pytest.raises(TypeError, match="int64"):
        triangle_centers_and_area_normals(vertices, triangles.to(torch.int32))
    with pytest.raises(ValueError, match="out-of-range"):
        triangle_centers_and_area_normals(
            vertices, torch.tensor([[0, 1, 99]], dtype=torch.int64)
        )
    with pytest.raises(ValueError, match="degenerate"):
        triangle_centers_and_area_normals(
            collinear, torch.tensor([[0, 1, 2]], dtype=torch.int64)
        )


def test_invalid_trajectory_fails_explicitly() -> None:
    points, _ = _shooting_inputs()
    invalid = ShootingTrajectory(
        control_points=torch.zeros((1, 2, 3), dtype=DTYPE),
        momenta=torch.zeros((1, 2, 3), dtype=DTYPE),
    )

    with pytest.raises(ValueError, match="at least two"):
        flow_points(points, invalid, 1.0)
