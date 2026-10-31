"""Separate capture distance from local movement for a missing protected feature."""

import math

VERSION = 'protected-missing-feature-v1'
NATIVE_TIMEPOINTS = 145


def active_regions(recipe, regions):
    active = recipe.get('active_regions')
    if recipe.get('protected_capture') != VERSION:
        return regions
    if (not active or len(active) != 1 or active[0] not in regions
            or active[0].get('purpose', 'problem') != 'problem'):
        raise ValueError('Protected capture must name one unchanged problem mark')
    return active


def proposal(snapshot, identifier, data, info, symptom):
    """New detail requests only; explicit same-objective extensions bypass this."""
    if symptom not in {'detail', 'missing'}:
        return None
    marked = data['regions']
    problem = [r for r in marked if r.get('purpose', 'problem') == 'problem']
    if (not any(r.get('purpose') == 'fixed' for r in marked) or not problem
            or any(r['symptom'] not in {'detail', 'missing'} for r in problem)
            or any(r.get('purpose') == 'preserve' for r in marked)):
        return None
    evidence = data.get('regional_capture') or {}
    rows = evidence.get('per_region') or []
    if [r['region'] for r in rows] != problem:
        return None
    reference = data['anchor'] or data['current_reference']
    previous = (info.get('strategy') or {}).get('regional_recipe') or {}
    persistent = previous.get('protected_capture') == VERSION
    if not persistent and not any(r['original_to_fit_p95'] > r['region']['radius'] for r in rows):
        return None
    from diffeoforge.regional_pilot import _quality_for_regions
    from diffeoforge.regional_search import capture_rows
    from diffeoforge.retained_mark_source import current_is_bound

    seed = reference
    quality = _quality_for_regions(data['current'], reference['target'], marked)
    feedback = (data['context'].get('feedback', {}).get(identifier) or {}).get('feedback') or {}
    if (data['current_reference'] and quality.get('numerical_selection_suitable')
            and current_is_bound(data) and feedback.get('outcome') != 'worse'):
        subject = ((data['current'].metrics or {}).get('attachment_comparison', {})
                   .get('subjects', {}).get(reference['target'], {}))
        measured = subject.get('marked_regions', {}).get('measurements', [])
        subset = [a for a in measured if a['region'] in problem]
        if [a['region'] for a in subset] == problem:
            seed, rows = data['current_reference'], capture_rows(subset)
    worst = max(rows, key=lambda r: r['symmetric_tail'])
    if not math.isfinite(worst['symmetric_tail']) or worst['symmetric_tail'] <= 0:
        return None
    active = worst['region']
    values = dict(seed['values'])
    before_width = values['deformation_kernel_width']
    # Dyadic refinement relative to this seed; repeating a request does not
    # blindly halve the movement scale again. Attachment capture is independent.
    size = active['radius']
    if active.get('shape') == 'box':
        b = active['bounds']
        size = max(b[i+1]-b[i] for i in (0, 2, 4)) / 2
    width = before_width
    for _ in range(16):
        if width <= size * .5:
            break
        width *= .5
    if width > size * .5:
        raise ValueError('This marked feature needs a smaller supported movement scale')
    values['deformation_kernel_width'] = width
    warm = (persistent and seed == data['current_reference'] and width == before_width
            and previous.get('active_regions') == [active])
    diagonal = data.get('spatial_diagonal')
    halo = min(before_width*2, diagonal*.1) if diagonal else before_width*2
    recipe = dict(version='protected-local-v12', protected_capture=VERSION,
        phase='capture', symptom=symptom, level=len(data['context']['cases']),
        active_regions=[active], residual=not warm, control_scope='marked_halo',
        control_support='source-target-coverage-v1',
        focus_width=2*worst['symmetric_tail'], focus_noise=values['noise_std']*.075,
        protection_noise=previous.get('protection_noise', values['noise_std']),
        protection_halo=previous.get('protection_halo', halo), guide_noise=None,
        guide_points=192,
        protection_close_distance=previous.get('protection_close_distance', values['noise_std']*.5),
        protection_tolerance=previous.get('protection_tolerance', values['noise_std']*.25),
        fixed_noise_divisor=16, native_timepoints=NATIVE_TIMEPOINTS,
        capture_evidence=dict(reference=seed, per_region=rows,
            before_movement_width=before_width, movement_width=width,
            capture_and_movement_independent=True, anatomical_approval=False))
    retention = data.get('retention_context')
    available = not retention or (retention['available'] and retention['automatic_start_allowed'])
    blocked = retention['reason'] if retention and not available else ''
    from diffeoforge.regional_search import distinct

    distinct_available, changed = distinct(recipe, values, reference['method'], seed,
                                            data['context']['cases'], quality)
    available &= distinct_available
    if not distinct_available:
        blocked = ('This protected contrast already reached its numerical weight guard. '
                   'Keep the saved fit and review the marks or movement scale.')
    parent = data['references'].get(seed['directory'], snapshot)
    if parent.plan.pilot_subject_count != 1:
        available = False
        blocked = 'Choose a compatible saved single-form fit before a local correction.'
    index = problem.index(active)+1
    return dict(goal='regional', title=f'Improve marked area {index}; retain the rest',
        reason=f'Work on area {index} of {len(problem)}, which has the largest measured remaining '
        'surface mismatch. Keep the complete starting fit and the Retain areas. '
        'Use a broad capture range with separate local movement; all your marks remain saved. '
        + ('An earlier identical test is retained; this is a distinct weight contrast. '
           if changed else '') +
        'After fitting, check all important projections in the saved result. '
        'This test does not approve the other areas or the final anatomy.',
        target=reference['target'], method=reference['method'], values=values,
        anchor=reference, initialization_reference=seed, from_base=False,
        available=available, blocked_reason=blocked, regions=marked, trials=1,
        symptom=symptom, regional_recipe=recipe,
        initialization='learned' if warm else 'residual', numerical_extension=False,
        optimization_iterations=None, remaining_checks=max(0, len(info['pilot_order'])-1),
        hypothesis_count=len(data['context']['cases']),
        contrast_level=len(data['context']['cases']),
        response_evidence=[])


def patch_capture_width(vertices, faces, target_vertices, target_faces, chosen, regions):
    """Measure the actual free patch on the numerical output, without point pairs."""
    import numpy as np

    from diffeoforge.reference_fit_search import grouped_surface_distances, surface_samples
    from diffeoforge.regional_fit import mask

    selected = target_faces[mask(target_vertices[target_faces].mean(1), regions)]
    if not len(selected) or not np.any(chosen):
        raise ValueError('Protected capture needs nonempty free source and original target patches')
    seeds = (2026103001, 2026103002)
    a = grouped_surface_distances([
        surface_samples(target_vertices, selected, 2048, seed=s) for s in seeds],
        vertices, faces[chosen])
    b = grouped_surface_distances([
        surface_samples(vertices, faces[chosen], 2048, seed=s) for s in seeds],
        target_vertices, selected)
    tail = max(float(np.quantile(d, .95)) for d in [*a, *b])
    if not np.isfinite(tail) or tail <= 0:
        raise ValueError('Protected capture needs a positive finite measured patch distance')
    return 2*tail, dict(version=VERSION, samples=2048, seeds=list(seeds),
        symmetric_patch_p95=tail, focus_width=2*tail, geometric_capture_only=True,
        biological_correspondence_claim=False)
