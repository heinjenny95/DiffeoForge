"""Native Slicer Markups JSON import into the ordered landmark cohort boundary."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import write_landmark_csv
from diffeoforge.config import ConfigurationError


@dataclass(frozen=True)
class LandmarkJsonData:
    source_path: Path
    coordinate_system: str
    coordinate_units: tuple[str, str] | None
    source_labels: tuple[str, ...]
    coordinates: np.ndarray


@dataclass(frozen=True)
class LandmarkJsonImportResult:
    csv_path: Path
    mesh_files: tuple[str, ...]
    json_files: tuple[Path, ...]
    landmark_labels: tuple[str, ...]
    coordinate_system: str
    coordinate_units: tuple[str, str] | None
    ignored_json_files: tuple[Path, ...]

    @property
    def units_label(self) -> str:
        if self.coordinate_units is None:
            return "unspecified (confirm against the meshes)"
        code, scheme = self.coordinate_units
        return f"{code} ({scheme})"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def read_landmark_json(path: Path | str) -> LandmarkJsonData:
    """Read one Fiducial list without transforming coordinates or reordering points.

    Follows the coordinate contract of Slicer's Markups JSON schema v1.0.3, not
    general scene/curve import. Missing positionStatus follows Slicer's 'defined'
    default, but finite 3D positions and explicit RAS/LPS are always required.
    Missing units remain unspecified. Schema URLs are never fetched or executed.
    Unit identity is (code, coding scheme); the display meaning is not identity.
    """

    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_json_object
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ConfigurationError(f"Could not read landmark JSON {source}: {error}") from error
    markups = payload.get("markups") if isinstance(payload, dict) else None
    if not isinstance(markups, list) or len(markups) != 1 or not isinstance(markups[0], dict):
        raise ConfigurationError(
            f"Landmark JSON {source} must contain exactly one Slicer Fiducial markup; "
            "export separate per-mesh Fiducial files, not a scene or multiple markups"
        )
    markup = markups[0]
    if markup.get("type") != "Fiducial":
        raise ConfigurationError(
            f"Landmark JSON {source} has unsupported markup type {markup.get('type')!r}; "
            "only Fiducial points are supported, not curves, planes, or ROIs"
        )
    system = markup.get("coordinateSystem")
    if system not in ("RAS", "LPS"):
        raise ConfigurationError(
            f"Landmark JSON {source} must explicitly declare coordinateSystem RAS or LPS"
        )
    units = markup.get("coordinateUnits")
    if "coordinateUnits" not in markup:
        coordinate_units = None
    elif isinstance(units, str) and units.strip():
        coordinate_units = (units.strip(), "UCUM")
    elif (
        isinstance(units, list)
        and len(units) == 3
        and all(isinstance(item, str) and item.strip() for item in units)
    ):
        coordinate_units = (units[0].strip(), units[1].strip())
    else:
        raise ConfigurationError(
            f"Landmark JSON {source} coordinateUnits must be a non-empty UCUM string "
            "or [code, coding scheme, meaning]"
        )
    points = markup.get("controlPoints")
    if not isinstance(points, list) or len(points) < 3:
        raise ConfigurationError(f"Landmark JSON {source} requires at least three control points")
    coordinates = []
    labels = []
    for index, point in enumerate(points, start=1):
        context = f"Landmark JSON {source} control point {index}"
        if not isinstance(point, dict):
            raise ConfigurationError(f"{context} must be an object")
        if point.get("positionStatus", "defined") != "defined":
            raise ConfigurationError(f"{context} is not a defined control point")
        position = point.get("position")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or any(type(value) not in (int, float) for value in position)
        ):
            raise ConfigurationError(f"{context} requires a numeric 3D position")
        try:
            xyz = tuple(float(value) for value in position)
        except OverflowError as error:
            raise ConfigurationError(f"{context} contains non-finite coordinates") from error
        if not all(math.isfinite(value) for value in xyz):
            raise ConfigurationError(f"{context} contains non-finite coordinates")
        label = point.get("label", "")
        point_id = point.get("id", "")
        if not isinstance(label, str) or not isinstance(point_id, str):
            raise ConfigurationError(f"{context} label and id must be strings when provided")
        labels.append(label.strip() or point_id.strip() or f"LM{index}")
        coordinates.append(xyz)
    values = np.asarray(coordinates, dtype=np.float64)
    values.setflags(write=False)
    return LandmarkJsonData(source, system, coordinate_units, tuple(labels), values)


def import_landmark_json_folder(
    json_directory: Path | str,
    mesh_files: Sequence[Path | str],
    output_path: Path | str,
    *,
    overwrite: bool = False,
) -> LandmarkJsonImportResult:
    """Match .mrk.json (or .json) files to exact case-insensitive mesh stems.

    Point order defines homology, not specimen-specific labels. All selected files
    must have equal point counts, coordinate systems, and declared units. Nothing
    is written until the entire cohort passes; original files remain untouched.
    """

    source_directory = Path(json_directory).expanduser().resolve()
    if not source_directory.is_dir():
        raise ConfigurationError(f"Landmark JSON folder does not exist: {source_directory}")
    mesh_names = tuple(Path(mesh_file).name for mesh_file in mesh_files)
    if len(mesh_names) < 2:
        raise ConfigurationError("Landmark JSON import requires at least two meshes")
    if any(not name for name in mesh_names):
        raise ConfigurationError("Landmark mesh filenames must be non-empty")
    mesh_stems = tuple(Path(name).stem.casefold() for name in mesh_names)
    if len(set(mesh_stems)) != len(mesh_stems):
        raise ConfigurationError(
            "Landmark JSON import requires unique mesh stems when compared case-insensitively"
        )
    try:
        candidates = tuple(
            sorted(
                (
                    path.resolve()
                    for path in source_directory.iterdir()
                    if path.is_file() and path.suffix.casefold() == ".json"
                ),
                key=lambda path: path.name.casefold(),
            )
        )
    except OSError as error:
        raise ConfigurationError(
            f"Could not inspect landmark JSON folder {source_directory}: {error}"
        ) from error
    output = Path(output_path).expanduser().resolve()
    protected_sources = set(candidates) | {
        Path(mesh_file).expanduser().resolve() for mesh_file in mesh_files
    }
    if output in protected_sources:
        raise ConfigurationError(
            f"Landmark CSV output must not replace a source JSON or mesh file: {output}"
        )
    by_stem: dict[str, Path] = {}
    for candidate in candidates:
        name = candidate.name.casefold()
        stem = name[:-9] if name.endswith(".mrk.json") else name[:-5]
        if stem in by_stem:
            raise ConfigurationError(
                "Landmark JSON filenames must have unique stems when compared "
                f"case-insensitively: {by_stem[stem].name!r}, {candidate.name!r}"
            )
        by_stem[stem] = candidate
    missing = [
        name for name, stem in zip(mesh_names, mesh_stems, strict=True) if stem not in by_stem
    ]
    if missing:
        raise ConfigurationError(
            "Missing landmark JSON file(s) matching mesh stem(s): " + ", ".join(missing)
        )
    selected = tuple(by_stem[stem] for stem in mesh_stems)
    parsed = tuple(read_landmark_json(path) for path in selected)
    first = parsed[0]
    count = first.coordinates.shape[0]
    for item in parsed[1:]:
        if item.coordinates.shape[0] != count:
            raise ConfigurationError(
                "Every landmark JSON must contain the same ordered defined-point count; "
                f"expected {count}, {item.source_path.name} has {item.coordinates.shape[0]}"
            )
        if item.coordinate_system != first.coordinate_system:
            raise ConfigurationError(
                "Every landmark JSON must declare the same coordinate system; "
                f"expected {first.coordinate_system}, {item.source_path.name} "
                f"declares {item.coordinate_system}. No RAS/LPS conversion is applied."
            )
        if item.coordinate_units != first.coordinate_units:
            raise ConfigurationError(
                "Every landmark JSON must have the same coordinate units declaration "
                f"(including unspecified units); mismatch at {item.source_path.name}. "
                "No unit conversion is applied."
            )
    labels = tuple(f"LM{index}" for index in range(1, count + 1))
    destination = write_landmark_csv(
        output,
        mesh_names,
        labels,
        np.stack([item.coordinates for item in parsed]),
        overwrite=overwrite,
    )
    selected_set = set(selected)
    return LandmarkJsonImportResult(
        csv_path=destination,
        mesh_files=mesh_names,
        json_files=selected,
        landmark_labels=labels,
        coordinate_system=first.coordinate_system,
        coordinate_units=first.coordinate_units,
        ignored_json_files=tuple(path for path in candidates if path not in selected_set),
    )
