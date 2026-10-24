"""Fail-closed checks for the public cross-platform observation comparator."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "platform_compatibility", ROOT / "tools/platform_compatibility.py"
)
assert spec is not None and spec.loader is not None
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def _observations() -> list[dict]:
    state = {key: np.ones(shape).tolist() for key, shape in compat.STATE_SHAPES.items()}
    base = {
        "protocol": compat.PROTOCOL,
        "source_commit": "a" * 40,
        "fixture_hashes": {name: "b" * 64 for name in compat.EXPECTED_FIXTURES},
        "engine": "1.8",
        "package_sha256": "c" * 64,
        "versions": {"numpy": "2.5.1", "torch": "2.13.0"},
        "boundary": compat.BOUNDARY,
        "checks": dict.fromkeys(
            (
                "worker_completed",
                "worker_cancelled",
                "result_reopened",
                "continuation_verified",
                "same_platform_resume",
                "dense_blockwise",
                "fixture_unchanged",
            ),
            True,
        ),
        "states": {
            scenario: copy.deepcopy(state) for scenario in ("dense", "blockwise", "continued")
        },
    }
    return [{**copy.deepcopy(base), "platform": name} for name in sorted(compat.EXPECTED_PLATFORMS)]


def test_cross_platform_comparison_checks_all_pairs_with_fixed_tolerance() -> None:
    observations = _observations()
    observations[0]["states"]["dense"]["objective"][0] += 1e-10
    result = compat.compare_observations(observations)
    assert result["status"] == "pass"
    assert len(result["comparisons_max_abs"]) == 3
    assert result["rtol"] == 1e-8
    assert result["atol"] == 1e-10


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra"])
def test_incomplete_platform_sets_never_pass(kind: str) -> None:
    observations = _observations()
    if kind == "missing":
        observations.pop()
    elif kind == "duplicate":
        observations[1] = copy.deepcopy(observations[0])
    else:
        observations.append(copy.deepcopy(observations[0]))
    with pytest.raises(ValueError):
        compat.compare_observations(observations)


@pytest.mark.parametrize(
    "field", ["source_commit", "fixture_hashes", "engine", "versions", "package_sha256"]
)
def test_incompatible_provenance_is_not_numerical_evidence(field: str) -> None:
    observations = _observations()
    observations[0][field] = "different"
    with pytest.raises(ValueError, match="provenance"):
        compat.compare_observations(observations)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", 10.0])
def test_invalid_or_materially_different_values_fail(bad) -> None:
    observations = _observations()
    observations[0]["states"]["dense"]["objective"][0] = bad
    with pytest.raises(ValueError):
        compat.compare_observations(observations)


def test_missing_local_check_and_wrong_geometry_shape_fail() -> None:
    observations = _observations()
    observations[0]["checks"].pop("worker_cancelled")
    with pytest.raises(ValueError, match="local check"):
        compat.compare_observations(observations)
    observations = _observations()
    observations[0]["states"]["continued"]["momenta"].pop()
    with pytest.raises(ValueError, match="shape"):
        compat.compare_observations(observations)


def test_identically_incomplete_fixture_provenance_fails() -> None:
    observations = _observations()
    for observation in observations:
        observation["fixture_hashes"].pop("template.vtk")
    with pytest.raises(ValueError, match="fixture provenance"):
        compat.compare_observations(observations)


def test_observation_sidecar_detects_changed_bytes_and_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "observation.json"
    compat._write(path, _observations()[0])
    assert compat._read(path)["protocol"] == compat.PROTOCOL
    with pytest.raises(FileExistsError):
        compat._write(path, {})
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        compat._read(path)
