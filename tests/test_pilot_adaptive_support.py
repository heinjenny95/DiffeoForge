"""A common support follows accepted demand and source scale, never a fixed target."""

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge.pilot_adaptive_support import select_sites
from diffeoforge.pilot_multiscale import LEGACY_VERSION, VERSION, specification


def test_small_covered_source_keeps_accepted_basis_without_padding():
    v, f = cube()
    prefix = np.asarray(v, float)
    points, reason = select_sites(prefix, v, f, kernel_width=10., required_controls=len(prefix))
    assert np.array_equal(points, prefix)
    assert reason['source_added_sites'] == 0 and reason['count'] < 2000
    assert reason['retained_sites'] == len(prefix)


def test_additions_follow_both_accepted_demand_and_original_surface_coverage():
    v, f = cube()
    prefix = np.asarray(v[:2], float)
    low, a = select_sites(prefix, v, f, kernel_width=10., required_controls=30)
    fine, b = select_sites(prefix, v, f, kernel_width=.3, required_controls=30)
    assert len(low) == 30 < len(fine) < 2000
    assert np.array_equal(fine[:len(prefix)], prefix)
    # Independently check every actual source vertex; measured coverage is a
    # sampled preparation criterion, never a claim of fit quality/convergence.
    distance = np.linalg.norm(np.asarray(v)[:, None] - fine[None], axis=2).min(axis=1)
    assert distance.max() <= .3
    assert b['maximum_candidate_support_distance'] <= b['coverage_radius']
    assert a['required_controls'] == b['required_controls'] == 30
    assert not b['target_geometry_used'] and not b['momenta_transferred']


def test_same_geometry_and_units_produce_reproducible_scaled_support():
    v, f = cube()
    prefix = np.asarray(v[:2], float)
    a, ra = select_sites(prefix, v, f, kernel_width=.3, required_controls=30)
    b, rb = select_sites(prefix * 2, np.asarray(v) * 2, f,
                         kernel_width=.6, required_controls=30)
    assert np.array_equal(a * 2, b) and ra['count'] == rb['count']
    c, rc = select_sites(prefix, v, f, kernel_width=.3, required_controls=30)
    assert np.array_equal(a, c) and ra == rc


def test_over_budget_coverage_fails_instead_of_returning_2000_as_adequate():
    v, f = cube()
    with pytest.raises(ValueError, match='coverage exceed'):
        select_sites(np.asarray(v[:1]), v, f, kernel_width=1e-6, required_controls=8)


@pytest.mark.parametrize('width,count', [
    (0., 30), (np.nan, 30), (True, 30), (.3, True), (.3, 2001)])
def test_invalid_selection_inputs_fail_without_silent_reduction(width, count):
    v, f = cube()
    with pytest.raises(ValueError):
        select_sites(np.asarray(v[:1]), v, f, kernel_width=width, required_controls=count)


def test_new_specification_has_bound_selected_count_but_legacy_keeps_exact_fixed_contract():
    values = dict(attachment_kernel_width=.1, deformation_kernel_width=.4,
                  initial_control_point_spacing=.4, noise_std=.025)
    old = specification(values, precision='float32', tolerance=1e-6,
                        required_controls=50, version=LEGACY_VERSION)
    new = specification(values, precision='float32', tolerance=1e-6,
                        required_controls=50, controls=79)
    assert old['version'] == LEGACY_VERSION and old['controls'] == 2000
    assert new['version'] == VERSION and new['controls'] == 79
    assert old['stages'] == new['stages']
    assert old['maximum_total_accepted_steps'] == new['maximum_total_accepted_steps'] == 240
    with pytest.raises(ValueError):
        specification(values, precision='float32', tolerance=1e-6,
                      required_controls=50, controls=49)
