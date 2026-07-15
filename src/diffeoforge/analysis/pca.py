"""Deterministic PCA for explicitly declared atlas-derived feature spaces."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, dtype=np.float64, copy=True)
    result.setflags(write=False)
    return result


def _labels(
    name: str,
    values: tuple[str, ...] | list[str] | None,
    count: int,
    *,
    prefix: str,
) -> tuple[str, ...]:
    if values is None:
        return tuple(f"{prefix}_{index:04d}" for index in range(count))
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list of strings")
    normalized = tuple(values)
    if len(normalized) != count:
        raise ValueError(f"{name} must contain exactly {count} labels")
    if any(not isinstance(value, str) or not value.strip() for value in normalized):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must contain unique labels")
    return normalized


def _feature_matrix(
    values: np.ndarray,
    *,
    name: str = "features",
    minimum_samples: int = 2,
) -> np.ndarray:
    if not isinstance(values, np.ndarray):
        raise TypeError(f"{name} must be a numpy.ndarray")
    if values.dtype != np.float64:
        raise TypeError(f"{name} must use numpy.float64")
    if values.ndim != 2:
        raise ValueError(f"{name} must have shape (samples, features)")
    if values.shape[0] < minimum_samples:
        raise ValueError(f"{name} must contain at least {minimum_samples} samples")
    if values.shape[1] < 1:
        raise ValueError(f"{name} must contain at least one feature")
    if not bool(np.isfinite(values).all()):
        raise ValueError(f"{name} must contain only finite values")
    return values


def _nonnegative_real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return normalized


@dataclass(frozen=True)
class PCAResult:
    """PCA products with declared sample/feature identity and spectral warnings."""

    mean: np.ndarray
    components: np.ndarray
    scores: np.ndarray
    singular_values: np.ndarray
    explained_variance: np.ndarray
    explained_variance_ratio: np.ndarray
    total_variance: float
    feature_space: str
    feature_labels: tuple[str, ...]
    sample_labels: tuple[str, ...]
    numerical_rank: int
    tied_component_groups: tuple[tuple[int, ...], ...]
    zero_variance_components: tuple[int, ...]
    sign_convention: str = "largest-absolute loading is positive; ties use lowest feature index"

    def __post_init__(self) -> None:
        for name in (
            "mean",
            "components",
            "scores",
            "singular_values",
            "explained_variance",
            "explained_variance_ratio",
        ):
            object.__setattr__(self, name, _readonly(getattr(self, name)))

    @property
    def number_of_components(self) -> int:
        return self.components.shape[0]

    def transform(self, features: np.ndarray) -> np.ndarray:
        """Project samples in the same declared feature order."""

        values = _feature_matrix(features, minimum_samples=1)
        if values.shape[1] != self.mean.shape[0]:
            raise ValueError(
                f"features must contain exactly {self.mean.shape[0]} columns in stored order"
            )
        return (values - self.mean) @ self.components.T

    def inverse_transform(self, scores: np.ndarray) -> np.ndarray:
        """Reconstruct feature rows from retained PCA scores."""

        if not isinstance(scores, np.ndarray):
            raise TypeError("scores must be a numpy.ndarray")
        if scores.dtype != np.float64:
            raise TypeError("scores must use numpy.float64")
        if scores.ndim != 2 or scores.shape[1] != self.number_of_components:
            raise ValueError(
                f"scores must have shape (samples, {self.number_of_components})"
            )
        if not bool(np.isfinite(scores).all()):
            raise ValueError("scores must contain only finite values")
        return scores @ self.components + self.mean

    def reconstruct_training_data(self) -> np.ndarray:
        """Reconstruct the fitted samples from the retained components."""

        return self.inverse_transform(self.scores)


def principal_component_analysis(
    features: np.ndarray,
    *,
    n_components: int | None = None,
    feature_space: str,
    feature_labels: tuple[str, ...] | list[str] | None = None,
    sample_labels: tuple[str, ...] | list[str] | None = None,
    tie_tolerance: float = 1e-12,
) -> PCAResult:
    """Fit centered float64 PCA using SVD and a deterministic sign convention."""

    values = _feature_matrix(features)
    if not isinstance(feature_space, str) or not feature_space.strip():
        raise ValueError("feature_space must be a non-empty string")
    normalized_feature_labels = _labels(
        "feature_labels", feature_labels, values.shape[1], prefix="feature"
    )
    normalized_sample_labels = _labels(
        "sample_labels", sample_labels, values.shape[0], prefix="sample"
    )
    tie_threshold = _nonnegative_real("tie_tolerance", tie_tolerance)
    maximum_components = min(values.shape[0] - 1, values.shape[1])
    if n_components is None:
        retained_components = maximum_components
    else:
        if isinstance(n_components, bool) or not isinstance(n_components, Integral):
            raise TypeError("n_components must be an integer")
        retained_components = int(n_components)
        if retained_components < 1 or retained_components > maximum_components:
            raise ValueError(f"n_components must be between 1 and {maximum_components}")

    mean = np.mean(values, axis=0)
    centered = values - mean
    _, all_singular_values, all_components = np.linalg.svd(
        centered,
        full_matrices=False,
    )
    variance_denominator = values.shape[0] - 1
    all_explained_variance = all_singular_values**2 / variance_denominator
    total_variance = float(np.sum(all_explained_variance))
    if not math.isfinite(total_variance) or total_variance <= 0:
        raise ValueError("features must contain positive total sample variance")

    singular_values = all_singular_values[:retained_components].copy()
    components = all_components[:retained_components].copy()
    scores = centered @ components.T
    for index, component in enumerate(components):
        pivot = int(np.argmax(np.abs(component)))
        if component[pivot] < 0:
            components[index] *= -1.0
            scores[:, index] *= -1.0

    explained_variance = singular_values**2 / variance_denominator
    explained_variance_ratio = explained_variance / total_variance
    rank_threshold = (
        max(values.shape) * np.finfo(np.float64).eps * float(all_singular_values[0])
    )
    numerical_rank = int(np.count_nonzero(all_singular_values > rank_threshold))
    zero_variance_components = tuple(
        index for index, value in enumerate(singular_values) if value <= rank_threshold
    )
    tied_groups: list[tuple[int, ...]] = []
    group = [0]
    for index in range(1, retained_components):
        scale = max(float(singular_values[index - 1]), float(singular_values[index]), 1.0)
        if abs(float(singular_values[index - 1] - singular_values[index])) <= (
            tie_threshold * scale
        ):
            group.append(index)
        else:
            if len(group) > 1:
                tied_groups.append(tuple(group))
            group = [index]
    if len(group) > 1:
        tied_groups.append(tuple(group))

    return PCAResult(
        mean=mean,
        components=components,
        scores=scores,
        singular_values=singular_values,
        explained_variance=explained_variance,
        explained_variance_ratio=explained_variance_ratio,
        total_variance=total_variance,
        feature_space=feature_space.strip(),
        feature_labels=normalized_feature_labels,
        sample_labels=normalized_sample_labels,
        numerical_rank=numerical_rank,
        tied_component_groups=tuple(tied_groups),
        zero_variance_components=zero_variance_components,
    )


def momenta_pca(
    momenta: np.ndarray,
    *,
    n_components: int | None = None,
    subject_labels: tuple[str, ...] | list[str] | None = None,
    control_point_labels: tuple[str, ...] | list[str] | None = None,
    tie_tolerance: float = 1e-12,
) -> PCAResult:
    """Fit PCA to subject momenta flattened in control-point then x/y/z order."""

    if not isinstance(momenta, np.ndarray):
        raise TypeError("momenta must be a numpy.ndarray")
    if momenta.dtype != np.float64:
        raise TypeError("momenta must use numpy.float64")
    if momenta.ndim != 3 or momenta.shape[2] != 3:
        raise ValueError("momenta must have shape (subjects, control_points, 3)")
    if momenta.shape[0] < 2:
        raise ValueError("momenta must contain at least two subjects")
    if momenta.shape[1] < 1:
        raise ValueError("momenta must contain at least one control point")
    if not bool(np.isfinite(momenta).all()):
        raise ValueError("momenta must contain only finite values")
    point_labels = _labels(
        "control_point_labels",
        control_point_labels,
        momenta.shape[1],
        prefix="control_point",
    )
    feature_labels = tuple(
        f"momenta:{point_label}:{axis}"
        for point_label in point_labels
        for axis in ("x", "y", "z")
    )
    return principal_component_analysis(
        momenta.reshape(momenta.shape[0], -1),
        n_components=n_components,
        feature_space="subject_initial_momenta_cartesian",
        feature_labels=feature_labels,
        sample_labels=subject_labels,
        tie_tolerance=tie_tolerance,
    )
