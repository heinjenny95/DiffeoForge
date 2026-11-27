"""A new good numerical part must not be pulled back toward the older Retain field."""

import numpy as np
import pytest
from test_regional_fit import fixture

from diffeoforge.mesh import read_vtk_points
from diffeoforge.regional_fit import _save, assets, prepare, read_plan
from diffeoforge.regional_quality import measure


def setup(tmp_path):
    config, source, target, faces = fixture(tmp_path, guides=False)
    numerical = source.copy()
    numerical[8:16] = target[8:16]  # New useful part, distinct from old Retain source.
    numerical[16:, 0] += .25       # Must NEVER redefine the explicit fixed patch.
    _save(tmp_path / 'numerical.vtk', numerical, faces)
    problem = dict(shape='box', bounds=[-3, -1, -1, 1, -1, 1],
                   center=[-2, 0, 0], radius=1, purpose='problem', symptom='detail')
    fixed = dict(center=[0, 0, 5], radius=.6, purpose='fixed', symptom='unsure')
    declaration = prepare(tmp_path / 'separate-references',
        tmp_path / 'source.vtk', tmp_path / 'target.vtk', [problem],
        fixed_regions=[fixed], focus_width=.1, focus_noise=.02,
        protection_noise=.001, protection_halo=.1,
        protection_close_distance=.01, protection_tolerance=.001,
        retained_path=tmp_path / 'source.vtk', automatic_path=tmp_path / 'numerical.vtk')
    config['project']['parameter_provenance']['regional_fit'] = declaration
    return config, source, target, numerical, faces


def test_automatic_anchors_use_numerical_progress_but_fixed_keeps_explicit_reference(tmp_path):
    config, source, target, numerical, faces = setup(tmp_path)
    plan = read_plan(config)
    root = tmp_path / 'separate-references'
    protect = next(o for o in plan['objects'] if o['id'] == 'protect')
    expected = np.asarray(read_vtk_points(root / protect['target']['copy']))
    assert np.array_equal(expected, numerical[plan['protection_vertex_ids']])
    assert not set(plan['protection_vertex_ids']) & set(plan['fixed_vertex_ids'])
    fixed = next(o for o in plan['objects'] if o['id'] == 'fixed')
    expected_fixed = np.asarray(read_vtk_points(root / fixed['target']['copy']))
    assert np.array_equal(expected_fixed, source[plan['fixed_vertex_ids']])
    assert not np.array_equal(expected_fixed, numerical[plan['fixed_vertex_ids']])
    _save(tmp_path / 'good.vtk', target, faces)
    quality = measure(config, tmp_path / 'good.vtk')
    assert quality['outside_preserved'] and quality['fixed_protection']['passed']
    # Returning to the older comparison would erase the newly achieved second part.
    lost = target.copy()
    lost[8:16] = source[8:16]
    _save(tmp_path / 'lost.vtk', lost, faces)
    quality = measure(config, tmp_path / 'lost.vtk')
    assert not quality['outside_preserved'] and quality['fixed_protection']['passed']


def test_automatic_reference_is_staged_and_immutable(tmp_path):
    config, *_ = setup(tmp_path)
    plan = read_plan(config)
    assert any(str(staged).replace('\\', '/') == 'input/regional/automatic-reference.vtk'
               for _, staged, _ in assets(config))
    path = tmp_path / 'separate-references' / plan['automatic_reference']['copy']
    with path.open('a') as stream:
        stream.write('changed')
    with pytest.raises(ValueError, match='Automatic preservation reference changed'):
        read_plan(config)


def test_fixed_instruction_stays_in_quality_scope_for_reuse_and_changed_marks_fail(
    tmp_path, monkeypatch,
):
    from copy import deepcopy
    from types import SimpleNamespace

    from diffeoforge.regional_pilot import _quality_for_regions
    from diffeoforge.regional_search import capture

    config, _, target, _, faces = setup(tmp_path)
    plan = read_plan(config)
    _save(tmp_path/'ready.vtk', target, faces)
    q = measure(config, tmp_path/'ready.vtk')
    marks = [*plan['focus_regions'], *plan['fixed_regions']]
    candidate = SimpleNamespace(candidate_id='local', metrics=dict(
        attachment_comparison=dict(subjects={'target.vtk': dict(regional_quality=q)})))
    assert q['marked_regions'] == marks and q['surface_regions'] == plan['focus_regions']
    assert _quality_for_regions(candidate, 'target.vtk', marks) is q
    changed = deepcopy(marks)
    changed[-1]['radius'] *= 1.1
    assert not _quality_for_regions(candidate, 'target.vtk', changed)
    from diffeoforge import pilot_recovery

    def unexpected(*args, **kwargs):
        raise AssertionError('Unchanged problem surfaces should reuse their measured capture')

    monkeypatch.setattr(pilot_recovery, 'capture', unexpected)
    result = capture(SimpleNamespace(candidates=[candidate]),
                     dict(candidate_id='local', target='target.vtk'), plan['focus_regions'])
    expected = max(r['original_to_fit_p95'] for r in q['active_surface'])
    assert result['original_to_fit_p95'] == expected
