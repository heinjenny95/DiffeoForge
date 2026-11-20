"""Fixed coordinates for NEW protected regional candidates; no native equations change."""

from pathlib import Path

import numpy as np

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import read_vtk_points, sha256_file

VERSION = 'retain-linear-coordinates-v1'


def validate(config):
    marker = config.get('project', {}).get('parameter_provenance', {}).get('regional_conditioning')
    if marker is None:
        return None
    path = Path(marker['matrix'])
    control_path = Path(config['model']['deformation']['initial_control_points'])
    if (not path.is_absolute() or sha256_file(path) != marker['sha256']
            or sha256_file(control_path) != marker['control_points_sha256']):
        raise ConfigurationError('Regional coordinate matrix or control identity changed')
    matrix = np.load(path, allow_pickle=False)
    count = marker['controls']
    controls = np.loadtxt(control_path, ndmin=2)
    if (marker.get('version') != VERSION or type(count) is not int or not 1 <= count <= 2000
            or controls.shape != (count, 3) or not np.isfinite(controls).all()
            or matrix.dtype != np.float64 or matrix.shape != (count, count)
            or not np.isfinite(matrix).all() or not np.array_equal(matrix, matrix.T)
            or np.linalg.eigvalsh(matrix).min() <= 0):
        raise ConfigurationError('Invalid positive-definite regional coordinate basis')
    return matrix


def prepare_new(config, directory, *, same_objective=False):
    """Prepare only: legacy numerical extensions keep their existing coordinates."""
    from diffeoforge.regional_fit import read_plan

    provenance = config['project'].get('parameter_provenance', {})
    plan = read_plan(config)
    marker = provenance.get('regional_conditioning')
    if not plan or not plan.get('fixed_protection'):
        provenance.pop('regional_conditioning', None)
        return
    if same_objective:
        if marker is not None:
            validate(config)
        return
    # This is a new objective contract. Old prepared plans are not rewritten or
    # silently upgraded merely by being opened/rendered in a newer application.
    if not plan.get('material_selection'):
        provenance.pop('regional_conditioning', None)
        return
    control_path = Path(config['model']['deformation']['initial_control_points'])
    controls = np.loadtxt(control_path, ndmin=2)
    if (controls.ndim != 2 or controls.shape[1] != 3 or not 1 <= len(controls) <= 2000
            or not np.isfinite(controls).all()):
        raise ConfigurationError('Protected regional coordinates require 1–2000 finite controls')
    fixed = next(o for o in plan['objects'] if o['id'] == 'fixed')
    focus = next(o for o in plan['objects'] if o['id'] == 'focus')
    root = Path(provenance['regional_fit']['manifest']).parent
    positions = np.asarray(read_vtk_points(root / fixed['source']['copy']), float)
    width = config['model']['deformation']['kernel_width']
    A = np.exp(-np.sum((positions[:, None]-controls[None])**2, axis=2)/width**2)
    _, singular, vt = np.linalg.svd(A, full_matrices=False)
    ridge = 1/focus['noise_std']**2
    matrix = np.eye(len(controls))/np.sqrt(ridge)+(vt.T*(
        1/np.sqrt(ridge+2*singular*singular/fixed['noise_std']**2)-1/np.sqrt(ridge)))@vt
    matrix = (matrix+matrix.T)*.5
    path = Path(directory).resolve() / 'optimizer-coordinates.npy'
    with path.open('xb') as stream:
        np.save(stream, matrix, allow_pickle=False)
    provenance['regional_conditioning'] = dict(version=VERSION, matrix=str(path),
        sha256=sha256_file(path), controls=len(controls),
        control_points_sha256=sha256_file(control_path))
    validate(config)
