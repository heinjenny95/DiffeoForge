"""Strict, engine-independent I/O for homologous 3D landmarks."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError

LANDMARK_COLUMNS = ("mesh_file", "landmark", "x", "y", "z")
_TAGGED_TXT_REQUIRED_SECTIONS = (
    "individuals",
    "dimensions",
    "landmarks",
    "rawpoints",
)


@dataclass(frozen=True)
class LandmarkTxtImportResult:
    """Auditable summary of one per-mesh landmark TXT folder import."""

    csv_path: Path
    mesh_files: tuple[str, ...]
    txt_files: tuple[Path, ...]
    landmark_labels: tuple[str, ...]
    ignored_txt_files: tuple[Path, ...]


def _tagged_txt_scalar(
    source: Path,
    sections: dict[str, list[tuple[int, str]]],
    section: str,
) -> int:
    payload = sections[section]
    if len(payload) != 1:
        raise ConfigurationError(
            f"Landmark TXT {source} section [{section}] must contain exactly one integer"
        )
    line_number, text = payload[0]
    try:
        value = int(text)
    except ValueError as error:
        raise ConfigurationError(
            f"Landmark TXT {source} line {line_number} in [{section}] is not an integer"
        ) from error
    if value < 1:
        raise ConfigurationError(f"Landmark TXT {source} section [{section}] must be positive")
    return value


def read_landmark_txt(path: Path | str) -> np.ndarray:
    """Read one strict tagged, single-specimen 3D landmark TXT file.

    The supported interchange format declares ``[individuals]``, ``[dimensions]``,
    ``[landmarks]``, and ``[rawpoints]`` sections. Coordinates are whitespace-delimited
    and remain in their original units; this function never rescales them.
    """

    source = Path(path).expanduser().resolve()
    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(f"Could not read landmark TXT {source}: {error}") from error

    sections: dict[str, list[tuple[int, str]]] = {}
    current_section: str | None = None
    for line_number, raw_line in enumerate(lines, start=1):
        text = raw_line.strip()
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1].strip().casefold()
            if not section:
                raise ConfigurationError(
                    f"Landmark TXT {source} line {line_number} has an empty section name"
                )
            if section in sections:
                raise ConfigurationError(f"Landmark TXT {source} repeats section [{section}]")
            sections[section] = []
            current_section = section
            continue
        if current_section is None:
            raise ConfigurationError(
                f"Landmark TXT {source} line {line_number} appears before any section"
            )
        sections[current_section].append((line_number, text))

    missing_sections = [
        section for section in _TAGGED_TXT_REQUIRED_SECTIONS if section not in sections
    ]
    if missing_sections:
        raise ConfigurationError(
            f"Landmark TXT {source} is missing required section(s): "
            + ", ".join(f"[{section}]" for section in missing_sections)
        )

    individuals = _tagged_txt_scalar(source, sections, "individuals")
    dimensions = _tagged_txt_scalar(source, sections, "dimensions")
    landmark_count = _tagged_txt_scalar(source, sections, "landmarks")
    if individuals != 1:
        raise ConfigurationError(
            f"Landmark TXT {source} must describe exactly one individual; found {individuals}"
        )
    if dimensions != 3:
        raise ConfigurationError(
            f"Landmark TXT {source} must contain 3D coordinates; found {dimensions} dimensions"
        )
    if landmark_count < 3:
        raise ConfigurationError(f"Landmark TXT {source} requires at least three landmarks")

    coordinates: list[tuple[float, float, float]] = []
    marker_seen = False
    for line_number, text in sections["rawpoints"]:
        marker = text.strip("'\"").strip()
        if marker.startswith("#"):
            if marker != "#1" or marker_seen:
                raise ConfigurationError(
                    f"Landmark TXT {source} line {line_number} has an invalid individual marker"
                )
            marker_seen = True
            continue
        fields = text.split()
        if len(fields) != 3:
            raise ConfigurationError(
                f"Landmark TXT {source} line {line_number} must contain exactly x y z"
            )
        try:
            point = tuple(float(field) for field in fields)
        except ValueError as error:
            raise ConfigurationError(
                f"Landmark TXT {source} line {line_number} contains non-numeric coordinates"
            ) from error
        if not all(math.isfinite(value) for value in point):
            raise ConfigurationError(
                f"Landmark TXT {source} line {line_number} contains non-finite coordinates"
            )
        coordinates.append(point)

    if len(coordinates) != landmark_count:
        raise ConfigurationError(
            f"Landmark TXT {source} declares {landmark_count} landmarks but contains "
            f"{len(coordinates)} coordinate rows"
        )
    return np.asarray(coordinates, dtype=np.float64)


def import_landmark_txt_folder(
    txt_directory: Path | str,
    mesh_files: Sequence[Path | str],
    output_path: Path | str,
    *,
    overwrite: bool = False,
) -> LandmarkTxtImportResult:
    """Import matching per-mesh TXT files into the canonical cohort CSV.

    TXT files are matched case-insensitively by stem to the supplied mesh filenames.
    Every selected mesh must have exactly one matching TXT file. Unmatched TXT files
    are reported but not interpreted. Landmark order is preserved and deterministic
    labels ``LM1`` through ``LMN`` are assigned because the tagged format has no labels.
    """

    source_directory = Path(txt_directory).expanduser().resolve()
    if not source_directory.is_dir():
        raise ConfigurationError(f"Landmark TXT folder does not exist: {source_directory}")

    mesh_names = tuple(Path(mesh_file).name for mesh_file in mesh_files)
    if len(mesh_names) < 2:
        raise ConfigurationError("Landmark TXT import requires at least two meshes")
    if any(not name for name in mesh_names):
        raise ConfigurationError("Landmark mesh filenames must be non-empty")
    if len({name.casefold() for name in mesh_names}) != len(mesh_names):
        raise ConfigurationError(
            "Landmark mesh filenames must be unique when compared case-insensitively"
        )
    mesh_stems = tuple(Path(name).stem.casefold() for name in mesh_names)
    if len(set(mesh_stems)) != len(mesh_stems):
        raise ConfigurationError(
            "Landmark TXT import requires unique mesh stems when compared case-insensitively"
        )

    try:
        txt_candidates = tuple(
            sorted(
                (
                    path.resolve()
                    for path in source_directory.iterdir()
                    if path.is_file() and path.suffix.casefold() == ".txt"
                ),
                key=lambda path: path.name.casefold(),
            )
        )
    except OSError as error:
        raise ConfigurationError(
            f"Could not inspect landmark TXT folder {source_directory}: {error}"
        ) from error

    by_stem: dict[str, Path] = {}
    for candidate in txt_candidates:
        key = candidate.stem.casefold()
        if key in by_stem:
            raise ConfigurationError(
                "Landmark TXT filenames must have unique stems when compared "
                f"case-insensitively: {by_stem[key].name!r}, {candidate.name!r}"
            )
        by_stem[key] = candidate

    missing = [
        name for name, stem in zip(mesh_names, mesh_stems, strict=True) if stem not in by_stem
    ]
    if missing:
        raise ConfigurationError(
            "Missing landmark TXT file(s) matching mesh stem(s): " + ", ".join(missing)
        )

    selected_txt = tuple(by_stem[stem] for stem in mesh_stems)
    arrays = tuple(read_landmark_txt(path) for path in selected_txt)
    landmark_count = arrays[0].shape[0]
    mismatched = [
        f"{path.name} ({values.shape[0]})"
        for path, values in zip(selected_txt, arrays, strict=True)
        if values.shape[0] != landmark_count
    ]
    if mismatched:
        raise ConfigurationError(
            "Every landmark TXT must contain the same ordered landmark count; "
            "mismatch at " + ", ".join(mismatched)
        )

    labels = tuple(f"LM{index}" for index in range(1, landmark_count + 1))
    values = np.stack(arrays).astype(np.float64, copy=False)
    destination = write_landmark_csv(
        output_path,
        mesh_names,
        labels,
        values,
        overwrite=overwrite,
    )
    selected_set = set(selected_txt)
    return LandmarkTxtImportResult(
        csv_path=destination,
        mesh_files=mesh_names,
        txt_files=selected_txt,
        landmark_labels=labels,
        ignored_txt_files=tuple(path for path in txt_candidates if path not in selected_set),
    )


def write_landmark_csv(
    path: Path | str,
    mesh_files: Sequence[str],
    labels: Sequence[str],
    values: np.ndarray,
    *,
    overwrite: bool = False,
) -> Path:
    """Write one complete ordered landmark cohort through the atomic file boundary."""

    destination = Path(path).expanduser().resolve()
    meshes = tuple(mesh_files)
    landmark_labels = tuple(labels)
    coordinates = np.asarray(values)
    if len(meshes) < 2 or len(set(meshes)) != len(meshes):
        raise ConfigurationError("Landmark output requires at least two unique mesh filenames")
    if len(landmark_labels) < 3 or len(set(landmark_labels)) != len(landmark_labels):
        raise ConfigurationError("Landmark output requires at least three unique labels")
    if any(not isinstance(label, str) or not label.strip() for label in landmark_labels):
        raise ConfigurationError("Landmark labels must be non-empty strings")
    if coordinates.dtype != np.float64:
        raise ConfigurationError("Landmark output coordinates must use float64")
    if coordinates.shape != (len(meshes), len(landmark_labels), 3):
        raise ConfigurationError(
            "Landmark output coordinates must have shape (meshes, landmarks, 3)"
        )
    if not np.isfinite(coordinates).all():
        raise ConfigurationError("Landmark output coordinates must be finite")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(LANDMARK_COLUMNS)
    for mesh_index, mesh_file in enumerate(meshes):
        for landmark_index, label in enumerate(landmark_labels):
            writer.writerow((mesh_file, label, *coordinates[mesh_index, landmark_index].tolist()))
    try:
        write_text_safely(destination, stream.getvalue(), overwrite=overwrite)
    except FileExistsError as error:
        raise ConfigurationError(
            f"Landmark CSV already exists and will not be overwritten: {destination}"
        ) from error
    return destination


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

    rows: dict[str, list[tuple[str, tuple[float, float, float]]]] = {name: [] for name in expected}
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
