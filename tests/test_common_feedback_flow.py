"""The common-view entry point must carry and persist actual relative feedback."""
from copy import deepcopy

from test_fit_preference_dialog import wait
from test_pilot_common_candidate import rejected_capacity
from test_reference_calibration_dialog import _model


def test_common_viewer_feedback_roundtrip_and_fixed_next_action(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    from diffeoforge import guided_feedback, guided_strategy, pilot_form_progress
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop import reference_calibration_dialog as ui
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    _, current, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None)
    from test_pilot_multiscale_journey import synthetic_inputs

    synthetic_inputs(monkeypatch)
    trend['value'] = 'improving'
    original_reviews = deepcopy(current.visual_reviews)
    original_ledger = deepcopy(pilot_form_progress.marker(current))
    original_folders = set(current.study_directory.parent.iterdir())
    target = guided.record(current)['target']
    original = tmp_path/target
    fitted = tmp_path/'current.vtk'
    earlier = tmp_path/'starting.vtk'

    def pairs(directory, candidate):
        return (ui.CalibrationQcPair(pair_id='current', label=target, original_path=original,
            reconstruction_path=fitted if directory == current.study_directory else earlier,
            required=True, original_sha256='0'*64, reconstruction_sha256='0'*64),)

    monkeypatch.setattr(ui, 'collect_calibration_qc_pairs', pairs)
    monkeypatch.setattr(ui, 'normalized_candidate_subject_fit', lambda *args: {})
    monkeypatch.setattr(PreviewMeshLoader, 'request_paths', lambda *args, **kwargs: None)
    parent = ui.ReferenceCalibrationDialog(current.study_directory)
    parent.show()
    queue = []
    parent._viewer_preparation.request_operation = lambda key, fn: queue.append((key, fn))
    reports = []
    try:
        wait_pilot_view(parent)
        assert parent._guided_review_target['pending']
        assert 'feedback' in parent._guided_review_target['label']
        for outcome in ('better', 'same', 'worse'):
            def inspect(viewer, outcome=outcome):
                viewer.show()
                assert viewer.guided_feedback is not None
                assert set(viewer.guided_feedback.outcomes) >= {'better', 'same', 'worse'}
                assert not viewer.guided_feedback.outcomes[outcome].isEnabled()
                viewer._pair_loaded(0, (_model(original), _model(fitted)))
                comparison = viewer.saved_comparison
                assert comparison.toggle.isChecked()
                seed = viewer._common_review["numerical_seed"]
                pair = comparison.choice.currentData()
                assert pair.rating_reference == seed
                comparison._loaded(pair.pair_id, (_model(original), _model(earlier)))
                wait(app, lambda: viewer.canvas.comparison_ready
                     and viewer.guided_feedback.outcomes[outcome].isEnabled())
                assert all(viewer.guided_feedback.outcomes[k].isVisible()
                           for k in ('better', 'same', 'worse'))
                viewer.guided_feedback.outcomes[outcome].click()
                assert comparison.choice.currentData().rating_reference == (
                    viewer._common_review["approved_individual"])
                wait(app, lambda: viewer.canvas.comparison_ready)
                viewer.guided_feedback.save.click()
                assert viewer._guided_feedback_only and not viewer.review_recorded
                reports.append(viewer.guided_feedback_decision)
                return 1

            monkeypatch.setattr(ui.CalibrationCandidateViewerDialog, 'exec', inspect)
            ref = guided_feedback.reference(current, 'guided-varifold')
            parent._open_common_saved_fit(ref)
            key, prepare = queue.pop()
            prepared = prepare()
            assert len(prepared) == 5 and prepared[4]['comparison']
            assert prepared[4]['common_review']['numerical_seed']
            parent._candidate_prepared(key, prepared)
            wait(app, lambda: not parent._review_saving)
            wait_pilot_view(parent)
            current = study.load_reference_calibration_study(current.study_directory)
            saved = guided_feedback.presentation(current, 'guided-varifold')['feedback']
            assert saved['outcome'] == outcome
            assert saved['comparison'] == saved['common_review']['numerical_seed']
            assert saved['comparison_displayed']
            choice = guided_strategy.state(current)['common_recovery']
            if outcome == 'better':
                assert choice['kind'] == 'iterations'
            else:
                assert (choice['mode'], choice['kind']) == ('candidate_refine', 'detail')
                assert choice['reference'] == ref
                assert choice['additional_iterations'] == 120
            assert parent.next_step_button.isVisible() and parent.next_step_button.isEnabled()
            assert parent.next_step_button.text() == choice['label']
            assert parent._guided_footer_action == (
                current.study_directory, 'adaptive_common_continue', 'guided-varifold')
            assert current.visual_reviews == original_reviews
            assert pilot_form_progress.marker(current) == original_ledger
            assert set(current.study_directory.parent.iterdir()) == original_folders
            assert parent._worker is None
        assert [r['outcome'] for r in reports] == ['better', 'same', 'worse']
    finally:
        parent.close()
        app.processEvents()


