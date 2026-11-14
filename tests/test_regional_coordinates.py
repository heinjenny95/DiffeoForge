"""Exact native f/g and callbacks survive fixed coordinates; legacy work is untouched."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_reference_finite_accepted_guard import render
from test_regional_anchor_references import setup

from diffeoforge.config import ConfigurationError, validate_schema
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_finite_accepted_guard import (
    clear_runtime_markers,
    mark_new_configuration,
)
from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_SOURCE
from diffeoforge.regional_coordinate_assets import SOURCE
from diffeoforge.regional_coordinates import prepare_new, validate


def config_fixture(tmp_path):
    config, source, *_ = setup(tmp_path)
    keys = ('attachment_kernel_width', 'deformation_kernel_width',
            'initial_control_point_spacing', 'noise_std')
    config['project']['parameter_provenance'].update(profile='advanced',
        scale_reference='template_bounding_box_diagonal',
        ratios={k: 1. for k in keys}, sources={k: 'absolute_override' for k in keys})
    controls = tmp_path/'controls.txt'
    np.savetxt(controls, source, fmt='%.17g')
    config['model']['deformation']['initial_control_points'] = str(controls)
    config['optimization']['method'] = 'lbfgs'
    return config


def test_new_protected_operator_is_positive_bound_and_packaged_without_native_math_changes(
    tmp_path,
):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    prepare_new(config, tmp_path)
    validate_schema(config)
    B = validate(config)
    assert B.shape == (24, 24) and np.linalg.eigvalsh(B).min() > 0
    generated = render(config)
    marker = config['project']['parameter_provenance']['regional_conditioning']
    assert generated['linear_conditioning.py'] == SOURCE
    assert hashlib.sha256(generated['conditioning.npy']).hexdigest() == marker['sha256']
    assert generated['finite_accepted_guard.py'] == C5_SOURCE
    assert generated['regional_guard_runtime.py'] == RUNTIME_SOURCE
    assert json.loads(generated['guard-policy.json'])['coordinates']['sha256'] == marker['sha256']
    compile(generated['sitecustomize.py'], 'sitecustomize.py', 'exec')


def test_operator_and_control_tampering_fail_closed(tmp_path):
    config = config_fixture(tmp_path)
    prepare_new(config, tmp_path)
    marker = config['project']['parameter_provenance']['regional_conditioning']
    path = tmp_path/'optimizer-coordinates.npy'
    matrix = np.load(path)
    matrix[0, 0] = -1.
    np.save(path, matrix)
    with pytest.raises(ConfigurationError, match='identity changed'):
        validate(config)
    marker['sha256'] = sha256_file(path)
    with pytest.raises(ConfigurationError, match='positive-definite'):
        validate(config)


def test_legacy_successors_keep_coordinates_and_cohort_staging_clears_contract(tmp_path):
    config = config_fixture(tmp_path)
    prepare_new(config, tmp_path, same_objective=True)
    assert 'regional_conditioning' not in config['project']['parameter_provenance']
    prepare_new(config, tmp_path)
    marker = dict(config['project']['parameter_provenance']['regional_conditioning'])
    original = (tmp_path/'optimizer-coordinates.npy').read_bytes()
    prepare_new(config, tmp_path/'unused', same_objective=True)
    assert marker == config['project']['parameter_provenance']['regional_conditioning']
    assert not (tmp_path/'unused').exists()
    clear_runtime_markers(config)
    assert 'regional_conditioning' not in config['project']['parameter_provenance']
    assert (tmp_path/'optimizer-coordinates.npy').read_bytes() == original


def test_old_prepared_plan_does_not_get_implicitly_upgraded(tmp_path):
    config = config_fixture(tmp_path)
    declaration = config['project']['parameter_provenance']['regional_fit']
    from pathlib import Path

    path = Path(declaration['manifest'])
    data = json.loads(path.read_text())
    data.pop('material_selection')
    path.write_text(json.dumps(data))
    declaration['sha256'] = sha256_file(path)
    prepare_new(config, tmp_path)
    assert not (tmp_path/'optimizer-coordinates.npy').exists()


def test_coordinate_budget_failure_never_silently_coarsens_controls(tmp_path):
    config = config_fixture(tmp_path)
    np.savetxt(tmp_path/'controls.txt', np.zeros((2001, 3)))
    with pytest.raises(ConfigurationError, match='1–2000 finite controls'):
        prepare_new(config, tmp_path)
    assert not (tmp_path/'optimizer-coordinates.npy').exists()


def test_chain_rule_exact_physical_result_callback_and_conservative_stopping(tmp_path):
    namespace = {}
    exec(compile(SOURCE, 'linear_conditioning.py', 'exec'), namespace)
    B = np.array([[.2, .03], [.03, .4]])
    path = tmp_path/'operator.npy'
    np.save(path, B)
    sha = sha256_file(path)
    H = np.diag([1., 4., 2., 3., 8., 9.])
    start, z = np.arange(6)*.03, np.arange(6)*.02
    expected = start+(B@z.reshape(2, 3)).ravel()
    callbacks, options = [], []

    def native(x):
        gradient = H@x
        return float(x@gradient*.5), gradient

    def raw(cost, z0, **kwargs):
        assert np.array_equal(z0, np.zeros(6))
        options.append(kwargs['options'])
        f, gradient = cost(z)
        assert np.array_equal(gradient, (B.T@(H@expected).reshape(2, 3)).ravel())
        eps = 1e-6
        fd = [(cost(z+np.eye(6)[j]*eps)[0]-cost(z-np.eye(6)[j]*eps)[0])/(2*eps)
              for j in range(6)]
        assert np.allclose(gradient, fd, rtol=1e-8, atol=1e-9)
        kwargs['callback'](z)
        return SimpleNamespace(x=z.copy(), fun=f, jac=gradient)

    answer = namespace['bind'](raw, path, sha)(native, start, method='L-BFGS-B', jac=True,
        callback=lambda x: callbacks.append(x.copy()), options=dict(ftol=1e-6, maxiter=20))
    assert np.array_equal(answer.x, expected) and np.array_equal(callbacks[0], expected)
    assert answer.fun.hex() == native(expected)[0].hex()
    assert np.array_equal(answer.jac, native(expected)[1])
    assert options[0]['ftol'] == 1e-6 and options[0]['maxiter'] == 20
    assert options[0]['gtol'] == 1e-5*np.linalg.eigvalsh(B).min()/np.sqrt(6)


def test_unknown_preimported_native_alias_is_rejected(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    prepare_new(config, tmp_path)
    body = render(config)['sitecustomize.py'].decode()
    start = body.index('    if (_df_condition_native.minimize')
    end = body.index('    _df_message_compat = _df_condition_bind', start)
    import textwrap

    check = textwrap.dedent(body[start:end])
    raw, compatible = object(), object()
    for alias in (raw, compatible):
        exec(check, dict(_df_condition_native=SimpleNamespace(minimize=alias),
                         _df_message_compat=compatible, _df_minimize=raw))
    with pytest.raises(ValueError, match='Unexpected pre-conditioning native alias'):
        exec(check, dict(_df_condition_native=SimpleNamespace(minimize=object()),
                         _df_message_compat=compatible, _df_minimize=raw))
