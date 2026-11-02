"""A better but unsuitable capacity result can be refined without false approval."""
from copy import deepcopy

import numpy as np
import pytest

from diffeoforge import pilot_common_candidate as candidate


def test_candidate_policy_uses_finite_iterations_or_surface_contrasts_without_approval():
    measured = dict(gap=True, trend='improving', warnings=[])
    assert candidate.decide(measured, capped=True, counts={}, outcome='better') == 'iterations'
    assert candidate.decide(measured, capped=True, counts={}) == 'detail'
    assert candidate.decide(measured, capped=True, counts={}, outcome='same') == 'detail'
    assert candidate.decide(measured, capped=True, counts={}, outcome='unsure') == 'detail'
    assert candidate.decide(measured, capped=True, counts={}, outcome='worse') == 'detail'
    assert candidate.decide(measured, capped=True, counts={'iterations': 2}) == 'detail'
    measured['trend'] = 'worse'
    assert candidate.decide(measured, capped=True, counts={}) == 'detail'
    assert candidate.decide(measured, capped=True, counts={'detail': 1}) == 'weight'
    assert candidate.decide(measured, capped=True, counts={'detail': 1, 'weight': 1}) is None
    measured['warnings'] = ['geometry-check']
    assert candidate.decide(measured, capped=True, counts={}) is None


def test_shared_field_transfer_allows_only_explicit_objective_contrasts(tmp_path):
    from test_reference_calibration_study import _project

    from diffeoforge.config import load_config
    from diffeoforge.pilot_common_basis import field_physics

    original = load_config(_project(tmp_path))
    before = deepcopy(original)
    objective = deepcopy(original)
    objective['model']['attachment']['kernel_width'] *= .9
    objective['model']['noise_std'] *= .9
    assert field_physics(objective) == field_physics(original)
    deformation = deepcopy(objective)
    deformation['model']['deformation']['kernel_width'] *= .9
    assert field_physics(deformation) != field_physics(original)
    accuracy = deepcopy(objective)
    accuracy['optimization']['convergence_tolerance'] *= .1
    assert field_physics(accuracy) != field_physics(original)
    assert original == before


def compared(snapshot, outcome):
    from diffeoforge import guided_feedback
    from diffeoforge import reference_guided_pilot as guided

    info = guided.record(snapshot)
    return guided_feedback.save_feedback(snapshot.study_directory, 'guided-varifold', dict(
        comparison=info['strategy']['baseline'], outcome=outcome,
        inspected_subjects=[info['target']], display_scopes={info['target']: 'original_proxy'},
        comparison_displayed=False, note='Explicit public-fixture comparison'))


def rejected_capacity(tmp_path, monkeypatch, *, outcome='better', reviewed=True):
    from test_guided_pilot import run_batch
    from test_pilot_common_diagnosis import evidence
    from test_pilot_region_feedback import reject
    from test_reviewed_start_progress import selected_local_after_common_failure

    from diffeoforge import guided_feedback
    from diffeoforge import pilot_common_diagnosis as diagnosis
    from diffeoforge import reference_guided_pilot as guided

    local, current = selected_local_after_common_failure(tmp_path, monkeypatch)
    accepted = guided_feedback.reference(local, 'guided-varifold')
    trend = {'value': 'worse'}
    def measured(snapshot, value, ref, previous=None):
        result = diagnosis.assess(evidence(local=True))
        result['trend'] = trend['value']
        return dict(version=diagnosis.VERSION, accepted=accepted, current=ref,
                    previous=previous, **result)
    monkeypatch.setattr(diagnosis, 'diagnose', measured)
    root = guided.next_action(current.study_directory, 'adaptive_common_continue',
                              'guided-varifold')
    root = run_batch(root, monkeypatch, capped=True)
    if reviewed:
        root = reject(root, 'guided-varifold')
    if outcome is not None:
        root = compared(root, outcome)
    return local, root, trend


