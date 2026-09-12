"""Sign- and rotation-invariant stability evidence for paired PCA results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np

from diffeoforge.analysis.pca import PCAResult

PCA_STABILITY_VERSION = "0.1"


def _unit_interval(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 < normalized <= 1:
        raise ValueError(f"{name} must be finite and in (0, 1]")
    return normalized


def _selected_component_count(
    pca: PCAResult,
    *,
    variance_target: float,
    component_count: int | None,
) -> int:
    if component_count is not None:
        if isinstance(component_count, bool) or not isinstance(component_count, Integral):
            raise TypeError("component_count must be an integer")
        selected = int(component_count)
        if selected < 1 or selected > pca.number_of_components:
            raise ValueError(
                "component_count exceeds the components retained by one PCA result"
            )
    else:
        cumulative = np.cumsum(pca.explained_variance_ratio)
        reached = np.flatnonzero(cumulative >= variance_target - 1e-15)
        if reached.size == 0:
            raise ValueError(
                "one PCA result does not retain enough components to reach the "
                "declared variance_target"
            )
        selected = int(reached[0]) + 1
    if selected > pca.numerical_rank:
        raise ValueError("selected PCA components exceed one result's numerical rank")
    if any(index < selected for index in pca.zero_variance_components):
        raise ValueError("selected PCA components include a zero-variance direction")
    return selected


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    position = 0
    while position < values.size:
        end = position + 1
        while end < values.size and math.isclose(
            float(values[order[end]]),
            float(values[order[position]]),
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            end += 1
        ranks[order[position:end]] = 0.5 * (position + end - 1) + 1.0
        position = end
    return ranks


def _pairwise_distances(values: np.ndarray) -> np.ndarray:
    rows, columns = np.triu_indices(values.shape[0], k=1)
    return np.linalg.norm(values[rows] - values[columns], axis=1)


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    centered_left = left - np.mean(left)
    centered_right = right - np.mean(right)
    denominator = float(
        np.linalg.norm(centered_left) * np.linalg.norm(centered_right)
    )
    if denominator <= np.finfo(np.float64).eps:
        raise ValueError("paired PCA score distances contain no comparable variation")
    return float(np.dot(centered_left, centered_right) / denominator)


def _linear_cka(left: np.ndarray, right: np.ndarray) -> float:
    centered_left = left - np.mean(left, axis=0, keepdims=True)
    centered_right = right - np.mean(right, axis=0, keepdims=True)
    cross = centered_left.T @ centered_right
    left_gram = centered_left.T @ centered_left
    right_gram = centered_right.T @ centered_right
    denominator = float(np.linalg.norm(left_gram) * np.linalg.norm(right_gram))
    if denominator <= np.finfo(np.float64).eps:
        raise ValueError("paired PCA scores contain no comparable variation")
    value = float(np.linalg.norm(cross) ** 2 / denominator)
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class PCAStabilityEvidence:
    """Paired numerical evidence without a biological-validity claim."""

    version: str
    sample_labels: tuple[str, ...]
    selection_rule: str
    variance_target: float
    reference_component_count: int
    comparison_component_count: int
    reference_retained_variance: float
    comparison_retained_variance: float
    score_linear_cka: float
    score_distance_rank_correlation: float
    feature_subspace_available: bool
    feature_subspace_unavailable_reason: str | None
    principal_angles_degrees: tuple[float, ...]
    minimum_principal_cosine: float | None
    rms_principal_sine: float | None
    limitations: tuple[str, ...]

    def as_manifest(self) -> dict[str, object]:
        return {
            "version": self.version,
            "sample_labels": list(self.sample_labels),
            "selection_rule": self.selection_rule,
            "variance_target": self.variance_target,
            "reference_component_count": self.reference_component_count,
            "comparison_component_count": self.comparison_component_count,
            "reference_retained_variance": self.reference_retained_variance,
            "comparison_retained_variance": self.comparison_retained_variance,
            "score_linear_cka": self.score_linear_cka,
            "score_distance_rank_correlation": self.score_distance_rank_correlation,
            "feature_subspace_available": self.feature_subspace_available,
            "feature_subspace_unavailable_reason": (
                self.feature_subspace_unavailable_reason
            ),
            "principal_angles_degrees": list(self.principal_angles_degrees),
            "minimum_principal_cosine": self.minimum_principal_cosine,
            "rms_principal_sine": self.rms_principal_sine,
            "limitations": list(self.limitations),
        }


def compare_pca_stability(
    reference: PCAResult,
    comparison: PCAResult,
    *,
    variance_target: float = 0.90,
    component_count: int | None = None,
) -> PCAStabilityEvidence:
    """Compare paired PCA structure without depending on PC signs or rotations.

    Score evidence uses the same named specimens but permits different feature
    dimensions. Direct principal angles are emitted only for identical named
    feature spaces and equal selected subspace dimensions.
    """

    if not isinstance(reference, PCAResult) or not isinstance(comparison, PCAResult):
        raise TypeError("reference and comparison must be PCAResult instances")
    target = _unit_interval("variance_target", variance_target)
    if len(reference.sample_labels) < 3 or len(comparison.sample_labels) < 3:
        raise ValueError("PCA stability requires at least three paired samples")
    if set(reference.sample_labels) != set(comparison.sample_labels):
        raise ValueError("PCA results must contain exactly the same sample labels")
    comparison_sample_index = {
        label: index for index, label in enumerate(comparison.sample_labels)
    }
    comparison_order = np.asarray(
        [comparison_sample_index[label] for label in reference.sample_labels],
        dtype=np.int64,
    )
    reference_count = _selected_component_count(
        reference,
        variance_target=target,
        component_count=component_count,
    )
    comparison_count = _selected_component_count(
        comparison,
        variance_target=target,
        component_count=component_count,
    )
    reference_scores = reference.scores[:, :reference_count]
    comparison_scores = comparison.scores[comparison_order, :comparison_count]
    cka = _linear_cka(reference_scores, comparison_scores)
    distance_correlation = _correlation(
        _rankdata(_pairwise_distances(reference_scores)),
        _rankdata(_pairwise_distances(comparison_scores)),
    )

    feature_reason: str | None = None
    principal_angles: tuple[float, ...] = ()
    minimum_cosine: float | None = None
    rms_sine: float | None = None
    if reference.feature_space != comparison.feature_space:
        feature_reason = "PCA feature-space declarations differ"
    elif set(reference.feature_labels) != set(comparison.feature_labels):
        feature_reason = "PCA feature identities differ"
    elif reference_count != comparison_count:
        feature_reason = (
            "variance-target selection retained different subspace dimensions"
        )
    else:
        comparison_feature_index = {
            label: index for index, label in enumerate(comparison.feature_labels)
        }
        feature_order = np.asarray(
            [comparison_feature_index[label] for label in reference.feature_labels],
            dtype=np.int64,
        )
        left = reference.components[:reference_count]
        right = comparison.components[:comparison_count, feature_order]
        singular_values = np.linalg.svd(left @ right.T, compute_uv=False)
        cosines = np.clip(singular_values, 0.0, 1.0)
        cosines[np.isclose(cosines, 1.0, rtol=0.0, atol=1e-12)] = 1.0
        principal_angles = tuple(
            float(value) for value in np.degrees(np.arccos(cosines))
        )
        minimum_cosine = float(np.min(cosines))
        rms_sine = float(np.sqrt(np.mean(1.0 - cosines**2)))

    selection_rule = (
        f"first {component_count} components"
        if component_count is not None
        else f"minimum components reaching {target:.6g} cumulative variance per PCA"
    )
    return PCAStabilityEvidence(
        version=PCA_STABILITY_VERSION,
        sample_labels=reference.sample_labels,
        selection_rule=selection_rule,
        variance_target=target,
        reference_component_count=reference_count,
        comparison_component_count=comparison_count,
        reference_retained_variance=float(
            np.sum(reference.explained_variance_ratio[:reference_count])
        ),
        comparison_retained_variance=float(
            np.sum(comparison.explained_variance_ratio[:comparison_count])
        ),
        score_linear_cka=cka,
        score_distance_rank_correlation=distance_correlation,
        feature_subspace_available=feature_reason is None,
        feature_subspace_unavailable_reason=feature_reason,
        principal_angles_degrees=principal_angles,
        minimum_principal_cosine=minimum_cosine,
        rms_principal_sine=rms_sine,
        limitations=(
            "PCA stability describes reproducibility of the fitted numerical shape "
            "structure; it does not establish biological meaning or group separation.",
            "Linear CKA is invariant to orthogonal score rotations and isotropic "
            "scaling; distance-rank correlation is additionally insensitive to "
            "monotone changes in pairwise distance scale.",
            "Principal angles are withheld unless named feature identity and selected "
            "subspace dimension are shared exactly.",
        ),
    )
