"""Deterministic landmark-based generalized Procrustes alignment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import numpy as np

ProcrustesTermination = Literal["tolerance", "max_iterations"]


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, dtype=np.float64, copy=True)
    result.setflags(write=False)
    return result


def _validate_points(name: str, values: np.ndarray) -> np.ndarray:
    if not isinstance(values, np.ndarray):
        raise TypeError(f"{name} must be a numpy.ndarray")
    if values.dtype != np.float64:
        raise TypeError(f"{name} must use numpy.float64")
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"{name} must have shape (points, 3)")
    if values.shape[0] == 0:
        raise ValueError(f"{name} must contain at least one point")
    if not bool(np.isfinite(values).all()):
        raise ValueError(f"{name} must contain only finite values")
    return values


@dataclass(frozen=True)
class SimilarityTransform:
    """Auditable row-vector transform from raw to aligned coordinates."""

    centroid: np.ndarray
    scale: float
    rotation: np.ndarray

    def __post_init__(self) -> None:
        centroid = np.asarray(self.centroid)
        rotation = np.asarray(self.rotation)
        if centroid.shape != (3,) or centroid.dtype != np.float64:
            raise ValueError("centroid must be a numpy.float64 vector with shape (3,)")
        if rotation.shape != (3, 3) or rotation.dtype != np.float64:
            raise ValueError("rotation must be a numpy.float64 matrix with shape (3, 3)")
        if not bool(np.isfinite(centroid).all()) or not bool(np.isfinite(rotation).all()):
            raise ValueError("transform arrays must contain only finite values")
        if not math.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("scale must be finite and greater than zero")
        if not np.allclose(rotation.T @ rotation, np.eye(3), rtol=1e-12, atol=1e-12):
            raise ValueError("rotation must be orthogonal")
        object.__setattr__(self, "centroid", _readonly(centroid))
        object.__setattr__(self, "rotation", _readonly(rotation))
        object.__setattr__(self, "scale", float(self.scale))

    def apply(self, points: np.ndarray) -> np.ndarray:
        """Apply this specimen transform to landmarks or complete mesh vertices."""

        values = _validate_points("points", points)
        return ((values - self.centroid) * self.scale) @ self.rotation

    def inverse(self, aligned_points: np.ndarray) -> np.ndarray:
        """Map aligned coordinates back into the original specimen frame."""

        values = _validate_points("aligned_points", aligned_points)
        return (values @ self.rotation.T) / self.scale + self.centroid


@dataclass(frozen=True)
class ProcrustesIteration:
    """One generalized-Procrustes mean update."""

    iteration: int
    mean_change: float
    total_squared_residual: float


@dataclass(frozen=True)
class GeneralizedProcrustesResult:
    """Aligned configurations, consensus, transforms, and convergence evidence."""

    aligned_landmarks: np.ndarray
    mean_shape: np.ndarray
    transforms: tuple[SimilarityTransform, ...]
    residuals: tuple[float, ...]
    history: tuple[ProcrustesIteration, ...]
    termination_reason: ProcrustesTermination
    converged: bool
    scale_to_unit_centroid_size: bool
    allow_reflection: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "aligned_landmarks", _readonly(self.aligned_landmarks))
        object.__setattr__(self, "mean_shape", _readonly(self.mean_shape))


def _nonnegative_real(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return normalized


def _positive_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{name} must be at least 1")
    return normalized


def _optimal_rotation(
    source: np.ndarray,
    target: np.ndarray,
    *,
    allow_reflection: bool,
) -> np.ndarray:
    left, _, right_transpose = np.linalg.svd(source.T @ target, full_matrices=False)
    rotation = left @ right_transpose
    if np.linalg.det(rotation) < 0 and not allow_reflection:
        left = left.copy()
        left[:, -1] *= -1.0
        rotation = left @ right_transpose
    return rotation


def generalized_procrustes(
    landmarks: np.ndarray,
    *,
    scale_to_unit_centroid_size: bool = True,
    allow_reflection: bool = False,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> GeneralizedProcrustesResult:
    """Align ordered homologous 3D landmark configurations.

    Landmark order is semantically significant. Reflections are prohibited by
    default, and every direct specimen-to-consensus transform is returned for
    application to the corresponding complete mesh.
    """

    if not isinstance(landmarks, np.ndarray):
        raise TypeError("landmarks must be a numpy.ndarray")
    if landmarks.dtype != np.float64:
        raise TypeError("landmarks must use numpy.float64")
    if landmarks.ndim != 3 or landmarks.shape[2] != 3:
        raise ValueError("landmarks must have shape (subjects, landmarks, 3)")
    if landmarks.shape[0] < 2:
        raise ValueError("landmarks must contain at least two subjects")
    if landmarks.shape[1] < 3:
        raise ValueError("each subject must contain at least three landmarks")
    if not bool(np.isfinite(landmarks).all()):
        raise ValueError("landmarks must contain only finite values")
    if not isinstance(scale_to_unit_centroid_size, bool):
        raise TypeError("scale_to_unit_centroid_size must be a boolean")
    if not isinstance(allow_reflection, bool):
        raise TypeError("allow_reflection must be a boolean")
    threshold = _nonnegative_real("tolerance", tolerance)
    iteration_limit = _positive_integer("max_iterations", max_iterations)

    centroids = np.mean(landmarks, axis=1)
    centered = landmarks - centroids[:, None, :]
    centroid_sizes = np.sqrt(np.sum(centered * centered, axis=(1, 2)))
    for index, configuration in enumerate(centered):
        if np.unique(landmarks[index], axis=0).shape[0] != landmarks.shape[1]:
            raise ValueError(f"subject {index} contains duplicate landmarks")
        if np.linalg.matrix_rank(configuration) < 2:
            raise ValueError(f"subject {index} landmarks are collinear or degenerate")
    if not bool(np.all(centroid_sizes > 0)):
        raise ValueError("all subjects must have positive centroid size")

    scales = 1.0 / centroid_sizes if scale_to_unit_centroid_size else np.ones_like(
        centroid_sizes
    )
    normalized = centered * scales[:, None, None]
    reference = normalized[0].copy()
    rotations = np.repeat(np.eye(3, dtype=np.float64)[None, :, :], landmarks.shape[0], axis=0)
    aligned = normalized.copy()
    history: list[ProcrustesIteration] = []
    converged = False

    for iteration in range(1, iteration_limit + 1):
        for index, configuration in enumerate(normalized):
            rotations[index] = _optimal_rotation(
                configuration,
                reference,
                allow_reflection=allow_reflection,
            )
            aligned[index] = configuration @ rotations[index]
        mean_shape = np.mean(aligned, axis=0)
        mean_shape -= np.mean(mean_shape, axis=0)
        if scale_to_unit_centroid_size:
            mean_size = float(np.linalg.norm(mean_shape))
            if not math.isfinite(mean_size) or mean_size <= 0:
                raise FloatingPointError("Procrustes consensus has zero or non-finite size")
            mean_shape /= mean_size
        mean_change = float(np.linalg.norm(mean_shape - reference))
        residual_array = np.sum((aligned - mean_shape[None, :, :]) ** 2, axis=(1, 2))
        history.append(
            ProcrustesIteration(
                iteration=iteration,
                mean_change=mean_change,
                total_squared_residual=float(np.sum(residual_array)),
            )
        )
        reference = mean_shape
        if mean_change <= threshold:
            converged = True
            break

    residual_array = np.sum((aligned - reference[None, :, :]) ** 2, axis=(1, 2))
    transforms = tuple(
        SimilarityTransform(
            centroid=centroids[index],
            scale=float(scales[index]),
            rotation=rotations[index],
        )
        for index in range(landmarks.shape[0])
    )
    return GeneralizedProcrustesResult(
        aligned_landmarks=aligned,
        mean_shape=reference,
        transforms=transforms,
        residuals=tuple(float(value) for value in residual_array),
        history=tuple(history),
        termination_reason="tolerance" if converged else "max_iterations",
        converged=converged,
        scale_to_unit_centroid_size=scale_to_unit_centroid_size,
        allow_reflection=allow_reflection,
    )
