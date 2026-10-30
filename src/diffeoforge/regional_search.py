"""Measured capture range and source/target coverage for new residual bases."""
import numpy as np


def capture(snapshot, reference, regions, *, per_region=False):
    """Background-only evidence from this retained fit, never a successful oracle."""
    candidate = next(c for c in snapshot.candidates
                     if c.candidate_id == reference['candidate_id'])
    quality = ((candidate.metrics or {}).get('attachment_comparison', {})
               .get('subjects', {}).get(reference['target'], {}).get('regional_quality', {}))
    if (not per_region and quality
            and regions == quality.get('surface_regions', quality.get('marked_regions'))):
        rows = quality['active_surface']
    else:
        from diffeoforge.pilot_recovery import capture as measure

        measured = measure(snapshot, candidate.candidate_id, reference['target'], regions=regions)
        rows = [repeat for area in measured['baseline'] for repeat in area['repeats']]
    result = dict(reference=reference, regions=regions,
                  original_to_fit_p95=max(r['original_to_fit_p95'] for r in rows))
    if per_region:
        result['per_region'] = capture_rows(measured['baseline'])
    return result


def capture_rows(measurements):
    """Keep missing reverse samples unknown and every brush separately identified."""
    rows = []
    for area in measurements:
        forward = max(r['original_to_fit_p95'] for r in area['repeats'])
        back = [r['fit_to_original_p95'] for r in area['repeats']
                if r.get('fit_to_original_p95') is not None]
        reverse = max(back) if back else None
        rows.append(dict(region=area['region'], original_to_fit_p95=forward,
                         fit_to_original_p95=reverse,
                         symmetric_tail=max(forward, reverse or 0)))
    return rows


def controls(source, target, regions, width, *, limit=2000, full_surface=False,
             budget_policy=None):
    """A zero-field basis covers both sides of the miss, not only the short source."""
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.regional_fit import mask

    source, target = np.asarray(source, float), np.asarray(target, float)
    if not np.isfinite(width) or width <= 0:
        raise ValueError('Residual movement width must be positive')
    lo, hi = np.minimum(source.min(0), target.min(0)), np.maximum(source.max(0), target.max(0))
    coarse, _ = control_grid(np.column_stack((lo, hi)).ravel(), target=200)
    if budget_policy not in {None, 'bounded-full-surface-v1'}:
        raise ValueError('Unknown residual control-budget policy')
    if budget_policy and not full_surface:
        raise ValueError('Bounded spacing is declared only for full-surface controls')
    spacing = width * .5
    local = (np.vstack((source, target)) if full_surface else
             np.vstack((source[mask(source, regions, halo=width)],
                        target[mask(target, regions, halo=width)])))
    if not len(local):
        raise ValueError('The active residual region has no control support')
    attempts = []
    while True:
        cells = np.unique(np.floor((local-lo)/spacing).astype(np.int64), axis=0)
        fine = lo + (cells+.5)*spacing
        points = np.unique(np.vstack((coarse, fine)), axis=0)
        attempts.append(dict(spacing=spacing, controls=len(points)))
        if len(points) <= limit:
            break
        if not budget_policy or spacing >= width:
            raise ValueError('The requested local movement exceeds the residual control limit; '
                             'choose a broader scale or review the marked areas')
        spacing = min(width, spacing*1.125)
    # Every selected source/target vertex is at most sqrt(3)*spacing/2 from
    # its occupied voxel centre; no nearest-control promise outside this halo.
    receipt = dict(version='source-target-coverage-v2' if budget_policy else
                   'source-target-coverage-v1',
        scope='full_surface' if full_surface else 'marked_halo',
        controls=len(points), local_voxels=len(fine), spacing=spacing,
        maximum_local_support_distance=float(np.sqrt(3)*spacing/2),
        maximum_local_support_distance_over_width=float(np.sqrt(3)*spacing/(2*width)),
        limit=limit, source_points=len(source), target_points=len(target))
    if budget_policy:
        receipt.update(budget_policy=budget_policy, attempts=attempts,
                       budget_adjusted=len(attempts) > 1, maximum_spacing=width,
                       deformation_width_unchanged=width)
    return points, spacing, receipt


def distinct(recipe, values, method, seed, cases, quality):
    """Do not repeat an identical objective/basis on a discarded same starting field."""
    keys = ('focus_width', 'focus_noise', 'protection_noise', 'guide_noise',
            'protection_halo', 'residual', 'control_support', 'control_scope', 'active_regions')
    def repeated():
        return any(r.get('reference') == seed and r.get('method') == method
                   and r.get('values') == values and r.get('regional_recipe')
                   and all(r['regional_recipe'].get(k) == recipe.get(k) for k in keys)
                   for r in cases)
    changed = False
    while repeated():
        protect = quality.get('outside_preserved') is False
        gentler = (quality.get('no_new_intersection_flags') is False
                   or quality.get('shape_preserved') is False)
        key = 'protection_noise' if protect else 'focus_noise'
        recipe[key] *= 2 if gentler and not protect else .5
        if not values['noise_std']*1e-4 <= recipe[key] <= values['noise_std']*8:
            return False, changed
        changed = True
    return True, changed


def recover_whole(recipe, values, original_values, previous, quality, whole_tail,
                  spatial_tail, *, explicit_fixed=False):
    """Once marked detail is reached, address measured remaining global error.

    This is a new hypothesis with independent controls, never replacement of a
    useful prefix. No external successful fit participates in its measurements.
    """
    rows = quality.get('active_surface') or []
    tolerance = previous.get('protection_tolerance', 0)
    marked = max((max(r['original_to_fit_p95'], r.get('fit_to_original_p95', np.inf))
                  for r in rows), default=np.inf)
    if (previous.get('phase') not in {'detail', 'whole_recovery'} or not tolerance
            or not quality.get('numerical_selection_suitable') or marked > tolerance
            or recipe.get('guide_noise') is not None
            or whole_tail <= max(2*marked, 2*tolerance)):
        return False
    width = max(original_values['attachment_kernel_width']*.5, spatial_tail*.5)
    relaxed = bool(not explicit_fixed and quality.get('outside_preserved')
                   and quality.get('outside_displacement_p95', np.inf) < tolerance*.25)
    recipe.update(version='protected-local-v8', phase='whole_recovery', residual=True,
        control_scope='full_surface', focus_width=previous['focus_width'],
        focus_noise=previous['focus_noise'],
        protection_noise=previous['protection_noise']*(2 if relaxed else 1),
        protection_close_distance=previous['protection_close_distance'],
        protection_tolerance=tolerance, protection_halo=previous['protection_halo'],
        whole_surface_recovery=dict(whole_p95=whole_tail, marked_p95=marked,
            spatial_tail=spatial_tail, before_width=original_values['attachment_kernel_width'],
            after_width=width, noise_factor=.5, automatic_anchor_weight_relaxed=relaxed,
            explicit_fixed_present=explicit_fixed, retained_prefix_unchanged=True))
    for key in ('whole_surface_contrast', 'whole_surface_balance', 'whole_surface_capture',
                'weight_continuation'):
        recipe.pop(key, None)
    values.update(attachment_kernel_width=width, noise_std=original_values['noise_std']*.5,
        deformation_kernel_width=max(original_values['deformation_kernel_width']*.5,
                                     2*recipe['focus_width'], 2*width))
    return True
