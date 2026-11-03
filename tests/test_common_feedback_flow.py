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
    from diffeoforge.desktop import saved_fit_comparison
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    _, current, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None)
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
    monkeypatch.setattr(saved_fit_comparison, 'alternatives', lambda *args: ())
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
                wait(app, lambda: viewer.canvas.comparison_ready
                     and viewer.guided_feedback.outcomes[outcome].isEnabled())
                assert all(viewer.guided_feedback.outcomes[k].isVisible()
                           for k in ('better', 'same', 'worse'))
                viewer.guided_feedback.outcomes[outcome].click()
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
            assert prepared[4]['comparison_reconstruction_path'] == str(earlier)
            parent._candidate_prepared(key, prepared)
            wait(app, lambda: not parent._review_saving)
            wait_pilot_view(parent)
            current = study.load_reference_calibration_study(current.study_directory)
            saved = guided_feedback.presentation(current, 'guided-varifold')['feedback']
            assert saved['outcome'] == outcome
            choice = guided_strategy.state(current)['common_recovery']
            if outcome == 'better':
                assert choice['kind'] == 'iterations'
            else:
                assert choice['mode'] == 'broad_detail'
                assert '2,000 CP' in choice['label']
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


def test_first_common_review_saves_comparison_and_rejection_in_one_visit(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication

    from diffeoforge import guided_feedback, guided_strategy, pilot_form_progress
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.desktop import reference_calibration_dialog as ui
    from diffeoforge.desktop import saved_fit_comparison
    from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader

    app = QApplication.instance() or QApplication([])
    _, current, trend = rejected_capacity(tmp_path, monkeypatch, outcome=None, reviewed=False)
    trend['value'] = 'improving'
    ledger = deepcopy(pilot_form_progress.marker(current))
    folders = set(current.study_directory.parent.iterdir())
    target = guided.record(current)['target']
    original, fitted, earlier = tmp_path/target, tmp_path/'fit.vtk', tmp_path/'earlier.vtk'
    monkeypatch.setattr(ui, 'collect_calibration_qc_pairs', lambda directory, candidate: (
        ui.CalibrationQcPair(pair_id='current', label=target, original_path=original,
            reconstruction_path=fitted if directory == current.study_directory else earlier,
            required=True, original_sha256='0'*64, reconstruction_sha256='0'*64),))
    monkeypatch.setattr(ui, 'normalized_candidate_subject_fit', lambda *args: {})
    monkeypatch.setattr(saved_fit_comparison, 'alternatives', lambda *args: ())
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
            viewer._pair_loaded(0, (_model(original), _model(fitted)))
            wait(app, lambda: viewer.canvas.comparison_ready)
            assert not viewer.fail_button.isEnabled()
            viewer.guided_feedback.outcomes['same'].click()
            assert viewer.fail_button.isEnabled()
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
        assert opinion['outcome'] == 'same'
        choice = guided_strategy.state(saved)['common_recovery']
        assert choice['mode'] == 'broad_detail'
        assert '2,000 CP' in choice['label']
        assert parent.next_step_button.isEnabled()
        assert parent.next_step_button.text() == choice['label']
        assert pilot_form_progress.marker(saved) == ledger
        assert set(current.study_directory.parent.iterdir()) == folders
        assert parent._worker is None
    finally:
        parent.close()
        app.processEvents()
