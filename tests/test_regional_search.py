from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import regional_pilot
from diffeoforge.regional_search import controls


def test_residual_support_reaches_missing_target_extent_and_remains_bounded():
    source = np.stack(np.meshgrid(np.linspace(-1, 1, 9), [0, .05], [0, .05]), -1).reshape(-1, 3)
    target = source + [1, 0, 0]
    regions = [dict(center=[1.5, 0, 0], radius=1)]
    q, spacing, receipt = controls(source, target, regions, .2)
    near = target[target[:, 0] >= 1]
    distances = np.linalg.norm(near[:, None]-q[None], axis=2).min(1)
    assert np.max(distances) <= .2*np.sqrt(3)/4+1e-12
    assert q[:, 0].max() > source[:, 0].max()
    assert spacing == .1 and receipt['controls'] == len(q)
    with pytest.raises(ValueError, match='control limit'):
        controls(source, target, regions, .2, limit=1)
    full, _, record = controls(source, target, regions, .2, full_surface=True)
    all_points = np.vstack((source, target))
    assert np.linalg.norm(all_points[:, None]-full[None], axis=2).min(1).max() <= (
        .2*np.sqrt(3)/4+1e-12)
    assert record['scope'] == 'full_surface'


def test_far_miss_keeps_capture_range_instead_of_blindly_narrowing(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1]))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['context']['cases'] = [dict(family='regional', target='shape.vtk')]*2
    data['regional_capture'] = dict(original_to_fit_p95=.3)
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert recipe['phase'] == 'capture' and recipe['focus_width'] == .15
    assert recipe['focus_noise'] >= .003
    assert result['values']['deformation_kernel_width'] >= 2*recipe['focus_width']
    assert recipe['control_support'] == 'source-target-coverage-v1'
    assert result['anchor'] == data['anchor'] and result['initialization'] == 'residual'


def test_first_marked_fit_reoptimizes_the_existing_broad_basis_then_checks_other_method(
    monkeypatch,
):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    info = dict(goal='regional', pilot_order=[1])
    monkeypatch.setattr(guided, 'record', lambda _: info)
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.3)
    initial = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert initial['regional_recipe']['phase'] == 'initial_warm'
    assert initial['initialization'] == 'learned'
    assert initial['values'] == data['anchor']['values']
    assert initial['regional_recipe']['protection_noise'] == initial['values']['noise_std']
    # Compare both methods from the SAME saved field and protection frame;
    # chaining the second model after the first model confounds the comparison.
    common = initial['initialization_reference']
    info['strategy'] = dict(regional_recipe=initial['regional_recipe'])
    data['context']['cases'] = [dict(family='regional', target='shape.vtk',
        method=initial['method'], reference=common, regions=data['regions'],
        regional_recipe=initial['regional_recipe'])]
    data['anchor'] = data['current_reference'] = dict(common, candidate_id='first-model-fit')
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(regional_quality=dict(outside_preserved=True, shape_preserved=True,
            active_surface=[dict(original_to_fit_p95=.1)], local_improved=True))}))
    other = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert other['regional_recipe']['phase'] == 'coarse_method_check'
    assert other['method'] != initial['method']
    assert other['initialization'] == 'learned'
    assert other['values'] == initial['values']
    assert other['regional_recipe']['focus_width'] == initial['regional_recipe']['focus_width']
    assert other['initialization_reference'] == common
    assert other['regional_recipe']['protection_reference'] == common
    assert other['anchor'] == data['anchor']  # Human comparison stays available.
    data['regions'] = [dict(symptom='detail', radius=.2)]
    changed = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert changed['regional_recipe']['phase'] != 'coarse_method_check'


def test_finer_movement_does_not_also_jump_to_a_much_stronger_local_weight(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    previous = dict(phase='coarse_method_check', focus_width=.15, focus_noise=.006)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.02)
    data['context']['cases'] = [dict(family='regional', target='shape.vtk',
        method=data['anchor']['method'], regions=data['regions'], regional_recipe=previous)]
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(regional_quality=dict(outside_preserved=True, shape_preserved=True,
            active_surface=[dict(original_to_fit_p95=.02)], local_improved=True))}))
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert result['initialization'] == 'residual'
    assert result['regional_recipe']['focus_width'] < previous['focus_width']
    assert result['regional_recipe']['focus_noise'] == previous['focus_noise']


