"""Deterministic, explicitly named shape-space embeddings for atlas momenta.

The module separates the LDDMM deformation metric from generic nonlinear kernels.
None of the exploratory embeddings supplies a biological interpretation or a
KernelPCA pre-image automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np

from diffeoforge.analysis.pca import PCAResult, principal_component_analysis

LDDMM_METRIC_PCA_METHOD = "LDDMM deformation-kernel metric tangent PCA"
RBF_KERNEL_PCA_METHOD = "generic RBF kernel PCA"
TANGENT_PCOA_METHOD = "LDDMM tangent-distance principal coordinates analysis"
ISOMAP_METHOD = "Isomap of declared pairwise distances"
DIFFUSION_MAP_METHOD = "diffusion map of declared pairwise distances"


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, dtype=np.float64, copy=True)
    result.setflags(write=False)
    return result


def _positive_real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return result


def _component_count(value: int | None, maximum: int) -> int:
    if value is None:
        return maximum
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError("n_components must be an integer")
    result = int(value)
    if result < 1 or result > maximum:
        raise ValueError(f"n_components must be between 1 and {maximum}")
    return result


def _momenta_and_controls(
    momenta: np.ndarray,
    control_points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(momenta, np.ndarray) or momenta.dtype != np.float64:
        raise TypeError("momenta must be a numpy.float64 array")
    if momenta.ndim != 3 or momenta.shape[0] < 2 or momenta.shape[1] < 1:
        raise ValueError("momenta must have shape (subjects >= 2, control_points >= 1, 3)")
    if momenta.shape[2] != 3 or not bool(np.isfinite(momenta).all()):
        raise ValueError("momenta must contain finite three-dimensional vectors")
    if not isinstance(control_points, np.ndarray) or control_points.dtype != np.float64:
        raise TypeError("control_points must be a numpy.float64 array")
    if control_points.shape != (momenta.shape[1], 3):
        raise ValueError("control_points must have shape (momenta control_points, 3)")
    if not bool(np.isfinite(control_points).all()):
        raise ValueError("control_points must contain only finite values")
    return momenta, control_points


def gaussian_control_point_kernel(
    control_points: np.ndarray,
    kernel_width: float,
) -> np.ndarray:
    """Return Deformetrica's Gaussian K(q_i,q_j)=exp(-||q_i-q_j||²/width²)."""

    if not isinstance(control_points, np.ndarray) or control_points.dtype != np.float64:
        raise TypeError("control_points must be a numpy.float64 array")
    if control_points.ndim != 2 or control_points.shape[0] < 1 or control_points.shape[1] != 3:
        raise ValueError("control_points must have shape (points >= 1, 3)")
    if not bool(np.isfinite(control_points).all()):
        raise ValueError("control_points must contain only finite values")
    width = _positive_real("kernel_width", kernel_width)
    differences = control_points[:, None, :] - control_points[None, :, :]
    squared = np.einsum("ijk,ijk->ij", differences, differences, optimize=True)
    kernel = np.exp(-np.maximum(squared, 0.0) / (width * width))
    return _readonly((kernel + kernel.T) * 0.5)


