"""Strict, engine-independent I/O for homologous 3D landmarks."""

from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from diffeoforge.config import ConfigurationError

LANDMARK_COLUMNS = ("mesh_file", "landmark", "x", "y", "z")


def read_landmark_csv(
    path: Path | str,
    mesh_files: Sequence[str],
) -> tuple[tuple[str, ...], np.ndarray]:
    """Read an ordered, complete landmark table for an exact mesh cohort."""

    source = Path(path).expanduser().resolve()
    expected = tuple(mesh_files)
    if len(expected) < 2:
        raise ConfigurationError("Landmark alignment requires at least two meshes")
    if any(not isinstance(name, str) or not name for name in expected):
        raise ConfigurationError("Landmark mesh filenames must be non-empty strings")
    if len(set(expected)) != len(expected):
        raise ConfigurationError("Landmark mesh filenames are not unique")
    if len({name.casefold() for name in expected}) != len(expected):
        raise ConfigurationError(
            "Landmark mesh filenames must be unique when compared case-insensitively"
        )

    rows: dict[str, list[tuple[str, tuple[float, float, float]]]] = {
        name: [] for name in expected
    }
    try:
        with source.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != LANDMARK_COLUMNS:
                raise ConfigurationError(
                    "Landmark CSV header must be exactly: " + ",".join(LANDMARK_COLUMNS)
                )
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ConfigurationError(
                        f"Landmark CSV row {line_number} has unexpected extra columns"
                    )
                mesh_file = (row["mesh_file"] or "").strip()
                label = (row["landmark"] or "").strip()
                if mesh_file not in rows:
                    raise ConfigurationError(
                        f"Landmark CSV row {line_number} names unknown mesh {mesh_file!r}"
                    )
                if not label:
                    raise ConfigurationError(
                        f"Landmark CSV row {line_number} has an empty landmark label"
                    )
                if any(existing[0] == label for existing in rows[mesh_file]):
                    raise ConfigurationError(
                        f"Landmark {label!r} is duplicated for mesh {mesh_file!r}"
                    )
                try:
                    coordinates = tuple(float(row[axis]) for axis in ("x", "y", "z"))
                except (TypeError, ValueError) as error:
                    raise ConfigurationError(
                        f"Landmark CSV row {line_number} contains non-numeric coordinates"
                    ) from error
                if not all(math.isfinite(value) for value in coordinates):
                    raise ConfigurationError(
                        f"Landmark CSV row {line_number} contains non-finite coordinates"
                    )
                rows[mesh_file].append((label, coordinates))
    except OSError as error:
        raise ConfigurationError(f"Could not read landmark CSV {source}: {error}") from error

    first_labels = tuple(label for label, _ in rows[expected[0]])
    if len(first_labels) < 3:
        raise ConfigurationError("Landmark CSV requires at least three landmarks per mesh")
    for mesh_file in expected:
        labels = tuple(label for label, _ in rows[mesh_file])
        if labels != first_labels:
            raise ConfigurationError(
                "Every mesh must use the same unique landmark labels in the same row order; "
                f"mismatch at {mesh_file!r}"
            )
    values = np.array(
        [[coordinates for _, coordinates in rows[mesh_file]] for mesh_file in expected],
        dtype=np.float64,
    )
    return first_labels, values
