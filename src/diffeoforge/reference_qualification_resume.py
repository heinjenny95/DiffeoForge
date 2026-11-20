"""Resume post-fit checks from sealed, normally completed native evidence only."""

import hashlib
import json
from pathlib import Path

LEGACY_VERSION = 'cancelled-fit-checks-v1'
VERSION = 'completed-fit-checks-v2'
LEGACY_FILES = ('manifest.json', 'result.json', 'output-inventory.json', 'events.jsonl')
FILES = (*LEGACY_FILES, 'manifest.sha256', 'logs/backend-control.json',
         'logs/backend-control-token')
# Presentation reads metadata only; never open inventoried scientific geometry.
_METADATA_LIMIT = 32 * 1024 * 1024
_SMALL_LIMIT = 2 * 1024 * 1024


def _bytes(path, limit=_METADATA_LIMIT):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Saved native metadata is missing, symbolic or exceeds its read limit')
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Saved native metadata exceeds its read limit')
    return value


def _object(raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Saved native metadata is not an object')
    return value


def binding(run, config):
    """Bind bounded metadata proving a completed native fit; never read geometry."""
    run, config = Path(run), Path(config)
    if any(not (run / name).resolve().is_relative_to(run.resolve()) for name in FILES):
        raise ValueError('Saved native metadata escapes its run directory')
    raw = {name: _bytes(run / name, _SMALL_LIMIT if name != 'output-inventory.json'
                        else _METADATA_LIMIT) for name in FILES}
    manifest, result = (_object(raw[name]) for name in ('manifest.json', 'result.json'))
    inventory = _object(raw['output-inventory.json'])
    control = _object(raw['logs/backend-control.json'])
    events = [_object(line) for line in raw['events.jsonl'].splitlines() if line.strip()]
    digest = hashlib.sha256(_bytes(config, _SMALL_LIMIT)).hexdigest()
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    checksum = raw['manifest.sha256'].decode('ascii').split()
    outputs = result.get('outputs', {})
    identity = control.get('identity', {})
    source_config = manifest.get('source_config', {})
    if (not checksum or checksum[0] != hashes['manifest.json']
            or result.get('status') != 'completed'
            or type(result.get('return_code')) is not int or result['return_code'] != 0
            or result.get('execution_error') is not None
            or manifest.get('run_id') != run.name or result.get('run_id') != run.name
            or not isinstance(source_config, dict) or source_config.get('sha256') != digest
            or not isinstance(outputs, dict)
            or outputs.get('inventory_path', 'output-inventory.json') != 'output-inventory.json'
            or outputs.get('inventory_sha256') != hashes['output-inventory.json']
            or not isinstance(inventory.get('files'), list)
            or not events or events[0].get('event') != 'prepared'
            or events[0].get('run_id') != run.name
            or events[-1].get('event') != 'completed'
            or type(events[-1].get('return_code')) is not int
            or events[-1]['return_code'] != 0
            or control.get('state') != 'completed' or control.get('session_empty') is not True
            or type(control.get('backend_return_code')) is not int
            or control['backend_return_code'] != 0
            or not isinstance(control.get('boot_id'), str) or not control['boot_id']
            or not isinstance(identity, dict)
            or type(identity.get('start_ticks')) is not int or identity['start_ticks'] <= 0
            or not raw['logs/backend-control-token']
            or control.get('token_sha256') != hashes['logs/backend-control-token']):
        raise ValueError('Saved checks have no matching normally completed native fit')
    if ((run / 'output/numerical-guard/violation.json').exists()
            or any(isinstance(row, dict) and str(row.get('path', '')).replace('\\', '/')
                   == 'numerical-guard/violation.json' for row in inventory['files'])):
        raise ValueError('Saved native evidence records a numerical guard violation')
    return dict(version=VERSION, config_sha256=digest, files=hashes,
                optimizer_restart=False, anatomical_approval=False)


def _latest(snapshot):
    from diffeoforge.reference_calibration_study import _load_events

    # Bound the journal before its normal hash-chain verification.
    _bytes(snapshot.study_directory / 'events.jsonl')
    latest = {}
    for event in _load_events(snapshot.study_directory):
        if (snapshot.current_stage and event.get('stage_id') == snapshot.current_stage.stage_id
                and event['event'] in {'candidate_started', 'candidate_completed',
                                       'candidate_failed', 'candidate_interrupted'}):
            latest[event['candidate_id']] = event
    return latest


def _run(snapshot, candidate, event):
    run = candidate.run_directory
    if (run is None or not run.resolve().is_relative_to(snapshot.study_directory.resolve())
            or not event.get('run_directory')
            or run.resolve() != (snapshot.study_directory / event['run_directory']).resolve()):
        raise ValueError('Saved fit for incomplete checks is outside this pilot or changed')
    return run


def _matches(run, config, expected):
    current = binding(run, config)
    if expected.get('version') == LEGACY_VERSION:
        legacy = dict(version=LEGACY_VERSION, config_sha256=current['config_sha256'],
                      files={name: current['files'][name] for name in LEGACY_FILES},
                      optimizer_restart=False, anatomical_approval=False)
        return legacy == expected, current
    return current == expected, current


def pending(snapshot):
    """Metadata-only eligibility, including historical post-fit qualification failures."""
    latest, result = _latest(snapshot), {}
    for candidate in snapshot.candidates:
        event = latest.get(candidate.candidate_id, {})
        if candidate.status not in {'interrupted', 'failed'}:
            continue
        expected = event.get('completed_native_fit')
        declared = event.get('phase') == 'qualification' and isinstance(expected, dict)
        historical = candidate.status == 'failed' and event.get('event') == 'candidate_failed'
        if not declared and not historical:
            continue
        try:
            run = _run(snapshot, candidate, event)
            if declared:
                matches, current = _matches(run, candidate.config_path, expected)
                if not matches:
                    continue
                # Preserve legacy seals; dispatch also proves current shutdown evidence.
                result[candidate.candidate_id] = expected
            else:
                result[candidate.candidate_id] = binding(run, candidate.config_path)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return result


def _completed_hint(run):
    """Distinguish a completed fit from a known unfinished/failed native lifecycle.

    Missing or unreadable evidence is not evidence of a failed backend. In
    particular, deleting both terminal files must not turn completed work into
    an implicit request to fit again.
    """
    try:
        result_path = run / 'result.json'
        result = (_object(_bytes(result_path, _SMALL_LIMIT))
                  if result_path.is_file() else None)
        events = [_object(line) for line in _bytes(run / 'events.jsonl').splitlines()
                  if line.strip()]
        if not events:
            raise ValueError('Empty native lifecycle')
        status = events[-1].get('event')
        if status == 'completed' or (result and result.get('status') == 'completed'):
            return True
        if result is None and status in {'prepared', 'started', 'failed', 'interrupted'}:
            return False
        if (result and status in {'failed', 'interrupted'}
                and result.get('status') == status
                and type(result.get('return_code')) is int
                and result['return_code'] == events[-1].get('return_code')):
            return False
        raise ValueError('Inconsistent native terminal lifecycle')
    except (OSError, ValueError, TypeError) as error:
        raise ValueError('Saved native lifecycle changed or is missing; '
                         'input review required before another fit') from error


def verified_run(snapshot, candidate):
    """Freshly verify a check-only dispatch; never construct a native controller."""
    if candidate.status not in {'interrupted', 'failed'}:
        return None
    event = _latest(snapshot).get(candidate.candidate_id, {})
    expected = event.get('completed_native_fit')
    declared = event.get('phase') == 'qualification'
    historical = candidate.status == 'failed' and event.get('event') == 'candidate_failed'
    if not declared and not historical:
        return None
    if (not declared and candidate.run_directory is None
            and event.get('run_directory') is None):
        return None  # Preparation failed before any native run was recorded.
    run = _run(snapshot, candidate, event)
    if not declared and not _completed_hint(run):
        return None  # A genuinely failed native backend is not reused by this route.
    try:
        if isinstance(expected, dict):
            matches, current = _matches(run, candidate.config_path, expected)
            if not matches:
                raise ValueError('Saved fit changed after its checks stopped')
        else:
            current = binding(run, candidate.config_path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError('Saved fit changed or does not permit resuming checks; '
                         'input review required') from error
    from diffeoforge import runs
    from diffeoforge.result_report import collect_run_report

    manifest = _object(_bytes(run / 'manifest.json', _SMALL_LIMIT))
    runs._verify_protected_artifacts(run, manifest)
    report = collect_run_report(run)
    if (report.result.get('status') != 'completed' or report.result.get('return_code') != 0
            or any(c.status == 'fail' for c in report.checks)
            or binding(run, candidate.config_path) != current):
        raise ValueError('Saved native evidence does not permit resuming checks')
    return run
