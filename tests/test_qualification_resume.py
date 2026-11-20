"""Incomplete checks must never refit or approve a normally completed native result."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from test_reference_calibration_study import _afk_runner, _metrics

from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_qualification_resume import (
    FILES,
    LEGACY_FILES,
    LEGACY_VERSION,
    VERSION,
    binding,
    pending,
    verified_run,
)


def cancelled_fixture(tmp_path, monkeypatch, *, fail_checks=False, historical=False):
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
            (request.destination/'logs').mkdir()
            (request.destination/'output').mkdir()
            inventory = json.dumps(dict(files=[]))
            rows = {'manifest.json': dict(run_id=request.run_id, protected_artifacts=[],
                    source_config=dict(sha256=sha256_file(request.config_path))),
                    'result.json': dict(run_id=request.run_id, status='completed', return_code=0,
                        execution_error=None, outputs=dict(inventory_path='output-inventory.json',
                            inventory_sha256=hashlib.sha256(inventory.encode()).hexdigest())),
                    'output-inventory.json': dict(files=[])}
            for name, row in rows.items():
                (request.destination/name).write_text(json.dumps(row))
            (request.destination/'manifest.sha256').write_text(
                sha256_file(request.destination/'manifest.json'))
            (request.destination/'events.jsonl').write_text('\n'.join(json.dumps(row) for row in (
                dict(event='prepared', run_id=request.run_id),
                dict(event='started'), dict(event='completed', return_code=0))))
            token = 'synthetic-control-token'
            (request.destination/'logs/backend-control-token').write_text(token)
            (request.destination/'logs/backend-control.json').write_text(json.dumps(dict(
                state='completed', backend_return_code=0, session_empty=True,
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                boot_id='synthetic-boot', identity=dict(start_ticks=1))))
            return SimpleNamespace(completed=True)

    runner = _afk_runner(tmp_path, monkeypatch, controller=Completed)
    snapshot = study.load_reference_calibration_study(runner.study_directory)
    identifier = snapshot.candidates[0].candidate_id

    def collect(run):
        atlas = run/'atlas.vtk'
        atlas.write_text('synthetic atlas')
        if fail_checks:
            raise ValueError('Synthetic post-fit geometry verification failed')
        runner.request_cancel()
        return _metrics(atlas)

    monkeypatch.setattr(study, 'collect_reference_calibration_run_metrics', collect)
    snapshot = runner.run_current_stage(candidate_ids={identifier})
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    assert candidate.status == ('failed' if fail_checks else 'interrupted')
    if historical:
        study._append_event(snapshot.study_directory, 'candidate_failed', dict(
            stage_id=snapshot.current_stage.stage_id, candidate_id=identifier,
            attempt=candidate.attempts, run_directory=candidate.run_directory.relative_to(
                snapshot.study_directory).as_posix(), error='Historical post-fit check failed'))
        snapshot = study.load_reference_calibration_study(snapshot.study_directory)
        candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    assert identifier in pending(snapshot)
    assert candidate.metrics is None and not snapshot.visual_reviews
    return snapshot, candidate, launches


@pytest.mark.parametrize('failure_kind', ['cancelled', 'failed', 'historical'])
def test_resume_finishes_checks_without_constructing_a_native_controller(
        tmp_path, monkeypatch, failure_kind):
    snapshot, candidate, launches = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=failure_kind != 'cancelled',
        historical=failure_kind == 'historical')
    original = {name: sha256_file(candidate.run_directory/name) for name in FILES}
    journal = (snapshot.study_directory/'events.jsonl').read_bytes()
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
    assert {name: sha256_file(done.run_directory/name) for name in FILES} == original
    assert (snapshot.study_directory/'events.jsonl').read_bytes().startswith(journal)
    assert not after.visual_reviews


@pytest.mark.parametrize('changed', FILES)
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


def test_historical_failed_checks_are_bound_from_current_completed_native_evidence(
        tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=True, historical=True)
    latest = study._load_events(snapshot.study_directory)[-1]
    assert latest['event'] == 'candidate_failed' and 'completed_native_fit' not in latest
    receipt = pending(snapshot)[candidate.candidate_id]
    assert receipt == binding(candidate.run_directory, candidate.config_path)
    assert receipt['version'] == VERSION
    assert not receipt['optimizer_restart'] and not receipt['anatomical_approval']


@pytest.mark.parametrize('change', ['result', 'control_rc', 'session', 'token',
                                   'inventory', 'guard', 'config'])
def test_invalid_historical_native_proof_never_dispatches_a_controller(
        tmp_path, monkeypatch, change):
    snapshot, candidate, launches = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=True, historical=True)
    run = candidate.run_directory
    if change == 'config':
        candidate.config_path.write_bytes(candidate.config_path.read_bytes()+b'\n')
    elif change == 'inventory':
        (run/'output-inventory.json').write_text('{"files": []}\n')
    elif change == 'guard':
        (run/'output/numerical-guard').mkdir()
        (run/'output/numerical-guard/violation.json').write_text('{}')
    else:
        path = run/('result.json' if change == 'result' else 'logs/backend-control.json')
        value = json.loads(path.read_text())
        if change == 'result':
            value['return_code'] = 1
        elif change == 'control_rc':
            value['backend_return_code'] = 1
        elif change == 'session':
            value['session_empty'] = False
        elif change == 'token':
            value['token_sha256'] = '0'*64
        path.write_text(json.dumps(value))
    assert not pending(snapshot)

    def forbidden(*args):
        raise AssertionError('Invalid saved fit may not trigger an accidental refit')

    runner = study.ReferenceCalibrationStudyRunner(snapshot.study_directory,
                                                   controller_factory=forbidden)
    with pytest.raises(ValueError, match='changed|does not permit'):
        runner.run_current_stage(candidate_ids={candidate.candidate_id})
    assert len(launches) == 1


def test_actual_failed_native_backend_is_not_a_qualification_resume(tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=True, historical=True)
    run = candidate.run_directory
    path = run/'result.json'
    result = json.loads(path.read_text())
    result.update(status='failed', return_code=9)
    path.write_text(json.dumps(result))
    (run/'events.jsonl').write_text('\n'.join(json.dumps(row) for row in (
        dict(event='prepared', run_id=run.name), dict(event='failed', return_code=9))))
    assert not pending(snapshot)
    assert verified_run(snapshot, candidate) is None
    with pytest.raises(ValueError, match='normally completed'):
        binding(run, candidate.config_path)


def test_legacy_cancelled_check_seal_requires_current_completed_shutdown_proof(
        tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(tmp_path, monkeypatch)
    current = binding(candidate.run_directory, candidate.config_path)
    legacy = dict(version=LEGACY_VERSION, config_sha256=current['config_sha256'],
                  files={name: current['files'][name] for name in LEGACY_FILES},
                  optimizer_restart=False, anatomical_approval=False)
    study._append_event(snapshot.study_directory, 'candidate_interrupted', dict(
        stage_id=snapshot.current_stage.stage_id, candidate_id=candidate.candidate_id,
        attempt=candidate.attempts, run_directory=candidate.run_directory.relative_to(
            snapshot.study_directory).as_posix(), phase='qualification',
        completed_native_fit=legacy, error='Historical cancelled checks'))
    snapshot = study.load_reference_calibration_study(snapshot.study_directory)
    assert pending(snapshot)[candidate.candidate_id] == legacy
    from diffeoforge import result_report
    monkeypatch.setattr(result_report, 'collect_run_report', lambda run: SimpleNamespace(
        result=dict(status='completed', return_code=0), checks=[]))
    assert verified_run(snapshot, snapshot.candidates[0]) == candidate.run_directory
    (candidate.run_directory/'logs/backend-control-token').write_text('wrong-token')
    with pytest.raises(ValueError, match='changed|does not permit'):
        verified_run(snapshot, snapshot.candidates[0])


def test_pending_reads_only_bounded_metadata_and_no_scientific_geometry(tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=True, historical=True)
    from diffeoforge import reference_qualification_resume as resume
    from diffeoforge import result_report, runs
    original = resume._bytes
    read = []

    def metadata(path, limit=resume._METADATA_LIMIT):
        assert 'output' not in path.parts
        assert path.suffix != '.vtk'
        read.append(path)
        return original(path, limit)

    def forbidden(*args):
        raise AssertionError('Presentation may not run a full artifact audit')

    monkeypatch.setattr(resume, '_bytes', metadata)
    monkeypatch.setattr(result_report, 'collect_run_report', forbidden)
    monkeypatch.setattr(runs, '_verify_protected_artifacts', forbidden)
    assert candidate.candidate_id in pending(snapshot) and read


def test_binding_rejects_oversized_metadata_before_reading_it(tmp_path, monkeypatch):
    snapshot, candidate, _ = cancelled_fixture(tmp_path, monkeypatch)
    from diffeoforge import reference_qualification_resume as resume
    monkeypatch.setattr(resume, '_SMALL_LIMIT', 8)
    with pytest.raises(ValueError, match='read limit'):
        binding(candidate.run_directory, candidate.config_path)


@pytest.mark.parametrize('declared', [False, True])
def test_missing_run_before_preparation_keeps_normal_failure_route_but_not_declared_checks(
        tmp_path, monkeypatch, declared):
    from diffeoforge import reference_qualification_resume as resume
    candidate = SimpleNamespace(candidate_id='candidate', status='failed', run_directory=None)
    snapshot = SimpleNamespace(study_directory=tmp_path)
    event = dict(event='candidate_failed', run_directory=None)
    if declared:
        event['phase'] = 'qualification'
    monkeypatch.setattr(resume, '_latest', lambda snapshot: {'candidate': event})
    if declared:
        with pytest.raises(ValueError, match='outside this pilot|changed'):
            verified_run(snapshot, candidate)
    else:
        assert verified_run(snapshot, candidate) is None


@pytest.mark.parametrize('missing', [('result.json', 'events.jsonl'), ('events.jsonl',)])
def test_deleted_historical_native_lifecycle_blocks_instead_of_refitting(
        tmp_path, monkeypatch, missing):
    snapshot, candidate, launches = cancelled_fixture(
        tmp_path, monkeypatch, fail_checks=True, historical=True)
    for name in missing:
        (candidate.run_directory/name).unlink()

    def forbidden(*args):
        raise AssertionError('Lost completed evidence may not dispatch another native fit')

    runner = study.ReferenceCalibrationStudyRunner(snapshot.study_directory,
                                                   controller_factory=forbidden)
    with pytest.raises(ValueError, match='lifecycle changed|missing'):
        runner.run_current_stage(candidate_ids={candidate.candidate_id})
    assert len(launches) == 1
