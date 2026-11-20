"""A direct local field may initialize a separately reviewed shared-basis trial."""
from copy import deepcopy

import pytest

from diffeoforge import pilot_common_basis as basis


def test_new_optimizer_is_an_initialization_contrast_without_relaxing_accuracy(tmp_path):
    from test_reference_calibration_study import _project

    from diffeoforge.config import load_config

    original = load_config(_project(tmp_path))
    other = deepcopy(original)
    other['optimization']['method'] = 'lbfgs'
    assert basis.direct_field_physics(original) == basis.direct_field_physics(other)
    assert basis.field_physics(original) != basis.field_physics(other)
    other['model']['deformation']['kernel_width'] *= .8
    assert basis.direct_field_physics(original) != basis.direct_field_physics(other)
    other = deepcopy(original)
    other['optimization']['convergence_tolerance'] *= .1
    assert basis.direct_field_physics(original) != basis.direct_field_physics(other)
    other = deepcopy(original)
    other['model']['deformation']['timepoints'] *= 2
    assert basis.direct_field_physics(original) != basis.direct_field_physics(other)


def test_direct_regional_field_is_eligible_but_a_residual_alone_is_not(tmp_path, monkeypatch):
    from test_reference_calibration_study import _project

    from diffeoforge import regional_fit
    from diffeoforge.config import load_config

    config = load_config(_project(tmp_path))
    config['optimization'].update(freeze_template=True, freeze_control_points=True)
    monkeypatch.setattr(regional_fit, 'read_plan',
                        lambda c: {'execution_scope': 'single_specimen_probe'})
    assert basis.transferable_direct_field(config)
    monkeypatch.setattr(regional_fit, 'read_plan',
                        lambda c: {'residual': {'parent_run': 'bound-parent'}})
    assert not basis.transferable_direct_field(config)
    monkeypatch.setattr(regional_fit, 'read_plan', lambda c: {})
    config['optimization']['freeze_control_points'] = False
    assert not basis.transferable_direct_field(config)


def test_saved_basis_bytes_and_prefix_are_required(tmp_path):
    from types import SimpleNamespace

    import numpy as np

    from diffeoforge.mesh import sha256_file

    points = np.array([[0., 0., 0.], [1., .2, 0.]])
    path = tmp_path / 'controls.txt'
    np.savetxt(path, points, fmt='%.17g')
    source = SimpleNamespace(study_directory=tmp_path, attachment_comparison=dict(
        controls=dict(copy=path.name, count=2, sha256=sha256_file(path))))
    assert basis._prefix_basis(source, np.vstack((points, [2., 2., 2.])))
    assert not basis._prefix_basis(source, np.vstack((points[::-1], [2., 2., 2.])))
    with path.open('a') as output:
        output.write('\n')
    with pytest.raises(ValueError, match='basis changed'):
        basis._prefix_basis(source, np.vstack((points, [2., 2., 2.])))


def test_prepare_review_adopt_and_next_form_keep_reviews_and_initialization(tmp_path, monkeypatch):
    from test_pilot_common_diagnosis import (
        test_capacity_preparation_preserves_field_protocol_reviews_and_requires_explicit_adoption,
    )

    test_capacity_preparation_preserves_field_protocol_reviews_and_requires_explicit_adoption(
        tmp_path, monkeypatch)
