"""Review and continuation stay outside the long scrolling history."""

import pytest
from test_guided_suitable_dialog import panel as panel


def test_finished_fit_review_stays_visible_after_scrolling_and_opens_current_result(panel):
    from PySide6.QtWidgets import QScrollArea

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFixedHeight(420)
    panel.window.layout().removeWidget(panel.window.content)
    scroll.setWidget(panel.window.content)
    panel.window.layout().insertWidget(0, scroll)
    panel.window._snapshot = panel.snapshot
    panel.window.selection_combo.currentData = lambda: None
    panel.window.review_next_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._open_next_review(panel.window))
    panel.render()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    panel.app.processEvents()
    button = panel.window.review_next_button
    assert button.isVisible() and button.isEnabled()
    assert 'individual result' in button.text()
    assert 'Test 5' in button.text() and 'specimen.vtk' in button.text()
    assert not scroll.isAncestorOf(button)
    assert panel.window.rect().contains(button.geometry())
    button.click()
    assert panel.inspected == [panel.candidate] and not panel.invoked


def test_suitable_latest_fit_has_sticky_next_action_and_no_default_old_fit_recovery(panel):
    from PySide6.QtWidgets import QFrame

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    identifier = panel.candidate.candidate_id
    panel.snapshot.visual_reviews[identifier] = True
    choices = panel.guidance['proposals'][identifier]
    panel.guidance['working_proposals'] = {identifier: choices}
    panel.guidance['next_forms'] = {identifier: dict(
        available=True, shapes=1, checked=0, total=6, action='next_form',
        label='Use suitable fit → next pilot form · next.vtk')}
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window))
    panel.render()
    button = panel.window.next_step_button
    assert button.isVisible() and button.isEnabled()
    assert button.property('actionEmphasis') is not False
    assert not any(w.property('workingFit') for w in panel.window.findChildren(QFrame))
    button.click()
    assert panel.invoked == [((), dict(adaptive=False,
        guided_action=('adaptive_next_form', identifier, None)))]


def test_review_and_next_actions_hide_during_export_or_other_live_work(panel):
    identifier = panel.candidate.candidate_id
    panel.snapshot.visual_reviews[identifier] = True
    panel.guidance['next_forms'] = {identifier: dict(
        available=True, shapes=1, checked=0, total=6, action='next_form', label='Next form')}
    panel.render()
    assert panel.window.next_step_button.isVisible()
    panel.window._worker = object()
    panel.render()
    assert not panel.window.next_step_button.isVisible()
    assert not panel.window.review_next_button.isVisible()
    assert panel.window._guided_footer_action is None and not panel.invoked


def test_next_form_input_failure_keeps_approval_and_explains_the_blocker(panel):
    from PySide6.QtWidgets import QLabel

    identifier = panel.candidate.candidate_id
    panel.snapshot.visual_reviews[identifier] = True
    panel.guidance['next_forms'] = {identifier: dict(
        available=False, reason='The original-basis input changed; review its source.')}
    panel.render()
    assert panel.window.next_step_button.isHidden()
    assert panel.window.review_next_button.isVisible()
    assert panel.snapshot.visual_reviews[identifier] is True
    assert any('original-basis input changed' in label.text()
               for label in panel.window.content.findChildren(QLabel))
    assert not panel.invoked


def test_saved_common_review_names_and_opens_its_exact_reference_not_selected_start(panel):
    from PySide6.QtWidgets import QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    ref = dict(directory='saved-common-result', candidate_id='guided-varifold',
               target='next-form.vtk')
    choice = dict(mode='review', available=True, reference=ref, target='next-form.vtk',
                  test_number=7, label='Review saved common-model fit · next-form.vtk')
    panel.guidance['common_recovery'] = choice
    panel.guidance['working_proposals'] = {
        panel.candidate.candidate_id: panel.guidance['proposals'][panel.candidate.candidate_id]}
    panel.window._snapshot = panel.snapshot
    opened = []
    panel.window._open_common_saved_fit = opened.append
    panel.window.review_next_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._open_next_review(panel.window))
    panel.render()
    button = panel.window.review_next_button
    assert button.isVisible() and 'common-model result' in button.text()
    assert 'Test 7' in button.text() and 'next-form.vtk' in button.text()
    assert panel.window.findChild(QLabel, 'pilotReviewTarget').text().startswith(button.text())
    primary = [b for b in panel.window.findChildren(QPushButton)
               if b.isVisible() and b.objectName() == 'primary']
    assert primary == [button]
    button.click()
    assert opened == [ref] and not panel.inspected and not panel.invoked


