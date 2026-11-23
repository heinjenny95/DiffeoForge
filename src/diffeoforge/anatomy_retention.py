"""Read-only, repeated surface measurements along a specimen's atlas handoff."""

from __future__ import annotations

import math
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from diffeoforge import anatomy_retention_material as fixed
from diffeoforge import pilot_regions
from diffeoforge.mesh import sha256_file
from diffeoforge.mesh_filter_worker import mesh_filter_cancellation
from diffeoforge.reconstruction_feedback import ReconstructionMaterialUnavailable, material_mask
from diffeoforge.reference_attachment_comparison import compare_geometry
from diffeoforge.surface_io import load_surface_mesh

WHOLE_METRICS = ("p95", "p99")
AREA_METRICS = ("original_to_fit_p95", "original_to_fit_p99", "fit_to_original_p95",
                "fit_to_original_p99")


@dataclass(frozen=True)
class SurfaceEvidence:
    path: Path
    sha256: str


@dataclass(frozen=True)
class RetentionStage:
    key: str
    label: str
    surface: SurfaceEvidence | None
    reason: str = ""
    material_template: SurfaceEvidence | None = None


@dataclass(frozen=True)
class RetentionRow:
    stage_key: str
    area: int | None
    metric: str
    approved: tuple[float, float] | None
    observed: tuple[float, float] | None
    change: str


@dataclass(frozen=True)
class AnatomyRetentionReport:
    target: str
    original: SurfaceEvidence
    regions: tuple[dict, ...]
    stages: tuple[RetentionStage, ...]
    rows: tuple[RetentionRow, ...]
    summary: str
    warnings: tuple[tuple[str, str], ...] = ()


