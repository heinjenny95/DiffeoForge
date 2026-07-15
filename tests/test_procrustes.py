from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
analysis = pytest.importorskip("diffeoforge.analysis")
generalized_procrustes = analysis.generalized_procrustes


def _base_landmarks() -> np.ndarray:
    return np.array(
        [
            [0.0, 0.0, 0.0],
            [1.1, 0.1, -0.1],
            [0.2, 1.0, 0.3],
            [-0.1, 0.2, 1.2],
            [0.7, -0.4, 0.5],
        ],
        dtype=np.float64,
    )


def _rotation_z(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _similarity_cohort() -> np.ndarray:
    base = _base_landmarks()
    second = 2.4 * (base @ _rotation_z(0.73)) + np.array(
        [3.0, -2.0, 4.0], dtype=np.float64
    )
    third = 0.65 * (base @ _rotation_z(-1.12)) + np.array(
        [-1.5, 0.25, -3.0], dtype=np.float64
    )
    return np.stack((base, second, third))


def test_generalized_procrustes_recovers_known_translation_rotation_and_scale() -> None:
    landmarks = _similarity_cohort()

    result = generalized_procrustes(landmarks)

    assert result.converged is True
    assert result.termination_reason == "tolerance"
    assert len(result.history) >= 1
    assert np.linalg.norm(np.mean(result.mean_shape, axis=0)) < 1e-14
    assert np.linalg.norm(result.mean_shape) == pytest.approx(1.0, abs=1e-14)
    for index, transform in enumerate(result.transforms):
        np.testing.assert_allclose(
            transform.apply(landmarks[index]),
            result.aligned_landmarks[index],
            rtol=1e-13,
            atol=1e-13,
        )
        np.testing.assert_allclose(
            result.aligned_landmarks[index],
            result.mean_shape,
            rtol=1e-12,
            atol=1e-12,
        )
        assert np.linalg.det(transform.rotation) == pytest.approx(1.0, abs=1e-12)
        assert result.residuals[index] < 1e-24


def test_transform_applies_to_complete_mesh_and_round_trips() -> None:
    landmarks = _similarity_cohort()
    result = generalized_procrustes(landmarks)
    full_mesh = np.array(
        [[3.2, -1.0, 2.1], [4.5, 0.2, -3.0], [-1.0, 2.0, 0.5]],
        dtype=np.float64,
    )

    aligned_mesh = result.transforms[1].apply(full_mesh)
    restored_mesh = result.transforms[1].inverse(aligned_mesh)

    np.testing.assert_allclose(restored_mesh, full_mesh, rtol=1e-13, atol=1e-13)


def test_disabling_scaling_preserves_centroid_size_differences() -> None:
    landmarks = _similarity_cohort()[:2]

    result = generalized_procrustes(landmarks, scale_to_unit_centroid_size=False)

    assert all(transform.scale == 1.0 for transform in result.transforms)
    first_size = np.linalg.norm(result.aligned_landmarks[0])
    second_size = np.linalg.norm(result.aligned_landmarks[1])
    assert second_size / first_size == pytest.approx(2.4, rel=1e-13)
    assert sum(result.residuals) > 0.1


def test_reflections_are_excluded_by_default_and_explicitly_optional() -> None:
    base = _base_landmarks()
    reflection = np.diag(np.array([-1.0, 1.0, 1.0], dtype=np.float64))
    mirrored = base @ reflection + np.array([2.0, -1.0, 0.5], dtype=np.float64)
    cohort = np.stack((base, mirrored))

    proper = generalized_procrustes(cohort)
    reflected = generalized_procrustes(cohort, allow_reflection=True)

    assert sum(proper.residuals) > 1e-3
    assert all(np.linalg.det(item.rotation) > 0 for item in proper.transforms)
    assert sum(reflected.residuals) < 1e-24
    assert np.linalg.det(reflected.transforms[1].rotation) == pytest.approx(-1.0, abs=1e-12)


def test_result_is_repeatable_nonmutating_and_read_only() -> None:
    landmarks = _similarity_cohort()
    original = landmarks.copy()

    first = generalized_procrustes(landmarks)
    second = generalized_procrustes(landmarks)

    assert np.array_equal(landmarks, original)
    assert np.array_equal(first.aligned_landmarks, second.aligned_landmarks)
    assert np.array_equal(first.mean_shape, second.mean_shape)
    assert first.history == second.history
    assert first.residuals == second.residuals
    with pytest.raises(ValueError, match="read-only"):
        first.mean_shape[0, 0] = 99.0
    with pytest.raises(ValueError, match="read-only"):
        first.transforms[0].rotation[0, 0] = 99.0


def test_iteration_limit_and_history_are_explicit() -> None:
    landmarks = _similarity_cohort().copy()
    landmarks[1, 2] += np.array([0.15, -0.08, 0.04], dtype=np.float64)

    result = generalized_procrustes(landmarks, max_iterations=1, tolerance=0.0)

    assert result.converged is False
    assert result.termination_reason == "max_iterations"
    assert len(result.history) == 1
    assert result.history[0].iteration == 1
    assert result.history[0].mean_change > 0
    assert result.history[0].total_squared_residual >= 0


@pytest.mark.parametrize(
    ("landmarks", "error", "message"),
    [
        (_similarity_cohort().astype(np.float32), TypeError, "float64"),
        (_similarity_cohort()[0], ValueError, "shape"),
        (_similarity_cohort()[:1], ValueError, "two subjects"),
        (_similarity_cohort()[:, :2], ValueError, "three landmarks"),
    ],
)
def test_invalid_landmark_arrays_fail_explicitly(
    landmarks: np.ndarray,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        generalized_procrustes(landmarks)


def test_nonfinite_duplicate_and_collinear_landmarks_fail_explicitly() -> None:
    nonfinite = _similarity_cohort()
    nonfinite[0, 0, 0] = np.nan
    duplicate = _similarity_cohort()
    duplicate[1, 1] = duplicate[1, 0]
    line = np.array(
        [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]] * 2,
        dtype=np.float64,
    )

    with pytest.raises(ValueError, match="finite"):
        generalized_procrustes(nonfinite)
    with pytest.raises(ValueError, match="duplicate"):
        generalized_procrustes(duplicate)
    with pytest.raises(ValueError, match="collinear"):
        generalized_procrustes(line)


@pytest.mark.parametrize(
    ("override", "error", "message"),
    [
        ({"tolerance": -1.0}, ValueError, "tolerance"),
        ({"tolerance": math.inf}, ValueError, "tolerance"),
        ({"max_iterations": 0}, ValueError, "max_iterations"),
        ({"max_iterations": 1.5}, TypeError, "max_iterations"),
        ({"scale_to_unit_centroid_size": 1}, TypeError, "boolean"),
        ({"allow_reflection": 0}, TypeError, "boolean"),
    ],
)
def test_invalid_settings_fail_explicitly(
    override: dict,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        generalized_procrustes(_similarity_cohort(), **override)


def test_transform_rejects_incompatible_points() -> None:
    transform = generalized_procrustes(_similarity_cohort()).transforms[0]

    with pytest.raises(TypeError, match="numpy.ndarray"):
        transform.apply([[0.0, 0.0, 0.0]])
    with pytest.raises(TypeError, match="float64"):
        transform.apply(np.zeros((2, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="shape"):
        transform.inverse(np.zeros((2, 2), dtype=np.float64))
