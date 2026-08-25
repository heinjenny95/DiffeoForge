"""Self-contained reports for transparent Deformetrica calibration plans."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from html import escape
from pathlib import Path

from diffeoforge.reference_calibration import (
    ReferenceCalibrationPlan,
    calibration_plan_json,
)
from diffeoforge.reference_recommendation import ReferenceParameterRecommendation


@dataclass(frozen=True)
class CalibrationPlanExport:
    directory: Path
    json_path: Path
    html_path: Path
    sha256_path: Path
    json_sha256: str
    recommendation_path: Path | None


def _format_value(value: float, unit: str) -> str:
    suffix = "" if unit == "unitless" else f" {escape(unit)}"
    return f"{value:.8g}{suffix}"


def render_reference_calibration_plan_html(plan: ReferenceCalibrationPlan) -> str:
    """Render a local, dependency-free review report."""

    unit = plan.coordinate_unit
    selected_rows = "\n".join(
        (
            "<tr>"
            f"<td>{subject.selection_order}</td>"
            f"<td><code>{escape(subject.filename)}</code></td>"
            f"<td>{escape(subject.selection_role)}</td>"
            f"<td>{subject.descriptor_distance:.6g}</td>"
            f"<td><code>{subject.sha256}</code></td>"
            "</tr>"
        )
        for subject in plan.selected_pilot_subjects
    )
    selected_names = {item.filename for item in plan.selected_pilot_subjects}
    if plan.pilot_subject_declarations:
        pilot_description = (
            "Researcher declarations are applied before geometric diversity filling. "
            "Every declared biological extreme is included and every declared stratum "
            "has at least one selected member; remaining slots use the deterministic "
            "geometry medoid/farthest-first heuristic. Declarations establish coverage, "
            "not biological validity."
        )
        declaration_rows = "".join(
            "<tr>"
            f"<td><code>{escape(item.filename)}</code></td>"
            f"<td>{escape(item.stratum or 'not declared')}</td>"
            f"<td>{'yes' if item.is_extreme else 'no'}</td>"
            f"<td>{'yes' if item.filename in selected_names else 'no'}</td>"
            "</tr>"
            for item in plan.pilot_subject_declarations
        )
        declaration_section = f"""
        <h3>Researcher-declared coverage</h3>
        <table><thead><tr><th>Specimen</th><th>Stratum</th>
        <th>Declared extreme</th><th>Selected</th></tr></thead>
        <tbody>{declaration_rows}</tbody></table>
        """
    else:
        pilot_description = (
            "The first subject is the geometry-descriptor medoid; subsequent subjects "
            "are farthest-first descriptor extremes. This is a reproducible geometric "
            "diversity heuristic, not proof of biological group representation."
        )
        declaration_section = ""
    baseline_rows = "\n".join(
        (
            "<tr>"
            f"<td>{escape(name.replace('_', ' '))}</td>"
            f"<td>{_format_value(value, unit)}</td>"
            f"<td>{plan.parameter_ratios[name]:.8g} × template diagonal</td>"
            "</tr>"
        )
        for name, value in plan.effective_values.items()
    )
    stage_sections: list[str] = []
    for stage in plan.stages:
        candidate_rows: list[str] = []
        for candidate in stage.candidates:
            rendered_values = "<br>".join(
                (
                    f"{escape(name.replace('_', ' '))}: "
                    + (
                        str(int(value))
                        if name == "timepoints"
                        else _format_value(value, unit)
                    )
                )
                for name, value in candidate.parameter_values
            )
            candidate_rows.append(
                "<tr>"
                f"<td><code>{escape(candidate.candidate_id)}</code></td>"
                f"<td>{escape(candidate.label)}</td>"
                f"<td>{rendered_values}</td>"
                f"<td>{escape(candidate.rationale)}</td>"
                "</tr>"
            )
        evidence = "".join(f"<li>{escape(item)}</li>" for item in stage.evidence_required)
        rejection = "".join(f"<li>{escape(item)}</li>" for item in stage.reject_when)
        locked = (
            ", ".join(
                escape(value.replace("_", " "))
                for value in stage.locked_from_previous_stages
            )
            or "None; this is the first stage."
        )
        stage_sections.append(
            f"""
            <section class="card">
              <p class="eyebrow">Stage {stage.order}</p>
              <h2>{escape(stage.title)}</h2>
              <p><strong>Locked from earlier stages:</strong> {locked}</p>
              <table>
                <thead><tr><th>ID</th><th>Intent</th><th>Values</th>
                <th>Why test it</th></tr></thead>
                <tbody>{''.join(candidate_rows)}</tbody>
              </table>
              <div class="columns">
                <div><h3>Required evidence</h3><ul>{evidence}</ul></div>
                <div><h3>Reject when</h3><ul>{rejection}</ul></div>
              </div>
              <p class="decision"><strong>Decision rule:</strong> {escape(stage.decision_rule)}</p>
            </section>
            """
        )
    confirmation = "".join(
        f"<li>{escape(item)}</li>" for item in plan.final_confirmation_required
    )
    limitations = "".join(f"<li>{escape(item)}</li>" for item in plan.limitations)
    feature = (
        "Not measured. The attachment comparison remains centered on the "
        "researcher-declared surface-detail intent."
        if plan.smallest_relevant_feature is None
        else _format_value(plan.smallest_relevant_feature, unit)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DiffeoForge parameter-calibration plan</title>
  <style>
    :root {{ color-scheme: light; font-family: "Segoe UI", Arial, sans-serif; }}
    body {{ margin: 0; background: #f4f7f8; color: #17252a; line-height: 1.45; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 34px 24px 60px; }}
    h1, h2, h3 {{ color: #123b3a; }}
    h1 {{ font-size: 31px; margin-bottom: 8px; }}
    h2 {{ margin-top: 0; }}
    h3 {{ font-size: 15px; }}
    .subtitle {{ color: #526b70; max-width: 850px; }}
    .eyebrow {{ color: #167c6b; text-transform: uppercase; font-size: 12px;
                font-weight: 750; letter-spacing: .04em; }}
    .status {{ background: #fff7df; border: 1px solid #ead28b; color: #6f5100;
               border-radius: 9px; padding: 13px 16px; font-weight: 650; }}
    .card {{ background: white; border: 1px solid #dbe4e6; border-radius: 12px;
             padding: 22px 24px; margin-top: 18px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #dbe4e6;
              text-align: left; vertical-align: top; }}
    th {{ background: #eef5f3; color: #123b3a; }}
    code {{ font-family: Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }}
    .columns {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 24px; }}
    .decision {{ background: #e8f4f0; border-radius: 8px; padding: 12px 14px; }}
    .meta {{ display: grid; grid-template-columns: minmax(190px, .4fr) 1fr;
             gap: 7px 16px; }}
    .meta dt {{ font-weight: 700; }}
    .meta dd {{ margin: 0; overflow-wrap: anywhere; }}
    @media print {{ body {{ background: white; }} .card {{ break-inside: avoid; }} }}
  </style>
</head>
<body><main>
  <p class="eyebrow">DiffeoForge · transparent Deformetrica calibration</p>
  <h1>Parameter-calibration plan</h1>
  <p class="subtitle">Predeclared candidate values, representative pilot selection,
  evidence requirements, and decision rules. This report intentionally separates
  measured geometry, researcher intent, and evidence that still has to be collected.</p>
  <p class="status">PLANNED — NOT EXECUTED. This report does not approve a parameter
  set or establish biological validity.</p>

  <section class="card">
    <h2>Bound provenance</h2>
    <dl class="meta">
      <dt>Plan version</dt><dd>{escape(plan.version)}</dd>
      <dt>Plan fingerprint</dt><dd><code>{plan.fingerprint}</code></dd>
      <dt>Recommendation fingerprint</dt>
        <dd><code>{plan.recommendation_fingerprint}</code></dd>
      <dt>Template</dt><dd><code>{escape(plan.template_filename)}</code></dd>
      <dt>Template SHA-256</dt><dd><code>{plan.template_sha256}</code></dd>
      <dt>Coordinate unit</dt><dd>{escape(unit)}</dd>
      <dt>Cohort</dt><dd>{plan.subject_count} subjects</dd>
      <dt>Pilot</dt><dd>{plan.pilot_subject_count} selected subjects</dd>
      <dt>Smallest relevant feature</dt><dd>{feature}</dd>
      <dt>Attachment center source</dt>
        <dd>{escape(plan.attachment_center_source.replace('_', ' '))}</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Deterministic pilot cohort</h2>
    <p>{escape(pilot_description)}</p>
    <table>
      <thead><tr><th>#</th><th>Specimen</th><th>Selection role</th>
      <th>Descriptor distance</th><th>SHA-256</th></tr></thead>
      <tbody>{selected_rows}</tbody>
    </table>
    {declaration_section}
  </section>

  <section class="card">
    <h2>Starting center</h2>
    <table>
      <thead><tr><th>Parameter</th><th>Absolute value</th><th>Scale record</th></tr></thead>
      <tbody>{baseline_rows}</tbody>
    </table>
  </section>

  {''.join(stage_sections)}

  <section class="card">
    <h2>Full-cohort confirmation required</h2><ol>{confirmation}</ol>
    <h2>Limitations</h2><ul>{limitations}</ul>
  </section>
</main></body></html>
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def export_reference_calibration_plan(
    plan: ReferenceCalibrationPlan,
    directory: Path | str,
    *,
    recommendation: ReferenceParameterRecommendation | None = None,
    overwrite: bool = False,
) -> CalibrationPlanExport:
    """Publish the plan and optional full geometry evidence without silent replacement."""

    destination = Path(directory).expanduser().resolve()
    json_path = destination / "parameter-calibration-plan.json"
    html_path = destination / "parameter-calibration-plan.html"
    sha256_path = destination / "parameter-calibration-plan.sha256"
    recommendation_path = (
        destination / "aligned-mesh-recommendation.json"
        if recommendation is not None
        else None
    )
    if (
        recommendation is not None
        and recommendation.fingerprint != plan.recommendation_fingerprint
    ):
        raise ValueError(
            "The supplied recommendation is not bound to this calibration plan"
        )
    targets = (json_path, html_path, sha256_path) + (
        () if recommendation_path is None else (recommendation_path,)
    )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Calibration plan export already exists and will not be overwritten: "
            + ", ".join(str(path) for path in existing)
        )
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(f"Calibration export destination is not a folder: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    json_payload = calibration_plan_json(plan).encode("utf-8")
    html_payload = render_reference_calibration_plan_html(plan).encode("utf-8")
    json_hash = _sha256(json_payload)
    sha_payload = f"{json_hash}  {json_path.name}\n".encode("ascii")
    payloads: tuple[tuple[Path, bytes], ...] = (
        (json_path, json_payload),
        (html_path, html_payload),
        (sha256_path, sha_payload),
    )
    if recommendation_path is not None:
        assert recommendation is not None
        recommendation_payload = (
            json.dumps(
                recommendation.as_manifest(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        payloads += ((recommendation_path, recommendation_payload),)
    temporary: list[tuple[Path, Path]] = []
    try:
        for target, payload in payloads:
            temp = destination / f".{target.name}.{uuid.uuid4().hex}.tmp"
            with temp.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.append((temp, target))
        for temp, target in temporary:
            os.replace(temp, target)
    finally:
        for temp, _target in temporary:
            temp.unlink(missing_ok=True)
    return CalibrationPlanExport(
        directory=destination,
        json_path=json_path,
        html_path=html_path,
        sha256_path=sha256_path,
        json_sha256=json_hash,
        recommendation_path=recommendation_path,
    )
