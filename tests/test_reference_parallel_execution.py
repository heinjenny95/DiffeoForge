import json
from types import SimpleNamespace

import pytest

from diffeoforge.reference_parallel_execution import (
    DeviceReduction,
    route_kernels,
    validate_cache_topology,
    validate_devices,
    validate_model,
)


@pytest.mark.parametrize("devices", [(0,), (0, 0), (-1, 1), (True, 1), (0, "1")])
def test_invalid_device_contract(devices):
    with pytest.raises(ValueError):
        validate_devices(devices)


def test_noncontiguous_visible_devices_are_explicit():
    assert validate_devices([1, 2, 3]) == (1, 2, 3)


def model():
    return SimpleNamespace(name="DeterministicAtlas", number_of_processes=4,
        freeze_template=True, freeze_control_points=True, freeze_momenta=False,
        tensor_scalar_type="double", gpu_mode="kernel")


@pytest.mark.parametrize("field,value", [
    ("name", "BayesianAtlas"), ("number_of_processes", 1), ("freeze_template", False),
    ("freeze_control_points", False), ("freeze_momenta", True),
    ("tensor_scalar_type", "float"), ("gpu_mode", "full"),
])
def test_incompatible_scientific_context_rejected(field, value):
    m = model()
    setattr(m, field, value)
    with pytest.raises(RuntimeError):
        validate_model(m, (0, 1, 2, 3), "double", "kernel")


def test_qualified_context():
    validate_model(model(), (0, 1, 2, 3), "double", "kernel")


def test_device_override_preserves_arguments_and_native_return():
    calls = []
    result = object()

    def native(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    assert DeviceReduction(native, 3)("x", "y", device_id=-1, axis=1) is result
    assert calls == [(("x", "y"), {"device_id": 3, "backend": "GPU_1D", "axis": 1})]


def test_aliases_are_routed_only_once():
    k = SimpleNamespace(**{n: [lambda *a, **kw: kw["device_id"]] for n in (
        "gaussian_convolve", "point_cloud_convolve", "varifold_convolve",
        "gaussian_convolve_gradient_x")})
    assert route_kernels([k, k], 2) == 4
    assert k.gaussian_convolve[0](device_id=-1) == 2
    with pytest.raises(RuntimeError, match="Duplicate"):
        route_kernels([k], 2)


def test_unsupported_kernel_layout_fails_closed():
    with pytest.raises(RuntimeError, match="Unsupported"):
        route_kernels([SimpleNamespace()], 0)


def test_unqualified_compiled_cache_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="prospectively"):
        validate_cache_topology(tmp_path, 4)


def test_single_gpu_cache_cannot_route_four_devices(tmp_path):
    (tmp_path / "device-topology.json").write_text(json.dumps({"visible_device_count": 1}))
    with pytest.raises(RuntimeError, match="topology"):
        validate_cache_topology(tmp_path, 4)


def test_four_gpu_cache_contract(tmp_path):
    (tmp_path / "device-topology.json").write_text(json.dumps({"visible_device_count": 4}))
    validate_cache_topology(tmp_path, 4)
