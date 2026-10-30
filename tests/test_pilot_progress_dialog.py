"""Review and continuation stay outside the long scrolling history."""


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
    assert button.text() == 'Review finished fit'
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