def test_approved_current_fit_reuses_next_saved_review_with_one_fixed_action(panel):
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    identifier = panel.candidate.candidate_id
    panel.snapshot.visual_reviews[identifier] = True
    ref = dict(directory='next-saved-result', candidate_id=identifier, target='other.vtk')
    choice = dict(mode='review', available=True, reference=ref, target='other.vtk',
                  test_number=9, label='Review saved common-model fit · other.vtk')
    panel.guidance['next_forms'] = {identifier: dict(
        available=True, shapes=6, checked=3, total=6, action='form_model_check',
        label=choice['label'], common_reuse=choice)}
    panel.window._snapshot = panel.snapshot
    opened = []
    panel.window._open_common_saved_fit = opened.append
    panel.window.review_next_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._open_next_review(panel.window))
    panel.render()
    assert panel.window.next_step_button.isHidden()
    assert 'Test 9' in panel.window.review_next_button.text()
    assert 'other.vtk' in panel.window.review_next_button.text()
    panel.window.review_next_button.click()
    assert opened == [ref] and not panel.inspected and not panel.invoked
    assert panel.snapshot.visual_reviews[identifier] is True


def test_local_repair_keeps_individual_scope_when_common_model_is_stalled(panel):
    panel.guidance['common_recovery'] = dict(
        mode='stalled', available=False, target='specimen.vtk',
        reference=dict(directory='older-common', candidate_id='guided-varifold',
                       target='specimen.vtk'), reason='The common field did not improve.')
    panel.render()
    assert 'individual result' in panel.window.review_next_button.text()
    assert 'common-model result' not in panel.window.review_next_button.text()


@pytest.mark.parametrize('goal', ['shared_check', 'form_model_check', 'common_continue'])
def test_existing_ordinary_common_routes_keep_their_review_scope(panel, goal):
    from diffeoforge.desktop.pilot_review_target import choose

    panel.snapshot.attachment_comparison.pop('regional_objective')
    panel.guidance['common_recovery'] = dict(mode='stalled', available=False)
    result = choose(panel.snapshot, panel.guidance, dict(
        phase='validate', goal=goal, target='specimen.vtk', screen_trials_spent=23))
    assert 'common-model result' in result['label']
    assert 'Test 23' in result['label'] and 'specimen.vtk' in result['label']


def test_pending_common_review_keeps_accepted_return_visible_as_secondary(panel):
    from PySide6.QtWidgets import QPushButton

    ref = dict(directory='accepted-study', candidate_id='guided-varifold')
    panel.guidance['accepted_fits'] = {panel.candidate.candidate_id: dict(
        reference=ref, label='Test 3', target='specimen.vtk', selected=False)}
    panel.guidance['common_recovery'] = dict(mode='review', available=True,
        target='specimen.vtk', test_number=23, reference=dict(
            directory='pending-common', candidate_id='guided-varifold', target='specimen.vtk'))
    panel.render()
    buttons = panel.window.findChildren(QPushButton)
    assert [b for b in buttons if b.isVisible() and b.objectName() == 'primary'] == [
        panel.window.review_next_button]
    restore = next(b for b in buttons if b.property('acceptedFitRecovery'))
    assert restore.isVisible() and restore.isEnabled()
    restore.click()
    assert panel.invoked == [((), dict(adaptive=False, guided_action=(
        'adaptive_restore_accepted', panel.candidate.candidate_id, ref)))]
