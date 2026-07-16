from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

GaussianTilePlan = engine.GaussianTilePlan
current_squared_distance = engine.current_squared_distance
current_squared_distance_blockwise = engine.current_squared_distance_blockwise
gaussian_convolve = engine.gaussian_convolve
gaussian_convolve_blockwise = engine.gaussian_convolve_blockwise
gaussian_convolve_gradient = engine.gaussian_convolve_gradient
gaussian_convolve_gradient_blockwise = engine.gaussian_convolve_gradient_blockwise
varifold_squared_distance = engine.varifold_squared_distance
varifold_squared_distance_blockwise = engine.varifold_squared_distance_blockwise

from diffeoforge.mesh import read_vtk_polydata  # noqa: E402

DTYPE = torch.float64
ROOT = Path(__file__).parents[1]


def _convolution_inputs() -> tuple[torch.Tensor, ...]:
    generator = torch.Generator().manual_seed(20260716)
    x = torch.randn((7, 3), dtype=DTYPE, generator=generator)
    y = torch.randn((5, 3), dtype=DTYPE, generator=generator)
    left = torch.randn((7, 4), dtype=DTYPE, generator=generator)
    right = torch.randn((5, 4), dtype=DTYPE, generator=generator)
    return x, y, left, right


def _tetrahedron() -> tuple[torch.Tensor, torch.Tensor]:
    vertices = torch.tensor(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 0.9, 0.0],
            [0.5, 0.3, 0.8],
        ],
        dtype=DTYPE,
    )
    triangles = torch.tensor(
        [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
        dtype=torch.int64,
    )
    return vertices, triangles


@pytest.mark.parametrize(
    ("query_tile_size", "source_tile_size"),
    [(1, 1), (2, 3), (5, 2), (99, 99)],
)
def test_blockwise_convolution_matches_dense_forward_and_autograd(
    query_tile_size: int,
    source_tile_size: int,
) -> None:
    inputs = _convolution_inputs()
    dense_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)
    block_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)

    dense = gaussian_convolve(dense_inputs[0], dense_inputs[1], dense_inputs[3], 1.3)
    blockwise = gaussian_convolve_blockwise(
        block_inputs[0],
        block_inputs[1],
        block_inputs[3],
        1.3,
        query_tile_size=query_tile_size,
        source_tile_size=source_tile_size,
    )
    dense_gradients = torch.autograd.grad(dense.square().sum(), dense_inputs[:2] + dense_inputs[3:])
    block_gradients = torch.autograd.grad(
        blockwise.square().sum(),
        block_inputs[:2] + block_inputs[3:],
    )

    torch.testing.assert_close(blockwise, dense, rtol=2e-13, atol=2e-14)
    for actual, expected in zip(block_gradients, dense_gradients, strict=True):
        torch.testing.assert_close(actual, expected, rtol=2e-12, atol=2e-13)


def test_blockwise_explicit_x_gradient_matches_dense_and_second_derivatives() -> None:
    inputs = _convolution_inputs()
    dense_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)
    block_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)

    dense = gaussian_convolve_gradient(
        dense_inputs[2],
        dense_inputs[0],
        dense_inputs[1],
        dense_inputs[3],
        0.9,
    )
    blockwise = gaussian_convolve_gradient_blockwise(
        block_inputs[2],
        block_inputs[0],
        block_inputs[1],
        block_inputs[3],
        0.9,
        query_tile_size=3,
        source_tile_size=2,
    )
    dense_gradients = torch.autograd.grad(dense.square().sum(), dense_inputs)
    block_gradients = torch.autograd.grad(blockwise.square().sum(), block_inputs)

    torch.testing.assert_close(blockwise, dense, rtol=2e-13, atol=2e-13)
    for actual, expected in zip(block_gradients, dense_gradients, strict=True):
        torch.testing.assert_close(actual, expected, rtol=3e-12, atol=3e-12)


@pytest.mark.parametrize(
    ("dense_distance", "blockwise_distance"),
    [
        (current_squared_distance, current_squared_distance_blockwise),
        (varifold_squared_distance, varifold_squared_distance_blockwise),
    ],
)
def test_blockwise_surface_distances_match_dense_forward_and_gradient(
    dense_distance,
    blockwise_distance,
) -> None:
    source, triangles = _tetrahedron()
    target = source.clone()
    target[3] += torch.tensor([0.03, -0.02, 0.04], dtype=DTYPE)
    dense_source = source.clone().requires_grad_(True)
    block_source = source.clone().requires_grad_(True)

    dense = dense_distance(dense_source, triangles, target, triangles, 0.75)
    blockwise = blockwise_distance(
        block_source,
        triangles,
        target,
        triangles,
        0.75,
        query_tile_size=3,
        source_tile_size=2,
    )
    (dense_gradient,) = torch.autograd.grad(dense, dense_source)
    (block_gradient,) = torch.autograd.grad(blockwise, block_source)

    torch.testing.assert_close(blockwise, dense, rtol=2e-12, atol=2e-13)
    torch.testing.assert_close(block_gradient, dense_gradient, rtol=3e-11, atol=3e-12)


