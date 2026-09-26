from __future__ import annotations

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
analysis = pytest.importorskip("diffeoforge.analysis")

compare_pca_stability = analysis.compare_pca_stability
principal_component_analysis = analysis.principal_component_analysis


def _features() -> np.ndarray:
    return np.array(
        [
            [2.0, -1.0, 0.5, 1.2],
            [0.0, 1.0, 1.5, -0.3],
            [-1.0, 0.5, -0.5, 2.1],
            [3.0, 2.0, 0.0, 0.4],
            [1.0, -2.0, 2.0, -1.4],
            [-2.0, 1.3, 0.8, 0.2],
            [0.4, -0.7, -1.6, 1.7],
            [1.8, 0.2, 0.9, -2.0],
        ],
        dtype=np.float64,
    )


def _pca(features: np.ndarray | None = None):
    return principal_component_analysis(
        _features() if features is None else features,
        feature_space="declared-shape-space",
        feature_labels=["a", "b", "c", "d"],
        sample_labels=[f"specimen-{index}" for index in range(8)],
    )


def test_pca_stability_is_invariant_to_component_sign_and_rotation() -> None:
    reference = _pca()
    angle = np.deg2rad(37.0)
    rotation = np.eye(reference.number_of_components, dtype=np.float64)
    rotation[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    comparison = replace(
        reference,
        components=rotation @ reference.components,
        scores=reference.scores @ rotation.T,
    )

    evidence = compare_pca_stability(
        reference,
        comparison,
        component_count=reference.number_of_components,
    )

    assert evidence.score_linear_cka == pytest.approx(1.0, abs=1e-14)
    assert evidence.score_distance_rank_correlation == pytest.approx(1.0, abs=1e-14)
    assert evidence.minimum_principal_cosine == pytest.approx(1.0, abs=1e-14)
    assert evidence.rms_principal_sine == pytest.approx(0.0, abs=2e-8)
    assert max(evidence.principal_angles_degrees) < 2e-6


def test_pca_stability_pairs_reordered_samples_and_features_by_identity() -> None:
    reference = _pca()
    sample_order = np.asarray([4, 1, 7, 0, 6, 2, 5, 3])
    feature_order = np.asarray([2, 0, 3, 1])
    comparison = replace(
        reference,
        scores=reference.scores[sample_order],
        sample_labels=tuple(reference.sample_labels[index] for index in sample_order),
        components=reference.components[:, feature_order],
        feature_labels=tuple(reference.feature_labels[index] for index in feature_order),
    )

    evidence = compare_pca_stability(reference, comparison, component_count=3)

    assert evidence.sample_labels == reference.sample_labels
    assert evidence.feature_subspace_available is True
    assert evidence.score_linear_cka == pytest.approx(1.0, abs=1e-14)
    assert evidence.minimum_principal_cosine == pytest.approx(1.0, abs=1e-14)


def test_score_geometry_remains_available_when_feature_spaces_differ() -> None:
    reference = _pca()
    comparison = replace(
        reference,
        feature_space="different-control-point-system",
        feature_labels=tuple(f"other-{index}" for index in range(4)),
    )

    evidence = compare_pca_stability(reference, comparison, component_count=3)

    assert evidence.score_linear_cka == pytest.approx(1.0, abs=1e-14)
    assert evidence.feature_subspace_available is False
    assert evidence.principal_angles_degrees == ()
    assert "feature-space" in str(evidence.feature_subspace_unavailable_reason)


def test_changed_subject_geometry_reduces_stability_metrics() -> None:
    reference = _pca()
    changed = _features().copy()
    changed[0] += np.array([8.0, -5.0, 3.0, 4.0])
    changed[5] += np.array([-4.0, 6.0, -2.0, 1.0])
    comparison = _pca(changed)

    evidence = compare_pca_stability(reference, comparison, component_count=3)

    assert evidence.score_linear_cka < 0.95
    assert evidence.score_distance_rank_correlation < 0.95
    assert evidence.minimum_principal_cosine is not None
    assert evidence.minimum_principal_cosine < 0.99


def test_variance_target_is_explicit_and_manifest_is_json_ready() -> None:
    reference = _pca()
    evidence = compare_pca_stability(reference, reference, variance_target=0.75)
    manifest = evidence.as_manifest()

    assert evidence.reference_component_count == evidence.comparison_component_count
    assert evidence.reference_retained_variance >= 0.75
    assert manifest["version"] == "0.1"
    assert manifest["sample_labels"] == list(reference.sample_labels)
    assert "biological meaning" in " ".join(manifest["limitations"])


@pytest.mark.parametrize(
    ("change", "error", "message"),
    [
        ({"variance_target": 0.0}, ValueError, "variance_target"),
        ({"component_count": True}, TypeError, "component_count"),
        ({"component_count": 99}, ValueError, "retained"),
    ],
)
def test_pca_stability_rejects_invalid_selection(
    change: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    reference = _pca()
    with pytest.raises(error, match=message):
        compare_pca_stability(reference, reference, **change)


def test_pca_stability_requires_exact_sample_identity_and_sufficient_variance() -> None:
    reference = _pca()
    different_samples = replace(
        reference,
        sample_labels=(*reference.sample_labels[:-1], "unseen-specimen"),
    )
    truncated = principal_component_analysis(
        _features(),
        n_components=1,
        feature_space="declared-shape-space",
        feature_labels=["a", "b", "c", "d"],
        sample_labels=reference.sample_labels,
    )

    with pytest.raises(ValueError, match="same sample labels"):
        compare_pca_stability(reference, different_samples)
    with pytest.raises(ValueError, match="does not retain enough"):
        compare_pca_stability(reference, truncated, variance_target=0.99)
