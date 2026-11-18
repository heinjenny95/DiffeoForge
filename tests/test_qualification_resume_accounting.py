"""Checks-only recovery keeps native checkpoint ancestry without constructing a launch."""
from dataclasses import replace
from types import SimpleNamespace

from test_qualification_resume import cancelled_fixture
from test_reference_calibration_study import _metrics

from diffeoforge import reference_calibration_study as study
from diffeoforge import result_report


def test_saved_checks_keep_declared_checkpoint_effort_and_source(tmp_path, monkeypatch):
    snapshot, candidate, launches = cancelled_fixture(tmp_path, monkeypatch, fail_checks=True)
    checkpoint = dict(version='native-pilot-continuation-v1', initial_iteration=50,
                      additional_iterations=300, maximum_iterations=350,
                      source_run='verified-parent', checkpoint_sha256='a'*64)
    declaration = dict(checkpoint_continuation=checkpoint,
                       source=dict(candidate_id='previous-reviewed-candidate'))
    monkeypatch.setattr(study, '_checkpoint_continuation', lambda *_: declaration)
    monkeypatch.setattr(result_report, 'collect_run_report', lambda _run: SimpleNamespace(
        result=dict(status='completed', return_code=0), checks=[SimpleNamespace(status='pass')]))
    monkeypatch.setattr(study, 'collect_reference_calibration_run_metrics',
        lambda run: replace(_metrics(run/'atlas.vtk'), final_iteration=350,
                            maximum_iterations=350))

    def forbidden(*_args, **_kwargs):
        raise AssertionError('A check-only recovery must not construct a native launch')

    monkeypatch.setattr(study, '_launch_request', forbidden)
    runner = study.ReferenceCalibrationStudyRunner(snapshot.study_directory,
                                                  controller_factory=forbidden)
    after = runner.run_current_stage(candidate_ids={candidate.candidate_id})
    done = next(c for c in after.candidates if c.candidate_id == candidate.candidate_id)
    assert done.status == 'completed' and len(launches) == 1
    assert done.metrics['pilot_continuation'] == dict(
        checkpoint, source_candidate_id='previous-reviewed-candidate')
    assert done.metrics['final_iteration'] == 350
    started = next(e for e in reversed(study._load_events(after.study_directory))
                   if e['event'] == 'candidate_started')
    assert started['qualification_only'] and started['iteration_offset'] == 0
    assert not after.visual_reviews
