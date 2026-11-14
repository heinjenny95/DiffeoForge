"""Cover actual movable material when preparing a new zero-field residual basis."""

import numpy as np


def augment(controls, material, spacing, origin, *, limit=2000):
    """Keep existing controls and add the occupied material voxels at the SAME scale."""
    q, v, lo = np.asarray(controls, float), np.asarray(material, float), np.asarray(origin, float)
    if (q.ndim != 2 or v.ndim != 2 or q.shape[1:] != (3,) or v.shape[1:] != (3,)
            or not len(q) or not len(v) or lo.shape != (3,)
            or not np.isfinite(q).all() or not np.isfinite(v).all() or not np.isfinite(lo).all()
            or not np.isfinite(spacing) or spacing <= 0):
        raise ValueError('Invalid actual-material control support')
    cells = np.unique(np.floor((v-lo)/spacing).astype(np.int64), axis=0)
    points = np.unique(np.vstack((q, lo+(cells+.5)*spacing)), axis=0)
    if len(points) > limit:
        raise ValueError('The movable source patch exceeds the residual control limit. '
                         'Review its scale or marks; no coarser basis was substituted.')
    receipt = dict(version='actual-material-voxel-coverage-v1',
        controls_before=len(q), controls_after=len(points), material_vertices=len(v),
        spacing=spacing, maximum_material_support_distance=float(np.sqrt(3)*spacing/2),
        limit=limit, existing_controls_preserved=True, movement_scale_unchanged=True)
    return points, receipt


def bind(root, manifest, record, plan, plan_root):
    """Never change a warm or same-objective basis; all coefficients here start at zero."""
    if record.get('refinement', {}).get('initialization') != 'residual':
        return record
    from diffeoforge.mesh import read_vtk_points, sha256_file
    from diffeoforge.surface_io import load_surface_mesh

    row = record['controls']
    control_path = root / row['copy']
    if sha256_file(control_path) != row['sha256']:
        raise ValueError('Residual control identity changed before material coverage')
    target = next(r for r in manifest['inputs']['subjects']
                  if r['filename'] == record['guided']['feedback']['target'])
    source = load_surface_mesh(root / record['refinement']['residual']['source']['copy'])
    original = load_surface_mesh(root / target['copy'])
    origin = np.minimum(np.asarray(source.geometry.vertices).min(0),
                        np.asarray(original.geometry.vertices).min(0))
    focus = next(o for o in plan['objects'] if o['id'] == 'focus')
    material = read_vtk_points(plan_root / focus['source']['copy'])
    controls, receipt = augment(np.loadtxt(control_path), material, row['spacing'], origin)
    np.savetxt(control_path, controls, fmt='%.17g')
    coverage = plan['residual'].get('control_coverage') or {}
    plan['residual']['control_coverage'] = dict(coverage, actual_material=receipt)
    return dict(record, controls=dict(row, sha256=sha256_file(control_path), count=len(controls)))
