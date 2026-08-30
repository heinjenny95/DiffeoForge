"""Post hoc subject-metadata interpretation for verified atlas PCA bundles."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np

from diffeoforge.analysis.pca import PCAResult
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_bundle import MANIFEST_NAME as MODERN_MANIFEST
from diffeoforge.modern_pca_stability import verify_modern_pca_bundle
from diffeoforge.reference_pca import (
    REFERENCE_PCA_MANIFEST,
    verify_reference_pca_bundle,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

PCA_METADATA_VERSION = "0.1"
PCA_METADATA_MANIFEST = "pca-metadata-manifest.json"
PCA_METADATA_SIDECAR = "pca-metadata-manifest.sha256"
PCA_METADATA_ANALYSIS = "metadata-analysis.json"
PCA_METADATA_JOINED = "joined-pca-metadata.csv"
PCA_METADATA_GROUPS = "categorical-group-summary.csv"
PCA_METADATA_CONTINUOUS = "continuous-pc-associations.csv"
PCA_METADATA_OUTLIERS = "pca-inspection-priorities.csv"
PCA_METADATA_HTML = "metadata-report.html"
SCIENTIFIC_BOUNDARY = (
    "Metadata are joined only after the unsupervised shape PCA is fixed. Colors, group "
    "summaries, correlations, and inspection flags are descriptive and do not force "
    "clusters, establish causation, validate registration, or exclude specimens."
)


class PCAMetadataError(RuntimeError):
    """Raised when metadata cannot be safely matched or an artifact has changed."""


@dataclass(frozen=True)
class PCAMetadataArtifact:
    artifact_directory: Path
    manifest: dict[str, Any]


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _csv_safe(value: object) -> str:
    text = str(value)
    return f"'{text}" if text and text[0] in "=+-@\t\r" else text


def _csv_text(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([_csv_safe(value) for value in headers])
    writer.writerows([_csv_safe(value) for value in row] for row in rows)
    return buffer.getvalue()


def _source_bundle(directory: Path | str) -> tuple[PCAResult, dict[str, object]]:
    root = Path(directory).expanduser().resolve()
    try:
        if (root / REFERENCE_PCA_MANIFEST).is_file():
            bundle = verify_reference_pca_bundle(root)
            return bundle.pca, {
                "kind": "deformetrica_reference_pca",
                "directory": str(bundle.bundle_directory),
                "manifest_name": REFERENCE_PCA_MANIFEST,
                "manifest_sha256": sha256_file(
                    bundle.bundle_directory / REFERENCE_PCA_MANIFEST
                ),
            }
        if (root / MODERN_MANIFEST).is_file():
            bundle = verify_modern_pca_bundle(root)
            return bundle.pca, {
                "kind": "modern_engine_pca",
                "directory": str(bundle.bundle_directory),
                "manifest_name": MODERN_MANIFEST,
                "manifest_sha256": bundle.manifest_sha256,
            }
    except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise PCAMetadataError(f"Could not verify source PCA bundle: {error}") from error
    raise PCAMetadataError("PCA bundle type is not recognized")


def _metadata_rows(
    path: Path,
    *,
    id_column: str,
    sample_labels: tuple[str, ...],
) -> tuple[tuple[str, ...], dict[str, dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeError, csv.Error) as error:
        raise PCAMetadataError(f"Could not read metadata CSV: {error}") from error
    if len(rows) < 2:
        raise PCAMetadataError("Metadata CSV requires a header and at least one data row")
    headers = tuple(value.strip() for value in rows[0])
    if any(not value for value in headers) or len(set(headers)) != len(headers):
        raise PCAMetadataError("Metadata CSV headers must be nonempty and unique")
    if id_column not in headers:
        raise PCAMetadataError(f"Metadata ID column does not exist: {id_column}")
    if len(headers) < 2:
        raise PCAMetadataError("Metadata CSV requires at least one variable beside the ID")
    by_subject: dict[str, dict[str, str]] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != len(headers):
            raise PCAMetadataError(
                f"Metadata row {row_number} has {len(row)} cells; expected {len(headers)}"
            )
        record = {header: value.strip() for header, value in zip(headers, row, strict=True)}
        subject = record[id_column]
        if not subject:
            raise PCAMetadataError(f"Metadata row {row_number} has an empty subject ID")
        if subject in by_subject:
            raise PCAMetadataError(f"Duplicate metadata subject ID: {subject}")
        by_subject[subject] = record
    expected = set(sample_labels)
    observed = set(by_subject)
    if expected != observed:
        raise PCAMetadataError(
            "Metadata subject IDs must exactly match the verified PCA labels; "
            f"missing={sorted(expected - observed)}, unexpected={sorted(observed - expected)}"
        )
    return tuple(header for header in headers if header != id_column), by_subject


def _classify_columns(
    columns: tuple[str, ...],
    rows: Mapping[str, Mapping[str, str]],
    labels: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, dict[str, float | None]]]:
    kinds = {}
    numeric: dict[str, dict[str, float | None]] = {}
    for column in columns:
        parsed: dict[str, float | None] = {}
        is_numeric = True
        for label in labels:
            raw = rows[label][column]
            if raw == "":
                parsed[label] = None
                continue
            try:
                value = float(raw)
            except ValueError:
                is_numeric = False
                break
            if not math.isfinite(value):
                raise PCAMetadataError(
                    f"Metadata column {column} contains a non-finite number for {label}"
                )
            parsed[label] = value
        if is_numeric and any(value is not None for value in parsed.values()):
            kinds[column] = "continuous"
            numeric[column] = parsed
        else:
            unique = {rows[label][column] for label in labels if rows[label][column]}
            kinds[column] = (
                "categorical"
                if len(unique) <= min(20, max(2, int(math.ceil(len(labels) * 0.5))))
                else "identifier_or_high_cardinality"
            )
    return kinds, numeric


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and math.isclose(
            float(values[order[start]]),
            float(values[order[end]]),
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            end += 1
        result[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return result


def _correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    left = first - np.mean(first)
    right = second - np.mean(second)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= np.finfo(np.float64).eps:
        return None
    return float(np.dot(left, right) / denominator)


def _inspection_priorities(pca: PCAResult) -> tuple[float, tuple[dict[str, object], ...]]:
    count = min(3, pca.number_of_components, max(1, pca.numerical_rank))
    scores = pca.scores[:, :count]
    scale = np.std(scores, axis=0, ddof=1)
    scale[scale <= np.finfo(float).eps] = 1.0
    radius = np.linalg.norm(scores / scale, axis=1)
    q1, q3 = np.quantile(radius, (0.25, 0.75), method="linear")
    threshold = float(q3 + 1.5 * (q3 - q1))
    records = tuple(
        {
            "subject": label,
            "standardized_score_radius": float(value),
            "inspection_priority": bool(value > threshold),
        }
        for label, value in zip(pca.sample_labels, radius, strict=True)
    )
    return threshold, records


def _analysis(
    pca: PCAResult,
    source: Mapping[str, object],
    metadata_path: Path,
    *,
    id_column: str,
    component_limit: int,
) -> dict[str, Any]:
    columns, rows = _metadata_rows(
        metadata_path,
        id_column=id_column,
        sample_labels=pca.sample_labels,
    )
    kinds, numeric = _classify_columns(columns, rows, pca.sample_labels)
    component_count = min(component_limit, pca.number_of_components)
    groups: list[dict[str, object]] = []
    for column in columns:
        if kinds[column] != "categorical":
            continue
        values = sorted(
            {rows[label][column] for label in pca.sample_labels if rows[label][column]},
            key=str.casefold,
        )
        for value in values:
            indices = [
                index
                for index, label in enumerate(pca.sample_labels)
                if rows[label][column] == value
            ]
            groups.append(
                {
                    "variable": column,
                    "group": value,
                    "count": len(indices),
                    "pc_means": [
                        float(np.mean(pca.scores[indices, component]))
                        for component in range(component_count)
                    ],
                    "pc_standard_deviations": [
                        (
                            None
                            if len(indices) < 2
                            else float(np.std(pca.scores[indices, component], ddof=1))
                        )
                        for component in range(component_count)
                    ],
                }
            )
    associations: list[dict[str, object]] = []
    for column, values in numeric.items():
        indices = [
            index
            for index, label in enumerate(pca.sample_labels)
            if values[label] is not None
        ]
        metadata_values = np.asarray(
            [values[pca.sample_labels[index]] for index in indices], dtype=np.float64
        )
        for component in range(component_count):
            scores = pca.scores[indices, component]
            associations.append(
                {
                    "variable": column,
                    "component": component + 1,
                    "complete_case_count": len(indices),
                    "pearson_correlation": _correlation(metadata_values, scores),
                    "spearman_rank_correlation": _correlation(
                        _rankdata(metadata_values), _rankdata(scores)
                    ),
                }
            )
    threshold, outliers = _inspection_priorities(pca)
    return {
        "analysis_version": PCA_METADATA_VERSION,
        "source_pca": dict(source),
        "metadata": {
            "path": str(metadata_path),
            "sha256": sha256_file(metadata_path),
            "id_column": id_column,
            "subject_count": len(pca.sample_labels),
            "columns": [
                {
                    "name": column,
                    "kind": kinds[column],
                    "missing_count": sum(
                        not rows[label][column] for label in pca.sample_labels
                    ),
                }
                for column in columns
            ],
        },
        "pca_component_count_used": component_count,
        "categorical_group_summaries": groups,
        "continuous_pc_associations": associations,
        "pca_inspection_priorities": {
            "component_count": min(3, pca.number_of_components, max(1, pca.numerical_rank)),
            "rule": "Q3 + 1.5 IQR of standardized PCA score radius",
            "threshold": threshold,
            "subjects": list(outliers),
            "boundary": (
                "Inspection priorities are not biological outliers or automatic exclusions."
            ),
        },
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }


def _slug(value: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "metadata"
    return f"{readable[:48]}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]}"


def _color_category(value: str) -> str:
    hue = int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16) % 360
    return f"hsl({hue} 62% 42%)"


def _scatter_svg(
    pca: PCAResult,
    rows: Mapping[str, Mapping[str, str]],
    column: str,
    kind: str,
) -> str:
    if pca.number_of_components < 2:
        return ""
    x = pca.scores[:, 0]
    y = pca.scores[:, 1]
    x_min, x_max = float(np.min(x)), float(np.max(x))
    y_min, y_max = float(np.min(y)), float(np.max(y))
    x_span = max(x_max - x_min, np.finfo(float).eps)
    y_span = max(y_max - y_min, np.finfo(float).eps)
    width, height = 900, 650
    left, top, plot_width, plot_height = 90, 55, 610, 520
    raw_values = [rows[label][column] for label in pca.sample_labels]
    numeric_values = [float(value) for value in raw_values if value] if kind == "continuous" else []
    numeric_min = min(numeric_values) if numeric_values else 0.0
    numeric_span = max(
        (max(numeric_values) - numeric_min) if numeric_values else 1.0,
        np.finfo(float).eps,
    )

    def color(value: str) -> str:
        if not value:
            return "#9aa8a6"
        if kind == "continuous":
            fraction = (float(value) - numeric_min) / numeric_span
            red = int(35 + 205 * fraction)
            blue = int(220 - 180 * fraction)
            return f"rgb({red},85,{blue})"
        return _color_category(value)

    points = []
    for label, x_value, y_value, raw in zip(
        pca.sample_labels, x, y, raw_values, strict=True
    ):
        px = left + (float(x_value) - x_min) / x_span * plot_width
        py = top + plot_height - (float(y_value) - y_min) / y_span * plot_height
        tooltip = html.escape(f"{label} | {column}: {raw or 'missing'}")
        points.append(
            f'<circle cx="{px:.3f}" cy="{py:.3f}" r="4.2" fill="{color(raw)}" '
            f'fill-opacity="0.82"><title>{tooltip}</title></circle>'
        )
    categories = sorted({value for value in raw_values if value}, key=str.casefold)
    legend = []
    if kind == "categorical":
        for index, value in enumerate(categories[:20]):
            y_position = 85 + index * 24
            legend.append(
                f'<circle cx="735" cy="{y_position}" r="5" fill="{_color_category(value)}"/>'
                f'<text x="748" y="{y_position + 4}" font-size="12">{html.escape(value)}</text>'
            )
    else:
        legend.append(
            f'<text x="725" y="85" font-size="12">min {numeric_min:.5g}</text>'
            f'<text x="725" y="110" font-size="12">max '
            f'{numeric_min + numeric_span:.5g}</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
viewBox="0 0 {width} {height}" role="img" aria-label="PC1 PC2 colored by {html.escape(column)}">
<rect width="100%" height="100%" fill="white"/><text x="90" y="28" font-family="Segoe UI,Arial"
font-size="19" font-weight="600">PC1–PC2 colored by {html.escape(column)}</text>
<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}"
stroke="#355"/><line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#355"/>
<text x="370" y="625" font-family="Segoe UI,Arial" font-size="14">PC1</text>
<text x="24" y="330" transform="rotate(-90 24 330)" font-family="Segoe UI,Arial"
font-size="14">PC2</text>{''.join(points)}<g font-family="Segoe UI,Arial">{''.join(legend)}</g>
<text x="725" y="610" font-family="Segoe UI,Arial" font-size="11" fill="#566">
Post-PCA metadata only</text>
</svg>"""


