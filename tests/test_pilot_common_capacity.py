"""Complete-field CP demand, oversized shared bases and preserved approvals."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import pilot_common_capacity as capacity


def test_composed_demand_counts_local_additions_without_doubling_refinements(monkeypatch):
    from diffeoforge import guided_feedback

    def ref(name):
        return dict(directory=name, candidate_id='fit')
    def field(number, mode=None, parent=None):
        return SimpleNamespace(attachment_comparison=dict(controls=dict(count=number),
            refinement=dict(initialization=mode, reference=ref(parent)) if mode else {}))
    rows = dict(base=field(200), local=field(201, 'residual', 'base'),
                second=field(75, 'residual', 'local'),
                refined=field(300, 'nested', 'base'),
                continued=field(201, 'learned', 'local'))
    rows['continued'].attachment_comparison['regional_objective'] = dict(version='test')
    monkeypatch.setattr(guided_feedback, 'verify_reference', lambda r: rows[r['directory']])
    assert capacity.count(ref('local')) == 401
    assert capacity.count(ref('second')) == 476
    assert capacity.count(ref('refined')) == 300
    assert capacity.count(ref('continued')) == 401
    rows['base'].attachment_comparison['refinement'] = dict(
        initialization='residual', reference=ref('second'))
    with pytest.raises(ValueError, match='Cyclic'):
        capacity.count(ref('second'))


def test_demand_rejects_an_unapproved_or_different_cohort_reference(monkeypatch):
    from diffeoforge import guided_feedback
    from diffeoforge import reference_guided_pilot as guided

    ref = dict(directory='accepted', candidate_id='fit')
    base = SimpleNamespace(origin='cohort', visual_reviews={'fit': True})
    accepted = SimpleNamespace(origin='cohort', visual_reviews={'fit': False},
                                attachment_comparison={'controls': {'count': 400}})
    monkeypatch.setattr(guided_feedback, 'verify_reference',
                        lambda r: base if r['directory'] == 'base' else accepted)
    monkeypatch.setattr(guided, 'record', lambda p: dict(origin=p.origin))
    value = dict(protocol=dict(reference=dict(ref, directory='base')),
                 reviews=[dict(ref, filename='animal.vtk')])
    with pytest.raises(ValueError, match='accepted'):
        capacity.demand(value)
    accepted.visual_reviews['fit'] = True
    accepted.origin = 'other'
    with pytest.raises(ValueError, match='cohort'):
        capacity.demand(value)


def test_native_basis_adds_the_whole_demand_without_the_old_fifty_percent_ceiling():
    from diffeoforge.guided_density import extend

    old = np.array([[x, y, z] for x in (0., 1.) for y in (0., 1.) for z in (0., 1.)])
    dense = extend(old, .2, target_count=41)
    assert len(dense) == 41 and np.array_equal(dense[:len(old)], old)
    with pytest.raises(ValueError, match='too large'):
        extend(old, .2, target_count=2001)


def test_fresh_capacity_is_shared_after_explicit_adoption_and_keeps_each_saved_field(
        tmp_path, monkeypatch):
    from test_guided_pilot import approve, run_batch
    from test_reviewed_start_progress import selected_local_after_common_failure

    from diffeoforge import guided_strategy, pilot_common_model, pilot_form_progress
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca import read_deformetrica_momenta

    local, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    value = pilot_form_progress.marker(current)
    hardest = guided.record(local)['target']
    # Classification-only fixture: emulate a composed field's measured demand.
    # The field binding/approvals/basis preparation and adoption are real paths.
    monkeypatch.setattr(capacity, 'demand', lambda v: {
        r['filename']: 480 if r['filename'] == hardest else 200 for r in v['reviews']})
    monkeypatch.setattr(pilot_common_model, '_saved', lambda *a: [])
    protected = {p: sha256_file(p) for p in local.study_directory.rglob('*') if p.is_file()}
    choice = guided_strategy.state(current)['common_recovery']
    assert choice['mode'] == 'fresh_capacity' and choice['target'] == hardest
    assert choice['proposed_controls'] == 480
    child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    assert child.candidates[0].attempts == 0 and not child.visual_reviews
    assert child.attachment_comparison['controls']['count'] == 480
    assert child.attachment_comparison['iterations'] == 120
    assert not child.attachment_comparison.get('refinement')
    assert pilot_form_progress.marker(child) == value
    config = load_config(child.candidates[0].config_path)
    assert 'initial_momenta' not in config['model']['deformation']
    assert guided_strategy.state(child)['common_recovery']['mode'] == 'prepared'
    folders = set(child.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='Complete or resolve|already prepared'):
        guided.next_action(child.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(child.study_directory.parent.iterdir()) == folders
    accepted = approve(run_batch(child, monkeypatch, capped=True))
    assert pilot_form_progress.marker(accepted) == value
    from diffeoforge.pilot_common_start import prepare

    hypothetical = deepcopy(value)
    row = guided._approved_record(accepted, 'guided-varifold')
    hypothetical['reviews'] = [row if r['filename'] == hardest else r
                               for r in hypothetical['reviews']]
    selected, policy = prepare(current, hypothetical)
    assert policy['controls'] == 480 and policy['required_controls'] == 480
    assert selected['protocol']['reference']['directory'] == str(accepted.study_directory)
    adopted = guided.next_action(accepted.study_directory, 'adaptive_adopt_common_model',
                                 'guided-varifold')
    assert pilot_form_progress.marker(adopted)['reviews'] == value['reviews']
    assert adopted.attachment_comparison['controls']['sha256'] == (
        accepted.attachment_comparison['controls']['sha256'])
    assert adopted.attachment_comparison['controls']['count'] == 480
    refinement = adopted.attachment_comparison['refinement']
    assert refinement['initialization'] == 'nested'
    cp = np.loadtxt(adopted.study_directory / adopted.attachment_comparison['controls']['copy'])
    old = np.loadtxt(adopted.study_directory / refinement['source_controls']['copy'])
    weights = read_deformetrica_momenta(adopted.study_directory / refinement['momenta']['copy'],
                                       allow_singleton=True)
    previous = read_deformetrica_momenta(
        adopted.study_directory / refinement['source_momenta']['copy'], allow_singleton=True)
    assert np.array_equal(cp[:len(old)], old)
    assert np.array_equal(weights[:, :len(old)], previous)
    assert not weights[:, len(old):].any()
    assert all(sha256_file(p) == digest for p, digest in protected.items())
    # A first common phase must also start with the demand rather than preparing
    # one undersized check on every animal before noticing the local additions.
    from diffeoforge import reference_calibration_study as study

    fixture_state = deepcopy(guided.record(current)['strategy'])
    for key in ('common_capacity_request', 'common_diagnosis_test', 'common_basis_step',
                'baseline', 'anchor', 'optimization', 'common_model_step'):
        fixture_state.pop(key, None)
    fixture_state['form_progress'] = dict(value, stage='forms')
    fixture_state['control_basis'] = value['protocol']['reference']
    previous_ref = dict(directory=str(current.study_directory),
        manifest_sha256=sha256_file(current.study_directory / study.STUDY_MANIFEST))
    fixture_state['previous'] = previous_ref
    source, _ = guided._origin(current.study_directory)
    info = guided.record(current)
    other = next(r['filename'] for r in value['reviews'] if r['filename'] != hardest)
    first = guided._batch(source, previous=None, phase='refine', target=other,
        methods=('varifold',), values=value['protocol']['reference']['values'],
        approved=info['approved'], history=[*info['history'],
        dict(previous_ref, outcome='prospective_capacity_fixture')],
        spent=info['screen_trials_spent'], strategy=fixture_state, goal='weight')
    first = approve(run_batch(first, monkeypatch))
    initial_common = guided.next_action(first.study_directory, 'adaptive_form_model_check',
                                        'guided-varifold')
    assert initial_common.attachment_comparison['controls']['count'] == 480
    assert guided.record(initial_common)['target'] == hardest
    assert initial_common.attachment_comparison['iterations'] == 120
    request = guided.record(child)['strategy']['common_capacity_request']
    tampered = deepcopy(request)
    tampered['target_count'] -= 1
    with pytest.raises(ValueError, match='bound accepted'):
        capacity.validate(tampered, value)
    monkeypatch.setattr(capacity, 'demand', lambda v: {hardest: 2100})
    blocked = capacity.choice(value, hardest)
    assert blocked['proposed_controls'] == 2100 and not blocked['available']
    with pytest.raises(ValueError, match='not silently reduced'):
        capacity.apply(dict(strategy={}), blocked)
