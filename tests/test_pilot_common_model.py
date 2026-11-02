"""Journeys from retained local approval through a shared-model continuation."""
from pathlib import Path

import pytest
from test_guided_pilot import approve, run_batch
from test_reviewed_start_progress import selected_local_after_common_failure

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import pilot_common_model as common
from diffeoforge import pilot_form_progress as progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def test_first_common_continuation_requires_explicit_relative_feedback(tmp_path, monkeypatch):
    _, current = selected_local_after_common_failure(tmp_path, monkeypatch, outcome=None)
    choice = strategy.state(current)['common_recovery']
    assert choice['mode'] == 'feedback' and choice['available'] and choice['review_reference']
    folders = set(current.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='explicit Better'):
        guided.next_action(current.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(current.study_directory.parent.iterdir()) == folders


def test_saved_common_field_continues_without_cold_restart_and_reaches_joint(tmp_path, monkeypatch):
    local, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    ledger = progress.marker(current)
    pins = {p: sha256_file(p) for p in local.study_directory.rglob('*') if p.is_file()}
    choice = strategy.state(current)['common_recovery']
    assert choice['mode'] == 'continue' and choice['previous_iterations'] == 120
    assert Path(choice['reference']['directory']) == current.study_directory
    child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    assert progress.marker(child) == ledger and not child.visual_reviews
    assert child.attachment_comparison['refinement']['reference'] == choice['reference']
    assert child.attachment_comparison['refinement']['initialization'] == 'learned'
    assert common.physics(load_config(child.candidates[0].config_path)) == common.physics(
        load_config(current.candidates[0].config_path))
    completed = run_batch(child, monkeypatch, capped=True)
    assert completed.candidates[0].metrics['iteration_accounting']['total_iterations'] == 240
    assert strategy.state(completed)['common_recovery']['mode'] == 'review'
    folders = set(completed.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='already exists'):
        guided.next_action(completed.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(completed.study_directory.parent.iterdir()) == folders
    from test_pilot_region_feedback import reject
    completed = reject(completed, 'guided-varifold')
    assert strategy.state(completed)['common_recovery']['mode'] == 'feedback'
    accepted = approve(completed)
    assert strategy.state(accepted)['checked'] == len(guided.record(accepted)['pilot_order'])
    joint = guided.next_action(accepted.study_directory, 'adaptive_next_form', 'guided-varifold')
    assert guided.record(joint)['phase'] == 'joint'
    assert joint.attachment_comparison['joint_initialization']['references']
    assert not joint.visual_reviews and all(sha256_file(p) == h for p, h in pins.items())
    reviewed_joint = approve(run_batch(joint, monkeypatch))
    assert not strategy.state(reviewed_joint)['common_revision']


def test_no_improvement_stops_repeat_and_model_revision_is_explicit(tmp_path, monkeypatch):
    _, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    old = progress.marker(current)
    child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    completed = run_batch(child, monkeypatch, capped=True)
    target = guided.record(completed)['target']
    completed = feedback.save_feedback(completed.study_directory, 'guided-varifold', dict(
        comparison=feedback.reference(current, 'guided-varifold'), outcome='same',
        inspected_subjects=[target], display_scopes={target: 'original_proxy'},
        note='No further shape improvement', comparison_displayed=False))
    assert strategy.state(completed)['common_recovery']['mode'] == 'stalled'
    with pytest.raises(ValueError, match='did not improve'):
        guided.next_action(completed.study_directory, 'adaptive_common_continue', 'guided-varifold')
    changed = guided.next_action(completed.study_directory, 'adaptive_recover',
                                 'guided-varifold', goal='goal:weight')
    changed = approve(run_batch(changed, monkeypatch))
    state = strategy.state(changed)
    assert progress.marker(changed)['protocol'] == old['protocol']
    assert state['checked'] == len(guided.record(changed)['pilot_order']) - 1
    revised = state['common_revision']['guided-varifold']
    assert revised['checked'] == 1
    successor = guided.next_action(changed.study_directory, 'adaptive_adopt_common_model',
                                   'guided-varifold')
    assert progress.marker(successor)['protocol'] != old['protocol']
    assert progress.marker(successor)['reviews']
    assert not successor.visual_reviews and successor.candidates[0].attempts == 0


def test_common_review_button_opens_existing_result_without_preparing(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop.pilot_common_model import dispatch, recovery

    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    calls = []
    ref = dict(directory='saved-common', target='form.vtk')
    root._open_common_saved_fit = lambda value: calls.append(('review', value))
    root._start_pilot = lambda **kw: pytest.fail('Review must not prepare or run a fit')
    choice = dict(mode='review', available=True, reference=ref, target='form.vtk',
                  label='Review saved common-model fit · form.vtk')
    recovery(root, layout, 'guided-varifold', choice)
    root.findChild(QPushButton).click()
    dispatch(root, dict(common_reuse=choice), 'guided-varifold', starting=True)
    assert calls == [('review', ref), ('review', ref)]
    root.close()
    app.processEvents()


def test_optional_optimization_cannot_bypass_common_no_improvement_from_older_fit(
    tmp_path, monkeypatch
):
    from diffeoforge import guided_working_fit as working

    _, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    completed = run_batch(child, monkeypatch, capped=True)
    target = guided.record(completed)['target']
    completed = feedback.save_feedback(completed.study_directory, 'guided-varifold', dict(
        comparison=feedback.reference(current, 'guided-varifold'), outcome='same',
        inspected_subjects=[target], display_scopes={target: 'original_proxy'},
        note='No useful improvement', comparison_displayed=False))
    context = strategy.state(completed)
    parent, data = working.inputs(completed, 'guided-varifold', context)
    assert parent.study_directory == current.study_directory
    proposed = working.propose(parent, 'goal:optimize', data)
    assert not proposed['available'] and 'did not improve' in proposed['blocked_reason']
    folders = set(completed.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='did not improve'):
        guided.next_action(completed.study_directory, 'adaptive_recover_start',
                           'guided-varifold', goal='goal:optimize')
    assert set(completed.study_directory.parent.iterdir()) == folders


def test_optional_common_optimization_keeps_allowance_accounts_effort_and_requires_feedback(
    tmp_path, monkeypatch
):
    from diffeoforge import pilot_iteration_accounting as effort

    _, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    current = feedback.select(current.study_directory, 'guided-varifold',
                              feedback.reference(current, 'guided-varifold'))
    child = guided.next_action(current.study_directory, 'adaptive_recover',
                               'guided-varifold', goal='goal:optimize')
    marker = guided.record(child)['strategy']['optimization']
    assert marker['version'] == common.EFFORT_VERSION
    assert marker['common_model'] is True and marker['initial_iterations'] == 120
    assert marker['iterations'] == child.attachment_comparison['iterations'] == 120
    assert common.physics(load_config(child.candidates[0].config_path)) == common.physics(
        load_config(current.candidates[0].config_path))
    completed = run_batch(child, monkeypatch, capped=True)
    assert effort.total(completed.candidates[0].metrics) == 240
    manifest = study._verify_manifest(completed.study_directory)
    assert effort.source(manifest, 'guided-varifold') == (
        current.study_directory, 'guided-varifold')
    # Historical optional optimizations had no cumulative marker. Reading an old
    # contract must not retroactively reinterpret its recorded native counter.
    import copy
    legacy = copy.deepcopy(manifest)
    legacy['attachment_comparison']['guided']['strategy']['optimization'].pop('version')
    assert effort.source(legacy, 'guided-varifold') is None
    from test_pilot_region_feedback import reject

    inspected = reject(completed, 'guided-varifold')
    assert strategy.state(inspected)['common_recovery']['mode'] == 'feedback'
