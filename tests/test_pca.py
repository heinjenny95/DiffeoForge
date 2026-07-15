from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
analysis = pytest.importorskip("diffeoforge.analysis")

momenta_pca = analysis.momenta_pca
principal_component_analysis = analysis.principal_component_analysis


def _features() -> np.ndarray:
    return np.array(
        [
            [2.0, -1.0, 0.5],
            [0.0, 1.0, 1.5],
            [-1.0, 0.5, -0.5],
            [3.0, 2.0, 0.0],
            [1.0, -2.0, 2.0],
        ],
        dtype=np.float64,
    )


def test_pca_matches_covariance_eigenvalues_and_sign_convention() -> None:
    features = _features()

    result = principal_component_analysis(
        features,
        feature_space="test_features",
        feature_labels=["length", "width", "height"],
        sample_labels=["a", "b", "c", "d", "e"],
    )
    expected_eigenvalues = np.linalg.eigvalsh(np.cov(features, rowvar=False))[::-1]

    np.testing.assert_allclose(
        result.explained_variance,
        expected_eigenvalues,
        rtol=1e-13,
        atol=1e-14,
    )
    assert result.total_variance == pytest.approx(float(np.trace(np.cov(features, rowvar=False))))
    assert np.sum(result.explained_variance_ratio) == pytest.approx(1.0, abs=1e-14)
    assert result.feature_space == "test_features"
    assert result.feature_labels == ("length", "width", "height")
    assert result.sample_labels == ("a", "b", "c", "d", "e")
    for component in result.components:
        pivot = int(np.argmax(np.abs(component)))
        assert component[pivot] >= 0


def test_full_rank_pca_reconstructs_training_data_and_projects_new_sample() -> None:
    features = _features()
    result = principal_component_analysis(features, feature_space="test_features")

    np.testing.assert_allclose(
        result.reconstruct_training_data(),
        features,
        rtol=1e-13,
        atol=1e-13,
    )
    np.testing.assert_allclose(
        result.transform(features),
        result.scores,
        rtol=1e-14,
        atol=1e-14,
    )
    new_sample = np.array([[0.25, -0.5, 1.25]], dtype=np.float64)
    scores = result.transform(new_sample)
    np.testing.assert_allclose(
        result.inverse_transform(scores),
        new_sample,
        rtol=1e-13,
        atol=1e-13,
    )


def test_truncated_pca_reports_retained_and_total_variance_separately() -> None:
    result = principal_component_analysis(
        _features(),
        n_components=2,
        feature_space="test_features",
    )

    assert result.number_of_components == 2
    assert 0 < float(np.sum(result.explained_variance_ratio)) < 1
    assert result.total_variance > float(np.sum(result.explained_variance))
    assert not np.allclose(result.reconstruct_training_data(), _features())


def test_momenta_pca_freezes_control_point_axis_and_subject_order() -> None:
    momenta = np.array(
        [
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
            [[2.0, 0.0, 4.0], [3.0, 8.0, 5.0]],
            [[0.0, 3.0, 2.0], [7.0, 4.0, 9.0]],
        ],
        dtype=np.float64,
    )

    result = momenta_pca(
        momenta,
        n_components=2,
        subject_labels=["specimen-a", "specimen-b", "specimen-c"],
        control_point_labels=["anterior", "posterior"],
    )

    assert result.feature_space == "subject_initial_momenta_cartesian"
    assert result.sample_labels == ("specimen-a", "specimen-b", "specimen-c")
    assert result.feature_labels == (
        "momenta:anterior:x",
        "momenta:anterior:y",
        "momenta:anterior:z",
        "momenta:posterior:x",
        "momenta:posterior:y",
        "momenta:posterior:z",
    )
    expected = principal_component_analysis(
        momenta.reshape(3, 6),
        n_components=2,
        feature_space="subject_initial_momenta_cartesian",
        feature_labels=result.feature_labels,
        sample_labels=result.sample_labels,
    )
    np.testing.assert_array_equal(result.scores, expected.scores)
    np.testing.assert_array_equal(result.components, expected.components)


def test_tied_and_zero_variance_components_are_reported() -> None:
    tied = np.array(
        [[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0]],
        dtype=np.float64,
    )
    rank_one = np.array(
        [[-2.0, -4.0], [-1.0, -2.0], [1.0, 2.0], [2.0, 4.0]],
        dtype=np.float64,
    )

    tied_result = principal_component_analysis(tied, feature_space="tied")
    rank_one_result = principal_component_analysis(rank_one, feature_space="rank_one")

    assert tied_result.tied_component_groups == ((0, 1),)
    assert tied_result.zero_variance_components == ()
    assert rank_one_result.numerical_rank == 1
    assert rank_one_result.zero_variance_components == (1,)
    np.testing.assert_allclose(
        rank_one_result.reconstruct_training_data(),
        rank_one,
        rtol=1e-13,
        atol=1e-13,
    )


def test_pca_is_repeatable_nonmutating_and_returns_read_only_evidence() -> None:
    features = _features()
    original = features.copy()

    first = principal_component_analysis(features, feature_space="repeatability")
    second = principal_component_analysis(features, feature_space="repeatability")

    assert np.array_equal(features, original)
    assert np.array_equal(first.components, second.components)
    assert np.array_equal(first.scores, second.scores)
    with pytest.raises(ValueError, match="read-only"):
        first.components[0, 0] = 99.0
    with pytest.raises(ValueError, match="read-only"):
        first.mean[0] = 99.0


