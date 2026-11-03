"""Generic deterministic support and finite prospective effort, no native runs."""

from copy import deepcopy

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge.pilot_multiscale import merge_sites, source_supported_sites, specification

BASE = dict(
    attachment_kernel_width=0.1,
    deformation_kernel_width=0.4,
    initial_control_point_spacing=0.4,
    noise_std=0.025,
)


def test_prospective_two_stages_keep_one_basis_and_do_not_relax_tolerance():
    before = deepcopy(BASE)
    result = specification(BASE, precision="float32", tolerance=1e-7, required_controls=602)
    a, b = result["stages"]
    assert a["values"]["attachment_kernel_width"] == 0.4
    assert b["values"]["attachment_kernel_width"] == 0.2 * 0.45
    assert a["values"]["deformation_kernel_width"] == b["values"]["deformation_kernel_width"] == 0.2
    assert a["values"]["noise_std"] == b["values"]["noise_std"] == 0.0125
    assert [a["maximum_iterations"], b["maximum_iterations"]] == [120, 120]
    assert result["tolerance"] == 1e-7 and result["maximum_native_stages"] == 2
    assert result["maximum_total_accepted_steps"] == 240
    assert not result["optimizer_history_restored"] and not result["approval_transferred"]
    assert not result["automatic_recovery"] and BASE == before


@pytest.mark.parametrize("precision,required", [("float64", 602), ("float32", 2001)])
def test_resource_or_precision_limits_do_not_silently_lower_the_requested_model(
    precision, required
):
    with pytest.raises(ValueError):
        specification(BASE, precision=precision, tolerance=1e-6, required_controls=required)


def test_site_union_keeps_original_bits_and_cannot_sum_fields():
    prefix = np.array([[0.0, 0, 0], [1, 1, 1]])
    blocks = [prefix + 1e-8, np.array([[2.0, 1, 0]])]
    result, proof = merge_sites(prefix, blocks, diagonal=4.0)
    assert len(result) == 3 and np.array_equal(result[:2], prefix)
    assert proof["added_per_block"] == [0, 1] and not proof["momenta_transferred"]
    assert np.array_equal(prefix, [[0, 0, 0], [1, 1, 1]])


def test_original_source_sampling_is_deterministic_preserves_sites_and_ignores_targets():
    v, f = cube()
    prefix = np.array([[0.0, 0, 0], [1, 1, 1]])
    before = np.array(v).copy()
    a, proof = source_supported_sites(prefix, v, f, target_count=24)
    b, second = source_supported_sites(prefix, v, f, target_count=24)
    assert np.array_equal(a, b) and proof == second
    assert np.array_equal(a[:2], prefix) and np.array_equal(v, before)
    assert (
        proof["maximum_candidate_support_distance"]
        < proof["maximum_candidate_support_distance_before"]
    )
    assert not proof["target_geometry_used"] and not proof["momenta_transferred"]
    assert len(np.unique(a, axis=0)) == 24


def test_source_candidate_budget_and_invalid_geometry_fail_before_generation():
    v, f = cube()
    prefix = np.array([[0.0, 0, 0]])
    with pytest.raises(ValueError):
        source_supported_sites(prefix, v, f, target_count=2001)
    with pytest.raises(ValueError):
        source_supported_sites(prefix, np.asarray(v) * np.nan, f, target_count=24)
