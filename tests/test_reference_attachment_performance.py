"""Offline cache semantics and explicit scientific resolution contracts."""

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge.reference_attachment_performance import (
    cached_target_normals,
    prepare_resolution_comparison,
    prepare_target_normals,
)


def _contract():
    return dict(
        source_hashes=dict(template="a" * 64, target="b" * 64),
        starting_field_hashes=dict(controls="c" * 64, momenta="d" * 64),
        candidate_mesh_hashes=dict(template="a" * 64, target="e" * 64),
        effective_settings=dict(
            attachment="varifold", attachment_width=0.2, deformation_width=0.5,
            noise_std=0.1, timepoints=37, precision="float64", max_iterations=600,
            convergence_tolerance=1e-4, optimizer="lbfgs",
            freeze_template=True, freeze_controls=True,
        ),
    )


def test_resolution_contract_retains_field_and_numerical_effort_without_dispatch():
    arguments = _contract()
    before = copy.deepcopy(arguments)
    plan = prepare_resolution_comparison(**arguments)
    assert arguments == before
    assert plan["effective_settings"] == before["effective_settings"]
    assert plan["starting_field_sha256"] == before["starting_field_hashes"]
    assert plan["status"] == "prepared_unqualified"
    assert plan["production_enabled"] is False
    assert "GPU/end-to-end" in plan["required_evidence"][-1]
    plan["effective_settings"]["max_iterations"] = 10
    assert arguments == before


@pytest.mark.parametrize("key", ["timepoints", "convergence_tolerance", "max_iterations"])
def test_resolution_contract_refuses_incomplete_numerical_evidence(key):
    arguments = _contract()
    del arguments["effective_settings"][key]
    with pytest.raises(ValueError, match="complete unchanged"):
        prepare_resolution_comparison(**arguments)


@pytest.mark.parametrize("section", ["source_hashes", "starting_field_hashes",
                                     "candidate_mesh_hashes"])
def test_resolution_contract_requires_actual_sha256_identity(section):
    arguments = _contract()
    arguments[section][next(iter(arguments[section]))] = "filename-is-not-identity"
    with pytest.raises(ValueError, match="SHA256"):
        prepare_resolution_comparison(**arguments)


def test_resolution_contract_refuses_same_geometry_or_unfrozen_basis():
    arguments = _contract()
    arguments["candidate_mesh_hashes"] = arguments["source_hashes"].copy()
    with pytest.raises(ValueError, match="different working geometry"):
        prepare_resolution_comparison(**arguments)
    arguments = _contract()
    arguments["effective_settings"]["freeze_controls"] = False
    with pytest.raises(ValueError, match="frozen controls"):
        prepare_resolution_comparison(**arguments)


@pytest.mark.parametrize(("key", "value"), [
    ("timepoints", True), ("timepoints", 1), ("max_iterations", 0),
    ("convergence_tolerance", float("nan")), ("noise_std", 0),
    ("precision", "automatic"),
])
def test_resolution_contract_rejects_undefined_or_invalid_effort(key, value):
    arguments = _contract()
    arguments["effective_settings"][key] = value
    with pytest.raises(ValueError):
        prepare_resolution_comparison(**arguments)


def test_fixed_target_cache_is_exact_and_actually_reuses_preparation():
    torch = pytest.importorskip("torch")
    normals = torch.tensor(((1., 2., 3.), (3., 4., 2.)), dtype=torch.float64)
    target = SimpleNamespace()
    expected = prepare_target_normals(normals, torch)
    first = cached_target_normals(target, normals, torch)
    second = cached_target_normals(target, normals, torch)
    assert all(torch.equal(a, b) for a, b in zip(expected, first, strict=True))
    assert second is first


def test_cache_invalidates_in_place_edits_and_replaced_normals():
    torch = pytest.importorskip("torch")
    normals = torch.tensor(((1., 2., 3.), (3., 4., 2.)), dtype=torch.float64)
    target = SimpleNamespace()
    first = cached_target_normals(target, normals, torch)
    normals.add_(0.25)
    second = cached_target_normals(target, normals, torch)
    assert second is not first
    assert all(torch.equal(a, b) for a, b in zip(
        second, prepare_target_normals(normals, torch), strict=True))
    third = cached_target_normals(target, normals.clone(), torch)
    assert third is not second
    assert all(torch.equal(a, b) for a, b in zip(second, third, strict=True))


def test_graph_bearing_target_is_never_detached_or_reused():
    torch = pytest.importorskip("torch")
    normals = torch.tensor(((1., 2., 3.), (3., 4., 2.)), dtype=torch.float64,
                           requires_grad=True)
    target = SimpleNamespace()
    first = cached_target_normals(target, normals, torch)
    second = cached_target_normals(target, normals, torch)
    assert first is not second
    expected = prepare_target_normals(normals, torch)
    actual_gradient, = torch.autograd.grad(first[0].sum() + first[1].sum(), normals)
    expected_gradient, = torch.autograd.grad(expected[0].sum() + expected[1].sum(), normals)
    assert torch.equal(actual_gradient, expected_gradient)


def _multires_tool():
    path = Path(__file__).resolve().parents[1] / "tools/probe_reference_multiresolution.py"
    spec = importlib.util.spec_from_file_location("offline_multiresolution_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multires_synthetic_surfaces_are_nested_and_keep_outward_connectivity():
    np = pytest.importorskip("numpy")
    tool = _multires_tool()
    coarse, coarse_faces = tool.sphere(2)
    full, faces = tool.sphere(3)
    assert coarse_faces.shape == (128, 3)
    assert faces.shape == (512, 3)
    assert np.array_equal(full[:len(coarse)], coarse)
    triangles = full[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0],
                       triangles[:, 2] - triangles[:, 0])
    assert np.all(np.sum(normals * triangles.mean(axis=1), axis=1) > 0)
    assert np.array_equal(tool.sample_surface(full, faces), tool.sample_surface(full, faces))


def test_multires_quality_uses_triangle_interiors_instead_of_nearest_vertices():
    np = pytest.importorskip("numpy")
    pytest.importorskip("vtk")
    tool = _multires_tool()
    vertices = np.array(((0., 0., 0.), (2., 0., 0.), (0., 2., 0.)))
    faces = np.array(((0, 1, 2),))
    # Both projected points are triangle interiors, away from any vertex.
    measured = tool.point_triangle_distances(((0.5, 0.5, 0.25), (0.4, 0.3, -0.5)),
                                             vertices, faces)
    assert measured == pytest.approx((0.25, 0.5), abs=1e-14)

