"""Descriptive comparison of a declared group contrast in two saved PCAs."""

from __future__ import annotations

from numbers import Integral

import numpy as np

from diffeoforge.analysis.pca import PCAResult
from diffeoforge.analysis.pca_stability import _correlation, _rankdata


def _labels(values: tuple[str, ...], name: str, minimum: int) -> set[str]:
    if (
        not isinstance(values, (tuple, list))
        or len(values) < minimum
        or any(not isinstance(v, str) or not v.strip() for v in values)
    ):
        raise ValueError(f"{name} must contain at least {minimum} nonempty specimen labels")
    names = set(values)
    if len(names) != len(values):
        raise ValueError(f"{name} must contain unique specimen labels")
    return names


def _full_scores(pca: PCAResult, order: tuple[str, ...]) -> np.ndarray:
    rank = pca.numerical_rank
    scores = pca.scores
    if (
        isinstance(rank, bool)
        or not isinstance(rank, Integral)
        or rank < 0
        or rank >= len(pca.sample_labels)
        or scores.shape != (len(pca.sample_labels), pca.number_of_components)
        or rank > scores.shape[1]
        or any(index < rank for index in pca.zero_variance_components)
    ):
        raise ValueError("Each PCA must retain scores for its full numerical rank")
    if not np.isfinite(scores).all():
        raise ValueError("PCA scores must be finite")
    indices = {label: index for index, label in enumerate(pca.sample_labels)}
    aligned = scores[[indices[label] for label in order], :rank]
    # The comparisons are scale-free. Rescale before squaring to avoid overflow.
    scale = float(np.max(np.abs(aligned), initial=0.0))
    return aligned / scale if scale > 0.0 else aligned


def _fraction(part: float, total: float) -> float | None:
    return min(1.0, max(0.0, part / total)) if total > 0.0 else None


def _group_summary(scores: np.ndarray, reference_count: int) -> dict:
    reference, comparison = scores[:reference_count], scores[reference_count:]
    centroid_delta_squared = np.square(reference.mean(axis=0) - comparison.mean(axis=0))
    sum_squares_by_axis = np.square(scores - scores.mean(axis=0)).sum(axis=0)
    group_weight = len(reference) * len(comparison) / len(scores)
    projected_gap = float(centroid_delta_squared[:2].sum())
    full_gap = float(centroid_delta_squared.sum())
    projected_variance = float(sum_squares_by_axis[:2].sum())
    full_variance = float(sum_squares_by_axis.sum())
    return {
        "numerical_rank": scores.shape[1],
        "pc1_pc2_component_count": min(2, scores.shape[1]),
        "full_group_variance_fraction": _fraction(group_weight * full_gap, full_variance),
        "pc1_pc2_group_variance_fraction": _fraction(
            group_weight * projected_gap, projected_variance
        ),
        "pc1_pc2_fraction_of_full_centroid_gap_squared": _fraction(projected_gap, full_gap),
        "pc1_pc2_fraction_of_full_selected_variance": _fraction(projected_variance, full_variance),
    }


def _distance_ranks(scores: np.ndarray) -> np.ndarray:
    count = len(scores)
    distances = np.empty(count * (count - 1) // 2)
    offset = 0
    for index in range(count - 1):
        block = np.linalg.norm(scores[index + 1 :] - scores[index], axis=1)
        distances[offset : offset + len(block)] = block
        offset += len(block)
    max_distance = distances.max()
    if max_distance > 0:
        distances /= max_distance
    return _rankdata(distances)


def _distance_rank_correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    try:
        value = _correlation(_distance_ranks(first), _distance_ranks(second))
    except ValueError:
        # Spearman correlation is undefined when all paired distances are tied.
        return None
    return min(1.0, max(-1.0, value))


def _largest_rank_changes(labels, first, second):
    """Locate changes that a high cohort-wide correlation can conceal."""
    changes = []
    for index, label in enumerate(labels):
        keep = np.arange(len(labels)) != index
        ranks = []
        for matrix in (first, second):
            distances = np.linalg.norm(matrix[keep] - matrix[index], axis=1)
            scale = distances.max()
            ranks.append(_rankdata(distances / scale if scale > 0 else distances))
        shift = float(np.mean(np.abs(ranks[0] - ranks[1])))
        changes.append({"specimen": label, "mean_rank_change": shift})
    return sorted(changes, key=lambda row: (-row["mean_rank_change"], row["specimen"]))[:5]


def compare_group_scores(
    first_pca: PCAResult,
    second_pca: PCAResult,
    reference_ids: tuple[str, ...],
    comparison_ids: tuple[str, ...],
) -> dict:
    """Compare scale-free group separation and matched distance ranks by PCA geometry.

    Group metrics use the two declared groups. Distance correlations use all
    matched specimens. Each atlas retains its own geometry and PCA basis.
    """
    if not isinstance(first_pca, PCAResult) or not isinstance(second_pca, PCAResult):
        raise TypeError("Two PCAResult objects are required")
    if (
        not isinstance(first_pca.feature_space, str)
        or not first_pca.feature_space.strip()
        or first_pca.feature_space != second_pca.feature_space
    ):
        raise ValueError("The two PCAs must declare the same type of feature space")
    labels = _labels(first_pca.sample_labels, "First PCA", 4)
    if labels != _labels(second_pca.sample_labels, "Second PCA", 4):
        raise ValueError("The two PCAs must contain exactly the same specimen labels")
    reference = _labels(reference_ids, "Reference group", 2)
    comparison = _labels(comparison_ids, "Comparison group", 2)
    if reference & comparison:
        raise ValueError("The two groups must have disjoint specimen labels")
    selected = reference | comparison
    if not selected <= labels:
        raise ValueError("Group labels must match specimens in both PCAs")

    unassigned = labels - selected
    order = (*sorted(reference), *sorted(comparison), *sorted(unassigned))
    first = _full_scores(first_pca, order)
    second = _full_scores(second_pca, order)
    return {
        "feature_space": first_pca.feature_space,
        "basis_relation": (
            "matching_declared_features"
            if set(first_pca.feature_labels) == set(second_pca.feature_labels)
            else "different_declared_features"
        ),
        "sample_count": len(labels),
        "reference_count": len(reference),
        "comparison_count": len(comparison),
        "unassigned_count": len(unassigned),
        "first": _group_summary(first[: len(selected)], len(reference)),
        "second": _group_summary(second[: len(selected)], len(reference)),
        "largest_subject_distance_rank_changes": _largest_rank_changes(order, first, second),
        "full_pairwise_distance_rank_correlation": _distance_rank_correlation(first, second),
        "pc1_pc2_pairwise_distance_rank_correlation": _distance_rank_correlation(
            first[:, :2], second[:, :2]
        ),
        "scientific_boundary": (
            "Group separation and specimen distances are descriptive within each atlas model. "
            "Matching feature labels may refer to different control-point coordinates. "
            "Independent anatomical evidence is needed to identify the regions involved. "
            "Reusing a cohort measures sensitivity to the atlas analysis."
        ),
    }
