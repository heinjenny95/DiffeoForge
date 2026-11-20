from dataclasses import replace
from itertools import product

import numpy as np
import pytest

from diffeoforge.analysis.atlas_group_scores import compare_group_scores
from diffeoforge.analysis.pca import principal_component_analysis

LABELS = tuple(f"case-{i}" for i in range(8))
REFERENCE = LABELS[::2]
COMPARISON = LABELS[1::2]
FEATURES = np.asarray(tuple(product((-10.0, 10.0), (-5.0, 5.0), (-1.0, 1.0))))


def _pca(features=FEATURES, labels=LABELS, **kwargs):
    return principal_component_analysis(
        features, sample_labels=labels, feature_space="common-test-space", **kwargs
    )


def test_full_score_relationships_survive_reordering_rotation_and_scale():
    first = _pca()
    rotation, _ = np.linalg.qr(np.random.default_rng(481).normal(size=(3, 3)))
    second = _pca(4.0 * FEATURES[::-1] @ rotation, LABELS[::-1])
    report = compare_group_scores(first, second, REFERENCE, COMPARISON)

    assert report["full_pairwise_distance_rank_correlation"] == pytest.approx(1.0)
    assert report["pc1_pc2_pairwise_distance_rank_correlation"] == pytest.approx(1.0)
    for summary in (report["first"], report["second"]):
        assert summary["full_group_variance_fraction"] == pytest.approx(1 / 126)
        assert summary["pc1_pc2_fraction_of_full_centroid_gap_squared"] == pytest.approx(0)
        assert summary["pc1_pc2_fraction_of_full_selected_variance"] == pytest.approx(125 / 126)


def test_pc1_pc2_can_hide_or_show_the_group_difference():
    first = _pca()
    second = _pca(
        FEATURES * np.asarray([1.0, 1.0, 20.0]), feature_labels=("x", "y", "z")
    )
    report = compare_group_scores(first, second, REFERENCE, COMPARISON)

    assert report["basis_relation"] == "different_declared_features"
    assert report["first"]["pc1_pc2_group_variance_fraction"] == pytest.approx(0)
    assert report["second"]["pc1_pc2_group_variance_fraction"] == pytest.approx(400 / 500)
    assert report["second"]["full_group_variance_fraction"] == pytest.approx(400 / 525)
    assert report["second"]["pc1_pc2_fraction_of_full_centroid_gap_squared"] == pytest.approx(1)
    assert report["full_pairwise_distance_rank_correlation"] < 1


def test_no_variation_in_declared_groups_is_reported_as_unavailable():
    scores = np.asarray([[0.0], [0.0], [0.0], [0.0], [-5.0], [5.0]])
    pca = _pca(scores, LABELS[:6])
    report = compare_group_scores(pca, pca, LABELS[:2], LABELS[2:4])

    assert report["unassigned_count"] == 2
    assert report["first"]["pc1_pc2_component_count"] == 1
    assert report["first"]["full_group_variance_fraction"] is None
    assert report["first"]["pc1_pc2_fraction_of_full_centroid_gap_squared"] is None
    assert report["full_pairwise_distance_rank_correlation"] == pytest.approx(1)


def test_equal_distances_do_not_get_a_fabricated_rank_correlation():
    pca = _pca(np.eye(4, dtype=np.float64), LABELS[:4])
    report = compare_group_scores(pca, pca, LABELS[:2], LABELS[2:4])

    assert report["full_pairwise_distance_rank_correlation"] is None


@pytest.mark.parametrize(
    "alter, message",
    [
        (lambda pca: _pca(n_components=2), "full numerical rank"),
        (lambda pca: replace(pca, feature_space="other"), "same type of feature space"),
        (lambda pca: replace(pca, sample_labels=("other", *LABELS[1:])), "exactly the same"),
        (lambda pca: replace(pca, scores=pca.scores * np.nan), "finite"),
    ],
)
def test_pairing_incompatible_or_incomplete_pca_fails(alter, message):
    first = _pca()
    with pytest.raises(ValueError, match=message):
        compare_group_scores(first, alter(first), REFERENCE, COMPARISON)