def test_first_common_review_saves_starting_progress_and_still_needs_work(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    from diffeoforge import guided_feedback, guided_strategy, pilot_form_progress
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop import reference_calibration_dialog as ui
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    _, current, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None, reviewed=False)
    from test_pilot_multiscale_journey import synthetic_inputs

    synthetic_inputs(monkeypatch)
    trend['value'] = 'improving'
    ledger = deepcopy(pilot_form_progress.marker(current))
    folders = set(current.study_directory.parent.iterdir())
    target = guided.record(current)['target']
    from test_pilot_region_feedback import patch

    from diffeoforge import guided_working_fit, regional_search

    # The public controller fixture has no individual-fit mesh output. The
    # common-model measurements for this continuation come from rejected_capacity.
    monkeypatch.setattr(regional_search, "capture", lambda *_a, **_k: None)
    marks = {target: [patch(current.plan.selected_pilot_subjects[0].sha256)]}
    current = guided_working_fit.save(current.study_directory, 'guided-varifold', dict(
        reference=current.attachment_comparison["refinement"]["reference"],
        inspected_subjects=[target], display_scopes={target: 'original_proxy'},
        problem_regions=marks))
    original, fitted, earlier = tmp_path/target, tmp_path/'fit.vtk', tmp_path/'earlier.vtk'
    monkeypatch.setattr(ui, 'collect_calibration_qc_pairs', lambda directory, candidate: (
        ui.CalibrationQcPair(pair_id='current', label=target, original_path=original,
            reconstruction_path=fitted if directory == current.study_directory else earlier,
            required=True, original_sha256='0'*64, reconstruction_sha256='0'*64),))
    monkeypatch.setattr(ui, 'normalized_candidate_subject_fit', lambda *args: {})
    monkeypatch.setattr(PreviewMeshLoader, 'request_paths', lambda *args, **kwargs: None)
    parent = ui.ReferenceCalibrationDialog(current.study_directory)
    parent.show()
    queue = []
    parent._viewer_preparation.request_operation = lambda key, fn: queue.append((key, fn))
    try:
        wait_pilot_view(parent)

        def inspect(viewer):
            viewer.show()
            assert viewer.guided_feedback.data['require_fit_decision']
            assert viewer.guided_feedback.save.isHidden()
            assert viewer.problem_regions == marks
            viewer._pair_loaded(0, (_model(original), _model(fitted)))
            wait(app, lambda: viewer.canvas.comparison_ready)
            assert not viewer.fail_button.isEnabled()
            saved_pane = viewer.saved_comparison
            seed = saved_pane.choice.currentData()
            assert seed.rating_reference == viewer._common_review["numerical_seed"]
            assert viewer._common_review["current_label"] in saved_pane.current_label.text()
            saved_pane._loaded(seed.pair_id, (_model(original), _model(earlier)))
            wait(app, lambda: viewer.guided_feedback.outcomes["better"].isEnabled())
            assert saved_pane.choice.currentText() in viewer.guided_feedback.title.text()
            viewer.guided_feedback.outcomes['better'].click()
            approved = saved_pane.choice.currentData()
            assert approved.rating_reference == viewer._common_review["approved_individual"]
            assert approved.rating_reference != seed.rating_reference
            assert not viewer.fail_button.isEnabled()
            saved_pane._loaded(approved.pair_id, (_model(original), _model(earlier)))
            wait(app, lambda: viewer.fail_button.isEnabled())
            assert viewer.fail_button.text() == "Still needs work → next step"
            viewer.fail_button.click()
            assert viewer.review_recorded and not viewer.review_passed
            assert not viewer._guided_feedback_only
            return 0

        monkeypatch.setattr(ui.CalibrationCandidateViewerDialog, 'exec', inspect)
        parent._open_common_saved_fit(guided_feedback.reference(current, 'guided-varifold'))
        key, prepare = queue.pop()
        prepared = prepare()
        assert prepared[4]['require_fit_decision']
        parent._candidate_prepared(key, prepared)
        wait(app, lambda: not parent._review_saving)
        wait_pilot_view(parent)
        saved = study.load_reference_calibration_study(current.study_directory)
        assert saved.visual_reviews['guided-varifold'] is False
        opinion = guided_feedback.presentation(saved, 'guided-varifold')['feedback']
        assert opinion['outcome'] == 'better'
        assert opinion['comparison'] == opinion['common_review']['numerical_seed']
        assert opinion['comparison_displayed']
        assert opinion['problem_regions'] == saved.problem_regions['guided-varifold'] == marks
        choice = guided_strategy.state(saved)['common_recovery']
        assert choice['kind'] == 'iterations'
        assert choice['reference'] == opinion['current'] and choice['additional_iterations'] == 120
        assert parent.next_step_button.isEnabled()
        assert parent.next_step_button.text() == choice['label']
        assert pilot_form_progress.marker(saved) == ledger
        assert set(current.study_directory.parent.iterdir()) == folders
        assert parent._worker is None
    finally:
        parent.close()
        app.processEvents()
