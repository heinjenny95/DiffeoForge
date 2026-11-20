"""NumPy-only atlas distances shared with the native Python 3.8 runtime."""

import math
from numbers import Real

import numpy as np

WINDOW_ITERATIONS = 200
CHECK_INTERVAL = 25
COHORT_THRESHOLD_PERCENT = 1.0
SUBJECT_THRESHOLD_PERCENT = 2.0
_MAX_DIAGNOSTIC_KERNEL_ELEMENTS = 1 << 20


def _readonly(values):
    result = np.array(values, dtype=np.float64, copy=True)
    result.setflags(write=False)
    return result


def _positive_real(name, value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real scalar")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return result


def _momenta_and_controls(momenta, control_points):
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


def gaussian_control_point_kernel(control_points, kernel_width):
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


def lddmm_momenta_squared_distances(momenta, control_points, *, deformation_kernel_width):
    """Return pairwise squared tangent distances induced by the LDDMM kernel."""
    values, controls = _momenta_and_controls(momenta, control_points)
    kernel = gaussian_control_point_kernel(controls, deformation_kernel_width)
    gram = np.einsum("sic,ij,tjc->st", values, kernel, values, optimize=True)
    return _squared_distances_from_gram(gram)


def _squared_distances_from_gram(gram):
    diagonal = np.diag(gram)
    squared = diagonal[:, None] + diagonal[None, :] - 2.0 * gram
    squared = np.maximum((squared + squared.T) * 0.5, 0.0)
    np.fill_diagonal(squared, 0.0)
    return _readonly(squared)


def distance_matrix(momenta, controls, width):
    """Measure a checkpoint in its own basis without normalizing the distance scale."""
    momenta, controls = _momenta_and_controls(
        np.asarray(momenta, dtype=np.float64), np.asarray(controls, dtype=np.float64),
    )
    count = controls.shape[0]
    if count * count <= _MAX_DIAGNOSTIC_KERNEL_ELEMENTS:
        return np.sqrt(lddmm_momenta_squared_distances(
            momenta, controls, deformation_kernel_width=width,
        ))

    # The full Gaussian workspace grows quadratically in control-point count.
    # Accumulate the same quadratic form over its rows for large runtime snapshots.
    width = _positive_real("kernel_width", width)
    subject_count = momenta.shape[0]
    gram = np.zeros((subject_count, subject_count), dtype=np.float64)
    block_size = max(1, _MAX_DIAGNOSTIC_KERNEL_ELEMENTS // count)
    for start in range(0, count, block_size):
        block = slice(start, start + block_size)
        difference = controls[block, None, :] - controls[None, :, :]
        squared = np.einsum("ijk,ijk->ij", difference, difference, optimize=True)
        kernel = np.exp(-np.maximum(squared, 0.0) / (width * width))
        gram += np.einsum("sic,ij,tjc->st", momenta[:, block, :], kernel, momenta, optimize=True)
    return np.sqrt(_squared_distances_from_gram(gram))


def compare_distances(old, new, subject_labels):
    """Compare cohort and per-subject distances in the same declared specimen order."""
    unavailable = {
        "status": "unavailable", "cohort_percent": None, "max_subject_percent": None,
        "worst_subjects": [], "subject_percent": None, "stable": False,
    }
    labels = tuple(subject_labels)
    n = len(labels)
    if n < 2 or any(not isinstance(label, str) or not label for label in labels):
        return unavailable
    if len(set(labels)) != n:
        return unavailable
    if any(
        not isinstance(matrix, np.ndarray) or matrix.shape != (n, n)
        or matrix.dtype.kind not in "fiu"
        or not np.isfinite(matrix).all() or np.any(matrix < 0.0)
        or not np.array_equal(matrix, matrix.T) or np.any(np.diag(matrix) != 0.0)
        for matrix in (old, new)
    ):
        return unavailable
    old = old.astype(np.float64, copy=False)
    new = new.astype(np.float64, copy=False)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore", under="ignore"):
        before = np.linalg.norm(old, axis=1)
        after = np.linalg.norm(new, axis=1)
        if not (np.isfinite(before).all() and np.isfinite(after).all()
                and np.all(before > 0.0) and np.all(after > 0.0)):
            return unavailable
        delta = new - old
        upper = np.triu_indices(n, 1)
        cohort = float(100.0 * (np.linalg.norm(delta[upper]) / np.linalg.norm(old[upper])))
        subjects = 100.0 * (np.linalg.norm(delta, axis=1) / before)
    if not math.isfinite(cohort) or not np.isfinite(subjects).all():
        return unavailable
    maximum = float(np.max(subjects))
    return {
        "status": "measured", "cohort_percent": cohort, "max_subject_percent": maximum,
        "worst_subjects": [labels[index] for index in np.flatnonzero(subjects == maximum)],
        "subject_percent": subjects.tolist(),
        "stable": cohort < COHORT_THRESHOLD_PERCENT and maximum < SUBJECT_THRESHOLD_PERCENT,
    }
