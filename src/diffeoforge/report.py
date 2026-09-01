"""Self-contained HTML preflight reports for atlas configurations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import (
    ConfigurationError,
    InputSummary,
    load_config,
    validate_input_paths,
)
from diffeoforge.mesh import MeshMetadata, inspect_inputs, read_vtk_polydata
from diffeoforge.mesh_quality import (
    ATLAS_INPUT_MESH_QUALITY_SETTINGS,
    QUALITY_BOUNDARY,
    MeshQualityError,
    MeshQualityResult,
    assess_triangle_mesh,
    enforce_mesh_quality,
)

_REPORT_MARKER = '<meta name="generator" content="DiffeoForge preflight">'


def ensure_preflight_report_replaceable(path: Path | str) -> Path:
    """Refuse replacement unless an existing path is an owned regular report file."""

    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ConfigurationError(
            "Refusing replacement because the existing preflight-report path is a "
            f"symbolic link: {candidate.absolute()}"
        )
    destination = candidate.resolve()
    if not destination.exists():
        return destination
    if not destination.is_file():
        raise ConfigurationError(
            "Refusing replacement because the existing preflight-report path is not a "
            f"regular file: {destination}"
        )
    try:
        prefix = destination.read_text(encoding="utf-8")[:2048]
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(
            f"Could not verify existing preflight report {destination}: {error}"
        ) from error
    if _REPORT_MARKER not in prefix:
        raise ConfigurationError(
            "Refusing replacement because the existing HTML file is not recognized as "
            f"a DiffeoForge preflight report: {destination}"
        )
    return destination


@dataclass(frozen=True)
class PreflightResult:
    """Validated configuration, geometry inventory, and observable notices."""

    config_path: Path
    config: Mapping[str, Any]
    inputs: InputSummary
    template: MeshMetadata
    subjects: tuple[MeshMetadata, ...]
    notices: tuple[str, ...]
    mesh_quality: tuple[PreflightMeshQuality, ...] = field(default_factory=tuple)

    @property
    def total_input_bytes(self) -> int:
        return self.template.bytes + sum(subject.bytes for subject in self.subjects)

    @property
    def parameter_ratios(self) -> Mapping[str, float]:
        diagonal = self.template.bounding_box_diagonal
        model = self.config["model"]
        return {
            "Attachment kernel width / template diagonal": (
                model["attachment"]["kernel_width"] / diagonal
            ),
            "Deformation kernel width / template diagonal": (
                model["deformation"]["kernel_width"] / diagonal
            ),
            "Control-point spacing / template diagonal": (
                model["deformation"]["initial_control_point_spacing"] / diagonal
            ),
            "Noise standard deviation / template diagonal": model["noise_std"] / diagonal,
        }


@dataclass(frozen=True)
class PreflightMeshQuality:
    """Exact structural diagnostics for one preflight input mesh."""

    role: str
    path: str
    result: MeshQualityResult


def _bbox_center(mesh: MeshMetadata) -> tuple[float, float, float]:
    bounds = mesh.bounds
    return (
        (bounds[0] + bounds[1]) / 2.0,
        (bounds[2] + bounds[3]) / 2.0,
        (bounds[4] + bounds[5]) / 2.0,
    )


def _structural_quality(
    template: MeshMetadata,
    subjects: tuple[MeshMetadata, ...],
) -> tuple[PreflightMeshQuality, ...]:
    records: list[PreflightMeshQuality] = []
    for role, metadata in (("template", template), *[("subject", item) for item in subjects]):
        mesh = read_vtk_polydata(metadata.path)
        quality = assess_triangle_mesh(mesh.vertices, mesh.triangles)
        try:
            enforce_mesh_quality(
                f"{role} {Path(metadata.path).name}",
                quality,
                ATLAS_INPUT_MESH_QUALITY_SETTINGS,
            )
        except MeshQualityError as error:
            raise ConfigurationError(str(error)) from error
        records.append(
            PreflightMeshQuality(role=role, path=metadata.path, result=quality)
        )
    return tuple(records)


def make_preflight_result(
    config_path: Path | str,
    config: Mapping[str, Any],
    inputs: InputSummary,
    template: MeshMetadata,
    subjects: tuple[MeshMetadata, ...],
    *,
    mesh_quality: tuple[PreflightMeshQuality, ...] = (),
) -> PreflightResult:
    """Assemble notices from already validated, already inspected inputs."""

    source = Path(config_path).expanduser().resolve()
    notices: list[str] = []
    if config["input"]["units"] == "unitless":
        notices.append(
            "Units are declared as unitless. Confirm this is intentional before interpreting "
            "kernel widths or atlas distances."
        )

    point_counts = [subject.points for subject in subjects]
    if max(point_counts) / min(point_counts) > 1.25:
        notices.append(
            "Subject point counts differ by more than 25%. This can be valid, but unusually "
            "heterogeneous mesh resolution should be reviewed."
        )

    face_counts = [subject.cells for subject in subjects]
    if max(face_counts) / min(face_counts) > 2.0:
        notices.append(
            "Subject triangle counts differ by more than a factor of two. Review unusual "
            "mesh density and resampling provenance before starting the atlas."
        )

    diagonals = [subject.bounding_box_diagonal for subject in subjects]
    if max(diagonals) / min(diagonals) > 1.5:
        notices.append(
            "Subject bounding-box diagonals differ by more than 50%. Check units, scale, and "
            "registration before starting the atlas."
        )

    centers = [_bbox_center(subject) for subject in subjects]
    median_center = tuple(median(center[axis] for center in centers) for axis in range(3))
    median_diagonal = median(diagonals)
    maximum_center_offset = max(math.dist(center, median_center) for center in centers)
    if maximum_center_offset > 0.25 * median_diagonal:
        notices.append(
            "Subject bounding-box centers differ by more than 25% of the median subject "
            "diagonal. Review rigid/GPA alignment before starting the atlas."
        )

    hashes: dict[str, list[str]] = {}
    for subject in subjects:
        hashes.setdefault(subject.sha256, []).append(Path(subject.path).name)
    duplicate_groups = [names for names in hashes.values() if len(names) > 1]
    if duplicate_groups:
        examples = "; ".join(", ".join(names[:3]) for names in duplicate_groups[:3])
        notices.append(
            "Different subject filenames contain byte-identical meshes. Confirm that these "
            f"are distinct intended specimens: {examples}."
        )

    if mesh_quality:
        open_meshes = [
            Path(record.path).name
            for record in mesh_quality
            if record.result.boundary_edges > 0
        ]
        if open_meshes:
            notices.append(
                f"{len(open_meshes)} of {len(mesh_quality)} input surfaces are open "
                "(boundary edges present). Open anatomical surfaces can be intentional; "
                "confirm this study-level decision."
            )
        multipart = [
            Path(record.path).name
            for record in mesh_quality
            if record.result.face_connected_components > 1
        ]
        if multipart:
            notices.append(
                f"{len(multipart)} of {len(mesh_quality)} input surfaces contain multiple "
                "face-connected components. Confirm that disconnected anatomical parts are "
                "intentional."
            )

    if len(subjects) > 250:
        notices.append(
            "This is a large cohort. Run a small representative pilot before committing the "
            "full dataset and monitor disk use and convergence."
        )

    return PreflightResult(
        config_path=source,
        config=config,
        inputs=inputs,
        template=template,
        subjects=subjects,
        notices=tuple(notices),
        mesh_quality=mesh_quality,
    )


def collect_preflight(config_path: Path | str) -> PreflightResult:
    """Run schema, path, and full geometry validation without executing an engine."""

    source = Path(config_path).expanduser().resolve()
    config = load_config(source)
    inputs = validate_input_paths(config, source)
    template, subjects = inspect_inputs(inputs)
    mesh_quality = _structural_quality(template, subjects)
    return make_preflight_result(
        source,
        config,
        inputs,
        template,
        subjects,
        mesh_quality=mesh_quality,
    )


def default_preflight_report_path(config_path: Path | str) -> Path:
    """Return ``atlas.preflight.html`` beside ``atlas.yaml``."""

    return Path(config_path).expanduser().resolve().with_suffix(".preflight.html")


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KiB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MiB"
    return f"{value / 1024**3:.2f} GiB"


def _mesh_row(role: str, mesh: MeshMetadata) -> str:
    path = Path(mesh.path)
    values = (
        role,
        path.name,
        str(mesh.points),
        str(mesh.cells),
        mesh.encoding,
        f"{mesh.bounding_box_diagonal:.6g}",
        _format_bytes(mesh.bytes),
        mesh.sha256,
    )
    return "<tr>" + "".join(f"<td>{escape(value)}</td>" for value in values) + "</tr>"


def _quality_row(record: PreflightMeshQuality) -> str:
    result = record.result
    values = (
        record.role,
        Path(record.path).name,
        str(result.boundary_edges),
        str(result.nonmanifold_edges),
        str(result.inconsistently_oriented_manifold_edges),
        str(result.duplicate_faces),
        str(result.isolated_vertices),
        str(result.zero_area_faces),
        str(result.face_connected_components),
    )
    return "<tr>" + "".join(f"<td>{escape(value)}</td>" for value in values) + "</tr>"


def _list_html(values: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(value))}</li>" for value in values) + "</ul>"


def _parameter_provenance_html(config: Mapping[str, Any]) -> str:
    provenance = config["project"].get("parameter_provenance")
    if provenance is None:
        return """
  <section>
    <h2>Parameter provenance</h2>
    <p>This legacy configuration does not contain structured parameter provenance.</p>
  </section>"""

    profile = escape(str(provenance["profile"]).replace("_", " "))
    recommendation = provenance.get("recommendation")
    if recommendation is None:
        return f"""
  <section>
    <h2>Parameter provenance</h2>
    <p><strong>Source:</strong> {profile}. The effective configuration below records the
      exact ratios and any absolute overrides.</p>
  </section>"""

    measurements = recommendation["measurements"]
    alignment_basis = (
        "DiffeoForge GPA evidence"
        if recommendation["alignment_basis"] == "diffeoforge_gpa"
        else "researcher-declared external GPA"
    )
    automatic = _list_html(recommendation["automatic_inferences"])
    decisions = _list_html(recommendation["user_decisions"])
    pilot = _list_html(recommendation["pilot_validation_required"])
    warnings = _list_html(recommendation["warnings"])
    fingerprint = escape(str(recommendation["fingerprint"]))
    calibration_plan = recommendation.get("calibration_plan")
    if calibration_plan is None:
        calibration_html = """
    <h3>Dataset-specific calibration</h3>
    <div class="notices"><ul><li>No staged calibration plan is bound to this
      configuration. Representative neighboring-parameter pilots remain required.</li>
    </ul></div>"""
    else:
        selected = _list_html(
            [
                f"{item['selection_order']}: {item['filename']} "
                f"({str(item['selection_role']).replace('_', ' ')})"
                for item in calibration_plan["selected_pilot_subjects"]
            ]
        )
        stages = _list_html(
            [
                f"Stage {stage['order']}: {stage['title']} "
                f"({len(stage['candidates'])} candidates)"
                for stage in calibration_plan["stages"]
            ]
        )
        feature = calibration_plan["smallest_relevant_feature"]
        feature_text = (
            "not measured"
            if feature is None
            else f"{float(feature):.8g} {calibration_plan['coordinate_unit']}"
        )
        calibration_html = f"""
    <h3>Dataset-specific calibration plan</h3>
    <p><strong>Status:</strong> planned — not executed<br>
      <strong>Plan fingerprint:</strong>
        <code>{escape(str(calibration_plan["fingerprint"]))}</code><br>
      <strong>Pilot cohort:</strong> {calibration_plan["pilot_subject_count"]} of
        {calibration_plan["subject_count"]} subjects<br>
      <strong>Smallest relevant feature:</strong> {escape(feature_text)}</p>
    <div class="cards">
      <div class="card"><span>Representative specimens</span>{selected}</div>
      <div class="card"><span>Sequential comparisons</span>{stages}</div>
    </div>
    <div class="notices"><ul><li>This plan is predeclared provenance, not evidence
      that a pilot ran or that any parameter was approved.</li></ul></div>"""
    return f"""
  <section>
    <h2>Parameter provenance</h2>
    <p><strong>Source:</strong> {profile}<br>
      <strong>Alignment basis:</strong> {escape(alignment_basis)}<br>
      <strong>Analyzed cohort:</strong> {recommendation["subject_count"]} subjects plus
      template <code>{escape(str(recommendation["template_filename"]))}</code><br>
      <strong>Evidence fingerprint:</strong> <code>{fingerprint}</code></p>
    <div class="cards">
      <div class="card"><span>Median aligned diagonal</span>
        <strong>{measurements["cohort_median_diagonal"]:.6g}</strong></div>
      <div class="card"><span>Aligned size CV</span>
        <strong>{measurements["cohort_diagonal_cv"]:.3%}</strong></div>
      <div class="card"><span>Centroid dispersion / diagonal</span>
        <strong>{measurements["normalized_centroid_dispersion"]:.3%}</strong></div>
      <div class="card"><span>Conservative four-edge sampling diagnostic</span>
        <strong>{measurements["sampling_floor_ratio"]:.3%}</strong></div>
    </div>
    <table>
      <thead><tr><th>Inferred automatically</th><th>Chosen by researcher</th>
        <th>Requires pilot validation</th></tr></thead>
      <tbody><tr><td>{automatic}</td><td>{decisions}</td><td>{pilot}</td></tr></tbody>
    </table>
    <h3>Recommendation warnings</h3>
    <div class="notices">{warnings}</div>
    {calibration_html}
  </section>"""


def render_preflight_html(result: PreflightResult) -> str:
    """Render a portable report with no scripts, network calls, or external assets."""

    config = result.config
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    project_name = escape(str(config["project"]["name"]))
    input_directory = escape(str(result.inputs.input_directory))
    template_path = escape(str(result.inputs.template))
    units = escape(str(config["input"]["units"]))
    input_size = _format_bytes(result.total_input_bytes)
    template_diagonal = f"{result.template.bounding_box_diagonal:.6g}"
    subject_points = [subject.points for subject in result.subjects]
    subject_cells = [subject.cells for subject in result.subjects]

    if result.notices:
        notice_items = "".join(f"<li>{escape(notice)}</li>" for notice in result.notices)
        notices_html = f'<ul class="notices">{notice_items}</ul>'
    else:
        notices_html = "<p>No geometry-scale notices were triggered.</p>"

    parameter_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{ratio:.6g}</td><td>{ratio * 100:.3g}%</td></tr>"
        for label, ratio in result.parameter_ratios.items()
    )
    mesh_rows = _mesh_row("template", result.template) + "".join(
        _mesh_row("subject", subject) for subject in result.subjects
    )
    quality_rows = "".join(_quality_row(record) for record in result.mesh_quality)
    quality_html = (
        f"""
  <section>
    <h2>Structural mesh quality</h2>
    <p>Every triangle and indexed edge was checked before execution. Non-manifold edges,
      inconsistent face orientation, duplicate faces, isolated vertices, and zero-area
      faces are blocking errors. Boundary edges and multiple connected components are
      reported for study-level review because open or multipart anatomy can be intentional.</p>
    <div class="scroll"><table>
      <thead><tr><th>Role</th><th>File</th><th>Boundary edges</th>
        <th>Non-manifold edges</th><th>Orientation conflicts</th>
        <th>Duplicate faces</th><th>Isolated vertices</th><th>Zero-area faces</th>
        <th>Components</th></tr></thead>
      <tbody>{quality_rows}</tbody>
    </table></div>
    <p class="boundary"><strong>Operational boundary:</strong>
      {escape(QUALITY_BOUNDARY)} DiffeoForge never edits an input mesh during preflight;
      any future repair workflow must write a new copy and preserve a provenance log.</p>
  </section>"""
        if result.mesh_quality
        else ""
    )
    effective_yaml = escape(
        yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True), quote=False
    )
    provenance_html = _parameter_provenance_html(config)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  {_REPORT_MARKER}
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DiffeoForge preflight – {project_name}</title>
  <style>
    :root {{ color-scheme: light; --ink: #17202a; --muted: #5d6d7e; --line: #d5d8dc;
      --panel: #f8f9f9; --good: #176b3a; --good-bg: #e8f5e9; --warn: #7d5200;
      --warn-bg: #fff4d6; }}
    body {{ margin: 0; font: 15px/1.5 system-ui, sans-serif; color: var(--ink); }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 2rem; }}
    h1 {{ margin-bottom: .2rem; }} h2 {{ margin-top: 2rem; }}
    .subtitle, .boundary {{ color: var(--muted); }}
    .status {{ display: inline-block; padding: .35rem .7rem; border-radius: 999px;
      color: var(--good); background: var(--good-bg); font-weight: 700; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: .8rem; margin: 1rem 0; }}
    .card {{ padding: 1rem; border: 1px solid var(--line); border-radius: .5rem;
      background: var(--panel); }}
    .card strong {{ display: block; font-size: 1.25rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    th, td {{ padding: .55rem; border: 1px solid var(--line); text-align: left;
      vertical-align: top; }} th {{ background: var(--panel); }}
    .scroll {{ overflow-x: auto; }}
    .notices {{ padding: 1rem 1rem 1rem 2rem; border-left: .35rem solid var(--warn);
      background: var(--warn-bg); }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    pre {{ padding: 1rem; overflow: auto; background: #111820; color: #edf2f7;
      border-radius: .5rem; }}
    footer {{ margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
      color: var(--muted); }}
  </style>
</head>
<body>
<main>
  <header>
    <span class="status">Engineering preflight passed</span>
    <h1>{project_name}</h1>
    <p class="subtitle">Generated {escape(generated)} from
      <code>{escape(str(result.config_path))}</code></p>
  </header>

  <section>
    <h2>Input summary</h2>
    <div class="cards">
      <div class="card"><span>Subject meshes</span><strong>{len(result.subjects)}</strong></div>
      <div class="card"><span>Input size</span><strong>{input_size}</strong></div>
      <div class="card"><span>Units</span><strong>{units}</strong></div>
      <div class="card"><span>Template diagonal</span><strong>{template_diagonal}</strong></div>
    </div>
    <p><strong>Input directory:</strong> <code>{input_directory}</code><br>
       <strong>Template:</strong> <code>{template_path}</code><br>
       <strong>Subject points:</strong> {min(subject_points)}–{max(subject_points)}<br>
       <strong>Subject triangles:</strong> {min(subject_cells)}–{max(subject_cells)}</p>
  </section>

  <section>
    <h2>Review notices</h2>
    {notices_html}
    <p class="boundary"><strong>Scientific boundary:</strong> Passing this report means the
      files, paths, declared parameters, and supported mesh geometry are internally readable.
      It does not establish biological validity, adequate registration, parameter suitability,
      or equivalence of numerical engines.</p>
  </section>

  <section>
    <h2>Parameter scale</h2>
    <p>Ratios make the configured values inspectable across datasets; they are not acceptance
      thresholds.</p>
    <table><thead><tr><th>Parameter</th><th>Ratio</th><th>Template diagonal</th></tr></thead>
      <tbody>{parameter_rows}</tbody></table>
  </section>

  {provenance_html}

  <section>
    <h2>Mesh inventory</h2>
    <div class="scroll"><table>
      <thead><tr><th>Role</th><th>File</th><th>Points</th><th>Triangles</th>
        <th>Encoding</th><th>Diagonal</th><th>Bytes</th><th>SHA-256</th></tr></thead>
      <tbody>{mesh_rows}</tbody>
    </table></div>
  </section>

  {quality_html}

  <section>
    <h2>Effective configuration</h2>
    <p>This is the exact validated configuration represented by the report.</p>
    <pre>{effective_yaml}</pre>
  </section>

  <footer>DiffeoForge pre-alpha · self-contained report · no external scripts or assets</footer>
</main>
</body>
</html>
"""


def write_preflight_report(
    result: PreflightResult,
    output_path: Path | str | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a report once unless explicit replacement was requested."""

    destination = (
        default_preflight_report_path(result.config_path)
        if output_path is None
        else Path(output_path).expanduser().resolve()
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and overwrite:
        ensure_preflight_report_replaceable(destination)
    try:
        write_text_safely(
            destination,
            render_preflight_html(result),
            overwrite=overwrite,
        )
    except FileExistsError as error:
        raise ConfigurationError(
            f"Preflight report already exists and will not be overwritten: {destination}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Could not write preflight report {destination}: {error}"
        ) from error
    return destination
