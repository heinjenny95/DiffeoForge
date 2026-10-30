from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.regional_protected_capture import VERSION, active_regions, proposal
from diffeoforge.regional_search import capture_rows


def setup_data():
    from test_regional_fit import proposal_data

    data = proposal_data()
    data['regions'] = [dict(center=[i, 0, 0], radius=.3, symptom='detail') for i in (0, 1)]
    data['regions'].append(dict(center=[2, 0, 0], radius=.2,
                                purpose='fixed', symptom='unsure'))
    data['anchor']['values']['deformation_kernel_width'] = .4
    data['current_reference']['values'] = dict(data['anchor']['values'])
    data['regional_capture'] = dict(per_region=[
        dict(region=r, original_to_fit_p95=v, symmetric_tail=v)
        for r, v in zip(data['regions'][:2], (.06, .4), strict=True)])
    data['spatial_diagonal'] = 4
    return data, dict(goal='regional', pilot_order=[1, 2])


def test_protected_far_feature_separates_broad_capture_from_local_movement():
    data, info = setup_data()
    before = deepcopy(data['anchor'])
    result = proposal(None, 'x', data, info, 'detail')
    recipe = result['regional_recipe']
    assert recipe['protected_capture'] == VERSION
    assert recipe['active_regions'] == [data['regions'][1]]
    assert result['values']['deformation_kernel_width'] == .1
    assert recipe['focus_width'] == .8  # Broader capture does not broaden movement.
    assert recipe['native_timepoints'] == 145 and recipe['fixed_noise_divisor'] == 16
    assert recipe['residual'] and recipe['focus_noise'] == .02*.075
    assert result['regions'] == data['regions'] and data['anchor'] == before
    assert result['remaining_checks'] == 1


def test_supported_current_field_keeps_progress_and_targets_remaining_area(monkeypatch):
    from diffeoforge import retained_mark_source

    data, info = setup_data()
    initial = proposal(None, 'x', data, info, 'missing')
    data['current_reference']['values']['deformation_kernel_width'] = .1
    data['current'].metrics = dict(attachment_comparison=dict(subjects={'shape.vtk': dict(
        regional_quality=dict(marked_regions=deepcopy(data['regions']),
                              numerical_selection_suitable=True),
        marked_regions=dict(measurements=[dict(region=r, repeats=[dict(
            original_to_fit_p95=v, fit_to_original_p95=v)]*2)
            for r, v in zip(data['regions'], (.10, .04, .001), strict=True)]))}))
    info['strategy'] = dict(regional_recipe=initial['regional_recipe'])
    monkeypatch.setattr(retained_mark_source, 'current_is_bound', lambda _: True)
    result = proposal(None, 'x', data, info, 'detail')
    assert result['initialization_reference'] == data['current_reference']
    assert result['regional_recipe']['active_regions'] == [data['regions'][0]]
    assert result['values']['deformation_kernel_width'] == .1  # No repeated halving.
    assert result['initialization'] == 'residual'  # New area, preserve complete old field.
    info['strategy']['regional_recipe'] = result['regional_recipe']
    again = proposal(None, 'x', data, info, 'detail')
    assert again['initialization'] == 'learned'
    data['context']['feedback']['x'] = dict(feedback=dict(outcome='worse'))
    rejected = proposal(None, 'x', data, info, 'detail')
    assert rejected['initialization_reference'] == data['anchor']


def test_numeric_extension_other_symptoms_and_small_ordinary_miss_are_unchanged():
    data, info = setup_data()
    assert proposal(None, 'x', data, info, None) is None
    assert proposal(None, 'x', data, info, 'distortion') is None
    data['regional_capture']['per_region'][1]['original_to_fit_p95'] = .1
    assert proposal(None, 'x', data, info, 'detail') is None
    data['regions'].pop()
    assert proposal(None, 'x', data, info, 'detail') is None


def test_reverse_unknown_stays_unknown_and_active_scope_cannot_change():
    regions = [dict(symptom='detail', radius=.3)]
    rows = capture_rows([dict(region=regions[0], repeats=[dict(
        original_to_fit_p95=.4, fit_to_original_p95=None)]*2)])
    assert rows[0]['fit_to_original_p95'] is None and rows[0]['symmetric_tail'] == .4
    assert active_regions(dict(protected_capture=VERSION,
                               active_regions=regions), regions) == regions
    with pytest.raises(ValueError, match='unchanged'):
        active_regions(dict(protected_capture=VERSION,
                            active_regions=[dict(symptom='detail', radius=.4)]), regions)


def test_per_brush_capture_does_not_reuse_a_merged_partial_surface_cache(monkeypatch):
    from diffeoforge import pilot_recovery
    from diffeoforge.regional_search import capture

    areas = [dict(radius=.3), dict(radius=.4)]
    candidate = SimpleNamespace(candidate_id='fit', metrics=dict(attachment_comparison=dict(
        subjects={'shape.vtk': dict(regional_quality=dict(surface_regions=areas,
            active_surface=[dict(original_to_fit_p95=.9)]))})))
    baseline = [dict(region=r, repeats=[dict(original_to_fit_p95=v,
                    fit_to_original_p95=None)]*2)
                for r, v in zip(areas, (.1, .5), strict=True)]
    calls = []
    def measured(snapshot, identifier, target, *, regions):
        calls.append(regions)
        return dict(baseline=baseline)
    monkeypatch.setattr(pilot_recovery, 'capture', measured)
    result = capture(SimpleNamespace(candidates=[candidate]),
                     dict(candidate_id='fit', target='shape.vtk'), areas, per_region=True)
    assert calls == [areas] and result['original_to_fit_p95'] == .5
    assert [r['region'] for r in result['per_region']] == areas
    assert [r['symmetric_tail'] for r in result['per_region']] == [.1, .5]


def test_patch_capture_uses_current_free_material_and_keeps_strict_fixed_bound(tmp_path):
    from test_regional_fit import fixture

    from diffeoforge.regional_fit import prepare, read_plan
    from diffeoforge.regional_pilot import configure

    cfg, source, _, _ = fixture(tmp_path, guides=False)
    region = dict(center=[-2, 0, 0], radius=1, symptom='detail')
    fixed = dict(center=source[16].tolist(), radius=.01, purpose='fixed', symptom='unsure')
    declaration = prepare(tmp_path/'capture', tmp_path/'source.vtk', tmp_path/'target.vtk',
        [region], focus_width=.0001, focus_noise=.02, protection_noise=.02,
        protection_halo=.1, retained_path=tmp_path/'source.vtk',
        automatic_path=tmp_path/'source.vtk', fixed_regions=[fixed],
        capture_profile=True, fixed_noise_divisor=16)
    cfg['project']['parameter_provenance']['regional_fit'] = declaration
    plan = read_plan(cfg)
    focus = next(o for o in plan['objects'] if o['id'] == 'focus')
    assert focus['kernel_width'] == 2*plan['patch_capture']['symmetric_patch_p95']
    assert focus['kernel_width'] > .0001
    fixed_object = next(o for o in plan['objects'] if o['id'] == 'fixed')
    assert fixed_object['noise_std'] == plan['fixed_protection']['limit']/16
    assert plan['fixed_protection']['limit'] == plan['fixed_protection']['reference_diagonal']*1e-4
    configure(cfg, dict(regional_objective=declaration, guided=dict(strategy=dict(
        regional_recipe=dict(protected_capture=VERSION, native_timepoints=145)))))
    assert cfg['model']['deformation']['timepoints'] >= 145
    assert cfg['optimization']['convergence_tolerance'] <= 1e-6
    assert np.isfinite(focus['kernel_width'])
