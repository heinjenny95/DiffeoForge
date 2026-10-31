"""Resume cancelled post-fit checks only from a bound normally completed native run."""
import json
from pathlib import Path

from diffeoforge.mesh import sha256_file

VERSION = 'cancelled-fit-checks-v1'
FILES = ('manifest.json', 'result.json', 'output-inventory.json', 'events.jsonl')


def binding(run, config):
    """Small cancellation receipt; full read-only validation happens before reuse."""
    run, config = Path(run), Path(config)
    manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    result = json.loads((run/'result.json').read_text(encoding='utf-8'))
    digest = sha256_file(config)
    if (result.get('status') != 'completed' or result.get('return_code') != 0
            or manifest.get('run_id') != run.name or result.get('run_id') != run.name
            or manifest.get('source_config', {}).get('sha256') != digest):
        raise ValueError('Cancelled checks have no matching normally completed native fit')
    return dict(version=VERSION, config_sha256=digest,
                files={name: sha256_file(run/name) for name in FILES},
                optimizer_restart=False, anatomical_approval=False)


def pending(snapshot):
    """Metadata-only presentation; no mesh work or native execution on the UI thread."""
    from diffeoforge.reference_calibration_study import _load_events

    latest = {}
    for event in _load_events(snapshot.study_directory):
        if (snapshot.current_stage and event.get('stage_id') == snapshot.current_stage.stage_id
                and event['event'] in {'candidate_started', 'candidate_completed',
                                       'candidate_failed', 'candidate_interrupted'}):
            latest[event['candidate_id']] = event
    return {c.candidate_id: latest[c.candidate_id]['completed_native_fit']
            for c in snapshot.candidates if c.status == 'interrupted'
            and latest.get(c.candidate_id, {}).get('phase') == 'qualification'
            and latest[c.candidate_id].get('completed_native_fit', {}).get('version') == VERSION}


def verified_run(snapshot, candidate):
    expected = pending(snapshot).get(candidate.candidate_id)
    if expected is None:
        return None
    run = candidate.run_directory
    if run is None or not run.resolve().is_relative_to(snapshot.study_directory.resolve()):
        raise ValueError('Saved fit for cancelled checks is outside this pilot')
    if binding(run, candidate.config_path) != expected:
        raise ValueError('Saved fit changed after its checks were cancelled; input review required')
    from diffeoforge.result_report import collect_run_report

    report = collect_run_report(run)
    if (report.result.get('status') != 'completed' or report.result.get('return_code') != 0
            or any(c.status == 'fail' for c in report.checks)
            or (run/'output/numerical-guard/violation.json').exists()):
        raise ValueError('Saved native evidence does not permit resuming checks')
    return run
