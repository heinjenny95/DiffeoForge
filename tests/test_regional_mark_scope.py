"""New missing areas must not inherit improvement measured on older marks."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from diffeoforge import reference_guided_pilot as guided
from diffeoforge import regional_pilot


def context(monkeypatch):
    from test_regional_fit import proposal_data

    data = proposal_data()
    mark = dict(center=[0., 0., 0.], radius=.2, purpose='problem',
                symptom='detail', source_sha256='a'*64)
    data['regions'] = [mark]
    data['anchor'] = data['current_reference']
    quality = dict(marked_regions=deepcopy(data['regions']),
                   active_surface=[dict(original_to_fit_p95=.02)],
                   outside_preserved=True, shape_preserved=True, local_improved=True,
                   numerical_selection_suitable=True)
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(regional_quality=quality)}))
    old_recipe = dict(phase='detail', focus_width=.15, focus_noise=.006)
    data['context']['cases'] = [dict(family='regional', target='shape.vtk',
        method='varifold', regions=deepcopy(data['regions']), regional_recipe=old_recipe)]
    info = dict(goal='regional', pilot_order=[1], strategy=dict(regional_recipe=old_recipe))
    monkeypatch.setattr(guided, 'record', lambda _: info)
    snapshot = SimpleNamespace(plan=SimpleNamespace(pilot_subject_count=1,
        baseline_parameter_ratios={}))
    return snapshot, data, quality


@pytest.mark.parametrize('change',
                         ['added', 'moved', 'resized', 'source', 'purpose', 'missing_scope'])
def test_changed_marks_keep_measured_capture_and_saved_broad_field(monkeypatch, change):
    snapshot, data, quality = context(monkeypatch)
    if change == 'added':
        data['regions'].append(dict(data['regions'][0], center=[1., 0., 0.]))
    elif change == 'moved':
        data['regions'][0]['center'] = [1., 0., 0.]
    elif change == 'resized':
        data['regions'][0]['radius'] = .3
    elif change == 'source':
        data['regions'][0]['source_sha256'] = 'b'*64
    elif change == 'purpose':
        data['regions'][0]['purpose'] = 'preserve'
    else:
        quality.pop('marked_regions')
    data['regional_capture'] = dict(original_to_fit_p95=.45, regions=deepcopy(data['regions']))
    old_data, old_quality = deepcopy(data['regions']), deepcopy(quality)
    result = regional_pilot.proposal(snapshot, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert recipe['focus_width'] >= .225
    if change != 'missing_scope':
        assert result['values']['deformation_kernel_width'] == (
            data['anchor']['values']['deformation_kernel_width'])
        assert result['initialization'] == 'learned' and not recipe['residual']
    else:
        assert recipe['phase'] == 'capture'
        assert result['initialization'] == 'residual' and recipe['residual']
    assert result['initialization_reference'] == data['anchor']
    assert result['regions'] == old_data and data['regions'] == old_data
    assert quality == old_quality  # Stored measurements are evidence, never edited.


def test_identical_marks_keep_the_existing_measured_detail_route(monkeypatch):
    snapshot, data, _ = context(monkeypatch)
    data['regional_capture'] = dict(original_to_fit_p95=.45, regions=deepcopy(data['regions']))
    result = regional_pilot.proposal(snapshot, 'x', data, symptom='detail')
    assert result['regional_recipe']['phase'] == 'detail'
    assert result['regional_recipe']['focus_width'] < .15


def test_global_retry_cannot_restore_quality_from_an_old_mark_scope(monkeypatch):
    from diffeoforge import guided_feedback

    snapshot, data, _ = context(monkeypatch)
    data['anchor'] = dict(data['anchor'], candidate_id='old')
    data['regions'].append(dict(data['regions'][0], center=[1., 0., 0.]))
    data['regional_capture'] = dict(original_to_fit_p95=.45, regions=deepcopy(data['regions']))
    data['context']['feedback'] = dict(x=dict(feedback=dict(outcome='worse')))
    previous = dict(phase='whole_recovery', focus_width=.15, focus_noise=.006)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    retained = SimpleNamespace(candidates=[SimpleNamespace(candidate_id='old',
        metrics=deepcopy(data['current'].metrics))])
    monkeypatch.setattr(guided_feedback, 'verify_reference', lambda _: retained)
    result = regional_pilot.proposal(snapshot, 'x', data, symptom='detail')
    assert result['regional_recipe']['focus_width'] >= .225
    assert 'whole_surface_recovery' not in result['regional_recipe']
    assert result['initialization_reference'] == data['anchor']
