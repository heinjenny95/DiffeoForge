from __future__ import annotations

import numpy as np
import pytest

from diffeoforge.analysis.pca import principal_component_analysis
from diffeoforge.analysis.shape_space import (
    DIFFUSION_MAP_METHOD,
    ISOMAP_METHOD,
    LDDMM_METRIC_PCA_METHOD,
    TANGENT_PCOA_METHOD,
    diffusion_map_from_squared_distances,
    gaussian_control_point_kernel,
    isomap_from_squared_distances,
    lddmm_metric_momenta_pca,
    lddmm_momenta_squared_distances,
    median_heuristic_gamma,
    metric_principal_component_analysis,
    principal_coordinates_analysis,
    rbf_kernel_pca,
    rbf_kernel_pca_from_squared_distances,
)


def _features() -> np.ndarray:
    return np.asarray(
        [
            [-2.0, -0.5, 0.0],
            [-1.0, 0.5, 0.2],
            [0.5, 1.0, -0.1],
            [2.5, -1.0, 0.4],
        ],
        dtype=np.float64,
    )


def _squared_distances(values: np.ndarray) -> np.ndarray:
    differences = values[:, None, :] - values[None, :, :]
    return np.asarray(
        np.einsum("ijk,ijk->ij", differences, differences),
        dtype=np.float64,
    )


def test_metric_pca_matches_cartesian_pca_for_identity_metric() -> None:
    values = _features()
    ordinary = principal_component_analysis(
        values,
        feature_space="test",
        sample_labels=("a", "b", "c", "d"),
    )
    metric = metric_principal_component_analysis(
        values,
        np.eye(values.shape[1], dtype=np.float64),
        feature_space="test_metric",
        method="identity metric PCA",
        sample_labels=("a", "b", "c", "d"),
    )

    np.testing.assert_allclose(metric.scores, ordinary.scores, atol=1e-12)
    np.testing.assert_allclose(metric.components, ordinary.components, atol=1e-12)
    np.testing.assert_allclose(metric.transform(values), metric.scores, atol=1e-12)
    np.testing.assert_allclose(
        metric.reconstruct_training_data(),
        ordinary.reconstruct_training_data(),
        atol=1e-12,
    )


def test_lddmm_metric_pca_is_metric_orthonormal_and_shootable() -> None:
    controls = np.asarray([[0.0, 0.0, 0.0], [0.4, 0.0, 0.0]], dtype=np.float64)
    momenta = np.asarray(
        [
            [[-1.0, 0.0, 0.2], [0.3, 0.1, 0.0]],
            [[-0.2, 0.4, 0.1], [0.8, -0.1, 0.2]],
            [[0.7, 0.2, -0.2], [-0.1, 0.5, 0.4]],
            [[1.2, -0.3, 0.3], [-0.6, 0.2, -0.1]],
        ],
        dtype=np.float64,
    )
    result = lddmm_metric_momenta_pca(
        momenta,
        controls,
        deformation_kernel_width=0.75,
        subject_labels=("a", "b", "c", "d"),
    )
    kernel = gaussian_control_point_kernel(controls, 0.75)
    feature_metric = np.kron(kernel, np.eye(3, dtype=np.float64))

    assert result.method == LDDMM_METRIC_PCA_METHOD
    assert result.projection_components is not None
    np.testing.assert_allclose(
        result.components @ feature_metric @ result.components.T,
        np.eye(result.number_of_components),
        atol=1e-10,
    )
    np.testing.assert_allclose(
        result.transform(momenta.reshape(4, -1)),
        result.scores,
        atol=1e-11,
    )
    assert result.reconstruct_training_data().shape == (4, 6)


def test_lddmm_pairwise_distances_match_direct_kernel_quadratic_form() -> None:
    controls = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
    momenta = np.asarray(
        [
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        ],
        dtype=np.float64,
    )
    observed = lddmm_momenta_squared_distances(
        momenta,
        controls,
        deformation_kernel_width=1.0,
    )
    kernel = gaussian_control_point_kernel(controls, 1.0)
    difference = momenta[0] - momenta[1]
    expected = float(np.einsum("ic,ij,jc->", difference, kernel, difference))

    assert observed[0, 1] == pytest.approx(expected)
    np.testing.assert_allclose(observed, observed.T)
    np.testing.assert_allclose(np.diag(observed), 0.0)


def test_rbf_kernel_pca_uses_declared_gamma_and_has_no_automatic_preimage() -> None:
    values = _features()
    squared = _squared_distances(values)
    gamma = median_heuristic_gamma(squared)
    direct = rbf_kernel_pca(values, gamma=gamma, n_components=2)
    precomputed = rbf_kernel_pca_from_squared_distances(
        squared,
        gamma=gamma,
        n_components=2,
    )

    assert direct.gamma == pytest.approx(gamma)
    assert direct.preimage_available is False
    np.testing.assert_allclose(direct.scores, precomputed.scores, atol=1e-12)
    np.testing.assert_allclose(np.sum(direct.centered_kernel, axis=0), 0.0, atol=1e-12)


def test_pcoa_recovers_euclidean_distances_and_reports_method() -> None:
    values = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 2.0], [0.0, 2.0]], dtype=np.float64)
    squared = _squared_distances(values)
    result = principal_coordinates_analysis(squared, n_components=2)

    assert result.method == TANGENT_PCOA_METHOD
    np.testing.assert_allclose(
        _squared_distances(result.coordinates),
        squared,
        atol=1e-11,
    )
    assert result.negative_eigenvalue_sum == pytest.approx(0.0, abs=1e-12)


def test_isomap_and_diffusion_maps_are_deterministic_exploratory_outputs() -> None:
    values = np.asarray(
        [[0.0, 0.0], [1.0, 0.2], [2.0, -0.1], [3.0, 0.1], [4.0, 0.0]],
        dtype=np.float64,
    )
    squared = _squared_distances(values)
    isomap = isomap_from_squared_distances(squared, n_neighbors=2, n_components=2)
    diffusion = diffusion_map_from_squared_distances(squared, n_components=2)
    repeated = diffusion_map_from_squared_distances(squared, n_components=2)

    assert isomap.method == ISOMAP_METHOD
    assert diffusion.method == DIFFUSION_MAP_METHOD
    np.testing.assert_allclose(diffusion.coordinates, repeated.coordinates, atol=1e-12)
    assert np.isfinite(isomap.coordinates).all()
    assert np.isfinite(diffusion.coordinates).all()


def test_shape_space_inputs_fail_closed() -> None:
    values = _features()
    squared = _squared_distances(values)
    squared[0, 1] = -1.0

    with pytest.raises(ValueError, match="nonnegative"):
        rbf_kernel_pca_from_squared_distances(squared)
    with pytest.raises(ValueError, match="positive semidefinite"):
        metric_principal_component_analysis(
            values,
            np.diag(np.asarray([1.0, 1.0, -1.0], dtype=np.float64)),
            feature_space="bad",
            method="bad",
        )