def test_automatic_preservation_accepts_same_surface_reparameterization_but_holds_fixed_marks(
    tmp_path,
):
    from copy import deepcopy

    from test_regional_fit import fixture

    from diffeoforge.regional_fit import _save, prepare
    from diffeoforge.regional_quality import measure

    config, source, _, faces = fixture(tmp_path, guides=False)
    rotated = source.copy()
    centre = np.array([0., 0., 5.])
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    rotated[16:] = (rotated[16:]-centre)@rotation.T+centre
    _save(tmp_path/'same-surface.vtk', rotated, faces)
    for fixed in (False, True):
        entry = prepare(tmp_path/('fixed-shape' if fixed else 'soft-shape'),
            tmp_path/'source.vtk', tmp_path/'target.vtk',
            [dict(shape='box', bounds=[-3, 3, -1, 1, -1, 1],
                  center=[0, 0, 0], radius=4, symptom='detail')],
            focus_width=.1, focus_noise=.02, protection_noise=.02,
            protection_halo=.2, retained_path=tmp_path/'source.vtk',
            protection_close_distance=.02, protection_tolerance=.005,
            fixed_regions=([dict(center=source[16].tolist(), radius=.01,
                                 symptom='unsure', purpose='fixed')] if fixed else []))
        cfg = deepcopy(config)
        cfg['project']['parameter_provenance']['regional_fit'] = entry
        quality = measure(cfg, tmp_path/'same-surface.vtk')
        assert quality['outside_displacement_p95'] > quality['outside_position_limit']
        assert quality['unmarked_preservation_basis'] == 'original_surface'
        assert quality['outside_preserved'] is not fixed
        assert quality['explicit_fixed_preserved'] is not fixed
        if not fixed:
            soft_config = deepcopy(cfg)
    expanded = source.copy()
    expanded[16:] = (expanded[16:]-centre)*2+centre
    _save(tmp_path/'changed-surface.vtk', expanded, faces)
    changed = measure(soft_config, tmp_path/'changed-surface.vtk')
    assert changed['explicit_fixed_preserved']  # No fixed mark explains this rejection.
    assert not changed['outside_preserved']
    assert any(not r['passed'] for r in changed['previously_good_surface'])


def test_matching_quality_reuses_measured_capture_without_geometry_reads(monkeypatch):
    from diffeoforge import pilot_recovery
    from diffeoforge.regional_search import capture

    areas = [dict(center=[0, 0, 0], radius=1)]
    candidate = SimpleNamespace(candidate_id='fit', metrics=dict(attachment_comparison=dict(
        subjects={'shape.vtk': dict(regional_quality=dict(marked_regions=areas,
            active_surface=[dict(original_to_fit_p95=.15), dict(original_to_fit_p95=.16)]))})))
    snapshot = SimpleNamespace(candidates=[candidate])
    def forbidden(*args, **kwargs):
        raise AssertionError('A matching bound measurement already exists')
    monkeypatch.setattr(pilot_recovery, 'capture', forbidden)
    result = capture(snapshot, dict(candidate_id='fit', target='shape.vtk'), areas)
    assert result['original_to_fit_p95'] == .16


def test_reached_finer_scale_keeps_capture_and_adds_independent_detail_field(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=dict(phase='capture', focus_width=.15))))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['context']['cases'] = [dict(family='regional', target='shape.vtk', outcome='worse')]*2
    data['regional_capture'] = dict(original_to_fit_p95=.03)
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(regional_quality=dict(local_improved=True, outside_preserved=True,
            shape_preserved=True, active_surface=[dict(original_to_fit_p95=.03)]))}))
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert result['initialization_reference'] == data['current_reference']
    assert result['initialization'] == 'residual'
    assert result['method'] == 'current'  # Other global method, with retained prefix.
    assert recipe['whole_surface_contrast']['retained_prefix_unchanged']
    assert recipe['control_scope'] == 'full_surface'
    assert result['values']['deformation_kernel_width'] < .1


