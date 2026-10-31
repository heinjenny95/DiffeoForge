"""Cancellation of checks must never refit or approve the retained native result."""
import json
from types import SimpleNamespace

import pytest
from test_reference_calibration_study import _afk_runner, _metrics

from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_qualification_resume import pending, verified_run


def cancelled_fixture(tmp_path, monkeypatch):
    launches = []

    class Completed:
        def __init__(self, request):
            self.request = request

        def request_cancel(self):
            return True

        def run(self, **kwargs):
            request = self.request
            launches.append(request.destination)
            request.destination.mkdir(parents=True)
            rows = {'manifest.json': dict(run_id=request.run_id,
                    source_config=dict(sha256=sha256_file(request.config_path))),
                    'result.json': dict(run_id=request.run_id, status='completed', return_code=0),
                    'output-inventory.json': dict(files=[])}
            for name, row in rows.items():
                (request.destination/name).write_text(json.dumps(row))
            (request.destination/'events.jsonl').write_text('synthetic completed native lifecycle')
            return SimpleNamespace(completed=True)

    runner = _afk_runner(tmp_path, monkeypatch, controller=Completed)
    snapshot = study.load_reference_calibration_study(runner.study_directory)
    identifier = snapshot.candidates[0].candidate_id

    def collect(run):
        atlas = run/'atlas.vtk'
        atlas.write_text('synthetic atlas')
        runner.request_cancel()
        return _metrics(atlas)

    monkeypatch.setattr(study, 'collect_reference_calibration_run_metrics', collect)
    snapshot = runner.run_current_stage(candidate_ids={identifier})
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    assert candidate.status == 'interrupted' and identifier in pending(snapshot)
    assert candidate.metrics is None and not snapshot.visual_reviews
    return snapshot, candidate, launches


def test_resume_finishes_checks_without_constructing_a_native_controller(tmp_path, monkeypatch):
    snapshot, candidate, launches = cancelled_fixture(tmp_path, monkeypatch)
    original = {p.name: sha256_file(p) for p in candidate.run_directory.glob('*.json*')}
    from diffeoforge import result_report

    monkeypatch.setattr(result_report, 'collect_run_report', lambda run: SimpleNamespace(
        result=dict(status='completed', return_code=0), checks=[SimpleNamespace(status='pass')]))
    monkeypatch.setattr(study, 'collect_reference_calibration_run_metrics',
                        lambda run: _metrics(run/'atlas.vtk'))

    def forbidden(*args):
        raise AssertionError('A completed native fit must not run again')

    fresh = study.ReferenceCalibrationStudyRunner(snapshot.study_directory,
                                                 controller_factory=forbidden)
    after = fresh.run_current_stage(candidate_ids={candidate.candidate_id})
    done = next(c for c in after.candidates if c.candidate_id == candidate.candidate_id)
    assert done.status == 'completed' and done.run_directory == candidate.run_directory
    assert done.metrics['qualification_resumed_without_fitting'] and len(launches) == 1
    assert done.metrics['qualification_resume_wall_seconds'] >= 0
    assert 'pipeline_wall_seconds' not in done.metrics
    assert {p.name: sha256_file(p) for p in done.run_directory.glob('*.json*')} == original
    assert not after.visual_reviews


@pytest.mark.parametrize('changed', ['result.json', 'manifest.json', 'events.jsonl',
                                    'output-inventory.json'])
def test_changed_native_evidence_is_blocked_before_any_execution(tmp_path, monkeypatch, changed):
    snapshot, candidate, launches = cancelled_fixture(tmp_path, monkeypatch)
    path = candidate.run_directory/changed
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='changed'):
        verified_run(snapshot, candidate)
    assert len(launches) == 1 and candidate.metrics is None


def test_failed_artifact_check_cannot_resume_or_approve(tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(tmp_path, monkeypatch)
    from diffeoforge import result_report

    monkeypatch.setattr(result_report, 'collect_run_report', lambda run: SimpleNamespace(
        result=dict(status='completed', return_code=0), checks=[SimpleNamespace(status='fail')]))
    with pytest.raises(ValueError, match='does not permit'):
        verified_run(snapshot, candidate)