def check_review_route(snapshot, choice, monkeypatch):
    """The primary experiment and the reopen action have different destinations."""
    from types import SimpleNamespace

    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop import reference_calibration_dialog as dialog_module
    from diffeoforge.desktop.pilot_common_model import recovery
    from diffeoforge.desktop.pilot_review_target import choose

    target = choose(snapshot, {'common_recovery': choice}, guided.record(snapshot))
    assert target['kind'] == 'common' and not target['pending']
    assert target['reference'] == choice['review_reference']
    assert 'individual' not in target['label']
    prepared = []
    window = SimpleNamespace(_view_loading=False, _view_closed=False, _review_saving=False,
        _worker=None, study_directory=snapshot.study_directory,
        _viewer_preparation=SimpleNamespace(request_operation=lambda key, fn: prepared.append(fn)))
    monkeypatch.setattr(dialog_module, 'collect_calibration_qc_pairs', lambda *args: ())
    monkeypatch.setattr(dialog_module, 'normalized_candidate_subject_fit', lambda *args: ())
    from diffeoforge import guided_feedback
    from diffeoforge.desktop import guided_feedback as feedback_ui
    from diffeoforge.desktop import saved_fit_comparison

    monkeypatch.setattr(feedback_ui, 'prepare_context', guided_feedback.presentation)
    monkeypatch.setattr(saved_fit_comparison, 'alternatives', lambda *args: ())
    open_result = dialog_module.ReferenceCalibrationDialog._open_common_saved_fit
    open_result(window, target['reference'])
    loaded = prepared.pop()()
    assert len(loaded) == 5 and loaded[4]['comparison']
    assert str(loaded[0].study_directory) == target['reference']['directory']
    bad = dict(target['reference'], field_sha256='changed')
    open_result(window, bad)
    with pytest.raises(ValueError, match='current missing common-model check'):
        prepared.pop()()

    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    layout = QVBoxLayout(widget)
    calls = []
    widget._start_pilot = lambda **kwargs: calls.append(kwargs)
    widget._open_guided_saved_fit = lambda *_: pytest.fail('Wrong review destination')
    widget._open_common_saved_fit = lambda *_: pytest.fail('Refine must prepare, not review')
    recovery(widget, layout, 'guided-varifold', choice)
    primary = [button for button in widget.findChildren(QPushButton)
               if button.objectName() == 'primary']
    assert len(primary) == 1
    primary[0].click()
    assert calls == [dict(adaptive=False, guided_action=(
        'adaptive_common_continue', 'guided-varifold', choice['target']))]
    assert snapshot.visual_reviews['guided-varifold'] is False
    widget.close()
    app.processEvents()