def test_exact_discarded_settings_receive_distinct_feedback_driven_contrast():
    from copy import deepcopy

    from diffeoforge.regional_search import distinct

    recipe = dict(focus_width=.1, focus_noise=.01, protection_noise=.02, residual=True)
    values = dict(noise_std=.1)
    seed = dict(directory='same retained field')
    cases = [dict(reference=seed, method='current', values=values,
                  regional_recipe=deepcopy(recipe))]
    available, changed = distinct(recipe, values, 'current', seed, cases,
                                  dict(outside_preserved=True))
    assert available and changed and recipe['focus_noise'] == .005
    cases.append(dict(reference=seed, method='current', values=values,
                      regional_recipe=deepcopy(recipe)))
    recipe['focus_noise'] = .01
    distinct(recipe, values, 'current', seed, cases, dict(outside_preserved=True))
    assert recipe['focus_noise'] == .0025


def test_local_gain_with_remaining_whole_error_rebalances_same_field(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    previous = dict(whole_surface_contrast=dict(from_method='current'),
        focus_width=.04, protection_noise=.01,
        protection_close_distance=.01, protection_tolerance=.005)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.01)
    data['current'].metrics = dict(maximum_iterations=120, attachment_comparison=dict(subjects={
        'shape.vtk': dict(repeats=[dict(p95=.04), dict(p95=.041)], regional_quality=dict(
            local_improved=True, outside_preserved=True, shape_preserved=True,
            active_surface=[dict(original_to_fit_p95=.01)]))}))
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert recipe['phase'] == 'balance'
    assert result['initialization'] == 'learned'
    assert result['initialization_reference'] == data['current_reference']
    assert result['values']['deformation_kernel_width'] == .1
    assert recipe['focus_width'] == previous['focus_width']
    assert recipe['focus_noise'] == result['values']['noise_std']
    assert recipe['protection_tolerance'] == previous['protection_tolerance']
    assert result['optimization_iterations'] is None
    # An unrelated large error must not trigger this change without a useful
    # local result, nor should it silently enlarge the marked areas.
    data['current'].metrics['attachment_comparison']['subjects']['shape.vtk'][
        'regional_quality']['local_improved'] = False
    next_result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert next_result['regional_recipe']['phase'] != 'balance'
    assert next_result['regions'] == data['regions']


def test_far_unmarked_feature_broadens_global_capture_without_restarting_local_fit(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    previous = dict(whole_surface_balance=dict(noise_factor=.5),
        focus_width=.03, focus_noise=.003, protection_noise=.01,
        protection_close_distance=.01, protection_tolerance=.005)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.01)
    before = dict(data['current_reference']['values'])
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(repeats=[dict(p95=.04, p99=.1, regional_tail=.3)],
            regional_quality=dict(numerical_selection_suitable=True, outside_preserved=True,
                shape_preserved=True, active_surface=[dict(original_to_fit_p95=.01)]))}))
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert recipe['phase'] == 'whole_capture'
    assert result['initialization'] == 'learned'
    assert result['values']['attachment_kernel_width'] >= .15
    assert recipe['focus_width'] == previous['focus_width']
    assert recipe['focus_noise'] == previous['focus_noise']
    assert result['values']['deformation_kernel_width'] == before['deformation_kernel_width']
    assert result['values']['noise_std']/result['values']['attachment_kernel_width'] == (
        before['noise_std']/before['attachment_kernel_width'])
    assert data['current_reference']['values'] == before
    assert result['regions'] == data['regions']


def test_finer_local_step_keeps_full_support_requirement_in_the_marked_halo(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=dict(focus_width=.15))))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['context']['cases'] = [dict(family='regional', target='shape.vtk', outcome='better')]*2
    data['regional_capture'] = dict(original_to_fit_p95=.03)
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(regional_quality=dict(local_improved=True, outside_preserved=True,
            shape_preserved=True, active_surface=[dict(original_to_fit_p95=.03)]))}))
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert result['regional_recipe']['residual']
    assert result['regional_recipe']['control_scope'] == 'marked_halo'
    assert result['regional_recipe']['control_support'] == 'source-target-coverage-v1'
    assert not result['regional_recipe'].get('whole_surface_contrast')