def _check_cancelled(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("Anatomy comparison cancelled.")


def _load(source):
    if source.path.is_symlink() or not source.sha256:
        raise ValueError("A regular source-bound mesh is required")
    mesh = load_surface_mesh(source.path)
    if mesh.metadata.sha256 != source.sha256:
        raise ValueError("The saved anatomy comparison mesh changed")
    return mesh.geometry


def _range(measure, key):
    if not measure:
        return None
    values = [row.get(key) for row in measure["repeats"]]
    diagonal = measure["diagonal"]
    if (not math.isfinite(diagonal) or diagonal <= 0 or len(values) != 2
            or any(v is None or not math.isfinite(v) or v < 0 for v in values)):
        return None
    return min(values) * 100 / diagonal, max(values) * 100 / diagonal


def _distances(original, fitted, digest, regions, lineage):
    global_result = compare_geometry(original, fitted, original_key=digest)
    available = []
    patches = [None] * len(regions)
    for i, region in enumerate(regions):
        if region.get("reconstruction"):
            try:
                material_mask(fitted.vertices, fitted.triangles, [region], lineage=lineage)
            except ReconstructionMaterialUnavailable:
                continue
        available.append(i)
    if available:
        measured = pilot_regions.measure(original, fitted, [regions[i] for i in available],
                                         material_lineage=lineage)
        for i, row in zip(available, measured, strict=True):
            patches[i] = row
    measurements = {(None, k): _range(global_result, k) for k in WHOLE_METRICS}
    for i, row in enumerate(patches):
        measurements.update({(i, k): _range(row, k) for k in AREA_METRICS})
    return measurements, global_result.get("warnings", ())


def _change(before, observed):
    if before is None or observed is None:
        return "unavailable"
    # Existing repeat-comparison guard. Values are percentages of the original diagonal.
    if observed[0] > before[1] * 1.05 + 1e-4:
        return "worse"
    if observed[1] + 1e-4 < before[0] * .95:
        return "better"
    return "unclear"


def _empty_original_patch(row, regions, by_key):
    """A mark on added reconstruction material may intentionally lie in empty original space."""
    if (row.area is None or not regions[row.area].get("reconstruction")
            or not row.metric.startswith("original_to_fit_")
            or row.approved is not None or row.observed is not None):
        return False
    opposite = row.metric.replace("original_to_fit", "fit_to_original")
    reverse = by_key[row.stage_key, row.area, opposite]
    return reverse.approved is not None and reverse.observed is not None


def _area_labels(areas):
    labels = [chr(65 + i) for i in sorted(i for i in areas if i is not None)]
    if None in areas:
        labels.append("whole surface")
    return ", ".join(labels)


def _stage_notes(stages, rows):
    """Attribute a change to an adjacent measured interval, never over a missing boundary."""
    result = list(stages)
    measured = {(r.stage_key, r.area, r.metric): r.observed for r in rows}
    for index in range(2, len(result)):
        current, previous = result[index], result[index - 1]
        if not current.surface or not previous.surface:
            continue
        worsening = set()
        improvement = set()
        for row in rows:
            if row.stage_key != current.key:
                continue
            earlier = measured[previous.key, row.area, row.metric]
            if row.metric in fixed.METRICS:
                continue  # The dense position guard is relative to the approved material.
            change = _change(earlier, row.observed)
            if change == "worse":
                worsening.add(row.area)
            if change == "better":
                improvement.add(row.area)
        notes = [current.reason] if current.reason else []
        for areas, change in ((worsening, "increased"), (improvement, "decreased")):
            if areas:
                notes.append(f"Since “{previous.label}”, distances {change} in at least one "
                             f"measure ({_area_labels(areas)}).")
        result[index] = replace(current, reason=" ".join(notes))
    return tuple(result)


def _interpret(stages, rows, warnings, regions):
    messages = []
    by_key = {(r.stage_key, r.area, r.metric): r for r in rows}
    for stage in stages[1:]:
        if not stage.surface:
            continue
        current = [r for r in rows if r.stage_key == stage.key]
        loss = {r.area for r in current if r.change == "worse"}
        if loss:
            messages.append(f"{stage.label} shows larger distances than the approved fit "
                            f"({_area_labels(loss)}).")
        if any(r.change == "unavailable" and not _empty_original_patch(r, regions, by_key)
               for r in current):
            messages.append(f"{stage.label} has incomplete local coverage or material mapping.")
    if not any(s.surface for s in stages[1:]):
        messages.append("The approved fit is available. A second verified surface is needed.")
    elif not messages:
        messages.append("Available measurements show no repeat-confirmed distance increase.")
    observed = [i for i, s in enumerate(stages) if s.surface]
    if any(not s.surface for s in stages[:max(observed)]):
        messages.append("A missing intermediate surface leaves the timing of a change unresolved.")
    latest = stages[max(observed)]
    outstanding = {(r.area, r.metric) for r in rows
                   if r.stage_key == latest.key and r.change == "worse"}
    first = next((s for s in stages[1:] if any(
        r.stage_key == s.key and r.change == "worse" and (r.area, r.metric) in outstanding
        for r in rows)), None)
    if not outstanding and any(r.change == "worse" for r in rows):
        messages.append("The last measured surface shows no confirmed increase in the available "
                        "measures. Inspect any remaining gaps in coverage there.")
    if any(r.metric in fixed.METRICS for r in rows):
        messages.append("Fixed material displacement uses all identifiable vertices of each green "
                        "patch relative to the approved fit. The dense fixed-area check allows "
                        "up to 0.01% of the original diagonal at any vertex.")
    if first:
        actions = {
            "transfer": "Inspect the shared starting field before spending more iterations.",
            "common": "Inspect the affected areas after fitting the original before joint testing.",
            "pilot_joint": "Inspect the affected areas in the joint pilot before full atlasing.",
            "atlas_start": "Inspect the exported starting surface before interpreting the atlas.",
            "atlas": "Inspect the affected final-atlas areas before interpreting shape space.",
        }
        if first.key in actions:
            messages.append(actions[first.key])
    if any(_empty_original_patch(r, regions, by_key) for r in rows):
        messages.append("A marked patch lies in empty original space. "
                        "Read its fit-to-original distances for the selected material.")
    messages.extend(f"{s.label} · {warning}." for s in stages for key, warning in warnings
                    if s.key == key)
    return " ".join(messages)


def assess_stages(target, original, regions, stages, *, lineages=None, cancelled=None):
    """Compare every verified full surface with the same original and review marks."""
    regions = tuple(pilot_regions.validate({target: regions}, {target: original.sha256})[target]
                    if regions else ())
    stages = tuple(stages)
    if (not stages or stages[0].key != "approved" or stages[0].surface is None
            or len({s.key for s in stages}) != len(stages)):
        raise ValueError("Retention needs one approved reference and unique stage identities")
    rows = []
    warnings = []
    baseline = {}
    cached = {}
    fixed_areas = any(row.get("purpose") == "fixed" for row in regions)
    patches = None
    templates = {}
    _check_cancelled(cancelled)
    original_mesh = _load(original)
    scope = mesh_filter_cancellation(cancelled) if cancelled is not None else nullcontext()
    with scope:
        for stage in stages:
            _check_cancelled(cancelled)
            values = {}
            if stage.surface:
                lineage = (lineages or {}).get(stage.key)
                key = stage.surface.sha256, id(lineage)
                if key in cached:
                    if (stage.surface.path.is_symlink()
                            or sha256_file(stage.surface.path) != stage.surface.sha256):
                        raise ValueError("The saved anatomy comparison mesh changed")
                else:
                    fitted = _load(stage.surface)
                    distances, notes = _distances(original_mesh, fitted, original.sha256, regions,
                                                  lineage)
                    cached[key] = distances, notes, fitted if fixed_areas else None
                values, notes, fitted = cached[key]
                if fixed_areas:
                    template = stage.material_template
                    if template and template not in templates:
                        templates[template] = _load(template)
                    grid = templates.get(template)
                    if stage.key == "approved":
                        patches = fixed.FixedPatches(stage, fitted, grid, lineage, regions,
                                                     original_mesh)
                    values = {**values, **patches.compare(stage, fitted, grid, lineage)}
                warnings.extend((stage.key, note) for note in notes)
            if stage.key == "approved":
                baseline = values
            for (index, metric), ref in baseline.items():
                obs = values.get((index, metric))
                change = _change(ref, obs)
                if metric in fixed.METRICS and ref is not None and obs is not None:
                    change = "worse" if obs[1] > fixed.LIMIT_PERCENT else "unclear"
                rows.append(RetentionRow(stage.key, index, metric, ref, obs, change))
    stages = _stage_notes(stages, rows)
    return AnatomyRetentionReport(target, original, regions, stages, tuple(rows),
                                 _interpret(stages, rows, warnings, regions), tuple(warnings))


def compare_approved_endpoint(approved_reference, path, sha256, *, regions=None, cancelled=None,
                              stage="projection", material_template_sha256=None):
    """Review a proposed transfer endpoint before a new fit to the original can be offered."""
    from diffeoforge.anatomy_retention_sources import approved_source

    original, approved, saved_marks, lineage = approved_source(approved_reference, cancelled)
    stages = {"projection": ("transfer", "Projected starting field"),
              "original": ("common", "After fitting the original")}
    if stage not in stages:
        raise ValueError("Choose the projected field or the fitted original")
    key, label = stages[stage]
    template = approved.material_template
    if not template or template.sha256 != material_template_sha256:
        template = None
    fit = RetentionStage(key, label, SurfaceEvidence(Path(path), sha256),
                         material_template=template)
    report = assess_stages(approved_reference["target"], original,
                           saved_marks if regions is None else regions, (approved, fit),
                           lineages={"approved": lineage}, cancelled=cancelled)
    rows = [r for r in report.rows if r.stage_key == key]
    by_key = {(r.stage_key, r.area, r.metric): r for r in rows}
    changes = {r.change for r in rows if not _empty_original_patch(r, report.regions, by_key)}
    warnings = [note for stage_key, note in report.warnings if stage_key == key]
    return dict(status="regression" if "worse" in changes else "unmeasured"
                if "unavailable" in changes or warnings else "comparable",
                rows=[asdict(r) for r in rows], warnings=warnings,
                summary=report.summary, anatomical_approval=False)


def prepare_pilot_retention(directory, candidate_id, target, *, context_directory=None,
                            cancelled=None):
    from diffeoforge.anatomy_retention_sources import pilot_report

    return pilot_report(directory, candidate_id, target, context_directory, cancelled)


def prepare_atlas_retention(run, target, *, cancelled=None):
    from diffeoforge.anatomy_retention_sources import atlas_report

    return atlas_report(run, target, cancelled)


def atlas_retention_targets(config):
    """Discover linked pilot labels without reading meshes or reloading studies."""
    from diffeoforge.reference_atlas_handoff import METHOD, initialization

    plan = initialization(config)
    if not plan or plan.get("method") != METHOD or not plan.get("source_run_manifest_sha256"):
        return ()
    labels = plan.get("pilot_subject_labels", [])
    return tuple(labels) if len(set(labels)) == len(labels) else ()


def prepare_projection_retention(directory, *, cancelled=None):
    from diffeoforge.anatomy_retention_sources import projection_report

    return projection_report(directory, cancelled)
