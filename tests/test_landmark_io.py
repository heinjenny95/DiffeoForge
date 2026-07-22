from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis.landmarks import read_landmark_csv, write_landmark_csv
from diffeoforge.config import ConfigurationError


def test_landmark_csv_writer_round_trips_ordered_float64_values(tmp_path: Path) -> None:
    meshes = ("template.vtk", "subject.vtk")
    labels = ("anterior", "dorsal", "posterior")
    values = np.arange(18, dtype=np.float64).reshape(2, 3, 3)

    path = write_landmark_csv(tmp_path / "landmarks.csv", meshes, labels, values)
    observed_labels, observed_values = read_landmark_csv(path, meshes)

    assert observed_labels == labels
    assert np.array_equal(observed_values, values)
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_landmark_csv(path, meshes, labels, values)


def test_landmark_csv_writer_rejects_incomplete_or_wrong_precision_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="float64"):
        write_landmark_csv(
            tmp_path / "bad.csv",
            ("template.vtk", "subject.vtk"),
            ("a", "b", "c"),
            np.zeros((2, 3, 3), dtype=np.float32),
        )
