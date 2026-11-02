"""Accepted-reference diagnosis, real public geometry and preserved pilot journeys."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from diffeoforge import pilot_common_diagnosis as diagnosis


def surface(value=.01, local=None):
    row = dict(mean=value, p95=value, p99=value, regional_tail=value,
               regions=local or {})
    return dict(diagonal=10., repeats=[deepcopy(row), deepcopy(row)], warnings=[])


def evidence(gap=.2, *, local=False):
    return dict(accepted=surface(), current=surface(gap), agreement=surface(gap),
                accepted_local=local, accepted_controls=201, current_controls=200,
                objective_tail=[-100., -99., -98.])


def test_improving_geometry_justifies_bounded_iterations_but_plateau_tests_capacity():
    old = evidence(.4)
    value = diagnosis.assess(evidence(.2), old)
    assert value['gap'] and value['trend'] == 'improving'
    assert diagnosis.recommend(value, capped=True)['kind'] == 'iterations'
    value = diagnosis.assess(evidence(.4, local=True), old)
    assert value['trend'] == 'plateau'
    assert diagnosis.recommend(value, capped=True)['kind'] == 'capacity'
    assert diagnosis.recommend(value, capped=False)['kind'] == 'capacity'


def test_human_veto_iteration_budget_and_capacity_budget_do_not_repeat_forever():
    value = diagnosis.assess(evidence(), evidence(.4))
    assert diagnosis.recommend(value, capped=True, veto=True)['kind'] == 'capacity'
    assert diagnosis.recommend(value, capped=True, iteration_tests=2)['kind'] == 'capacity'
    assert diagnosis.recommend(value, capped=True, iteration_tests=2,
                               density_tested=True)['kind'] == 'stalled'
    assert diagnosis.recommend(diagnosis.assess(evidence(.01)), capped=True)['kind'] == 'inspect'


def test_small_local_tooth_and_new_reverse_spike_are_not_hidden_by_global_p95():
    value = evidence(.01)
    value['accepted']['repeats'] = [dict(r, regions={
        '0:3': dict(count=2, tail=.01)}) for r in value['accepted']['repeats']]
    value['current']['repeats'] = [dict(r, regions={
        '0:3': dict(count=2, tail=.3), '1:63': dict(count=3, tail=.5)})
        for r in value['current']['repeats']]
    assessed = diagnosis.assess(value)
    assert assessed['gap'] and len(assessed['local_losses']) == 2
    assert {r['region'] for r in assessed['local_losses']} == {'0:3', '1:63'}


def test_sample_uncertainty_and_mixed_regression_veto_an_iteration_recommendation():
    current, before = evidence(.2), evidence(.4)
    current['current']['repeats'] = [dict(r, regional_tail=1.)
                                     for r in current['current']['repeats']]
    assert diagnosis.assess(current, before)['trend'] == 'worse'
    assert diagnosis.recommend(diagnosis.assess(current, before), capped=True)['kind'] == 'capacity'
    current = evidence(.39)
    current['agreement']['repeats'][0]['p95'] = .41
    assert diagnosis.assess(current, before)['trend'] == 'plateau'
    current['current']['warnings'] = ['collapse']
    assert diagnosis.recommend(diagnosis.assess(current, before), capped=True)['kind'] == 'stalled'


def test_first_comparison_uses_actual_objective_progress_and_local_capacity_evidence():
    current = evidence()
    assert diagnosis.recommend(diagnosis.assess(current), capped=True)['kind'] == 'iterations'
    current['accepted_local'] = True
    assert diagnosis.recommend(diagnosis.assess(current), capped=True)['kind'] == 'capacity'


def test_common_start_ranks_a_transferable_seed_separately_from_complete_demand():
    from diffeoforge.pilot_common_start import rank

    small = dict(controls=200, eligible_basis=True)
    dense = dict(controls=300, eligible_basis=True)
    local = dict(controls=1200, eligible_basis=False)
    assert rank([small, local, dense]) is dense
    assert rank([local]) is None


def test_previously_accepted_tooth_and_extra_reverse_spike_veto_global_improvement():
    before, current = evidence(.4), evidence(.2)
    def patch(value):
        return [dict(region={'source': 'same-original', 'purpose': 'fixed'}, repeats=[
            dict(original_to_fit_p95=.01, fit_to_original_p95=value)] * 2)]
    for row in (before, current):
        row['marked_accepted'] = patch(.01)
    before['marked_current'] = patch(.02)
    current['marked_current'] = patch(.4)
    value = diagnosis.assess(current, before)
    assert value['trend'] == 'worse'
    assert any(r['region'].endswith('fit_to_original_p95') for r in value['local_losses'])
    assert diagnosis.recommend(value, capped=True)['kind'] == 'capacity'
    current['accepted_local'] = False
    current['objective_tail'] = [-100., -99., -101.]
    assert diagnosis.recommend(diagnosis.assess(current), capped=True)['kind'] == 'capacity'


def test_global_improvement_cannot_hide_a_plateau_in_a_marked_missing_feature():
    before, current = evidence(.4), evidence(.2)
    def patch(forward):
        return [dict(region={'source': 'same-original', 'purpose': 'details'}, repeats=[
            dict(original_to_fit_p95=forward, fit_to_original_p95=.01)] * 2)]
    for row in (before, current):
        row['marked_accepted'] = patch(.01)
        row['marked_current'] = patch(.4)
    measured = diagnosis.assess(current, before)
    assert measured['trend'] == 'improving' and measured['marked_progress'] is False
    assert diagnosis.recommend(measured, capped=True)['kind'] != 'iterations'
    from diffeoforge.pilot_common_candidate import decide

    assert decide(measured, capped=True, counts={}, outcome='better') != 'iterations'
    current['marked_current'] = patch(.3)
    measured = diagnosis.assess(current, before)
    assert measured['marked_progress'] is True
    assert decide(measured, capped=True, counts={}, outcome='better') == 'iterations'


def test_real_triangle_surfaces_find_a_small_missing_projection_in_both_directions():
    from diffeoforge.mesh import TriangleMesh
    from diffeoforge.reference_attachment_comparison import compare_geometry

    # Two disconnected public triangles: a broad body and a small elevated feature.
    original = TriangleMesh(((0., 0., 0.), (10., 0., 0.), (0., 10., 0.),
                             (8., 0., 2.), (8.2, 0., 2.), (8., .2, 2.)),
                            ((0, 1, 2), (3, 4, 5)))
    missing = TriangleMesh(original.vertices[:3], ((0, 1, 2),))
    perfect = compare_geometry(original, original)
    incomplete = compare_geometry(original, missing)
    current = dict(accepted=perfect, current=incomplete,
                   agreement=compare_geometry(original, missing), accepted_local=True,
                   accepted_controls=10, current_controls=5, objective_tail=[])
    assessed = diagnosis.assess(current)
    assert assessed['gap'] and assessed['local_losses']
    assert incomplete['repeats'][0]['p95'] < .01  # Global P95 misses this tooth.
    assert any(r['region'].startswith('0:') for r in assessed['local_losses'])
    extra = dict(current, accepted=incomplete, current=perfect,
                 agreement=compare_geometry(missing, original))
    # A direct fit-to-reference discrepancy remains measurable in the opposite direction.
    assert max(r['regional_tail'] for r in extra['agreement']['repeats']) > .1


def test_capacity_preparation_preserves_field_protocol_reviews_and_requires_explicit_adoption(
        tmp_path, monkeypatch):
    from test_guided_pilot import approve, run_batch
    from test_reviewed_start_progress import selected_local_after_common_failure

    from diffeoforge import guided_feedback, guided_strategy, pilot_form_progress
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca import read_deformetrica_momenta

    local, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    ledger = pilot_form_progress.marker(current)
    pins = {p: sha256_file(p) for p in local.study_directory.rglob('*') if p.is_file()}
    accepted = guided_feedback.reference(local, 'guided-varifold')
    from diffeoforge import pilot_common_capacity

    # Exercise a whole-field demand well above the old 50% increment. The
    # classification-only fixture has no composed native field of its own.
    monkeypatch.setattr(pilot_common_capacity, 'demand', lambda v: {
        r['filename']: 480 if r['filename'] == accepted['target'] else 120
        for r in v['reviews']})
    def measured(snapshot, value, ref, previous=None):
        return dict(version=diagnosis.VERSION, accepted=accepted, current=ref,
                    previous=previous, **diagnosis.assess(evidence(local=True)))
    monkeypatch.setattr(diagnosis, 'diagnose', measured)
    choice = guided_strategy.state(current)['common_recovery']
    assert choice['mode'] == 'capacity' and choice['available']
    from diffeoforge.pilot_common_model import optimization_context

    blocked = optimization_context(current, {'common_recovery': choice}, [choice['reference']])
    assert next(iter(blocked.values()))['blocked_reason']
    child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    # A singleton's frozen learned field is initialization, not a request to
    # freeze the eventual joint atlas. Retain the original project's choices.
    source, _ = guided._origin(current.study_directory)
    from diffeoforge import reference_calibration_study as study

    source_manifest = study._verify_manifest(source.study_directory)
    source_config = load_config(
        source.study_directory / source_manifest['source_config']['copy'])
    confirmation_flags = {k: source_config['optimization'][k]
                          for k in ('freeze_template', 'freeze_control_points')}
    assert confirmation_flags == dict(freeze_template=False, freeze_control_points=False)
    assert child.attachment_comparison['confirmation_freeze_settings'] == confirmation_flags
    assert child.candidates[0].attempts == 0 and not child.visual_reviews
    assert pilot_form_progress.marker(child) == ledger
    assert guided.record(child)['approved'] == guided.record(current)['approved']
    assert child.attachment_comparison['iterations'] == 120
    ref = child.attachment_comparison['refinement']
    assert ref['initialization'] == 'nested'
    points = np.loadtxt(child.study_directory / child.attachment_comparison['controls']['copy'])
    old = np.loadtxt(child.study_directory / ref['source_controls']['copy'])
    weights = read_deformetrica_momenta(child.study_directory / ref['momenta']['copy'],
                                       allow_singleton=True)
    previous_weights = read_deformetrica_momenta(
        child.study_directory / ref['source_momenta']['copy'], allow_singleton=True)
    assert np.array_equal(points[:len(old)], old)
    assert np.array_equal(weights[:, :len(old)], previous_weights)
    assert not weights[:, len(old):].any() and len(points) == choice['proposed_controls']
    config = load_config(child.candidates[0].config_path)
    prior = load_config(current.candidates[0].config_path)
    assert config['optimization'] == prior['optimization']
    assert config['runtime'] == prior['runtime']
    assert guided_strategy.state(child)['common_recovery']['mode'] == 'prepared'
    folders = set(child.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='Complete or resolve|already prepared'):
        guided.next_action(child.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(child.study_directory.parent.iterdir()) == folders
    completed = run_batch(child, monkeypatch, capped=True)
    assert completed.candidates[0].metrics['iteration_accounting']['total_iterations'] == 240
    choice = guided_strategy.state(completed)['common_recovery']
    assert choice['mode'] == 'review' and choice['comparison_kind'] == 'capacity'
    accepted_child = approve(completed)
    state = guided_strategy.state(accepted_child)
    assert state['common_recovery']['mode'] == 'adopt'
    assert pilot_form_progress.marker(accepted_child) == ledger
    assert state['common_revision']['guided-varifold']['checked'] == 1
    from diffeoforge.pilot_common_start import prepare

    hypothetical = deepcopy(ledger)
    row = guided._approved_record(accepted_child, 'guided-varifold')
    hypothetical['reviews'] = [row if r['filename'] == row['filename'] else r
                               for r in hypothetical['reviews']]
    before_start = deepcopy(hypothetical)
    starting, policy = prepare(current, hypothetical)
    assert policy['controls'] == len(points)
    assert starting['protocol']['reference']['directory'] == str(accepted_child.study_directory)
    assert hypothetical == before_start and starting['reviews'] == hypothetical['reviews']
    revised = guided.next_action(accepted_child.study_directory, 'adaptive_adopt_common_model',
                                 'guided-varifold')
    assert pilot_form_progress.marker(revised)['reviews'] == ledger['reviews']
    assert pilot_form_progress.marker(revised)['protocol'] != ledger['protocol']
    assert not revised.visual_reviews and revised.candidates[0].attempts == 0
    assert revised.attachment_comparison['refinement']['initialization'] == 'nested'
    assert revised.attachment_comparison['controls']['sha256'] == (
        accepted_child.attachment_comparison['controls']['sha256'])
    assert revised.attachment_comparison['confirmation_freeze_settings'] == confirmation_flags
    # The individual shared-model check still freezes its own template and
    # controls; only the saved future joint settings retain the source intent.
    assert all(load_config(revised.candidates[0].config_path)['optimization'][k]
               for k in confirmation_flags)
    assert guided.record(revised)['strategy']['common_basis_step']['approval_transferred'] is False
    assert guided.record(revised)['strategy']['common_basis_step']['reference']['target'] == (
        guided.record(revised)['target'])
    # A new common phase may select a denser accepted field from an earlier
    # animal, while the last individual review was on a different animal.
    from diffeoforge import reference_calibration_study as study

    fixture_state = deepcopy(guided.record(accepted_child)['strategy'])
    for key in ('common_model_step', 'common_diagnosis_test', 'common_basis_step',
                'common_capacity_request',
                'baseline', 'anchor', 'optimization'):
        fixture_state.pop(key, None)
    fixture_state['form_progress'] = dict(hypothetical, stage='forms')
    fixture_state['control_basis'] = ledger['protocol']['reference']
    previous = dict(directory=str(accepted_child.study_directory),
                    manifest_sha256=sha256_file(
                        accepted_child.study_directory / study.STUDY_MANIFEST))
    fixture_state['previous'] = previous
    other = next(r['filename'] for r in ledger['reviews'] if r['filename'] != row['filename'])
    source, _ = guided._origin(accepted_child.study_directory)
    info = guided.record(accepted_child)
    first = guided._batch(source, phase='refine', target=other, methods=('varifold',),
        values=ledger['protocol']['reference']['values'], approved=info['approved'],
        history=[*info['history'], dict(previous, outcome='prospective_start_fixture')],
        spent=info['screen_trials_spent'], strategy=fixture_state,
        previous=None, goal='weight')  # Independent fixture; do not replace the parent's successor.
    first = approve(run_batch(first, monkeypatch))
    first_common = guided.next_action(first.study_directory, 'adaptive_form_model_check',
                                      'guided-varifold')
    assert first_common.attachment_comparison['controls']['sha256'] == (
        accepted_child.attachment_comparison['controls']['sha256'])
    transfer = guided.record(first_common)['strategy']['common_basis_step']
    assert transfer['approval_transferred'] is False
    assert all(sha256_file(p) == h for p, h in pins.items())


def test_bound_geometry_cache_rechecks_output_original_approval_and_target(tmp_path, monkeypatch):
    from collections import OrderedDict
    from types import SimpleNamespace

    from diffeoforge import guided_feedback, regional_evaluation, result_report
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import TriangleMesh, sha256_file, write_vtk_polydata

    target = 'shape.vtk'
    mesh = TriangleMesh(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), ((0, 1, 2),))
    snapshots, manifests, reports, refs = {}, {}, {}, []
    for index, role in enumerate(('accepted', 'common')):
        root = tmp_path / role
        output = root / 'run' / 'output'
        output.mkdir(parents=True)
        source = root / 'original.vtk'
        write_vtk_polydata(source, mesh.vertices, mesh.triangles)
        fitted = output / ('Atlas__Reconstruction__object__subject_' + target + '.vtk')
        shape = TriangleMesh(tuple((x, y, z + index * .2) for x, y, z in mesh.vertices),
                             mesh.triangles)
        write_vtk_polydata(fitted, shape.vertices, shape.triangles)
        candidate = SimpleNamespace(candidate_id='fit', metrics={})
        snapshots[str(root)] = SimpleNamespace(study_directory=root, candidates=[candidate],
            visual_reviews={'fit': role == 'accepted'}, problem_regions={},
            attachment_comparison={'guided': {'origin': 'same-cohort'},
                                   'controls': {'count': 10}})
        manifests[root] = {'inputs': {'subjects': [dict(filename=target, copy=source.name,
            sha256=sha256_file(source))], 'template': {'sha256': 'same-template'}}}
        reports[root / 'run'] = SimpleNamespace(
            manifest={'effective_config': {'model': {'object_id': 'object'}}},
            inventory=[dict(path=fitted.name, sha256=sha256_file(fitted))],
            convergence=[SimpleNamespace(log_likelihood=x) for x in (-100., -99., -98.)])
        refs.append(dict(directory=str(root), target=target, candidate_id='fit'))
    monkeypatch.setattr(guided_feedback, 'verify_reference',
                        lambda ref: snapshots[ref['directory']])
    monkeypatch.setattr(study, '_verify_manifest', lambda root: manifests[root])
    monkeypatch.setattr(study, 'calibration_candidate_run_directory',
                        lambda candidate: next(p / 'run' for p, s in
                            ((Path(k), v) for k, v in snapshots.items())
                            if s.candidates[0] is candidate))
    monkeypatch.setattr(result_report, 'collect_run_report', lambda run: reports[run])
    monkeypatch.setattr(regional_evaluation, 'endpoint', lambda candidate: None)
    monkeypatch.setattr(diagnosis, '_CACHE', OrderedDict())
    a, b = refs
    first = diagnosis._compare(a, b)
    assert first['agreement']['repeats'][0]['p95'] == pytest.approx(.2, abs=1e-5)
    assert diagnosis._compare(a, b) == first
    snapshots[a['directory']].visual_reviews['fit'] = False
    with pytest.raises(ValueError, match='approved individual'):
        diagnosis._compare(a, b)
    snapshots[a['directory']].visual_reviews['fit'] = True
    with pytest.raises(ValueError, match='approved individual'):
        diagnosis._compare(a, dict(b, target='another.vtk'))
    fitted = next((tmp_path / 'common' / 'run' / 'output').iterdir())
    fitted.write_text(fitted.read_text() + '\n')
    with pytest.raises(ValueError, match='reconstruction changed'):
        diagnosis._compare(a, b)


def test_diagnosis_panel_displays_reason_and_inspects_only_the_accepted_reference(monkeypatch):
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop.pilot_common_model import recovery

    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    calls = []
    ref = {'target': 'form.vtk', 'directory': 'accepted'}
    value = dict(diagnosis.assess(evidence(local=True)), accepted=ref)
    window._open_guided_saved_fit = lambda row: calls.append(('inspect', row))
    window._start_pilot = lambda **kw: calls.append(('prepare', kw))
    recovery(window, layout, 'fit', dict(mode='capacity', available=True, target='form.vtk',
        label='Compare more controls · 200 → 300 · form.vtk', reason='Bounded capacity test',
        diagnosis=value))
    assert window.findChild(QLabel, 'commonAcceptedComparison').text().startswith('Compared')
    buttons = window.findChildren(QPushButton)
    next(b for b in buttons if b.text().startswith('Inspect accepted')).click()
    assert calls == [('inspect', ref)]
    next(b for b in buttons if b.text().startswith('Compare more')).click()
    assert calls[-1] == ('prepare', dict(adaptive=False,
        guided_action=('adaptive_common_continue', 'fit', 'form.vtk')))
    window.close()
    app.processEvents()
