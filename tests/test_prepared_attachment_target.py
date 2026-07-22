from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
engine = pytest.importorskip("diffeoforge.engine")

DTYPE = torch.float64


def _tetrahedron(offset: tuple[float, float, float] = (0.0, 0.0, 0.0)):
    vertices = torch.tensor(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
        dtype=DTYPE,
    )
    vertices = vertices + torch.tensor(offset, dtype=DTYPE)
    triangles = torch.tensor(
        ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
        dtype=torch.int64,
    )
    return vertices, triangles


@pytest.mark.parametrize(
    ("attachment_type", "distance_function"),
    [
        ("current", engine.current_squared_distance),
        ("varifold", engine.varifold_squared_distance),
    ],
)
def test_prepared_dense_target_preserves_value_and_source_gradient(
    attachment_type,
    distance_function,
) -> None:
    source, triangles = _tetrahedron()
    target, target_triangles = _tetrahedron((0.13, -0.08, 0.04))
    dense_source = source.clone().requires_grad_(True)
    prepared_source = source.clone().requires_grad_(True)

    dense = distance_function(
        dense_source,
        triangles,
        target,
        target_triangles,
        0.7,
    )
    prepared_target = engine.prepare_surface_attachment_target(
        target,
        target_triangles,
        0.7,
        attachment_type=attachment_type,
    )
    prepared = engine.surface_squared_distance_to_prepared_target(
        prepared_source,
        triangles,
        prepared_target,
    )
    (dense_gradient,) = torch.autograd.grad(dense, dense_source)
    (prepared_gradient,) = torch.autograd.grad(prepared, prepared_source)

    torch.testing.assert_close(prepared, dense, rtol=0.0, atol=0.0)
    torch.testing.assert_close(prepared_gradient, dense_gradient, rtol=0.0, atol=0.0)
    assert prepared_target.self_inner_product.requires_grad is False


@pytest.mark.parametrize("attachment_type", ["current", "varifold"])
@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_prepared_blockwise_target_preserves_value_and_source_gradient(
    attachment_type,
    autograd_strategy,
) -> None:
    source, triangles = _tetrahedron()
    target, target_triangles = _tetrahedron((0.13, -0.08, 0.04))
    dense_source = source.clone().requires_grad_(True)
    prepared_source = source.clone().requires_grad_(True)
    plan = engine.GaussianTilePlan(3, 2, autograd_strategy)
    distance_function = (
        engine.current_squared_distance_blockwise
        if attachment_type == "current"
        else engine.varifold_squared_distance_blockwise
    )

    dense = distance_function(
        dense_source,
        triangles,
        target,
        target_triangles,
        0.7,
        query_tile_size=plan.query_rows,
        source_tile_size=plan.source_rows,
        autograd_strategy=plan.autograd_strategy,
    )
    prepared_target = engine.prepare_surface_attachment_target(
        target,
        target_triangles,
        0.7,
        attachment_type=attachment_type,
        gaussian_tile_plan=plan,
    )
    prepared = engine.surface_squared_distance_to_prepared_target(
        prepared_source,
        triangles,
        prepared_target,
    )
    (dense_gradient,) = torch.autograd.grad(dense, dense_source)
    (prepared_gradient,) = torch.autograd.grad(prepared, prepared_source)

    torch.testing.assert_close(prepared, dense, rtol=0.0, atol=0.0)
    torch.testing.assert_close(prepared_gradient, dense_gradient, rtol=0.0, atol=0.0)


def test_subject_objective_rejects_a_prepared_target_from_another_tensor() -> None:
    template, triangles = _tetrahedron()
    target, target_triangles = _tetrahedron((0.1, 0.0, 0.0))
    prepared_target = engine.prepare_surface_attachment_target(
        target,
        target_triangles,
        0.7,
    )

    with pytest.raises(ValueError, match="does not match"):
        engine.subject_objective(
            template,
            triangles,
            target.clone(),
            target_triangles,
            template[:2].clone(),
            torch.zeros((2, 3), dtype=DTYPE),
            deformation_kernel_width=0.8,
            attachment_kernel_width=0.7,
            noise_variance=0.1,
            number_of_time_points=2,
            prepared_target=prepared_target,
        )


def test_prepared_target_rejects_in_place_target_mutation() -> None:
    source, triangles = _tetrahedron()
    target, target_triangles = _tetrahedron((0.1, 0.0, 0.0))
    prepared_target = engine.prepare_surface_attachment_target(
        target,
        target_triangles,
        0.7,
    )
    target.add_(0.01)

    with pytest.raises(RuntimeError, match="stale"):
        engine.surface_squared_distance_to_prepared_target(
            source,
            triangles,
            prepared_target,
        )
