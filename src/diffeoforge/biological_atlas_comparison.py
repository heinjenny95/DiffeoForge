"""Local sensitivity report for an explicit two-group question and two saved atlases."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from diffeoforge import atlas_comparison as atlas
from diffeoforge.analysis.atlas_group_anatomy import compare_group_anatomy
from diffeoforge.analysis.atlas_group_scores import compare_group_scores
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.mesh import sha256_file
from diffeoforge.pca_metadata import _metadata_rows
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

REPORT_NAME = "group-comparison.html"
DATA_NAME = "group-comparison.json"
VERSION = "1"


def _percent(value):
    return "Unavailable" if value is None else f"{value:.2%}"


def _number(value):
    return "Unavailable" if value is None else f"{value:.3f}"


def _nearby_views(anatomy):
    outline = np.asarray(anatomy["template_outline"], dtype=float)
    top = anatomy["top_vertices"]
    vertices = {
        key: np.asarray([row["coordinate"] for row in rows], dtype=float).reshape(-1, 3)
        for key, rows in top.items()
    }
    extent = anatomy["basis"]["template_diagonal"]
    if not len(outline) or not any(len(points) for points in vertices.values()):
        return ""
    low = np.min(outline, axis=0)
    high = np.max(outline, axis=0)
    center = (low + high) / 2

    def circles(points, axes, color, radius, opacity):
        positions = (points[:, axes] - center[list(axes)]) * (210 / extent)
        return "".join(
            f'<circle cx="{125 + x:.2f}" cy="{125 - y:.2f}" r="{radius}" '
            f'fill="{color}" opacity="{opacity}"/>'
            for x, y in positions
        )

    panels = []
    for axes, label in [((0, 1), "XY"), ((0, 2), "XZ"), ((1, 2), "YZ")]:
        marks = "".join(
            circles(points, axes, color, 3, 0.8)
            for points, color in zip(vertices.values(), ("#207b91", "#bc581e"), strict=True)
        )
        panels.append(
            f'<svg viewBox="0 0 250 250" role="img" aria-label="{label} projection">'
            f'<text x="12" y="22">{label}</text>'
            f"{circles(outline, axes, '#7c9295', 1.15, 0.38)}{marks}</svg>"
        )
    return '<div class="views">' + "".join(panels) + "</div>"


def _anatomy_section(anatomy):
    if not anatomy["available"]:
        return f"<p>Regional comparison unavailable. {escape(anatomy['unavailable_reason'])}</p>"
    overlap = anatomy["top_effect_overlap"]
    rms = anatomy["effect_rms_fraction"]
    return (
        "<p>Group mean reconstruction displacement at matched vertices of the shared "
        "starting template, scaled by the template diagonal. The views highlight examples "
        "from the largest effects in Atlas A (teal) and Atlas B (orange). "
        "Template indices describe model correspondence. Anatomical homology requires "
        "independent evidence.</p>"
        f"<p>Displacement RMS: A {_percent(rms['first'])}, B {_percent(rms['second'])}. "
        f"Direction agreement (cosine): {_number(anatomy['effect_direction_cosine'])}. "
        f"Overlap among the largest effects (Jaccard): {_number(overlap['jaccard'])}.</p>"
        f"{_nearby_views(anatomy)}"
    )


def _settings(review):
    if review.engine_route != "deformetrica_reference":
        return {}
    path = review.workflow_manifest_path
    config = load_strict_json_object(path.read_bytes(), path, label="Run manifest").get(
        "effective_config", {}
    )
    model = config.get("model", {})
    attachment = model.get("attachment", {})
    deformation = model.get("deformation", {})
    optimization = config.get("optimization", {})
    return {
        "Attachment": attachment.get("type"),
        "Attachment kernel width": attachment.get("kernel_width"),
        "Deformation kernel width": deformation.get("kernel_width"),
        "Initial control-point spacing": deformation.get("initial_control_point_spacing"),
        "Integration timepoints": deformation.get("timepoints"),
        "Convergence tolerance": optimization.get("convergence_tolerance"),
        "Iteration cap": optimization.get("max_iterations"),
        "Coordinate unit": config.get("input", {}).get("units"),
    }


def _setting_cell(value):
    return escape('Unavailable' if value is None else str(value))


def _settings_section(payload):
    sources = payload["sources"]
    left, right = (sources[key]["settings"] for key in ("first", "second"))
    rows = "".join(
        f"<tr><th scope='row'>{escape(name)}</th>"
        f"<td>{_setting_cell(left.get(name))}</td>"
        f"<td>{_setting_cell(right.get(name))}</td></tr>"
        for name in sorted(left.keys() | right.keys())
        if left.get(name) is not None or right.get(name) is not None
    )
    if not rows:
        return ""
    return (
        "<details><summary>Recorded atlas settings</summary>"
        "<table><thead><tr><th>Setting</th><th>Atlas A</th><th>Atlas B</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></details>"
    )


def _report(payload):
    scores = payload["scores"]
    anatomy = payload["anatomy"]
    metadata = payload["metadata"]
    headings = (
        "Group share of variation in all PC dimensions",
        "Group share of variation in the displayed PC1–2 plane",
        "Share of full group centroid separation squared visible in PC1–2",
    )
    metrics = (
        "full_group_variance_fraction",
        "pc1_pc2_group_variance_fraction",
        "pc1_pc2_fraction_of_full_centroid_gap_squared",
    )
    rows = "".join(
        f"<tr><th scope='row'>{label}</th>"
        + "".join(f"<td>{_percent(scores[key][metric])}</td>" for key in ("first", "second"))
        + "</tr>"
        for label, metric in zip(headings, metrics, strict=True)
    )
    shifted = "".join(
        f"<li>{escape(row['specimen'])} · {row['mean_rank_change']:.2f} rank positions</li>"
        for row in scores["largest_subject_distance_rank_changes"]
        if row["mean_rank_change"] > 0.0
    )
    shift_details = (
        "<details><summary>Specimens with largest changes in distance rankings</summary>"
        "<p>Mean absolute rank change across this specimen’s distances to all other specimens "
        f"in the full saved PCA spaces.</p><ul>{shifted}</ul></details>"
        if shifted else ""
    )
    first_run, second_run = (
        escape(Path(payload["sources"][key]["run_directory"]).name) for key in ("first", "second")
    )
    geometry = payload["cohort_binding"]
    matching = geometry["identical_staged_surfaces"]
    geometry_text = (
        "The user-declared specimen pairing was checked against both saved PCA label lists. "
        + (
            f"Staged input bytes match for {matching} of {scores['sample_count']} specimens. "
            if matching is not None
            else "A staged-input byte comparison was unavailable. "
        )
        + "Changes in preprocessing can contribute to differences between the atlases."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Group effects across atlases</title>
<style>
body{{font-family:Inter,Segoe UI,sans-serif;line-height:1.5;color:#183639;margin:32px auto;
padding:0 20px;max-width:1000px}} table{{width:100%;border-collapse:collapse}}
th,td{{border-bottom:1px solid #cad8d9;text-align:left;padding:10px 12px}}
thead{{background:#e8f0f1}} .views{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
svg{{background:#f1f5f5;width:100%}}
</style></head><body>
<h1>Group effects across atlases</h1>
<p>{escape(metadata["comparison_level"])} (n={scores["comparison_count"]}) versus
{escape(metadata["reference_level"])} (n={scores["reference_count"]}) based on
{escape(metadata["group_column"])}. {scores["unassigned_count"]} specimens in other
groups enter the distance comparison and contributed to the saved PCA axes.</p>
<p><strong>Atlas A</strong> {first_run} · <strong>Atlas B</strong> {second_run}</p>
<h2>Group separation</h2>
<table><thead><tr><th>Measure</th><th>Atlas A</th><th>Atlas B</th></tr></thead>
<tbody>{rows}</tbody></table>
<p>Read the full-space row alongside the PC1–2 row to see how much the displayed
projection contributes to the apparent difference. Each atlas uses its own
saved score metric. The table describes the association in this selected
cohort. Statistical inference and biological interpretation require the study design.</p>
<h2>Specimen relationships</h2>
<p>Between-atlas distance-rank correlation in all PC dimensions
<strong>{_number(scores["full_pairwise_distance_rank_correlation"])}</strong>.
In the PC1–2 planes
<strong>{_number(scores["pc1_pc2_pairwise_distance_rank_correlation"])}</strong>.</p>
<p>{escape(geometry_text)}</p>
{shift_details}
<h2>Where the group means differ</h2>
{_anatomy_section(anatomy)}
<h2>Sources</h2>
{_settings_section(payload)}
<p><a href="{DATA_NAME}">Download settings, source checksums and measurements (JSON)</a></p>
<p>The report leaves atlas selection and anatomical review with the researcher.</p>
</body></html>
"""