def test_physical_transition_halo_does_not_shrink_with_a_changed_attachment_scale(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1]))
    data = proposal_data()
    data['spatial_diagonal'] = 4.
    snapshot = SimpleNamespace(plan=SimpleNamespace(
        baseline_parameter_ratios=dict(attachment_kernel_width=.025)))
    first = regional_pilot.proposal(snapshot, 'x', data, symptom='gap')
    data['anchor']['values']['attachment_kernel_width'] *= .1
    second = regional_pilot.proposal(snapshot, 'x', data, symptom='gap')
    assert first['regional_recipe']['protection_halo'] == .2
    assert second['regional_recipe']['protection_halo'] == .2


def test_untrusted_unmarked_anchors_are_released_but_explicit_fixed_points_remain(tmp_path):
    from test_regional_fit import fixture

    from diffeoforge.mesh import read_vtk_points
    from diffeoforge.regional_fit import _save, prepare, read_plan

    config, source, target, faces = fixture(tmp_path, guides=False)
    retained = source.copy()
    retained[16:, 0] += .1
    _save(tmp_path/'retained.vtk', retained, faces)
    fixed_id = next(i for i in np.unique(faces[faces[:, 0] >= 16, 0]) if source[i, 0] > 0)
    fixed = dict(center=retained[fixed_id].tolist(), radius=.01, symptom='unsure', purpose='fixed')
    entry = prepare(tmp_path/'confident', tmp_path/'source.vtk', tmp_path/'target.vtk',
        [dict(center=[0, 0, 0], radius=3)], focus_width=.1, focus_noise=.02,
        protection_noise=.001, protection_halo=.1, retained_path=tmp_path/'retained.vtk',
        fixed_regions=[fixed], protection_close_distance=.02, protection_tolerance=.005)
    config['project']['parameter_provenance']['regional_fit'] = entry
    plan = read_plan(config)
    assert fixed_id in plan['fixed_vertex_ids']
    assert fixed_id in plan['protection_vertex_ids']
    assert len(plan['protection_vertex_ids']) < len(np.unique(faces[faces[:, 0] >= 16, 0]))
    _save(tmp_path/'retained-bad.vtk', retained, faces)
    from diffeoforge.regional_quality import measure

    displaced = retained.copy()
    displaced[fixed_id, 0] += .001
    _save(tmp_path/'fixed-moved.vtk', displaced, faces)
    assert not measure(config, tmp_path/'fixed-moved.vtk')['explicit_fixed_preserved']
    assert len(read_vtk_points(tmp_path/'confident/protect-target.vtk')) == len(
        plan['protection_vertex_ids'])


def test_warm_source_faces_are_selected_in_the_retained_display_frame(tmp_path):
    from test_shape_descriptor import cube

    from diffeoforge.mesh import read_vtk_polydata
    from diffeoforge.regional_fit import _save, prepare

    v, f = cube()
    source = np.vstack([v*.1+[x, 0, 0] for x in (0, 2, 20)])
    retained = np.vstack([v*.1+[x, 0, 0] for x in (2, 10, 20)])
    faces = np.vstack([f+8*i for i in range(3)])
    _save(tmp_path/'source.vtk', source, faces)
    _save(tmp_path/'retained.vtk', retained, faces)
    prepare(tmp_path/'frame', tmp_path/'source.vtk', tmp_path/'retained.vtk',
        [dict(center=[2, 0, 0], radius=.5)], focus_width=.1, focus_noise=.02,
        protection_noise=.001, protection_halo=.1, retained_path=tmp_path/'retained.vtk')
    selected = np.asarray(read_vtk_polydata(tmp_path/'frame/focus-source.vtk').vertices)
    # The displayed component at x=2 came from source x=0. Choosing source x=2
    # would fit the wrong material patch despite a valid owner annotation.
    assert np.abs(selected[:, 0]).max() <= .10000001


