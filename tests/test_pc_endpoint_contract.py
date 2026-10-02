from dataclasses import replace

import numpy as np
import pytest

from diffeoforge.analysis.method_labels import shape_method_label
from diffeoforge.analysis.pca import momenta_pca
from diffeoforge.analysis.shape_space import lddmm_metric_momenta_pca
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_pca_deformations import (
    ReferencePCADeformationError,
    _endpoint_definition,
    _write_momenta,
)


def test_axis_fields_recover_declared_scores_in_metric_and_cartesian_coordinates(tmp_path):
    rng = np.random.default_rng(31415)
    points = rng.normal(size=(5, 3)).astype(np.float64)
    fields = rng.normal(size=(9, 5, 3)).astype(np.float64)
    for pca in (
        momenta_pca(fields, n_components=3),
        lddmm_metric_momenta_pca(fields, points, deformation_kernel_width=1, n_components=3),
    ):
        endpoints, labels, skipped = _endpoint_definition(pca, 3, 2)
        # Independent score projection verifies the inverse metric mapping and SD scale.
        observed_scores = pca.transform(endpoints.reshape(len(endpoints), -1))
        expected_scores = np.zeros((7, 3))
        for index in range(3):
            expected_scores[1 + 2 * index, index] = -2 * np.sqrt(pca.explained_variance[index])
            expected_scores[2 + 2 * index, index] = 2 * np.sqrt(pca.explained_variance[index])
        np.testing.assert_allclose(observed_scores, expected_scores, atol=1e-10)
        assert not skipped and len(labels) == 7
        path = tmp_path / (pca.feature_space + ".txt")
        _write_momenta(path, endpoints)
        np.testing.assert_array_equal(read_deformetrica_momenta(path), endpoints)
    assert "PGA" in shape_method_label("lddmm_deformation_kernel_pca", "old label")
    assert shape_method_label("cartesian_momenta_pca", "Cartesian PCA") == "Cartesian PCA"
    assert shape_method_label("rbf_kernel_pca", "RBF KernelPCA") == "RBF KernelPCA"


def test_nonshootable_method_or_nonfinite_endpoint_is_rejected():
    fields = np.arange(36, dtype=np.float64).reshape(4, 3, 3)
    pca = momenta_pca(fields, n_components=1)
    with pytest.raises(ReferencePCADeformationError, match="shootable"):
        _endpoint_definition(replace(pca, feature_space="rbf_feature_space"), 1, 2)
    with pytest.raises(ReferencePCADeformationError, match="disagree"):
        _endpoint_definition(replace(pca, method="generic RBF kernel PCA"), 1, 2)
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ReferencePCADeformationError, match="non-finite"):
            _endpoint_definition(replace(pca, components=np.full_like(pca.components, 1e308)), 1, 2)


def test_momentum_writer_rejects_invalid_field_before_creating_file(tmp_path):
    path = tmp_path / "invalid.txt"
    for values in (np.zeros((0, 5, 3)), np.zeros((1, 0, 3)), np.full((1, 5, 3), np.nan)):
        with pytest.raises(ValueError):
            _write_momenta(path, values)
        assert not path.exists()
