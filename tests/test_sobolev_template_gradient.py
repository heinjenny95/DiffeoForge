from __future__ import annotations

import pytest
import torch

from diffeoforge import engine


def _inputs() -> tuple[torch.Tensor, torch.Tensor]:
    template = torch.tensor(
        [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.0, 0.75, 0.0]],
        dtype=torch.float64,
    )
    gradient = torch.tensor(
        [[1.0, -0.5, 0.25], [-0.25, 0.75, 1.0], [0.5, 0.25, -0.75]],
        dtype=torch.float64,
    )
    return template, gradient


def test_sobolev_template_gradient_matches_declared_gaussian_convolution() -> None:
    template, gradient = _inputs()
    observed = engine.sobolev_template_gradient(
        template,
        gradient,
        deformation_kernel_width=0.4,
        kernel_width_ratio=1.5,
    )
    expected = engine.gaussian_kernel(template, template, 0.6) @ gradient

    torch.testing.assert_close(observed, expected, rtol=1e-13, atol=1e-13)
    assert observed.requires_grad is False
    assert observed.dtype == template.dtype
    assert observed.device == template.device


@pytest.mark.parametrize("autograd_strategy", ["standard", "recompute"])
def test_sobolev_template_gradient_has_exact_dense_blockwise_parity(
    autograd_strategy: str,
) -> None:
    template, gradient = _inputs()
    dense = engine.sobolev_template_gradient(
        template,
        gradient,
        deformation_kernel_width=0.4,
        kernel_width_ratio=1.5,
    )
    blockwise = engine.sobolev_template_gradient(
        template,
        gradient,
        deformation_kernel_width=0.4,
        kernel_width_ratio=1.5,
        gaussian_tile_plan=engine.GaussianTilePlan(2, 1, autograd_strategy),
    )

    torch.testing.assert_close(blockwise, dense, rtol=1e-13, atol=1e-13)


def test_sobolev_template_gradient_does_not_mutate_inputs() -> None:
    template, gradient = _inputs()
    expected_template = template.clone()
    expected_gradient = gradient.clone()

    engine.sobolev_template_gradient(
        template,
        gradient,
        deformation_kernel_width=0.4,
    )

    assert torch.equal(template, expected_template)
    assert torch.equal(gradient, expected_gradient)


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"deformation_kernel_width": True}, TypeError, "deformation_kernel_width"),
        ({"deformation_kernel_width": 0.0}, ValueError, "deformation_kernel_width"),
        (
            {"deformation_kernel_width": 0.4, "kernel_width_ratio": False},
            TypeError,
            "kernel_width_ratio",
        ),
        (
            {"deformation_kernel_width": 0.4, "kernel_width_ratio": 0.0},
            ValueError,
            "kernel_width_ratio",
        ),
        (
            {"deformation_kernel_width": 0.4, "gaussian_tile_plan": "automatic"},
            TypeError,
            "gaussian_tile_plan",
        ),
    ],
)
def test_sobolev_template_gradient_rejects_ambiguous_settings(
    kwargs: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    template, gradient = _inputs()
    with pytest.raises(error, match=message):
        engine.sobolev_template_gradient(template, gradient, **kwargs)
