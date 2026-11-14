"""Probe the incoming material frame before reusing controls on a new area."""

from types import SimpleNamespace

import numpy as np
import pytest
from test_regional_material import geometry

from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save
from diffeoforge.regional_warm_support import assess


def case(tmp_path, *, controls_at_output):
    source, faces, target, tf, regions = geometry()
    numerical = source.copy()
    numerical[:8, 0] += 1.4
    for name, v, f in [('source', source, faces), ('numerical', numerical, faces),
                       ('retained', source, faces), ('target', target, tf)]:
        _save(tmp_path/f'{name}.vtk', v, f)
    cp = numerical[:8] if controls_at_output else source[:8]
    path = tmp_path/'controls.txt'
    np.savetxt(path, cp, fmt='%.17g')
    record = dict(refinement=dict(initialization='learned'),
                  controls=dict(copy=path.name, sha256=sha256_file(path)))
    residual = dict(control_coverage=dict(version='source-target-coverage-v1',
                                         maximum_local_support_distance=.05))
    return SimpleNamespace(record=record, residual=residual, regions=regions,
        fixed=[dict(center=[0., 0., 0.], radius=.3, purpose='fixed', symptom='unsure')])


def check(tmp_path, data):
    return assess(tmp_path, data.record, data.residual,
        tmp_path/'source.vtk', tmp_path/'numerical.vtk', tmp_path/'retained.vtk',
        tmp_path/'target.vtk', data.regions, data.fixed)


@pytest.mark.parametrize('controls_at_output', [False, True])
def test_material_support_uses_incoming_coordinates_without_changing_inputs(
    tmp_path, controls_at_output,
):
    data = case(tmp_path, controls_at_output=controls_at_output)
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    result = check(tmp_path, data)
    assert result['passed'] is (not controls_at_output)
    assert result['fraction_outside'] == (1. if controls_at_output else 0.)
    assert result['material_vertices'] == 8 and result['basis_and_coefficients_unchanged']
    assert all(p.read_bytes() == values for p, values in before.items())


def test_changed_control_identity_is_rejected(tmp_path):
    data = case(tmp_path, controls_at_output=False)
    with (tmp_path/'controls.txt').open('a') as stream:
        stream.write('1 2 3\n')
    with pytest.raises(ValueError, match='controls changed'):
        check(tmp_path, data)


@pytest.mark.parametrize('reason', ['legacy', 'residual', 'guides'])
def test_no_implicit_probe_or_basis_upgrade_outside_declared_warm_contract(tmp_path, reason):
    record = dict(refinement=dict(initialization='residual' if reason == 'residual' else 'learned'))
    residual = (None if reason == 'legacy' else dict(control_coverage=dict(
        version='source-target-coverage-v1', maximum_local_support_distance=.05)))
    assert assess(tmp_path, record, residual, None, None, None, None, [], [],
                  guide_noise=.01 if reason == 'guides' else None) is None
