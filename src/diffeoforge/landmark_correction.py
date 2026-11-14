"""Subset landmark correction with an unchanged, complete source cohort."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import read_landmark_csv, write_landmark_csv
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.mesh import sha256_file


@dataclass(frozen=True)
class LandmarkCorrection:
    source: Path
    source_sha256: str
    mesh_paths: tuple[Path, ...]
    labels: tuple[str, ...]
    values: np.ndarray
    selected: tuple[str, ...]
    selected_hashes: dict[str, str]
    output: Path

    @property
    def binding(self):
        return dict(source=str(self.source), source_sha256=self.source_sha256,
                    selected=list(self.selected), selected_sha256=self.selected_hashes,
                    cohort=[str(p) for p in self.mesh_paths], labels=list(self.labels))


def prepare(source, mesh_paths, selected, project_directory):
    """Read coordinates and hash only selected originals, outside the GUI thread."""
    source = Path(source).expanduser().resolve()
    paths = tuple(Path(p).expanduser().resolve() for p in mesh_paths)
    names = tuple(p.name for p in paths)
    requested = tuple(selected)
    if (not requested or len(set(requested)) != len(requested)
            or not set(requested) <= set(names)):
        raise ValueError("Select one or more specimens from the current mesh cohort")
    selected = tuple(n for n in names if n in requested)
    source_hash = sha256_file(source)
    labels, values = read_landmark_csv(source, names)
    hashes = {p.name: sha256_file(p) for p in paths if p.name in selected}
    if sha256_file(source) != source_hash:
        raise ValueError("The landmark CSV changed while it was being loaded. Reopen correction.")
    values.setflags(write=False)
    binding = dict(source=str(source), source_sha256=source_hash,
                   cohort=[str(p) for p in paths], selected=list(selected), hashes=hashes)
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:16]
    root = Path(project_directory).expanduser().resolve() / "landmark-corrections"
    output = root / key / "landmarks.csv"
    number = 1
    while output.exists():
        number += 1
        output = root / f"{key}-{number}" / "landmarks.csv"
    return LandmarkCorrection(source, source_hash, paths, labels, values, selected, hashes, output)


def placements(session):
    return {p.name: {label: tuple(float(v) for v in session.values[index, j])
                     for j, label in enumerate(session.labels)}
            for index, p in enumerate(session.mesh_paths) if p.name in session.selected}


def save(session, corrected):
    """Merge selected coordinates, preserving every other Float64 coordinate exactly."""
    if sha256_file(session.source) != session.source_sha256:
        raise ValueError("The original landmark CSV changed. Reopen correction before saving.")
    if set(corrected) != set(session.selected):
        raise ValueError("Correction must contain exactly the selected specimens")
    merged = session.values.copy()
    changed = []
    for i, path in enumerate(session.mesh_paths):
        if path.name not in corrected:
            continue
        if sha256_file(path) != session.selected_hashes[path.name]:
            raise ValueError(f"Source mesh changed: {path.name}. Reopen correction.")
        row = corrected[path.name]
        if set(row) != set(session.labels):
            raise ValueError("Keep the existing landmark labels and complete every selected point")
        points = np.asarray([row[label] for label in session.labels], dtype=np.float64)
        if points.shape != (len(session.labels), 3) or not np.isfinite(points).all():
            raise ValueError("Corrected landmarks must contain finite 3D coordinates")
        merged[i] = points
        if not np.array_equal(points, session.values[i]):
            changed.append(path.name)
    # Source files are immutable inputs; an independent complete CSV becomes active only
    # after the caller receives success. Existing alignment and fits are never rewritten.
    if sha256_file(session.source) != session.source_sha256:
        raise ValueError(
            "The original landmark CSV changed during verification. Reopen correction.")
    write_landmark_csv(session.output, tuple(p.name for p in session.mesh_paths),
                       session.labels, merged)
    receipt = dict(kind="landmark_subset_correction", schema_version=1, **session.binding,
                   output_sha256=sha256_file(session.output), changed_specimens=changed,
                   unselected_coordinates_unchanged=True, alignment_recheck_required=True,
                   scientific_fit_started=False)
    write_text_safely(session.output.with_suffix(".correction.json"),
                      json.dumps(receipt, indent=2) + "\n", overwrite=False)
    return session.output