def _metric_square_roots(metric: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    eigenvalues, eigenvectors = np.linalg.eigh(metric)
    scale = max(float(np.max(np.abs(eigenvalues))), 1.0)
    tolerance = metric.shape[0] * np.finfo(np.float64).eps * scale
    if float(np.min(eigenvalues)) < -100.0 * tolerance:
        raise ValueError("feature metric must be positive semidefinite")
    positive = eigenvalues > tolerance
    if not bool(np.any(positive)):
        raise ValueError("feature metric has no positive numerical direction")
    roots = np.zeros_like(eigenvalues)
    inverse_roots = np.zeros_like(eigenvalues)
    roots[positive] = np.sqrt(eigenvalues[positive])
    inverse_roots[positive] = 1.0 / roots[positive]
    square_root = (eigenvectors * roots) @ eigenvectors.T
    inverse_square_root = (eigenvectors * inverse_roots) @ eigenvectors.T
    return square_root, inverse_square_root, int(np.count_nonzero(positive))


def metric_principal_component_analysis(
    features: np.ndarray,
    feature_metric: np.ndarray,
    *,
    n_components: int | None = None,
    feature_space: str,
    method: str,
    feature_labels: tuple[str, ...] | list[str] | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
    tie_tolerance: float = 1e-12,
) -> PCAResult:
    """PCA whose projection and reconstruction are adjoint in a declared metric."""

    if not isinstance(features, np.ndarray) or features.dtype != np.float64:
        raise TypeError("features must be a numpy.float64 array")
    if features.ndim != 2 or features.shape[0] < 2 or features.shape[1] < 1:
        raise ValueError("features must have shape (samples >= 2, features >= 1)")
    if not bool(np.isfinite(features).all()):
        raise ValueError("features must contain only finite values")
    if not isinstance(feature_metric, np.ndarray) or feature_metric.dtype != np.float64:
        raise TypeError("feature_metric must be a numpy.float64 array")
    if feature_metric.shape != (features.shape[1], features.shape[1]):
        raise ValueError("feature_metric must be square in the feature dimension")
    if not bool(np.isfinite(feature_metric).all()) or not np.allclose(
        feature_metric,
        feature_metric.T,
        rtol=1e-12,
        atol=1e-14,
    ):
        raise ValueError("feature_metric must be finite and symmetric")
    square_root, inverse_square_root, metric_rank = _metric_square_roots(feature_metric)
    mean = np.mean(features, axis=0)
    transformed = (features - mean) @ square_root
    maximum = min(features.shape[0] - 1, metric_rank)
    retained = _component_count(n_components, maximum)
    whitened = principal_component_analysis(
        np.asarray(transformed, dtype=np.float64),
        n_components=retained,
        feature_space=f"{feature_space}:metric-whitened",
        feature_labels=feature_labels,
        sample_labels=sample_labels,
        tie_tolerance=tie_tolerance,
    )
    components = whitened.components @ inverse_square_root
    projection = whitened.components @ square_root
    scores = np.array(whitened.scores, copy=True)
    for index, component in enumerate(components):
        pivot = int(np.argmax(np.abs(component)))
        if component[pivot] < 0:
            components[index] *= -1.0
            projection[index] *= -1.0
            scores[:, index] *= -1.0
    return PCAResult(
        mean=mean,
        components=components,
        projection_components=projection,
        scores=scores,
        singular_values=whitened.singular_values,
        explained_variance=whitened.explained_variance,
        explained_variance_ratio=whitened.explained_variance_ratio,
        total_variance=whitened.total_variance,
        feature_space=feature_space,
        feature_labels=whitened.feature_labels,
        sample_labels=whitened.sample_labels,
        numerical_rank=whitened.numerical_rank,
        tied_component_groups=whitened.tied_component_groups,
        zero_variance_components=whitened.zero_variance_components,
        method=method,
    )


def lddmm_metric_momenta_pca(
    momenta: np.ndarray,
    control_points: np.ndarray,
    *,
    deformation_kernel_width: float,
    n_components: int | None = None,
    subject_labels: tuple[str, ...] | list[str] | None = None,
    tie_tolerance: float = 1e-12,
) -> PCAResult:
    """Fit tangent-momenta PCA using the atlas deformation-kernel inner product."""

    values, controls = _momenta_and_controls(momenta, control_points)
    kernel = gaussian_control_point_kernel(controls, deformation_kernel_width)
    metric = np.kron(kernel, np.eye(3, dtype=np.float64))
    feature_labels = tuple(
        f"momenta:control_point_{point:04d}:{axis}"
        for point in range(values.shape[1])
        for axis in ("x", "y", "z")
    )
    return metric_principal_component_analysis(
        values.reshape(values.shape[0], -1),
        np.asarray(metric, dtype=np.float64),
        n_components=n_components,
        feature_space="subject_initial_momenta_lddmm_deformation_metric",
        method=LDDMM_METRIC_PCA_METHOD,
        feature_labels=feature_labels,
        sample_labels=subject_labels,
        tie_tolerance=tie_tolerance,
    )


def lddmm_momenta_squared_distances(
    momenta: np.ndarray,
    control_points: np.ndarray,
    *,
    deformation_kernel_width: float,
) -> np.ndarray:
    """Return pairwise squared tangent distances induced by the LDDMM kernel."""

    values, controls = _momenta_and_controls(momenta, control_points)
    kernel = gaussian_control_point_kernel(controls, deformation_kernel_width)
    gram = np.einsum("sic,ij,tjc->st", values, kernel, values, optimize=True)
    diagonal = np.diag(gram)
    squared = diagonal[:, None] + diagonal[None, :] - 2.0 * gram
    squared = np.maximum((squared + squared.T) * 0.5, 0.0)
    np.fill_diagonal(squared, 0.0)
    return _readonly(squared)


def _squared_distance_matrix(values: np.ndarray) -> np.ndarray:
    gram = values @ values.T
    diagonal = np.diag(gram)
    result = diagonal[:, None] + diagonal[None, :] - 2.0 * gram
    result = np.maximum((result + result.T) * 0.5, 0.0)
    np.fill_diagonal(result, 0.0)
    return result


def _validate_squared_distances(squared_distances: np.ndarray) -> np.ndarray:
    if not isinstance(squared_distances, np.ndarray) or squared_distances.dtype != np.float64:
        raise TypeError("squared_distances must be a numpy.float64 array")
    if (
        squared_distances.ndim != 2
        or squared_distances.shape[0] < 2
        or squared_distances.shape[0] != squared_distances.shape[1]
    ):
        raise ValueError("squared_distances must be square for at least two samples")
    if not bool(np.isfinite(squared_distances).all()) or float(np.min(squared_distances)) < -1e-12:
        raise ValueError("squared_distances must be finite and nonnegative")
    if not np.allclose(squared_distances, squared_distances.T, rtol=1e-12, atol=1e-14):
        raise ValueError("squared_distances must be symmetric")
    if not np.allclose(np.diag(squared_distances), 0.0, rtol=0.0, atol=1e-12):
        raise ValueError("squared_distances must have a zero diagonal")
    return np.maximum(squared_distances, 0.0)


def median_heuristic_gamma(squared_distances: np.ndarray) -> float:
    """Choose gamma=1/median(nonzero pairwise squared distance)."""

    distances = _validate_squared_distances(squared_distances)
    upper = distances[np.triu_indices(distances.shape[0], 1)]
    positive = upper[upper > 0]
    if positive.size == 0:
        raise ValueError("gamma selection requires at least one nonzero pairwise distance")
    return 1.0 / float(np.median(positive))


@dataclass(frozen=True)
class KernelPCAResult:
    scores: np.ndarray
    eigenvalues: np.ndarray
    explained_variance_ratio: np.ndarray
    centered_kernel: np.ndarray
    gamma: float
    sample_labels: tuple[str, ...]
    numerical_rank: int
    method: str = RBF_KERNEL_PCA_METHOD
    preimage_available: bool = False

    def __post_init__(self) -> None:
        for name in ("scores", "eigenvalues", "explained_variance_ratio", "centered_kernel"):
            object.__setattr__(self, name, _readonly(getattr(self, name)))


def rbf_kernel_pca_from_squared_distances(
    squared_distances: np.ndarray,
    *,
    gamma: float | None = None,
    n_components: int | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
) -> KernelPCAResult:
    """Fit deterministic RBF KernelPCA from declared pairwise squared distances."""

    distances = _validate_squared_distances(squared_distances)
    selected_gamma = median_heuristic_gamma(distances) if gamma is None else _positive_real(
        "gamma", gamma
    )
    kernel = np.exp(-selected_gamma * distances)
    count = kernel.shape[0]
    centering = np.eye(count, dtype=np.float64) - np.full(
        (count, count), 1.0 / count, dtype=np.float64
    )
    centered = (centering @ kernel @ centering + (centering @ kernel @ centering).T) * 0.5
    eigenvalues, eigenvectors = np.linalg.eigh(centered)
    order = np.argsort(eigenvalues, kind="stable")[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    tolerance = count * np.finfo(np.float64).eps * max(float(eigenvalues[0]), 1.0)
    positive = eigenvalues > tolerance
    rank = int(np.count_nonzero(positive))
    positive_total = float(np.sum(eigenvalues[positive]))
    retained = _component_count(n_components, rank)
    eigenvalues = eigenvalues[:retained]
    eigenvectors = eigenvectors[:, :retained]
    scores = eigenvectors * np.sqrt(eigenvalues)
    for index in range(retained):
        pivot = int(np.argmax(np.abs(scores[:, index])))
        if scores[pivot, index] < 0:
            scores[:, index] *= -1.0
    labels = (
        tuple(f"sample_{index:04d}" for index in range(count))
        if sample_labels is None
        else tuple(sample_labels)
    )
    if len(labels) != count or len(set(labels)) != count or any(not label for label in labels):
        raise ValueError("sample_labels must contain one unique non-empty label per sample")
    return KernelPCAResult(
        scores=scores,
        eigenvalues=eigenvalues,
        explained_variance_ratio=eigenvalues / positive_total,
        centered_kernel=centered,
        gamma=selected_gamma,
        sample_labels=labels,
        numerical_rank=rank,
    )


def rbf_kernel_pca(
    features: np.ndarray,
    *,
    gamma: float | None = None,
    n_components: int | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
) -> KernelPCAResult:
    """Fit generic RBF KernelPCA to finite float64 feature rows."""

    if not isinstance(features, np.ndarray) or features.dtype != np.float64:
        raise TypeError("features must be a numpy.float64 array")
    if features.ndim != 2 or features.shape[0] < 2 or features.shape[1] < 1:
        raise ValueError("features must have shape (samples >= 2, features >= 1)")
    if not bool(np.isfinite(features).all()):
        raise ValueError("features must contain only finite values")
    return rbf_kernel_pca_from_squared_distances(
        np.asarray(_squared_distance_matrix(features), dtype=np.float64),
        gamma=gamma,
        n_components=n_components,
        sample_labels=sample_labels,
    )


@dataclass(frozen=True)
class OrdinationResult:
    coordinates: np.ndarray
    eigenvalues: np.ndarray
    explained_positive_ratio: np.ndarray
    sample_labels: tuple[str, ...]
    method: str
    negative_eigenvalue_sum: float = 0.0

    def __post_init__(self) -> None:
        for name in ("coordinates", "eigenvalues", "explained_positive_ratio"):
            object.__setattr__(self, name, _readonly(getattr(self, name)))


def principal_coordinates_analysis(
    squared_distances: np.ndarray,
    *,
    n_components: int | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
    method: str = TANGENT_PCOA_METHOD,
) -> OrdinationResult:
    """Classical metric MDS/PCoA with explicit negative-eigenvalue reporting."""

    distances = _validate_squared_distances(squared_distances)
    count = distances.shape[0]
    centering = np.eye(count, dtype=np.float64) - np.full(
        (count, count), 1.0 / count, dtype=np.float64
    )
    gram = -0.5 * centering @ distances @ centering
    gram = (gram + gram.T) * 0.5
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    order = np.argsort(eigenvalues, kind="stable")[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    tolerance = count * np.finfo(np.float64).eps * max(float(abs(eigenvalues[0])), 1.0)
    positive = eigenvalues > tolerance
    rank = int(np.count_nonzero(positive))
    retained = _component_count(n_components, rank)
    selected = eigenvalues[:retained]
    coordinates = eigenvectors[:, :retained] * np.sqrt(selected)
    for index in range(retained):
        pivot = int(np.argmax(np.abs(coordinates[:, index])))
        if coordinates[pivot, index] < 0:
            coordinates[:, index] *= -1.0
    labels = (
        tuple(f"sample_{index:04d}" for index in range(count))
        if sample_labels is None
        else tuple(sample_labels)
    )
    if len(labels) != count or len(set(labels)) != count or any(not label for label in labels):
        raise ValueError("sample_labels must contain one unique non-empty label per sample")
    positive_total = float(np.sum(eigenvalues[eigenvalues > tolerance]))
    negative_sum = float(np.sum(np.abs(eigenvalues[eigenvalues < -tolerance])))
    return OrdinationResult(
        coordinates=coordinates,
        eigenvalues=selected,
        explained_positive_ratio=selected / positive_total,
        sample_labels=labels,
        method=method,
        negative_eigenvalue_sum=negative_sum,
    )


def isomap_from_squared_distances(
    squared_distances: np.ndarray,
    *,
    n_neighbors: int,
    n_components: int | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
) -> OrdinationResult:
    """Deterministic Isomap using a symmetric k-nearest graph and Floyd-Warshall."""

    squared = _validate_squared_distances(squared_distances)
    count = squared.shape[0]
    if isinstance(n_neighbors, bool) or not isinstance(n_neighbors, Integral):
        raise TypeError("n_neighbors must be an integer")
    neighbors = int(n_neighbors)
    if neighbors < 1 or neighbors >= count:
        raise ValueError(f"n_neighbors must be between 1 and {count - 1}")
    distances = np.sqrt(squared)
    graph = np.full((count, count), np.inf, dtype=np.float64)
    np.fill_diagonal(graph, 0.0)
    for row in range(count):
        order = np.argsort(distances[row], kind="stable")
        for column in order[1 : neighbors + 1]:
            graph[row, column] = distances[row, column]
            graph[column, row] = distances[row, column]
    for pivot in range(count):
        graph = np.minimum(graph, graph[:, pivot, None] + graph[None, pivot, :])
    if not bool(np.isfinite(graph).all()):
        raise ValueError("the Isomap neighbor graph is disconnected")
    return principal_coordinates_analysis(
        np.asarray(graph * graph, dtype=np.float64),
        n_components=n_components,
        sample_labels=sample_labels,
        method=ISOMAP_METHOD,
    )


def diffusion_map_from_squared_distances(
    squared_distances: np.ndarray,
    *,
    epsilon: float | None = None,
    alpha: float = 0.5,
    diffusion_time: int = 1,
    n_components: int | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
) -> OrdinationResult:
    """Deterministic anisotropic diffusion-map coordinates."""

    squared = _validate_squared_distances(squared_distances)
    bandwidth = (
        1.0 / median_heuristic_gamma(squared)
        if epsilon is None
        else _positive_real("epsilon", epsilon)
    )
    if isinstance(alpha, bool) or not isinstance(alpha, Real):
        raise TypeError("alpha must be a real scalar")
    normalized_alpha = float(alpha)
    if not math.isfinite(normalized_alpha) or not 0.0 <= normalized_alpha <= 1.0:
        raise ValueError("alpha must be finite and between 0 and 1")
    if isinstance(diffusion_time, bool) or not isinstance(diffusion_time, Integral):
        raise TypeError("diffusion_time must be an integer")
    time = int(diffusion_time)
    if time < 1:
        raise ValueError("diffusion_time must be at least 1")
    affinity = np.exp(-squared / bandwidth)
    density = np.sum(affinity, axis=1)
    anisotropic = affinity / (
        density[:, None] ** normalized_alpha * density[None, :] ** normalized_alpha
    )
    degree = np.sum(anisotropic, axis=1)
    symmetric = anisotropic / np.sqrt(degree[:, None] * degree[None, :])
    eigenvalues, eigenvectors = np.linalg.eigh((symmetric + symmetric.T) * 0.5)
    order = np.argsort(eigenvalues, kind="stable")[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    nontrivial_values = eigenvalues[1:]
    nontrivial_vectors = eigenvectors[:, 1:] / np.sqrt(degree[:, None])
    tolerance = squared.shape[0] * np.finfo(np.float64).eps
    usable = np.abs(nontrivial_values) > tolerance
    rank = int(np.count_nonzero(usable))
    retained = _component_count(n_components, rank)
    selected = nontrivial_values[:retained]
    coordinates = nontrivial_vectors[:, :retained] * (selected**time)
    for index in range(retained):
        pivot = int(np.argmax(np.abs(coordinates[:, index])))
        if coordinates[pivot, index] < 0:
            coordinates[:, index] *= -1.0
    labels = (
        tuple(f"sample_{index:04d}" for index in range(squared.shape[0]))
        if sample_labels is None
        else tuple(sample_labels)
    )
    if len(labels) != squared.shape[0] or len(set(labels)) != len(labels):
        raise ValueError("sample_labels must contain one unique label per sample")
    weights = np.abs(selected)
    return OrdinationResult(
        coordinates=coordinates,
        eigenvalues=selected,
        explained_positive_ratio=weights / float(np.sum(weights)),
        sample_labels=labels,
        method=DIFFUSION_MAP_METHOD,
        negative_eigenvalue_sum=0.0,
    )
