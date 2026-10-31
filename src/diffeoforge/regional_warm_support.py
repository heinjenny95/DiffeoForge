"""Check an existing local basis before reusing it on newly selected material."""

import numpy as np

from diffeoforge.mesh import sha256_file


def assess(root, record, residual, source_path, numerical_path, retained_path,
           target_path, regions, fixed_regions, *, guide_noise=None):
    """Read-only geometry/control test; no coefficient or basis is modified."""
    coverage = (residual or {}).get('control_coverage') or {}
    if (record.get('refinement', {}).get('initialization') != 'learned'
            or guide_noise is not None
            or coverage.get('version') not in {
                'source-target-coverage-v1', 'source-target-coverage-v2',
            }):
        return None
    from diffeoforge.regional_material_patch import select
    from diffeoforge.regional_preservation import vertex_ids
    from diffeoforge.surface_io import load_surface_mesh

    source, numerical, retained, target = [load_surface_mesh(p).geometry for p in (
        source_path, numerical_path, retained_path, target_path)]
    sv, sf = np.asarray(source.vertices, float), np.asarray(source.triangles, int)
    nv, nf = np.asarray(numerical.vertices, float), np.asarray(numerical.triangles, int)
    rv, rf = np.asarray(retained.vertices, float), np.asarray(retained.triangles, int)
    if (sv.shape != nv.shape or sv.shape != rv.shape
            or not np.array_equal(sf, nf) or not np.array_equal(sf, rf)):
        raise ValueError('Saved numerical and Retain fields need matching material grids '
                         'before their control support can be checked')
    tv, tf = np.asarray(target.vertices, float), np.asarray(target.triangles, int)
    fixed_ids = vertex_ids(rv, rf, fixed_regions) if fixed_regions else []
    selected, _ = select(nv, nf, tv, tf, regions, fixed_ids)
    # The optimizer's current basis acts on its incoming material, not on a
    # mixture of output coordinates and initial control-point coordinates.
    material = sv[np.unique(sf[selected])]
    row = record['controls']
    path = root / row['copy']
    if sha256_file(path) != row['sha256']:
        raise ValueError('Saved controls changed before the material-support check')
    controls = np.loadtxt(path, ndmin=2)
    bound = coverage['maximum_local_support_distance']
    if (controls.shape[1:] != (3,) or not len(controls) or not np.isfinite(controls).all()
            or not np.isfinite(bound) or bound <= 0):
        raise ValueError('Invalid saved local-control support contract')
    distances = []
    for start in range(0, len(material), 512):
        query = material[start:start+512]
        distances.append(np.linalg.norm(query[:, None]-controls[None], axis=2).min(1))
    distances = np.concatenate(distances)
    return dict(version='warm-material-support-v1', material_vertices=len(material),
        controls=len(controls), maximum=float(distances.max()),
        p95=float(np.quantile(distances, .95)), declared_bound=bound,
        fraction_outside=float(np.mean(distances > bound+1e-12)),
        passed=bool(distances.max() <= bound+1e-12),
        source_sha256=sha256_file(source_path), controls_sha256=row['sha256'],
        basis_and_coefficients_unchanged=True, anatomical_approval=False)
