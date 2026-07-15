"""Self-contained HTML preflight reports for atlas configurations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import yaml

from diffeoforge.config import (
    ConfigurationError,
    InputSummary,
    load_config,
    validate_input_paths,
)
from diffeoforge.mesh import MeshMetadata, inspect_inputs

_REPORT_MARKER = '<meta name="generator" content="DiffeoForge preflight">'


@dataclass(frozen=True)
class PreflightResult:
    """Validated configuration, geometry inventory, and observable notices."""

    config_path: Path
    config: Mapping[str, Any]
    inputs: InputSummary
    template: MeshMetadata
    subjects: tuple[MeshMetadata, ...]
    notices: tuple[str, ...]

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


def make_preflight_result(
    config_path: Path | str,
    config: Mapping[str, Any],
    inputs: InputSummary,
    template: MeshMetadata,
    subjects: tuple[MeshMetadata, ...],
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

    diagonals = [subject.bounding_box_diagonal for subject in subjects]
    if max(diagonals) / min(diagonals) > 1.5:
        notices.append(
            "Subject bounding-box diagonals differ by more than 50%. Check units, scale, and "
            "registration before starting the atlas."
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
    )


def collect_preflight(config_path: Path | str) -> PreflightResult:
    """Run schema, path, and full geometry validation without executing an engine."""

    source = Path(config_path).expanduser().resolve()
    config = load_config(source)
    inputs = validate_input_paths(config, source)
    template, subjects = inspect_inputs(inputs)
    return make_preflight_result(source, config, inputs, template, subjects)


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
    effective_yaml = escape(
        yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True), quote=False
    )

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

  <section>
    <h2>Mesh inventory</h2>
    <div class="scroll"><table>
      <thead><tr><th>Role</th><th>File</th><th>Points</th><th>Triangles</th>
        <th>Encoding</th><th>Diagonal</th><th>Bytes</th><th>SHA-256</th></tr></thead>
      <tbody>{mesh_rows}</tbody>
    </table></div>
  </section>

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
        try:
            prefix = destination.read_text(encoding="utf-8")[:2048]
        except OSError as error:
            raise ConfigurationError(
                f"Could not verify existing preflight report {destination}: {error}"
            ) from error
        if _REPORT_MARKER not in prefix:
            raise ConfigurationError(
                "Refusing replacement because the existing HTML file is not recognized as "
                f"a DiffeoForge preflight report: {destination}"
            )
    mode = "w" if overwrite else "x"
    try:
        with destination.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(render_preflight_html(result))
    except FileExistsError as error:
        raise ConfigurationError(
            f"Preflight report already exists and will not be overwritten: {destination}"
        ) from error
    except OSError as error:
        raise ConfigurationError(
            f"Could not write preflight report {destination}: {error}"
        ) from error
    return destination