@pytest.mark.parametrize(
    ("features", "error", "message"),
    [
        ([[1.0], [2.0]], TypeError, "numpy.ndarray"),
        (np.ones((2, 2), dtype=np.float32), TypeError, "float64"),
        (np.ones((2, 2, 1), dtype=np.float64), ValueError, "shape"),
        (np.ones((1, 2), dtype=np.float64), ValueError, "at least 2 samples"),
        (np.ones((2, 0), dtype=np.float64), ValueError, "one feature"),
    ],
)
def test_invalid_feature_arrays_fail_explicitly(
    features,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        principal_component_analysis(features, feature_space="invalid")


def test_nonfinite_and_zero_variance_features_fail_explicitly() -> None:
    nonfinite = _features()
    nonfinite[0, 0] = np.nan

    with pytest.raises(ValueError, match="finite"):
        principal_component_analysis(nonfinite, feature_space="invalid")
    with pytest.raises(ValueError, match="positive total"):
        principal_component_analysis(
            np.ones((3, 2), dtype=np.float64), feature_space="invalid"
        )


@pytest.mark.parametrize(
    ("override", "error", "message"),
    [
        ({"feature_space": ""}, ValueError, "feature_space"),
        ({"n_components": 0}, ValueError, "n_components"),
        ({"n_components": 4}, ValueError, "n_components"),
        ({"n_components": 1.5}, TypeError, "n_components"),
        ({"n_components": True}, TypeError, "n_components"),
        ({"feature_labels": ["a", "a", "c"]}, ValueError, "unique"),
        ({"feature_labels": ["a", "b"]}, ValueError, "exactly"),
        ({"sample_labels": ["a"] * 5}, ValueError, "unique"),
        ({"tie_tolerance": -1.0}, ValueError, "tie_tolerance"),
        ({"tie_tolerance": math.inf}, ValueError, "tie_tolerance"),
    ],
)
def test_invalid_pca_settings_and_labels_fail_explicitly(
    override: dict,
    error: type[Exception],
    message: str,
) -> None:
    keywords = {"feature_space": "test_features", **override}
    with pytest.raises(error, match=message):
        principal_component_analysis(_features(), **keywords)


def test_projection_and_inverse_validate_shapes_and_dtypes() -> None:
    result = principal_component_analysis(_features(), feature_space="test_features")

    with pytest.raises(TypeError, match="float64"):
        result.transform(np.ones((1, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="columns"):
        result.transform(np.ones((1, 2), dtype=np.float64))
    with pytest.raises(TypeError, match="numpy.ndarray"):
        result.inverse_transform([[0.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="shape"):
        result.inverse_transform(np.ones((2, 2), dtype=np.float64))


def test_invalid_momenta_and_labels_fail_explicitly() -> None:
    valid = np.arange(18, dtype=np.float64).reshape(3, 2, 3)
    nonfinite = valid.copy()
    nonfinite[0, 0, 0] = np.inf

    with pytest.raises(TypeError, match="float64"):
        momenta_pca(valid.astype(np.float32))
    with pytest.raises(ValueError, match="shape"):
        momenta_pca(valid.reshape(3, 6))
    with pytest.raises(ValueError, match="finite"):
        momenta_pca(nonfinite)
    with pytest.raises(ValueError, match="unique"):
        momenta_pca(valid, control_point_labels=["same", "same"])


def test_momenta_pca_accepts_detached_optimizer_output() -> None:
    torch = pytest.importorskip("torch")
    engine = pytest.importorskip("diffeoforge.engine")
    fixture_path = (
        Path(__file__).parents[1]
        / "reference"
        / "modern-engine-v0.2"
        / "deformetrica-4.3.0-objective.json"
    )
    values = json.loads(fixture_path.read_text(encoding="utf-8"))["inputs"]

    def tensor(value):
        return torch.tensor(value, dtype=torch.float64)

    template = tensor(values["template_vertices"])
    target = tensor(values["target_vertices"])
    triangles = torch.tensor(values["triangles"], dtype=torch.int64)
    control_points = tensor(values["control_points"])
    offsets = (
        tensor([0.0, 0.0, 0.0]),
        tensor([0.01, -0.02, 0.015]),
        tensor([-0.015, 0.01, -0.005]),
    )
    targets = tuple((target + offset, triangles) for offset in offsets)
    initial_momenta = torch.zeros((3, *control_points.shape), dtype=torch.float64)
    optimized = engine.optimize_momenta(
        template,
        triangles,
        targets,
        control_points,
        initial_momenta,
        deformation_kernel_width=values["deformation_width"],
        attachment_kernel_width=values["attachment_width"],
        noise_variance=values["noise_variance"],
        number_of_time_points=values["number_of_time_points"],
        max_iterations=2,
    )
    momenta = optimized.momenta.numpy()

    result = momenta_pca(
        momenta,
        subject_labels=["target-a", "target-b", "target-c"],
        control_point_labels=["cp-0", "cp-1", "cp-2"],
    )

    assert result.number_of_components == 2
    assert result.feature_space == "subject_initial_momenta_cartesian"
    np.testing.assert_allclose(
        result.reconstruct_training_data(),
        momenta.reshape(3, -1),
        rtol=1e-12,
        atol=1e-12,
    )