def _render_files(
    pca: PCAResult,
    analysis: Mapping[str, Any],
    metadata_path: Path,
    *,
    id_column: str,
) -> dict[str, str]:
    columns, rows = _metadata_rows(
        metadata_path,
        id_column=id_column,
        sample_labels=pca.sample_labels,
    )
    kinds = {item["name"]: item["kind"] for item in analysis["metadata"]["columns"]}
    score_headers = tuple(f"PC{index + 1}" for index in range(pca.number_of_components))
    files = {
        PCA_METADATA_ANALYSIS: _canonical_json(analysis),
        PCA_METADATA_JOINED: _csv_text(
            (id_column, *score_headers, *columns),
            [
                (
                    label,
                    *(format(value, ".17g") for value in pca.scores[index]),
                    *(rows[label][column] for column in columns),
                )
                for index, label in enumerate(pca.sample_labels)
            ],
        ),
        PCA_METADATA_GROUPS: _csv_text(
            ("variable", "group", "count", "component", "mean", "standard_deviation"),
            [
                (
                    item["variable"],
                    item["group"],
                    item["count"],
                    component + 1,
                    format(item["pc_means"][component], ".17g"),
                    (
                        ""
                        if item["pc_standard_deviations"][component] is None
                        else format(item["pc_standard_deviations"][component], ".17g")
                    ),
                )
                for item in analysis["categorical_group_summaries"]
                for component in range(len(item["pc_means"]))
            ],
        ),
        PCA_METADATA_CONTINUOUS: _csv_text(
            (
                "variable",
                "component",
                "complete_case_count",
                "pearson_correlation",
                "spearman_rank_correlation",
            ),
            [
                (
                    item["variable"],
                    item["component"],
                    item["complete_case_count"],
                    (
                        ""
                        if item["pearson_correlation"] is None
                        else format(item["pearson_correlation"], ".17g")
                    ),
                    (
                        ""
                        if item["spearman_rank_correlation"] is None
                        else format(item["spearman_rank_correlation"], ".17g")
                    ),
                )
                for item in analysis["continuous_pc_associations"]
            ],
        ),
        PCA_METADATA_OUTLIERS: _csv_text(
            ("subject", "standardized_score_radius", "inspection_priority", "threshold"),
            [
                (
                    item["subject"],
                    format(item["standardized_score_radius"], ".17g"),
                    str(item["inspection_priority"]).lower(),
                    format(analysis["pca_inspection_priorities"]["threshold"], ".17g"),
                )
                for item in analysis["pca_inspection_priorities"]["subjects"]
            ],
        ),
    }
    plot_links = []
    for column in columns:
        if kinds[column] not in {"categorical", "continuous"}:
            continue
        relative = f"plots/{_slug(column)}.svg"
        files[relative] = _scatter_svg(pca, rows, column, kinds[column])
        plot_links.append(
            f'<figure><img src="{relative}" alt="PC scatter colored by {html.escape(column)}">'
            f"<figcaption>{html.escape(column)} ({kinds[column]})</figcaption></figure>"
        )
    files[PCA_METADATA_HTML] = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DiffeoForge PCA metadata report</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:36px auto;padding:0 24px;