@pytest.mark.parametrize(
    ("dense_distance", "blockwise_distance"),
    [
        (current_squared_distance, current_squared_distance_blockwise),
        (varifold_squared_distance, varifold_squared_distance_blockwise),
    ],
)
def test_blockwise_surface_forward_matches_dense_on_cc0_320_face_meshes(
    dense_distance,
    blockwise_distance,
) -> None:
    directory = ROOT / "examples" / "synthetic" / "meshes"
    source_mesh = read_vtk_polydata(directory / "template.vtk")
    target_mesh = read_vtk_polydata(directory / "subject-01.vtk")
    source = torch.tensor(source_mesh.vertices, dtype=DTYPE)
    source_triangles = torch.tensor(source_mesh.triangles, dtype=torch.int64)
    target = torch.tensor(target_mesh.vertices, dtype=DTYPE)
    target_triangles = torch.tensor(target_mesh.triangles, dtype=torch.int64)

    dense = dense_distance(source, source_triangles, target, target_triangles, 0.45)
    blockwise = blockwise_distance(
        source,
        source_triangles,
        target,
        target_triangles,
        0.45,
        query_tile_size=17,
        source_tile_size=23,
    )

    torch.testing.assert_close(blockwise, dense, rtol=2e-11, atol=2e-12)


def test_blockwise_varifold_orientation_and_joint_translation_contracts() -> None:
    vertices, triangles = _tetrahedron()
    reversed_triangles = triangles[:, [0, 2, 1]]
    translation = torch.tensor([7.0, -3.0, 2.5], dtype=DTYPE)

    reversed_current = current_squared_distance_blockwise(
        vertices,
        triangles,
        vertices,
        reversed_triangles,
        0.8,
        query_tile_size=3,
        source_tile_size=2,
    )
    reversed_varifold = varifold_squared_distance_blockwise(
        vertices,
        triangles,
        vertices,
        reversed_triangles,
        0.8,
        query_tile_size=3,
        source_tile_size=2,
    )
    translated = varifold_squared_distance_blockwise(
        vertices + translation,
        triangles,
        vertices + translation,
        triangles,
        0.8,
        query_tile_size=3,
        source_tile_size=2,
    )

    assert float(reversed_current) > 0
    torch.testing.assert_close(reversed_varifold, torch.zeros((), dtype=DTYPE), atol=1e-13, rtol=0)
    torch.testing.assert_close(translated, torch.zeros((), dtype=DTYPE), atol=1e-13, rtol=0)


def test_every_observed_gaussian_tile_respects_explicit_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.engine.dense as dense_module

    vertices, triangles = _tetrahedron()
    observed = []
    original = dense_module._gaussian_tile

    def observe(x, y, width):
        observed.append((x.shape[0], y.shape[0]))
        return original(x, y, width)

    monkeypatch.setattr(dense_module, "_gaussian_tile", observe)
    value = varifold_squared_distance_blockwise(
        vertices,
        triangles,
        vertices + 0.01,
        triangles,
        0.8,
        query_tile_size=3,
        source_tile_size=2,
    )

    assert torch.isfinite(value)
    assert observed
    assert max(query for query, _ in observed) <= 3
    assert max(source for _, source in observed) <= 2
    assert (1, 2) in observed


def test_tile_plan_has_exact_float64_payload_and_rejects_invalid_bounds() -> None:
    plan = GaussianTilePlan(query_rows=3, source_rows=2)

    assert plan.maximum_xyz_difference_tensor_bytes() == 3 * 2 * 3 * 8
    assert plan.maximum_xyz_difference_tensor_bytes(bytes_per_float=4) == 3 * 2 * 3 * 4
    with pytest.raises(ValueError, match="at least 1"):
        GaussianTilePlan(0, 2)
    with pytest.raises(TypeError, match="integer"):
        GaussianTilePlan(True, 2)
    with pytest.raises(TypeError, match="bytes_per_float"):
        plan.maximum_xyz_difference_tensor_bytes(bytes_per_float=True)