def test_reopened_plan_rejects_partial_protection_confidence_declarations(tmp_path):
    import json

    from test_regional_fit import fixture

    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_fit import read_plan

    config, *_ = fixture(tmp_path, guides=False)
    entry = config['project']['parameter_provenance']['regional_fit']
    from pathlib import Path

    path = Path(entry['manifest'])
    data = json.loads(path.read_text())
    data['protection_tolerance'] = .005
    path.write_text(json.dumps(data))
    entry['sha256'] = sha256_file(path)
    with pytest.raises(ValueError, match='protection confidence'):
        read_plan(config)


@pytest.mark.parametrize('fixed', [False, True])
def test_reached_marked_detail_recovers_remaining_surface_without_discarding_fields(
    monkeypatch, fixed,
):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    previous = dict(phase='detail', focus_width=.03, focus_noise=.003,
        protection_noise=.01, protection_close_distance=.01, protection_tolerance=.005,
        protection_halo=.2)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    if fixed:
        data['regions'].append(dict(symptom='unsure', purpose='fixed'))
    data['regional_capture'] = dict(original_to_fit_p95=.004)
    data['context']['cases'] = [dict(family='regional', target='shape.vtk', outcome='better')]*3
    data['current'].metrics = dict(attachment_comparison=dict(subjects={
        'shape.vtk': dict(repeats=[dict(p95=.04, regional_tail=.2)], regional_quality=dict(
            numerical_selection_suitable=True, outside_preserved=True, shape_preserved=True,
            outside_displacement_p95=.0001, outside_position_limit=.005,
            active_surface=[dict(original_to_fit_p95=.004, fit_to_original_p95=.004)]))}))
    old = dict(data['current_reference']['values'])
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    recipe = result['regional_recipe']
    assert recipe['phase'] == 'whole_recovery'
    assert recipe['residual'] and recipe['control_scope'] == 'full_surface'
    assert recipe['focus_width'] == previous['focus_width']
    assert recipe['focus_noise'] == previous['focus_noise']
    assert recipe['protection_tolerance'] == previous['protection_tolerance']
    assert recipe['protection_noise'] == previous['protection_noise']*(1 if fixed else 2)
    assert result['values']['attachment_kernel_width'] == .1
    assert result['values']['noise_std'] == old['noise_std']*.5
    assert result['values']['deformation_kernel_width'] >= .2
    assert result['initialization_reference'] == data['current_reference']
    assert result['regions'] == data['regions'] and data['current_reference']['values'] == old
    subject = data['current'].metrics['attachment_comparison']['subjects']['shape.vtk']
    quality = subject['regional_quality']
    # A local miss or unsafe field cannot trigger a whole-surface continuation.
    quality['active_surface'][0]['fit_to_original_p95'] = .02
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert result['regional_recipe']['phase'] != 'whole_recovery'
    quality['active_surface'][0]['fit_to_original_p95'] = .004
    quality['no_new_intersection_flags'] = False
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert result['regional_recipe']['phase'] != 'whole_recovery'