def _staged_hashes(review):
    return {
        row.subject_name: review.artifact(row.original_artifact_key).sha256
        for row in review.registration_qc
    }


def write_group_comparison(
    first_directory,
    second_directory,
    metadata_csv,
    destination,
    *,
    id_column,
    group_column,
    reference_level,
    comparison_level,
) -> Path:
    """Measure and publish one report beside the verified read-only sources."""
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"Group comparison destination already exists: {target}")
    first = atlas._review(first_directory, create_pca_if_missing=False)
    second = atlas._review(second_directory, create_pca_if_missing=False)
    if first.run_directory == second.run_directory:
        raise atlas.AtlasComparisonError("Choose two distinct saved atlas runs")
    for review in (first, second):
        if any(
            target.is_relative_to(path.resolve())
            for path in (review.run_directory, review.bundle_directory)
        ):
            raise atlas.AtlasComparisonError("Save this report outside the source atlas runs")

    pca_a, pca_b = (atlas._pca(run) for run in (first, second))
    labels = tuple(pca_a.sample_labels)
    if set(labels) != set(pca_b.sample_labels):
        raise atlas.AtlasComparisonError("The two atlases must contain the same PCA specimen IDs")
    metadata = Path(metadata_csv).expanduser().resolve()
    metadata_hash = sha256_file(metadata)
    columns, records = _metadata_rows(metadata, id_column=id_column, sample_labels=labels)
    if (
        group_column not in columns
        or not reference_level
        or not comparison_level
        or reference_level == comparison_level
    ):
        raise atlas.AtlasComparisonError("Choose a group column and two distinct group levels")
    if any(not row[group_column] for row in records.values()):
        raise atlas.AtlasComparisonError("The group column must have a value for each specimen")
    reference_ids = tuple(
        label for label in labels if records[label][group_column] == reference_level
    )
    comparison_ids = tuple(
        label for label in labels if records[label][group_column] == comparison_level
    )
    scores = compare_group_scores(pca_a, pca_b, reference_ids, comparison_ids)
    anatomy = compare_group_anatomy(first, second, reference_ids, comparison_ids)
    hashes_a, hashes_b = (_staged_hashes(review) for review in (first, second))
    matching = (
        sum(hashes_a[label] == hashes_b[label] for label in labels)
        if set(hashes_a) == set(hashes_b) == set(labels)
        else None
    )
    payload = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            key: dict(atlas._source(run), settings=_settings(run))
            for key, run in (("first", first), ("second", second))
        },
        "metadata": {
            "filename": metadata.name,
            "sha256": metadata_hash,
            "id_column": id_column,
            "group_column": group_column,
            "reference_level": reference_level,
            "comparison_level": comparison_level,
            "reference_ids": reference_ids,
            "comparison_ids": comparison_ids,
        },
        "cohort_binding": {"identical_staged_surfaces": matching, "sample_labels": labels},
        "scores": scores,
        "anatomy": anatomy,
    }
    if sha256_file(metadata) != metadata_hash:
        raise atlas.AtlasComparisonError("Group metadata changed during comparison")
    for review in (first, second):
        if (
            sha256_file(review.workflow_manifest_path) != review.workflow_manifest_sha256
            or sha256_file(review.bundle_manifest_path) != review.bundle_manifest_sha256
        ):
            raise atlas.AtlasComparisonError("An atlas or PCA manifest changed during comparison")

    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".group-comparison-", dir=target.parent) as temporary:
        staged = Path(temporary)
        for filename, content in (
            (REPORT_NAME, _report(payload)),
            (DATA_NAME, atlas._canonical_json(payload)),
        ):
            write_text_safely(staged / filename, content, overwrite=False)
            if (staged / filename).read_text(encoding="utf-8") != content:
                raise atlas.AtlasComparisonError("Group comparison report did not verify")
        publish_directory_exclusive(staged, target)
    return target / REPORT_NAME
