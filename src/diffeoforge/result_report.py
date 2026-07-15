"""Engine-independent, self-contained reports for terminal atlas runs."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.runs import run_status

_REPORT_MARKER = '<meta name="generator" content="DiffeoForge result report">'
_TERMINAL_STATES = {"completed", "failed", "interrupted"}
_CONVERGENCE_COLUMNS = (
    "iteration",
    "log_likelihood",
    "attachment",
    "regularity",
)


@dataclass(frozen=True)
class ConvergenceRow:
    """One objective observation parsed from a completed run."""

    iteration: int
    log_likelihood: float
    attachment: float
    regularity: float


@dataclass(frozen=True)
class EvidenceCheck:
    """One report-time consistency check with an explicit outcome."""

    label: str
    status: str
    detail: str


@dataclass(frozen=True)
class RunReport:
    """Observable run evidence used to render the result report."""

    run_directory: Path
    manifest: Mapping[str, Any]
    result: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    inventory: tuple[Mapping[str, Any], ...]
    convergence: tuple[ConvergenceRow, ...]
    checks: tuple[EvidenceCheck, ...]
    notices: tuple[str, ...]

    @property
    def max_iterations(self) -> int:
        return int(self.manifest["effective_config"]["optimization"]["max_iterations"])

    @property
    def final_iteration(self) -> int | None:
        return self.convergence[-1].iteration if self.convergence else None

    @property
    def stop_interpretation(self) -> str:
        final_iteration = self.final_iteration
        if final_iteration is None:
            return "No objective history was available; the stopping reason cannot be assessed."
        if self.result["status"] == "failed":
            return (
                f"The backend failed after the observation at iteration {final_iteration}; "
                "failure is not convergence."
            )
        if self.result["status"] == "interrupted":
            return (
                f"The run was interrupted after the observation at iteration {final_iteration}; "
                "interruption is not convergence."
            )
        if final_iteration >= self.max_iterations:
            return (
                f"The observed iteration reached the requested maximum of {self.max_iterations}. "
                "This report does not label that outcome as convergence."
            )
        return (
            f"The backend completed before the requested maximum ({final_iteration} of "
            f"{self.max_iterations}). The recorded artifacts alone do not prove which stopping "
            "criterion caused termination."
        )


def default_result_report_path(run_directory: Path | str) -> Path:
    """Return the default report path inside a run directory."""

    return Path(run_directory).expanduser().resolve() / "result-report.html"


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must contain a JSON object: {path}")
    return value


def _load_events(path: Path) -> tuple[Mapping[str, Any], ...]:
    events: list[Mapping[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigurationError(f"Could not read run events: {path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"Invalid JSON in run event line {line_number}: {path}"
            ) from error
        if not isinstance(event, dict) or "event" not in event:
            raise ConfigurationError(f"Invalid run event in line {line_number}: {path}")
        events.append(event)
    if not events:
        raise ConfigurationError(f"Run event log is empty: {path}")
    return tuple(events)


def _safe_run_path(run_directory: Path, relative_value: object, label: str) -> Path:
    relative = PurePosixPath(str(relative_value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ConfigurationError(f"{label} escapes the run directory: {relative}")
    candidate = run_directory.joinpath(*relative.parts).resolve()
    if not candidate.is_relative_to(run_directory):
        raise ConfigurationError(f"{label} escapes the run directory: {relative}")
    return candidate


def _load_inventory(
    run_directory: Path,
    result: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], EvidenceCheck]:
    outputs = result.get("outputs")
    if not isinstance(outputs, dict):
        raise ConfigurationError("Run result does not contain an outputs object.")
    inventory_path = _safe_run_path(
        run_directory,
        outputs.get("inventory_path", "output-inventory.json"),
        "Output inventory path",
    )
    inventory_document = _load_json(inventory_path, "Output inventory")
    records = inventory_document.get("files")
    if not isinstance(records, list):
        raise ConfigurationError("Output inventory does not contain a files array.")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ConfigurationError(f"Output inventory record {index} is not an object.")
        if not isinstance(record.get("path"), str) or not record["path"]:
            raise ConfigurationError(f"Output inventory record {index} has no path.")
        if not isinstance(record.get("bytes"), int) or record["bytes"] < 0:
            raise ConfigurationError(f"Output inventory record {index} has invalid bytes.")
        digest = record.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ConfigurationError(f"Output inventory record {index} has invalid SHA-256.")

    expected_digest = outputs.get("inventory_sha256")
    actual_digest = sha256_file(inventory_path)
    digest_matches = isinstance(expected_digest, str) and expected_digest == actual_digest
    check = EvidenceCheck(
        label="Output inventory digest",
        status="pass" if digest_matches else "fail",
        detail=(
            "The inventory SHA-256 matches result.json."
            if digest_matches
            else "The inventory SHA-256 does not match result.json; inspect the run artifacts."
        ),
    )
    return tuple(records), check


def _load_convergence(path: Path) -> tuple[ConvergenceRow, ...]:
    if not path.is_file():
        return ()
    rows: list[ConvergenceRow] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not set(_CONVERGENCE_COLUMNS).issubset(
                reader.fieldnames
            ):
                raise ConfigurationError(
                    "Convergence CSV is missing one or more required columns: "
                    + ", ".join(_CONVERGENCE_COLUMNS)
                )
            for line_number, value in enumerate(reader, start=2):
                try:
                    row = ConvergenceRow(
                        iteration=int(value["iteration"]),
                        log_likelihood=float(value["log_likelihood"]),
                        attachment=float(value["attachment"]),
                        regularity=float(value["regularity"]),
                    )
                except (TypeError, ValueError) as error:
                    raise ConfigurationError(
                        f"Invalid convergence value in CSV line {line_number}: {path}"
                    ) from error
                if row.iteration < 0 or not all(
                    math.isfinite(number)
                    for number in (row.log_likelihood, row.attachment, row.regularity)
                ):
                    raise ConfigurationError(
                        f"Non-finite or negative-iteration convergence value in line "
                        f"{line_number}: {path}"
                    )
                rows.append(row)
    except OSError as error:
        raise ConfigurationError(f"Could not read convergence CSV: {path}: {error}") from error
    return tuple(rows)


def collect_run_report(run_directory: Path | str) -> RunReport:
    """Collect terminal run evidence without changing or re-executing the run."""

    run_path = Path(run_directory).expanduser().resolve()
    snapshot = run_status(run_path)
    result = snapshot.get("result")
    if not isinstance(result, dict):
        raise ConfigurationError(
            "A terminal result.json is required. Execute the prepared run before creating "
            "a result report."
        )
    if snapshot["status"] not in _TERMINAL_STATES:
        raise ConfigurationError(
            f"Run is not in a terminal state; latest event is {snapshot['status']!r}."
        )
    if result.get("status") != snapshot["status"]:
        raise ConfigurationError("result.json status does not match the terminal lifecycle event.")
    manifest = _load_json(run_path / "manifest.json", "Run manifest")
    events = _load_events(run_path / "events.jsonl")
    inventory, inventory_digest_check = _load_inventory(run_path, result)
    convergence = _load_convergence(run_path / "logs" / "convergence.csv")

    outputs = result["outputs"]
    recorded_count = outputs.get("file_count")
    recorded_bytes = outputs.get("total_bytes")
    actual_bytes = sum(int(record["bytes"]) for record in inventory)
    inventory_summary_matches = recorded_count == len(inventory) and recorded_bytes == actual_bytes
    recorded_rows = result.get("convergence_rows")
    convergence_count_matches = recorded_rows == len(convergence)
    lifecycle_matches = events[-1].get("event") == result.get("status") and events[-1].get(
        "return_code"
    ) == result.get("return_code")
    checks = (
        EvidenceCheck(
            "Prepared manifest digest",
            "pass",
            "manifest.sha256 and the versioned manifest schema were verified.",
        ),
        EvidenceCheck(
            "Terminal lifecycle",
            "pass" if lifecycle_matches else "fail",
            (
                "The last append-only event matches result.json."
                if lifecycle_matches
                else "The last append-only event does not match result.json."
            ),
        ),
        inventory_digest_check,
        EvidenceCheck(
            "Output inventory summary",
            "pass" if inventory_summary_matches else "fail",
            (
                "File count and total bytes match result.json."
                if inventory_summary_matches
                else "File count or total bytes differs from result.json."
            ),
        ),
        EvidenceCheck(
            "Convergence row count",
            "pass" if convergence_count_matches else "fail",
            (
                "Parsed rows match result.json."
                if convergence_count_matches
                else "Parsed rows differ from result.json."
            ),
        ),
    )

    notices: list[str] = []
    if result["status"] == "failed":
        error_detail = result.get("execution_error") or f"return code {result.get('return_code')}"
        notices.append(f"The numerical backend failed: {error_detail}.")
    if result["status"] == "interrupted":
        error_detail = result.get("execution_error") or "the run was stopped"
        checkpoint = result.get("checkpoint") or {}
        checkpoint_detail = (
            "A checkpoint whose integrity matches the output inventory is available for "
            "an immutable successor run; loadability has not been established."
            if checkpoint.get("available")
            else "No checkpoint is available, so this run cannot be resumed."
        )
        notices.append(f"The numerical run was interrupted: {error_detail}. {checkpoint_detail}")
    if result.get("resume"):
        notices.append(
            "This is a Deformetrica 4.3 successor: model parameters and iteration were "
            "restored, while the objective baseline, gradient, and line-search step sizes "
            "were reinitialized. Exact optimization-trajectory continuity is not guaranteed."
        )
    if not convergence:
        notices.append(
            "No objective observations were parsed. Inspect logs/deformetrica.log before "
            "interpreting this run."
        )
    else:
        iterations = [row.iteration for row in convergence]
        if any(
            current <= previous
            for previous, current in zip(iterations, iterations[1:], strict=False)
        ):
            notices.append("Convergence iterations are not strictly increasing.")
        decreases = sum(
            current.log_likelihood < previous.log_likelihood
            for previous, current in zip(convergence, convergence[1:], strict=False)
        )
        if decreases:
            notices.append(
                f"Log-likelihood decreased in {decreases} recorded step(s); inspect the full log."
            )
    for check in checks:
        if check.status == "fail":
            notices.append(f"Evidence check failed: {check.label}. {check.detail}")
    notices.append(
        "A terminal backend state and a stable-looking objective curve are engineering "
        "evidence, not proof of biological validity or numerical equivalence."
    )

    return RunReport(
        run_directory=run_path,
        manifest=manifest,
        result=result,
        events=events,
        inventory=inventory,
        convergence=convergence,
        checks=checks,
        notices=tuple(notices),
    )


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KiB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MiB"
    return f"{value / 1024**3:.2f} GiB"


def _format_duration(value: object) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "unavailable"
    if seconds < 60:
        return f"{seconds:.3f} s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} min {remainder:.1f} s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)} h {int(minutes)} min {remainder:.0f} s"


def _svg_chart(
    rows: Sequence[ConvergenceRow],
    title: str,
    series: Sequence[tuple[str, str, Callable[[ConvergenceRow], float]]],
) -> str:
    if not rows:
        return '<p class="empty">No convergence observations available.</p>'
    width, height = 920, 300
    left, right, top, bottom = 84, 24, 40, 52
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_values = [row.iteration for row in rows]
    y_values = [value(row) for _label, _color, value in series for row in rows]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    if x_min == x_max:
        x_max = x_min + 1
    if y_min == y_max:
        padding = abs(y_min) * 0.05 or 1.0
        y_min -= padding
        y_max += padding
    else:
        padding = (y_max - y_min) * 0.06
        y_min -= padding
        y_max += padding

    def x_pixel(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def y_pixel(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_height

    grid_parts: list[str] = []
    for index in range(5):
        value = y_max - (y_max - y_min) * index / 4
        y = y_pixel(value)
        grid_parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" '
            'class="grid" />'
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" '
            f'class="tick">{escape(f"{value:.5g}")}</text>'
        )
    line_parts: list[str] = []
    legend_parts: list[str] = []
    for index, (label, color, value) in enumerate(series):
        points = " ".join(f"{x_pixel(row.iteration):.2f},{y_pixel(value(row)):.2f}" for row in rows)
        line_parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />'
        )
        legend_x = left + index * 190
        legend_parts.append(
            f'<line x1="{legend_x}" y1="18" x2="{legend_x + 24}" y2="18" '
            f'stroke="{color}" stroke-width="3" />'
            f'<text x="{legend_x + 32}" y="22" class="legend">{escape(label)}</text>'
        )
    return f"""<figure>
      <figcaption>{escape(title)}</figcaption>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
        {"".join(grid_parts)}
        <line x1="{left}" y1="{height - bottom}" x2="{width - right}"
          y2="{height - bottom}" class="axis" />
        <text x="{left}" y="{height - 20}" class="tick">iteration {x_min}</text>
        <text x="{width - right}" y="{height - 20}" text-anchor="end"
          class="tick">iteration {max(x_values)}</text>
        {"".join(legend_parts)}
        {"".join(line_parts)}
      </svg>
    </figure>"""


def render_result_html(report: RunReport) -> str:
    """Render a portable report without scripts, network requests, or external assets."""

    manifest = report.manifest
    result = report.result
    config = manifest["effective_config"]
    project_name = str(manifest["project"]["name"])
    status = str(result["status"])
    status_labels = {
        "completed": "Engine completed",
        "failed": "Engine failed",
        "interrupted": "Run interrupted",
    }
    status_label = status_labels[status]
    status_class = status
    final = report.convergence[-1] if report.convergence else None
    initial = report.convergence[0] if report.convergence else None
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    output_bytes = sum(int(record["bytes"]) for record in report.inventory)
    objective_change = (
        f"{final.log_likelihood - initial.log_likelihood:.6g}"
        if final is not None and initial is not None
        else "unavailable"
    )
    final_objective = f"{final.log_likelihood:.6g}" if final is not None else "unavailable"

    notices_html = "".join(f"<li>{escape(notice)}</li>" for notice in report.notices)
    check_rows = "".join(
        "<tr>"
        f'<td><span class="check {escape(check.status)}">{escape(check.status)}</span></td>'
        f"<th>{escape(check.label)}</th><td>{escape(check.detail)}</td></tr>"
        for check in report.checks
    )
    event_rows = "".join(
        "<tr>"
        f"<td>{escape(str(event.get('timestamp', '')))}</td>"
        f"<td>{escape(str(event.get('event', '')))}</td>"
        f"<td>{escape(str(event.get('return_code', '')))}</td>"
        f"<td>{escape(str(event.get('duration_seconds', '')))}</td>"
        "</tr>"
        for event in report.events
    )
    inventory_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(record['path']))}</code></td>"
        f"<td>{escape(_format_bytes(int(record['bytes'])))}</td>"
        f"<td><code>{escape(str(record['sha256']))}</code></td>"
        "</tr>"
        for record in report.inventory
    )
    objective_chart = _svg_chart(
        report.convergence,
        "Objective and attachment history",
        (
            ("log-likelihood", "#176b87", lambda row: row.log_likelihood),
            ("attachment", "#c05a19", lambda row: row.attachment),
        ),
    )
    regularity_chart = _svg_chart(
        report.convergence,
        "Regularity history",
        (("regularity", "#6f4aa8", lambda row: row.regularity),),
    )
    effective_yaml = escape(
        yaml.safe_dump(dict(config), sort_keys=False, allow_unicode=True), quote=False
    )
    result_json = escape(json.dumps(dict(result), indent=2, ensure_ascii=False, sort_keys=True))
    subject_count = manifest["input_count"]["subjects"]
    final_iteration = (
        report.final_iteration if report.final_iteration is not None else "unavailable"
    )
    duration = escape(_format_duration(result.get("duration_seconds")))
    output_size = escape(_format_bytes(output_bytes))
    backend_id = escape(str(manifest["backend"]["id"]))
    backend_contract = escape(str(manifest["backend"]["contract_version"]))
    started_at = escape(str(result.get("started_at")))
    ended_at = escape(str(result.get("ended_at")))
    tolerance = escape(str(config["optimization"]["convergence_tolerance"]))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  {_REPORT_MARKER}
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DiffeoForge result - {escape(project_name)}</title>
  <style>
    :root {{ color-scheme: light; --ink: #17202a; --muted: #5d6d7e; --line: #d5d8dc;
      --panel: #f8f9f9; --good: #176b3a; --good-bg: #e8f5e9; --bad: #9c2f24;
      --bad-bg: #fdecea; --warn: #7d5200; --warn-bg: #fff4d6; }}
    body {{ margin: 0; font: 15px/1.5 system-ui, sans-serif; color: var(--ink); }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 2rem; }}
    h1 {{ margin-bottom: .2rem; }} h2 {{ margin-top: 2rem; }}
    .subtitle, .boundary, .empty {{ color: var(--muted); }}
    .status {{ display: inline-block; padding: .35rem .7rem; border-radius: 999px;
      font-weight: 700; }}
    .status.completed, .check.pass {{ color: var(--good); background: var(--good-bg); }}
    .status.failed, .check.fail {{ color: var(--bad); background: var(--bad-bg); }}
    .status.interrupted {{ color: #7a4b00; background: #fff3cd; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: .8rem; margin: 1rem 0; }}
    .card {{ padding: 1rem; border: 1px solid var(--line); border-radius: .5rem;
      background: var(--panel); }}
    .card strong {{ display: block; font-size: 1.25rem; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    th, td {{ padding: .55rem; border: 1px solid var(--line); text-align: left;
      vertical-align: top; }} th {{ background: var(--panel); }}
    .scroll {{ overflow-x: auto; }}
    .notices {{ padding: 1rem 1rem 1rem 2rem; border-left: .35rem solid var(--warn);
      background: var(--warn-bg); }}
    .check {{ display: inline-block; min-width: 2.6rem; padding: .15rem .45rem;
      border-radius: 999px; text-align: center; font-weight: 700; text-transform: uppercase; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    td code {{ overflow-wrap: anywhere; }}
    pre {{ padding: 1rem; overflow: auto; background: #111820; color: #edf2f7;
      border-radius: .5rem; }}
    figure {{ margin: 1.25rem 0; }} figcaption {{ font-weight: 700; margin-bottom: .4rem; }}
    svg {{ display: block; width: 100%; border: 1px solid var(--line); background: white; }}
    .grid {{ stroke: #e6e9ec; stroke-width: 1; }} .axis {{ stroke: #68737d; stroke-width: 1; }}
    .tick, .legend {{ fill: #43515e; font: 12px system-ui, sans-serif; }}
    details {{ margin-top: 1rem; }} summary {{ cursor: pointer; font-weight: 700; }}
    footer {{ margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
      color: var(--muted); }}
  </style>
</head>
<body>
<main>
  <header>
    <span class="status {status_class}">{status_label}</span>
    <h1>{escape(project_name)}</h1>
    <p class="subtitle">Run <code>{escape(str(manifest["run_id"]))}</code> - report generated
      {escape(generated)}</p>
  </header>

  <section>
    <h2>Run summary</h2>
    <div class="cards">
      <div class="card"><span>Subjects</span><strong>{subject_count}</strong></div>
      <div class="card"><span>Last observed iteration</span>
        <strong>{final_iteration}</strong></div>
      <div class="card"><span>Duration</span><strong>{duration}</strong></div>
      <div class="card"><span>Output</span><strong>{len(report.inventory)} files</strong>
        <span>{output_size}</span></div>
    </div>
    <div class="scroll"><table><tbody>
      <tr><th>Run directory</th><td><code>{escape(str(report.run_directory))}</code></td></tr>
      <tr><th>Backend</th><td>{backend_id}, contract {backend_contract}</td></tr>
      <tr><th>Return code</th><td>{escape(str(result.get("return_code")))}</td></tr>
      <tr><th>Started / ended</th><td>{started_at} / {ended_at}</td></tr>
      <tr><th>Requested maximum</th><td>{report.max_iterations} iterations</td></tr>
      <tr><th>Convergence tolerance</th><td>{tolerance}</td></tr>
      <tr><th>Observed objective change</th>
        <td>{escape(objective_change)}; final {escape(final_objective)}</td></tr>
      <tr><th>Stopping interpretation</th><td>{escape(report.stop_interpretation)}</td></tr>
    </tbody></table></div>
  </section>

  <section>
    <h2>Review notices</h2>
    <ul class="notices">{notices_html}</ul>
    <p class="boundary"><strong>Scientific boundary:</strong> This report describes recorded
      engineering evidence. It does not establish adequate registration, parameter suitability,
      biological validity, group representativeness, or equivalence to another numerical engine.</p>
  </section>

  <section>
    <h2>Evidence consistency</h2>
    <p>These checks validate relationships among recorded files. Output meshes are not rehashed
      while rendering this report; their execution-time hashes remain listed below.</p>
    <table><thead><tr><th>Status</th><th>Check</th><th>Detail</th></tr></thead>
      <tbody>{check_rows}</tbody></table>
  </section>

  <section>
    <h2>Objective history</h2>
    <p>{len(report.convergence)} observations were parsed from
      <code>logs/convergence.csv</code>. Curves are shown on their recorded scales.</p>
    {objective_chart}
    {regularity_chart}
  </section>

  <section>
    <h2>Lifecycle</h2>
    <table><thead><tr><th>Timestamp</th><th>Event</th><th>Return code</th>
      <th>Duration (s)</th></tr></thead>
      <tbody>{event_rows}</tbody></table>
  </section>

  <section>
    <h2>Output inventory</h2>
    <p>Execution-time file sizes and SHA-256 hashes are retained for integrity and provenance,
      not as scientific similarity measures.</p>
    <details><summary>Show all {len(report.inventory)} output files</summary>
      <div class="scroll"><table><thead><tr><th>Path below output/</th><th>Size</th>
        <th>SHA-256</th></tr></thead>
        <tbody>{inventory_rows}</tbody></table></div>
    </details>
  </section>

  <section>
    <h2>Exact recorded configuration and result</h2>
    <details><summary>Effective configuration</summary><pre>{effective_yaml}</pre></details>
    <details><summary>Terminal result.json</summary><pre>{result_json}</pre></details>
  </section>

  <footer>DiffeoForge pre-alpha - self-contained result report - no scripts, network calls,
    or external assets</footer>
</main>
</body>
</html>
"""


def write_result_report(
    report: RunReport,
    output_path: Path | str | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a result report once unless replacement is explicitly requested."""

    destination = (
        default_result_report_path(report.run_directory)
        if output_path is None
        else Path(output_path).expanduser().resolve()
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and overwrite:
        try:
            prefix = destination.read_text(encoding="utf-8")[:2048]
        except OSError as error:
            raise ConfigurationError(
                f"Could not verify existing result report {destination}: {error}"
            ) from error
        if _REPORT_MARKER not in prefix:
            raise ConfigurationError(
                "Refusing replacement because the existing HTML file is not recognized as "
                f"a DiffeoForge result report: {destination}"
            )
    mode = "w" if overwrite else "x"
    try:
        with destination.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(render_result_html(report))
    except FileExistsError as error:
        raise ConfigurationError(
            f"Result report already exists and will not be overwritten: {destination}"
        ) from error
    except OSError as error:
        raise ConfigurationError(f"Could not write result report {destination}: {error}") from error
    return destination