def test_failed_global_attempt_retries_finer_from_the_retained_good_field(monkeypatch):
    from copy import deepcopy

    from test_regional_fit import proposal_data

    from diffeoforge import guided_feedback
    from diffeoforge import reference_guided_pilot as guided

    data = proposal_data()
    data['anchor']['candidate_id'] = 'old'
    data['current_reference']['values'] = dict(attachment_kernel_width=.12,
        deformation_kernel_width=.24, noise_std=.01, initial_control_point_spacing=.3)
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.004)
    data['context']['feedback'] = dict(x=dict(feedback=dict(outcome='same')))
    previous = dict(phase='detail', focus_width=.03, focus_noise=.003, protection_noise=.01,
        protection_close_distance=.01, protection_tolerance=.005, protection_halo=.2)
    good_quality = dict(numerical_selection_suitable=True, outside_preserved=True,
        shape_preserved=True, outside_displacement_p95=.0001, marked_regions=data['regions'],
        active_surface=[dict(original_to_fit_p95=.004, fit_to_original_p95=.004)])
    good = dict(repeats=[dict(p95=.03, regional_tail=.2)], regional_quality=good_quality)
    bad_quality = dict(good_quality, numerical_selection_suitable=False,
        active_surface=[dict(original_to_fit_p95=.007, fit_to_original_p95=.007)])
    bad = dict(repeats=[dict(p95=.031, regional_tail=.2)], regional_quality=bad_quality)
    data['current'].metrics = dict(attachment_comparison=dict(subjects={'shape.vtk': bad}))
    parent = SimpleNamespace(candidates=[SimpleNamespace(candidate_id='old',
        metrics=dict(attachment_comparison=dict(subjects={'shape.vtk': good})))])
    monkeypatch.setattr(guided_feedback, 'verify_reference', lambda ref: parent)
    monkeypatch.setattr(guided, 'record', lambda snap: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=(previous if snap is parent else
            dict(previous, phase='whole_recovery')))))
    before = deepcopy(data['current_reference'])
    result = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert result['initialization_reference'] == data['anchor']
    assert result['values']['attachment_kernel_width'] == .06
    assert result['values']['deformation_kernel_width'] == .12
    assert result['values']['noise_std'] == .005
    recipe = result['regional_recipe']
    assert recipe['whole_surface_recovery']['discarded_trial'] == before
    assert recipe['focus_width'] == .03 and recipe['focus_noise'] == .003
    assert recipe['protection_tolerance'] == .005
    assert recipe['control_scope'] == 'full_surface'
    assert data['current_reference'] == before
    # Resolution helped globally but the complete fit is still unsuitable:
    # keep that tested resolution and strengthen surface fidelity, rather than
    # narrowing the grid again or carrying the unsuitable deformation.
    bad['repeats'][0]['p95'] = .02
    previous['focus_noise'] = .007
    balanced = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert balanced['initialization_reference'] == data['anchor']
    assert balanced['values']['attachment_kernel_width'] == .12
    assert balanced['values']['deformation_kernel_width'] == .24
    assert balanced['values']['noise_std'] == .01
    # Stronger global fidelity must not make the good marked objective weaker
    # in relative terms; keep its retained local/global noise ratio as a cap.
    assert balanced['regional_recipe']['focus_noise'] == pytest.approx(.002)
    assert (balanced['regional_recipe']['focus_noise']/balanced['values']['noise_std']
            <= previous['focus_noise']/data['anchor']['values']['noise_std'])
    assert balanced['regional_recipe']['protection_noise'] == previous['protection_noise']
    assert balanced['regional_recipe']['whole_surface_recovery']['kernel_widths_changed'] is False
    assert balanced['regional_recipe']['whole_surface_recovery']['control_support_rebuilt']
    # A useful global improvement can be reused even when the local reviewer
    # says Same: only the failed global deformation is excluded above.
    bad['repeats'][0]['p95'] = .02
    bad['regional_quality'] = dict(good_quality)
    useful = regional_pilot.proposal(None, 'x', data, symptom='detail')
    assert useful['initialization_reference'] == data['current_reference']


def test_surface_noise_change_does_not_redefine_physical_preservation_limits(monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided

    previous = dict(phase='capture', focus_width=.15, focus_noise=.003,
        protection_close_distance=.01, protection_tolerance=.005, protection_halo=.2)
    monkeypatch.setattr(guided, 'record', lambda _: dict(goal='regional', pilot_order=[1],
        strategy=dict(regional_recipe=previous)))
    data = proposal_data()
    data['regions'] = [dict(symptom='detail')]
    data['regional_capture'] = dict(original_to_fit_p95=.02)
    data['current_reference']['values'] = dict(data['current_reference']['values'], noise_std=.01)
    data['current'].metrics = dict(attachment_comparison=dict(subjects={'shape.vtk':
        dict(regional_quality=dict(outside_preserved=True, shape_preserved=True,
            active_surface=[dict(original_to_fit_p95=.02)]))}))
    recipe = regional_pilot.proposal(None, 'x', data, symptom='detail')['regional_recipe']
    for key in ('protection_close_distance', 'protection_tolerance', 'protection_halo'):
        assert recipe[key] == previous[key]
