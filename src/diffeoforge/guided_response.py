"""Verified response of saved fits to the SAME original patches; no optimizer calls.

All geometry work runs in pilot preparation workers. The small in-memory cache
stores measurements, never approval or permission to skip fresh input checks.
"""
from collections import OrderedDict
from threading import RLock

from diffeoforge.reference_calibration import _canonical_hash

_CACHE = OrderedDict()
_LOCK = RLock()


def measured(reference, regions):
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.pilot_recovery import capture

    parent = verify_reference(reference)  # Validate current bytes even on cache hits.
    key = _canonical_hash(dict(version=2, reference=reference, regions=regions))
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    candidate = next(c for c in parent.candidates if c.candidate_id == reference['candidate_id'])
    subject = (candidate.metrics or {}).get('attachment_comparison', {}).get('subjects', {}).get(
        reference['target'], {})
    saved = subject.get('marked_regions', {}).get('measurements', [])
    if ([r['region'] for r in saved] == regions and all(
            'original_to_fit_mean' in repeat for r in saved for repeat in r['repeats'])):
        result = dict(baseline=saved, global_baseline=subject)
    else:
        result = capture(parent, reference["candidate_id"], reference["target"], regions=regions)
    with _LOCK:
        _CACHE[key] = result
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return result


def compare(before, after):
    """Treat mixed changes as trade-offs, not successes. Sampling uncertainty matters."""
    if [r['region'] for r in before['baseline']] != [r['region'] for r in after['baseline']]:
        raise ValueError("Compare saved fits on identical source-bound marked areas")
    better = worse = False
    gain = 0.
    for first, second in zip(before['baseline'], after['baseline'], strict=True):
        floor = first['diagonal'] * 1e-6
        for key in ('original_to_fit_mean', 'original_to_fit_p95', 'original_to_fit_p99',
                    'fit_to_original_p95'):
            x = [r[key] for r in first['repeats'] if r.get(key) is not None]
            y = [r[key] for r in second['repeats'] if r.get(key) is not None]
            if len(x) != 2 or len(y) != 2:
                continue
            if key != 'fit_to_original_p95':
                better |= max(y) + floor < min(x) * .95
                gain = max(gain, 1. - max(y) / max(min(x), floor))
            worse |= min(y) > max(x) * 1.05 + floor
    x, y = before['global_baseline'], after['global_baseline']
    global_worse = bool(y.get('warnings')) or any(
        min(r[k] for r in y['repeats']) > max(r[k] for r in x['repeats']) * 1.15
        + before['baseline'][0]['diagonal'] * 1e-4 for k in ('mean', 'p95', 'p99'))
    status = ('tradeoff' if better and worse else 'worse' if worse else
              'improved' if better else 'unchanged')
    return dict(status=status, global_worse=global_worse, gain=gain,
                # Raw intervals retained for explanation; never anatomical acceptance.
                before=[r['repeats'] for r in before['baseline']],
                after=[r['repeats'] for r in after['baseline']])


def history(cases, reference, regions):
    """Measure existing results only; no files are changed or scientific jobs launched."""
    if not regions or not reference:
        return cases, []
    baseline = measured(reference, regions)
    # New marks must not trigger a full historical geometry replay on every
    # selector refresh. Keep all decisions, but remeasure recent relevant
    # contrasts only; older fits remain available for explicit inspection.
    selected, counts = set(), {}
    for index in reversed(range(len(cases))):
        row = cases[index]
        family = row.get('family', row.get('goal'))
        if (row.get('fit') and row['target'] == reference['target']
                and row['method'] == reference['method'] and counts.get(family, 0) < 2):
            selected.add(index)
            counts[family] = counts.get(family, 0) + 1
            if len(selected) == 8:
                break
    result, evidence = [], []
    for index, case in enumerate(cases):
        row = dict(case)
        fit = case.get('fit')
        if (index in selected and fit and case['target'] == reference['target']
                and case['method'] == reference['method']
                and fit != reference):
            response = compare(baseline, measured(fit, regions))
            row['response'] = response
            evidence.append(dict(fit=fit, family=case.get('family', case.get('goal')),
                                 outcome=case.get('outcome'), **response))
        result.append(row)
    return result, evidence


def choose(cases, fallback):
    """Use measured response to choose a different explanation or a justified contrast.

    A user's Worse veto always wins. Untried directions outrank repeated measured
    failures. Explicit alternatives remain available at distinct settings.
    """
    families = (('smooth', 'motion', 'local_motion') if fallback == 'smooth' else
                ('motion', 'local_motion', 'density', 'weight') if fallback == 'motion' else
                ('detail', 'weight', 'local_motion', 'density'))
    rows = [r for r in cases if r.get('response') and r.get('family', r.get('goal')) in families]
    if not rows:
        return None
    def rank(family):
        tested = [r for r in rows if r.get('family', r.get('goal')) == family]
        if not tested:
            return (1, 0, 0 if family == fallback else 1, families.index(family))
        latest = tested[-1]
        response = latest['response']
        bad = (response['status'] in {'worse', 'tradeoff'} or response['global_worse']
               or latest.get('outcome') == 'worse')
        useful = (response['status'] == 'improved' and not bad
                  and latest.get('outcome') not in {'worse', 'rejected'})
        return (0 if useful else 3 if bad else 2,
                -response.get('gain', 0.) if useful else len(tested), 0, families.index(family))
    family = min(families, key=rank)
    counts = {g: sum(r.get('family', r.get('goal')) == g for r in rows) for g in families}
    improved = any(r['response']['status'] == 'improved' and not r['response']['global_worse']
                   and r.get('outcome') != 'worse' for r in rows)
    reason = ('Saved tests reduced some marked-area errors; refine that evidence while checking '
              'the remaining errors. ' if improved else
              'Saved tests did not reliably reduce the marked-area errors. Change the explanation '
              'instead of repeating the same unsuccessful direction. ')
    if all(counts.values()) and not improved:
        reason += ('Several explanations have stalled. Check alignment and the template now; '
                   'further tests remain optional and cannot guarantee recovery. ')
    return family, reason
