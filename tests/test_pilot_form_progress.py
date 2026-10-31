"""Approved regional shapes can progress without becoming common-model approval."""

from copy import deepcopy

import pytest
from test_guided_feedback import attempted
from test_guided_pilot import approve, run_batch
from test_pilot_region_feedback import reject

from diffeoforge import guided_strategy as strategy
from diffeoforge import pilot_form_progress as progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def local_fit(tmp_path, monkeypatch):
    from dataclasses import replace

    base, completed = attempted(tmp_path, monkeypatch)
    accepted = approve(completed, 'guided-varifold')
    load = study.load_reference_calibration_study
    root = accepted.study_directory

    def classified(directory, **kwargs):
        snapshot = load(directory, **kwargs)
        if snapshot.study_directory != root:
            return snapshot
        # Only regional classification is synthetic. Source references, approved
        # receipts, next-form staging and joint assembly are real controller paths.
        return replace(snapshot, attachment_comparison=dict(snapshot.attachment_comparison,
            regional_objective=dict(version='synthetic-regional-classification')))

    monkeypatch.setattr(study, 'load_reference_calibration_study', classified)
    return base, classified(root)


def test_suitable_regional_result_prepares_next_form_without_transferring_field_or_approval(
        tmp_path, monkeypatch):
    base, local = local_fit(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in local.study_directory.rglob('*') if p.is_file()}
    context = strategy.state(local)
    following = context['next_forms']['guided-varifold']
    assert following['available'] and following['checked'] == 0 and following['shapes'] == 1
    assert following['target'] != guided.record(local)['target']
    child = guided.next_action(local.study_directory, 'adaptive_next_form', 'guided-varifold')
    info = guided.record(child)
    assert info['target'] == following['target'] and info['phase'] == 'validate'
    assert len(info['strategy']['form_progress']['reviews']) == 1 and not info['approved']
    assert not child.attachment_comparison.get('refinement')
    assert not child.attachment_comparison.get('regional_objective')
    assert not {'baseline', 'anchor', 'regional_recipe'} & info['strategy'].keys()
    assert not info['feedback'] and not child.visual_reviews
    assert child.candidates[0].attempts == 0
    assert child.attachment_comparison['iterations'] == 120
    controls = child.attachment_comparison['controls']
    assert controls['sha256'] == base.attachment_comparison['controls']['sha256']
    cfg = load_config(child.candidates[0].config_path)
    previous = load_config(local.candidates[0].config_path)
    assert 'initial_momenta' not in cfg['model']['deformation']
    assert cfg['model']['deformation']['timepoints'] == (
        previous['model']['deformation']['timepoints'])
    assert cfg['optimization']['convergence_tolerance'] == (
        previous['optimization']['convergence_tolerance'])
    assert all(sha256_file(p) == digest for p, digest in before.items()
               if p.name not in {study.STUDY_EVENTS, 'fit-search-latest.json'})


def test_individual_reviews_do_not_claim_joint_coverage(tmp_path, monkeypatch):
    _, local = local_fit(tmp_path, monkeypatch)
    current = guided.next_action(local.study_directory, 'adaptive_next_form', 'guided-varifold')
    seen = {guided.record(local)['target']}
    while True:
        current = approve(run_batch(current, monkeypatch), 'guided-varifold')
        target = guided.record(current)['target']
        assert target not in seen
        seen.add(target)
        current = guided.next_action(current.study_directory, 'adaptive_next_form',
                                     'guided-varifold')
        value = progress.marker(current)
        if len(seen) == len(guided.record(local)['pilot_order']):
            break
        assert guided.record(current)['phase'] == 'validate'
    assert len(value['reviews']) == len(seen)
    assert guided.record(current)['phase'] != 'joint'
    state = strategy.state(current)
    assert 'guided-varifold' in state.get('next_forms', {}), (
        current.visual_reviews, guided.record(current)['phase'],
        state.get('next_forms'), guided.record(current).get('goal'))
    next_check = state['next_forms']['guided-varifold']
    assert next_check['action'] == 'form_model_check'
    assert next_check['checked'] < next_check['total']
    assert next_check['target'] == guided.record(local)['target']
    common = guided.next_action(current.study_directory, 'adaptive_form_model_check',
                                'guided-varifold')
    assert not common.attachment_comparison.get('regional_objective')
    assert not common.attachment_comparison.get('refinement')
    assert not common.visual_reviews and common.candidates[0].attempts == 0
    checked = approve(run_batch(common, monkeypatch), 'guided-varifold')
    joint = guided.next_action(checked.study_directory, 'adaptive_next_form', 'guided-varifold')
    assert guided.record(joint)['phase'] == 'joint'
    assert len(guided.record(joint)['approved']) == len(seen)
    assert not joint.visual_reviews and joint.candidates[0].attempts == 0


def test_progress_rejects_unapproved_or_changed_protocol(tmp_path, monkeypatch):
    _, local = local_fit(tmp_path, monkeypatch)
    rejected = reject(local, 'guided-varifold')
    with pytest.raises(ValueError, match='approve'):
        guided.next_action(rejected.study_directory, 'adaptive_next_form', 'guided-varifold')
    accepted = approve(rejected, 'guided-varifold')
    data = progress.proposal(accepted, 'guided-varifold', strategy.state(accepted))
    bad = deepcopy(data['marker'])
    bad['protocol']['integration']['timepoints'] += 1
    with pytest.raises(ValueError, match='protocol'):
        progress.verify_marker(bad, guided.record(accepted)['origin'],
                               guided.record(accepted)['pilot_order'])
