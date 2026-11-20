"""Generic binding and mathematical-equivalence checks; no study data."""

import ast
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_reference_finite_accepted_guard import config_fixture, render

from diffeoforge.config import ConfigurationError, validate_schema
from diffeoforge.reference_finite_accepted_guard import mark_new_configuration
from diffeoforge.reference_surface_gather import DECLARATION, SOURCE


def test_new_trial_declares_and_protects_exact_adapter(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    validate_schema(config)
    assert config["project"]["parameter_provenance"]["surface_gather"] == DECLARATION
    files = render(config)
    assert files["cpu_surface_gather.py"] == SOURCE
    assert json.loads(files["guard-policy.json"])["surface_gather"] == dict(
        declaration=DECLARATION, sha256=hashlib.sha256(SOURCE).hexdigest()
    )
    ast.parse(SOURCE, feature_version=(3, 8))


def test_existing_prepared_guard_does_not_silently_receive_new_math_path(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    del config["project"]["parameter_provenance"]["surface_gather"]
    files = render(config)
    assert "cpu_surface_gather.py" not in files
    assert "surface_gather" not in json.loads(files["guard-policy.json"])
    assert b"_df_gather_install" not in files["sitecustomize.py"]


def test_unknown_adapter_version_is_rejected(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    config["project"]["parameter_provenance"]["surface_gather"]["version"] = "unknown"
    with pytest.raises(ConfigurationError):
        validate_schema(config)
    with pytest.raises(ConfigurationError, match="Unsupported deterministic"):
        render(config)


def generated_function():
    torch = pytest.importorskip("torch")
    # Compile the actual nested function from the shipped source, not a rewritten copy.
    install = next(n for n in ast.parse(SOURCE).body if isinstance(n, ast.FunctionDef)
                   and n.name == "install")
    selected = next(n for n in install.body if isinstance(n, ast.FunctionDef))
    namespace = dict(torch=torch, default=SimpleNamespace(
        tensor_scalar_type=torch.float32, tensor_integer_type=torch.int64),
        utilities=SimpleNamespace(
            move_data=lambda a, dtype, device: a.to(dtype=dtype, device=device)))
    exec(compile(ast.Module(body=[selected], type_ignores=[]), "cpu_surface_gather.py", "exec"),
         namespace)
    return torch, namespace


@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_exact_forward_geometry_and_repeated_backward(dtype):
    torch, namespace = generated_function()
    dtype = getattr(torch, dtype)
    generator = torch.Generator().manual_seed(1973)
    p = torch.randn((12, 3), dtype=dtype, generator=generator)
    indices = torch.randint(0, 12, (30, 3), generator=generator)
    a, b, c = (p[indices[:, i]] for i in range(3))
    expected = ((a + b + c) / 3., torch.cross(b - a, c - a, dim=1) / 2)
    reference = None
    for _ in range(12):
        points = p.clone().requires_grad_(True)
        centers, normals = namespace["selected"](points, indices, tensor_scalar_type=dtype)
        assert torch.equal(centers, expected[0]) and torch.equal(normals, expected[1])
        (centers.square().sum() + normals.square().sum()).backward()
        gradient = points.grad.numpy().copy()
        if reference is None:
            reference = gradient
        assert reference.tobytes() == gradient.tobytes()


def test_gradient_matches_independent_finite_differences():
    torch, namespace = generated_function()
    points = torch.tensor([[0., 0., 0.], [1., .1, 0.], [.1, 1., .2], [.4, .3, 1.]],
                          dtype=torch.float64, requires_grad=True)
    triangles = torch.tensor([[0, 1, 2], [0, 1, 3], [1, 2, 3]], dtype=torch.int64)

    def evaluate(p):
        centers, normals = namespace["selected"](p, triangles, tensor_scalar_type=torch.float64)
        return centers.square().sum() + normals.square().sum()

    assert torch.autograd.gradcheck(evaluate, (points,), eps=1e-6, atol=1e-6, rtol=1e-5)
    gradient, = torch.autograd.grad(evaluate(points), points)
    assert np.isfinite(gradient.numpy()).all()


def test_non_cpu_path_is_delegated_without_conversion():
    _torch, namespace = generated_function()
    calls = []
    namespace["original"] = lambda *args: calls.append(args) or ("native", "unchanged")
    assert namespace["selected"](None, None, device="cuda:0") == ("native", "unchanged")
    assert calls[0][0:2] == (None, None) and calls[0][-1] == "cuda:0"