color:#103b3b;line-height:1.45}}.notice{{background:#e3f6ef;border-left:5px solid #13856f;
padding:14px 18px}}figure{{margin:28px 0}}img{{max-width:100%;height:auto;border:1px solid #ccd}}
</style></head><body><h1>DiffeoForge PCA metadata report</h1>
<p class="notice">{html.escape(SCIENTIFIC_BOUNDARY)}</p>
<p>{analysis['metadata']['subject_count']} subjects; {len(columns)} metadata variables; metadata
were joined after PCA and did not alter the atlas or axes.</p>{''.join(plot_links)}</body></html>"""
    return files


def write_pca_metadata_analysis(
    pca_bundle: Path | str,
    metadata_csv: Path | str,
    destination: Path | str,
    *,
    id_column: str = "subject",
    component_limit: int = 10,
    created_at: str | None = None,
) -> PCAMetadataArtifact:
    """Create an immutable post-PCA metadata interpretation bundle."""

    pca, source = _source_bundle(pca_bundle)
    metadata_path = Path(metadata_csv).expanduser().resolve()
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise PCAMetadataError(f"Metadata CSV is missing or symbolic: {metadata_path}")
    if (
        isinstance(component_limit, bool)
        or not isinstance(component_limit, int)
        or component_limit < 1
    ):
        raise PCAMetadataError("component_limit must be a positive integer")
    timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise PCAMetadataError("created_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise PCAMetadataError("created_at must include a timezone offset")
    analysis = _analysis(
        pca,
        source,
        metadata_path,
        id_column=id_column,
        component_limit=component_limit,
    )
    files = _render_files(pca, analysis, metadata_path, id_column=id_column)
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"PCA metadata destination exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for relative, content in files.items():
            path = temporary.joinpath(*Path(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_safely(path, content, overwrite=False)
        artifacts = [
            {
                "path": path.relative_to(temporary).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "artifact_version": PCA_METADATA_VERSION,
            "created_at": timestamp,
            "source_pca": source,
            "metadata_source": {
                "path": str(metadata_path),
                "sha256": sha256_file(metadata_path),
                "id_column": id_column,
            },
            "settings": {"component_limit": component_limit},
            "analysis": analysis,
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
            "verification_contract": (
                "The source PCA, metadata CSV, subject join, analysis, figures, tables, "
                "and exact artifact inventory are reverified and recomputed."
            ),
        }
        manifest_path = temporary / PCA_METADATA_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / PCA_METADATA_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
        )
        verify_pca_metadata_analysis(temporary)
        publish_directory_exclusive(temporary, target)
        return verify_pca_metadata_analysis(target)
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def verify_pca_metadata_analysis(directory: Path | str) -> PCAMetadataArtifact:
    """Reverify source inputs and exactly recompute post-PCA metadata outputs."""

    root = Path(directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PCAMetadataError(f"PCA metadata artifact is missing or symbolic: {root}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise PCAMetadataError("PCA metadata artifact contains a symbolic path")
    manifest_path = root / PCA_METADATA_MANIFEST
    sidecar_path = root / PCA_METADATA_SIDECAR
    try:
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
        manifest = load_strict_json_object(
            manifest_path.read_bytes(), manifest_path, label="PCA metadata manifest"
        )
    except (ConfigurationError, OSError, UnicodeError) as error:
        raise PCAMetadataError(f"Could not read PCA metadata manifest: {error}") from error
    if expected_digest != sha256_file(manifest_path):
        raise PCAMetadataError("PCA metadata manifest SHA-256 differs")
    if manifest.get("artifact_version") != PCA_METADATA_VERSION:
        raise PCAMetadataError("PCA metadata artifact version is unsupported")
    if manifest.get("scientific_boundary") != SCIENTIFIC_BOUNDARY:
        raise PCAMetadataError("PCA metadata scientific boundary differs")
    source = manifest["source_pca"]
    pca, actual_source = _source_bundle(str(source["directory"]))
    if source != actual_source:
        raise PCAMetadataError("PCA metadata source identity or manifest changed")
    metadata = manifest["metadata_source"]
    metadata_path = Path(str(metadata["path"])).resolve()
    if (
        not metadata_path.is_file()
        or metadata_path.is_symlink()
        or sha256_file(metadata_path) != metadata["sha256"]
    ):
        raise PCAMetadataError("PCA metadata source CSV changed")
    analysis = _analysis(
        pca,
        source,
        metadata_path,
        id_column=str(metadata["id_column"]),
        component_limit=int(manifest["settings"]["component_limit"]),
    )
    if manifest["analysis"] != analysis:
        raise PCAMetadataError("PCA metadata analysis differs from exact recomputation")
    files = _render_files(
        pca, analysis, metadata_path, id_column=str(metadata["id_column"])
    )
    records = manifest["artifacts"]
    expected_records = []
    for relative, content in files.items():
        encoded = content.encode("utf-8")
        expected_records.append(
            {
                "path": Path(relative).as_posix(),
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    expected_records.sort(key=lambda item: item["path"])
    if records != expected_records:
        raise PCAMetadataError("PCA metadata artifact inventory differs from recomputation")
    expected_files = {
        PCA_METADATA_MANIFEST,
        PCA_METADATA_SIDECAR,
        *(record["path"] for record in records),
    }
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if expected_files != actual_files:
        raise PCAMetadataError("PCA metadata exact file inventory differs")
    for record in records:
        path = root.joinpath(*Path(record["path"]).parts)
        if (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise PCAMetadataError(f"PCA metadata artifact changed: {record['path']}")
    return PCAMetadataArtifact(root, dict(manifest))
