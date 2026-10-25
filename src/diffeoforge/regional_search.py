"""Measured capture range and source/target coverage for new residual bases."""
import numpy as np


def capture(snapshot, reference, regions):
    """Background-only evidence from this retained fit, never a successful oracle."""
    candidate = next(c for c in snapshot.candidates
                     if c.candidate_id == reference['candidate_id'])
    quality = ((candidate.metrics or {}).get('attachment_comparison', {})
               .get('subjects', {}).get(reference['target'], {}).get('regional_quality', {}))
    if quality and regions == quality.get('marked_regions'):
        rows = quality['active_surface']
    else:
        from diffeoforge.pilot_recovery import capture as measure

        measured = measure(snapshot, candidate.candidate_id, reference['target'], regions=regions)
        rows = [repeat for area in measured['baseline'] for repeat in area['repeats']]
    return dict(reference=reference, regions=regions,
                original_to_fit_p95=max(r['original_to_fit_p95'] for r in rows))


def controls(source, target, regions, width, *, limit=2000, full_surface=False):
    """A zero-field basis covers both sides of the miss, not only the short source."""
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.regional_fit import mask

    source, target = np.asarray(source, float), np.asarray(target, float)
    if not np.isfinite(width) or width <= 0:
        raise ValueError('Residual movement width must be positive')
    lo, hi = np.minimum(source.min(0), target.min(0)), np.maximum(source.max(0), target.max(0))
    coarse, _ = control_grid(np.column_stack((lo, hi)).ravel(), target=200)
    spacing = width * .5
    local = (np.vstack((source, target)) if full_surface else
             np.vstack((source[mask(source, regions, halo=width)],
                        target[mask(target, regions, halo=width)])))
    if not len(local):
        raise ValueError('The active residual region has no control support')
    cells = np.unique(np.floor((local-lo)/spacing).astype(np.int64), axis=0)
    fine = lo + (cells+.5)*spacing
    points = np.unique(np.vstack((coarse, fine)), axis=0)
    if len(points) > limit:
        raise ValueError('The requested local movement exceeds the residual control limit; '
                         'choose a broader scale or review the marked areas')
    # Every selected source/target vertex is at most sqrt(3)*spacing/2 from
    # its occupied voxel centre; no nearest-control promise outside this halo.
    return points, spacing, dict(version='source-target-coverage-v1',
        scope='full_surface' if full_surface else 'marked_halo',
        controls=len(points), local_voxels=len(fine), spacing=spacing,
        maximum_local_support_distance=float(np.sqrt(3)*spacing/2),
        maximum_local_support_distance_over_width=float(np.sqrt(3)/4),
        limit=limit, source_points=len(source), target_points=len(target))


def distinct(recipe, values, method, seed, cases, quality):
    """Do not repeat an identical objective/basis on a discarded same starting field."""
    keys = ('focus_width', 'focus_noise', 'protection_noise', 'guide_noise',
            'protection_halo', 'residual', 'control_support', 'control_scope')
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