def test_rejected_candidate_keeps_its_field_and_approvals_through_contrast_and_adoption(
        tmp_path, monkeypatch):
    from test_guided_pilot import approve, run_batch
    from test_pilot_region_feedback import reject

    from diffeoforge import guided_feedback, guided_strategy, pilot_form_progress
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca import read_deformetrica_momenta

    local, root, _ = rejected_capacity(tmp_path, monkeypatch)
    ledger = pilot_form_progress.marker(root)
    approvals = deepcopy(guided.record(root)['approved'])
    protected = {p: sha256_file(p) for p in local.study_directory.rglob('*') if p.is_file()}
    choice = guided_strategy.state(root)['common_recovery']
    assert choice['mode'] == 'candidate_refine' and choice['kind'] == 'detail'
    assert choice['reference'] == guided_feedback.reference(root, 'guided-varifold')
    assert choice['additional_iterations'] == 120
    assert root.visual_reviews['guided-varifold'] is False
    check_review_route(root, choice, monkeypatch)
    from diffeoforge.pilot_common_model import optimization_context

    guarded = optimization_context(root, {'common_recovery': choice}, [choice['reference']])
    assert next(iter(guarded.values()))['blocked_reason']
    child = guided.next_action(root.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert child.candidates[0].attempts == 0 and not child.visual_reviews
    assert child.attachment_comparison['controls']['sha256'] == root.attachment_comparison[
        'controls']['sha256']
    refinement = child.attachment_comparison['refinement']
    assert refinement['initialization'] == 'learned'
    new_weights = read_deformetrica_momenta(child.study_directory / refinement['momenta']['copy'],
                                           allow_singleton=True)
    from diffeoforge.guided_refinement import load_field

    old_field = load_field(study.calibration_candidate_run_directory(root.candidates[0]))
    assert np.array_equal(new_weights, old_field.momenta)
    assert pilot_form_progress.marker(child) == ledger
    assert guided.record(child)['approved'] == approvals
    assert guided.record(child)['goal'] == 'common_candidate'
    assert child.plan.effective_values == choice['values']
    manifest = study._verify_manifest(child.study_directory)
    with study.calibration_verification_scope():
        for field, changed in [('additional_iterations', 121), ('kind', 'unknown'),
                               ('approval_transferred', True), ('previous_iterations', 0),
                               ('reference', guided_feedback.reference(local, 'guided-varifold'))]:
            invalid = deepcopy(manifest)
            info = invalid['attachment_comparison']['guided']
            info['strategy']['common_candidate_step'][field] = changed
            with pytest.raises(ValueError):
                candidate.verify(info, invalid['attachment_comparison'], invalid,
                                 child.study_directory)
        invalid = deepcopy(manifest)
        invalid['attachment_comparison']['controls']['sha256'] = '0' * 64
        with pytest.raises(ValueError):
            candidate.verify(invalid['attachment_comparison']['guided'],
                             invalid['attachment_comparison'], invalid, child.study_directory)
    assert guided_strategy.state(child)['common_recovery']['mode'] == 'prepared'
    folders = set(child.study_directory.parent.iterdir())
    with pytest.raises(ValueError, match='Complete or resolve|already prepared'):
        guided.next_action(child.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(child.study_directory.parent.iterdir()) == folders
    completed = reject(run_batch(child, monkeypatch, capped=True), 'guided-varifold')
    assert completed.candidates[0].metrics['iteration_accounting']['total_iterations'] == 360
    assert guided_strategy.state(completed)['common_recovery']['mode'] == 'feedback'
    completed = compared(completed, 'worse')
    next_choice = guided_strategy.state(completed)['common_recovery']
    assert next_choice['kind'] == 'weight'
    assert next_choice['reference'] == choice['reference']  # Roll back a worse contrast.
    assert next_choice['review_reference'] != next_choice['reference']
    check_review_route(completed, next_choice, monkeypatch)
    other = guided.next_action(completed.study_directory, 'adaptive_common_continue',
                               'guided-varifold')
    other = approve(run_batch(other, monkeypatch, capped=True))
    assert guided_strategy.state(other)['common_recovery']['mode'] == 'adopt'
    assert pilot_form_progress.marker(other) == ledger
    adopted = guided.next_action(other.study_directory, 'adaptive_adopt_common_model',
                                 'guided-varifold')
    assert pilot_form_progress.marker(adopted)['reviews'] == ledger['reviews']
    assert adopted.attachment_comparison['controls']['sha256'] == root.attachment_comparison[
        'controls']['sha256']
    assert adopted.attachment_comparison['refinement']['initialization'] == 'nested'
    config = load_config(adopted.candidates[0].config_path)
    assert config['model']['noise_std'] == other.plan.effective_values['noise_std']
    assert all(sha256_file(p) == digest for p, digest in protected.items())
    assert not adopted.visual_reviews


def test_candidate_iteration_accounting_and_exhaustion_do_not_reset_on_navigation(
        tmp_path, monkeypatch):
    from test_guided_pilot import run_batch
    from test_pilot_region_feedback import reject

    from diffeoforge import guided_strategy
    from diffeoforge import reference_guided_pilot as guided

    _, current, trend = rejected_capacity(tmp_path, monkeypatch)
    trend['value'] = 'improving'
    for expected in (1, 2):
        proposed = guided_strategy.state(current)['common_recovery']
        assert proposed['kind'] == 'iterations'
        child = guided.next_action(current.study_directory, 'adaptive_common_continue',
                                   'guided-varifold')
        assert child.attachment_comparison['iterations'] == 120
        current = reject(run_batch(child, monkeypatch, capped=True), 'guided-varifold')
        assert guided_strategy.state(current)['common_recovery']['mode'] == 'feedback'
        current = compared(current, 'better')
        assert current.candidates[0].metrics['iteration_accounting']['total_iterations'] == (
            240 + expected * 120)
    assert guided_strategy.state(current)['common_recovery']['kind'] == 'detail'


def test_candidate_requires_comparison_and_same_vetoes_further_unchanged_iterations(
        tmp_path, monkeypatch):
    from diffeoforge import guided_strategy
    from diffeoforge import reference_guided_pilot as guided

    _, current, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None)
    trend['value'] = 'improving'  # A geometric trend must not substitute for a human opinion.
    folders = set(current.study_directory.parent.iterdir())
    choice = guided_strategy.state(current)['common_recovery']
    assert choice['mode'] == 'feedback' and choice['review_reference']
    with pytest.raises(ValueError, match='Better|About the same|Worse'):
        guided.next_action(current.study_directory, 'adaptive_common_continue', 'guided-varifold')
    assert set(current.study_directory.parent.iterdir()) == folders
    current = compared(current, 'same')
    choice = guided_strategy.state(current)['common_recovery']
    assert choice['kind'] != 'iterations' and not current.visual_reviews['guided-varifold']
