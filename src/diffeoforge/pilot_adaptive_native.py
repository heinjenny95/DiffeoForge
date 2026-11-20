"""Verified native fields and scalar evidence for opt-in bounded pilot stages.

No solver, replay, annotation, approval or owner-file mutation is performed here.
All distances retain native mesh units. Display proxies never supply evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_adaptive_fit import HARD_QUALITY_FLAGS, VERSION, _contract, digest

PROBES = {"baseline_probe", "cp_probe", "motion_probe"}


def eligible_seed(snapshot, identifier):
    """Cheap metadata eligibility, not numerical qualification or inspection.

    This helper reads configuration/receipt metadata only; it never imports a
    field, mesh or native checkpoint. Actual preparation still calls inspect_field.
    """
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import reference
    from diffeoforge.reference_ordinary_guard import DECLARATION as ORDINARY
    from diffeoforge.reference_ordinary_guard import validate
    from diffeoforge.regional_continuation import GUARD

    try:
        if snapshot.plan.pilot_subject_count != 1:
            return False
        candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
        reference(snapshot, identifier)
        config = load_config(candidate.config_path)
        provenance = config["project"].get("parameter_provenance", {})
        scope = provenance.get("finite_accepted_guard")
        if scope == ORDINARY:
            validate(config)
        return bool(
            (scope == GUARD and provenance.get("regional_fit") or scope == ORDINARY)
            and config["optimization"]["method"] == "lbfgs"
            and config["optimization"]["freeze_template"]
            and config["optimization"]["freeze_control_points"]
        )
    except (OSError, ValueError, KeyError, TypeError, StopIteration, AttributeError):
        return False


def basis_sha256(points):
    """Canonical ordered float64 values, independent of text serialization."""
    values = np.ascontiguousarray(points, dtype="<f8")
    if values.ndim != 2 or values.shape[1] != 3 or not len(values) or not np.isfinite(values).all():
        raise ValueError("An adaptive control basis needs finite ordered three-dimensional points")
    return hashlib.sha256(values.tobytes()).hexdigest()


def _number(value, name, *, positive=False):
    if (
        type(value) not in (float, int)
        or not math.isfinite(value)
        or value < 0
        or positive
        and value <= 0
    ):
        raise ValueError("Missing finite adaptive evidence: " + name)
    return float(value)


def _marker(info):
    marker = (info.get("strategy") or {}).get("adaptive_fit")
    if marker is None:
        return None
    if marker.get("version") != VERSION:
        raise ValueError("Unsupported adaptive native-stage declaration")
    _contract(marker["contract"])
    if marker["plan"]["purpose"] not in {"warm", "continue", *PROBES}:
        raise ValueError("Unsupported adaptive native-stage purpose")
    if (
        marker["plan"].get("optimizer_history") != "new"
        or marker["plan"].get("anatomical_approval") is not False
    ):
        raise ValueError("Adaptive stages require fresh optimizer history and separate review")
    return marker


def _staged_plan(run, config):
    from diffeoforge.regional_fit import declaration, read_plan

    row = declaration(config)
    if not row:
        return None
    config = copy.deepcopy(config)
    config["project"]["parameter_provenance"]["regional_fit"] = dict(
        row, manifest=str(Path(run) / "input/regional/plan.json")
    )
    return read_plan(config)


def _field_identity(run, *, inputs=None, plan=None, seen=()):
    """Seal every prefix's verified coefficients without shooting or re-evaluation."""
    from diffeoforge.regional_continuation import physics
    from diffeoforge.regional_evaluation import field_inputs

    run = Path(run).resolve()
    if run in seen or len(seen) >= 64:
        raise ValueError("Cyclic or unbounded residual field ancestry")
    data = inputs if inputs is not None else field_inputs(run, None)
    config = data.run_report.manifest["effective_config"]
    plan = plan if plan is not None else _staged_plan(run, config)
    cp = np.asarray(data.control_points)
    momenta = np.ascontiguousarray(data.momenta, dtype="<f8")
    if (
        momenta.shape != (1, len(cp), 3)
        or not np.isfinite(momenta).all()
        or tuple(data.subject_labels) == ()
    ):
        raise ValueError("The complete singleton field has no finite matching coefficients")
    source_seals = dict(getattr(data, "source_hashes", {}))
    for key, expected in source_seals.items():
        if sha256_file(run / key) != expected:
            raise ValueError("An inherited field source changed")
    # Manifest-only ancestry is insufficient: recursively bind actual CP/momenta.
    residual = (plan or {}).get("residual")
    prefix = None
    if residual:
        parent = Path(residual["parent_run"]).resolve()
        if sha256_file(parent / "manifest.json") != residual["parent_manifest_sha256"]:
            raise ValueError("The inherited field manifest changed")
        prefix = _field_identity(parent, seen=(*seen, run))["field_sha256"]
    identity = dict(
        version="adaptive-native-field-v1",
        basis_sha256=basis_sha256(cp),
        momenta_sha256=hashlib.sha256(momenta.tobytes()).hexdigest(),
        momenta_shape=list(momenta.shape),
        physics=physics(config),
        sources=source_seals,
        regional_plan_sha256=(
            config["project"].get("parameter_provenance", {}).get("regional_fit") or {}
        ).get("sha256"),
        prefix_sha256=prefix,
    )
    return dict(field_sha256=digest(identity), prefix_sha256=prefix, identity=identity)


def _normal_stop(run, frozen):
    log = (Path(run) / "logs/deformetrica.log").read_text(errors="replace")
    cap = frozen["config"]["optimization"]["max_iterations"]
    iteration = frozen["last_logged_native_iteration"]
    if re.search(r"number of line search loops exceeded", log, re.I):
        raise ValueError("A line-search failure cannot authorize an adaptive successor")
    maximum = bool(
        re.search(r"STOP:\s*TOTAL\s+NO\.\s*of\s+ITERATIONS\s+EXCEEDS\s+LIMIT", log, re.I)
    )
    tolerance = bool(re.search(r"tolerance threshold met", log, re.I))
    if maximum and not tolerance and iteration == cap:
        return "maximum_iterations"
    if tolerance and not maximum and 0 <= iteration <= cap:
        return "tolerance"
    raise ValueError("Unknown native stop cannot authorize an adaptive successor")


def inspect_field(snapshot, identifier):
    """Read a normally stopped finite accepted field; never create inspection."""
    from diffeoforge import guided_feedback
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.reference_ordinary_guard import DECLARATION as ORDINARY
    from diffeoforge.regional_continuation import bundle, ordinary_bundle

    ref = guided_feedback.reference(snapshot, identifier)
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    run = study.calibration_candidate_run_directory(candidate)
    config = load_config(candidate.config_path)
    scope = config["project"].get("parameter_provenance", {}).get("finite_accepted_guard")
    verifier = ordinary_bundle if scope == ORDINARY else bundle
    frozen = verifier(run, require_cap=False)
    stop = _normal_stop(run, frozen)
    full = _field_identity(run, inputs=frozen["inputs"], plan=frozen["plan"])
    info = guided.record(snapshot)
    marker = _marker(info)
    if marker:
        seed = marker["plan"]["seed"]
        expected = (
            seed["field_sha256"]
            if marker["plan"]["purpose"] in PROBES
            else seed.get("prefix_sha256")
        )
        if full["prefix_sha256"] != expected:
            raise ValueError("Adaptive child does not preserve its declared complete prefix")
        if marker["plan"]["purpose"] in PROBES:
            residual = frozen["plan"].get("residual")
            source = seed["reference"]
            parent = study.load_reference_calibration_study(source["directory"])
            old = next(c for c in parent.candidates if c.candidate_id == source["candidate_id"])
            parent_run = study.calibration_candidate_run_directory(old)
            if not residual or Path(residual["parent_run"]).resolve() != parent_run.resolve():
                raise ValueError("Adaptive residual belongs to a different selected seed")
        if frozen["config"]["optimization"]["max_iterations"] != marker["plan"]["iterations"]:
            raise ValueError("Adaptive child native cap differs from its sealed allowance")
    cp = frozen["inputs"].control_points
    if not 1 <= len(cp) <= 2000:
        raise ValueError("The adaptive control-point ceiling is 2,000")
    return dict(
        reference=ref,
        field_sha256=full["field_sha256"],
        basis_sha256=basis_sha256(cp),
        control_count=len(cp),
        control_points_path=str(Path(frozen["inputs"].control_points_path).resolve()),
        movement_width=_number(
            frozen["config"]["model"]["deformation"]["kernel_width"],
            "movement width",
            positive=True,
        ),
        prefix_sha256=full["prefix_sha256"],
        native_receipt_sha256=digest(frozen["seals"]),
        iterations=frozen["last_logged_native_iteration"],
        evaluations=frozen["objective_evaluations"],
        normal_terminal=True,
        accepted=True,
        finite=True,
        stop=stop,
        config=frozen["config"],
        bundle=frozen,
        child_manifest_sha256=ref["manifest_sha256"],
    )


def _regions(info, contract):
    marks = (info.get("feedback") or {}).get("regions")
    if not isinstance(marks, list) or not marks or digest(marks) != contract["marks_sha256"]:
        raise ValueError("Adaptive evidence requires the exact ordered red and green marks")
    red, green = {}, {}
    for index, region in enumerate(marks):
        purpose = region.get("purpose", "problem")
        if purpose == "problem":
            red[f"R{index}"] = region
        elif purpose == "fixed":
            green[f"G{index}"] = region
        else:
            raise ValueError("Adaptive scalar policy does not support keep-shape instructions")
    if set(red) != set(contract["red_tolerances"]) or set(green) != set(contract["green_limits"]):
        raise ValueError("Every adaptive instruction needs its own unchanged ROI identity")
    return marks, red, green


def _red_errors(measurements, red):
    errors = {}
    for key, region in red.items():
        matches = [area for area in measurements if area.get("region") == region]
        if len(matches) != 1 or not matches[0].get("repeats"):
            raise ValueError("Missing unique full-resolution ROI measurement: " + key)
        values = []
        for repeat in matches[0]["repeats"]:
            # Absent reverse samples are unknown, not a zero error or successful fit.
            for direction in ("original_to_fit_p95", "fit_to_original_p95"):
                values.append(_number(repeat.get(direction), key + ":" + direction))
        errors[key] = max(values)
    return errors


def _base_receipt(field, contract):
    return {
        key: copy.deepcopy(field[key])
        for key in (
            "reference",
            "field_sha256",
            "basis_sha256",
            "control_count",
            "movement_width",
            "prefix_sha256",
            "native_receipt_sha256",
            "normal_terminal",
            "finite",
            "accepted",
            "iterations",
            "evaluations",
            "stop",
            "child_manifest_sha256",
        )
    } | {key: contract[key] for key in ("objective_sha256", "marks_sha256", "evaluation_sha256")}


def _quality_warnings(quality):
    return [key for key in HARD_QUALITY_FLAGS if quality.get(key) is False]


def baseline_receipt(snapshot, identifier, contract, *, red_errors=None, regions=None):
    """Numerical baseline relative to the explicitly selected field, not approval."""
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.pilot_recovery import capture

    contract = _contract(contract)
    field = inspect_field(snapshot, identifier)
    info = guided.record(snapshot)
    if regions is not None:
        info = dict(info, feedback=dict(info.get("feedback") or {}, regions=regions))
    marks, red, green = _regions(info, contract)
    if red_errors is None:
        rows = capture(snapshot, identifier, field["reference"]["target"], regions=marks)
        red_errors = _red_errors(rows["baseline"], red)
    if set(red_errors) != set(red):
        raise ValueError("The selected baseline lacks a separate error for every red mark")
    errors = {key: _number(value, key) for key, value in red_errors.items()}
    if field["field_sha256"] != contract["seed_sha256"]:
        raise ValueError("The baseline is not the declared selected field")
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    subject = (
        (candidate.metrics or {})
        .get("attachment_comparison", {})
        .get("subjects", {})
        .get(field["reference"]["target"], {})
    )
    warnings = _quality_warnings(
        subject.get("regional_quality") or subject.get("ordinary_quality") or {}
    )
    return dict(
        _base_receipt(field, contract),
        stop="seed",
        iterations=0,
        evaluations=0,
        duration_seconds=0.0,
        red_errors=errors,
        green_errors={key: 0.0 for key in green},
        outside_error=0.0,
        anatomical_approval=False,
        automatic_user_preference=False,
        baseline_relative_to_selected_field=True,
        native_accepted=True,
        quality_warnings=warnings,
        stop_reason=(
            "Explicitly selected provisional repair seed; anatomical review remains separate."
        ),
    )


def stage_receipt(snapshot, identifier, contract):
    """Read every declared ROI and protection check from completed scientific QC."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.regional_fit import instruction_regions

    contract = _contract(contract)
    field = inspect_field(snapshot, identifier)
    info = guided.record(snapshot)
    marker = _marker(info)
    if not marker or marker["contract"] != contract:
        raise ValueError("No matching predeclared bounded native stage")
    marks, red, green = _regions(info, contract)
    if instruction_regions(field["bundle"]["plan"]) != marks:
        raise ValueError("Actual regional fitting instructions differ from the declared marks")
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    subject = candidate.metrics["attachment_comparison"]["subjects"][field["reference"]["target"]]
    quality = subject.get("regional_quality")
    if not quality or quality.get("marked_regions") != marks:
        raise ValueError("Full scientific checks do not match every declared instruction")
    if any(type(quality.get(key)) is not bool for key in HARD_QUALITY_FLAGS):
        raise ValueError("Every full numerical qualification guard must have a known outcome")
    red_errors = _red_errors((subject.get("marked_regions") or {}).get("measurements", []), red)
    green_errors = {}
    fixed = quality.get("fixed_protection") or {}
    if green and fixed.get("active") is not True:
        raise ValueError("Missing all-vertex protection checks for retained regions")
    for fixed_index, key in enumerate(green):
        rows = [r for r in fixed.get("regions", []) if r.get("region") == fixed_index]
        if len(rows) != 1 or type(rows[0].get("vertices")) is not int or rows[0]["vertices"] < 3:
            raise ValueError("Missing complete retained-region material support: " + key)
        green_errors[key] = _number(rows[0].get("maximum"), key + ":maximum")
    if quality.get("unmarked_preservation_basis") == "original_surface":
        rows = quality.get("previously_good_surface") or []
        if not rows or any(
            type(row.get("points")) is not int or row["points"] <= 0 for row in rows
        ):
            raise ValueError("Missing surrounding-original-surface preservation evidence")
        outside = max(
            max(
                0.0,
                _number(row.get("after_p95"), "outside after")
                - _number(row.get("before_p95"), "outside before"),
            )
            for row in rows
        )
    elif quality.get("unmarked_preservation_basis") == "material_positions":
        outside = _number(quality.get("outside_displacement_p95"), "outside material P95")
    else:
        raise ValueError("Unknown surrounding-surface preservation protocol")
    warnings = _quality_warnings(quality)
    run = study.calibration_candidate_run_directory(candidate)
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    duration = _number(
        result.get("duration_seconds", candidate.metrics.get("runtime_seconds")), "native duration"
    )
    return dict(
        _base_receipt(field, contract),
        duration_seconds=duration,
        red_errors=red_errors,
        green_errors=green_errors,
        outside_error=outside,
        quality_warnings=warnings,
        native_accepted=True,
        accepted=not warnings,
        stop_reason=(
            "Numerical qualification needs review: " + ", ".join(warnings)
            if warnings
            else "The native field passed numerical qualification; inspect anatomy."
        ),
        anatomical_approval=False,
        automatic_user_preference=False,
        requires_visual_review=True,
    )


def residual_basis(root, manifest, record, source, target):
    """Construct a declared zero residual probe; never truncate a scientific basis."""
    info = record.get("guided") or {}
    marker = _marker(info)
    if marker is None or marker["plan"]["purpose"] not in PROBES:
        return None
    from diffeoforge.regional_search import controls

    purpose, row = marker["plan"]["purpose"], marker["basis_source"]
    path = Path(row["path"])
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != row["sha256"]
    ):
        raise ValueError("The declared incoming adaptive control file changed")
    points = np.loadtxt(path, dtype=np.float64).reshape(-1, 3)
    if (
        type(row.get("count")) is not int
        or len(points) != row["count"]
        or not 1 <= len(points) <= 2000
        or basis_sha256(points) != row["basis_sha256"]
    ):
        raise ValueError("The declared ordered adaptive control basis changed")
    seed = marker["plan"]["seed"]
    expected = marker.get("parent_basis_sha256")
    if expected != row["sha256"]:
        raise ValueError("The adaptive probe has a different incoming control file")
    width = _number(
        manifest["plan"]["baseline_effective_values"]["deformation_kernel_width"],
        "probe movement width",
        positive=True,
    )
    spacing = _number(row.get("spacing"), "incoming nominal CP spacing", positive=True)
    if purpose == "motion_probe":
        if (
            marker.get("basis_relation") != "unchanged"
            or len(points) <= seed["control_count"]
            or not width < seed["movement_width"]
        ):
            raise ValueError("A motion probe must reuse the exact larger CP-arm basis")
        return (
            points,
            spacing,
            dict(
                version=VERSION,
                scope="declared_cp_probe_basis",
                controls=len(points),
                basis_sha256=basis_sha256(points),
                parent_basis_sha256=row["basis_sha256"],
                unchanged_basis=True,
                nominal_spacing=spacing,
            ),
        )
    if (
        basis_sha256(points) != seed["basis_sha256"]
        or len(points) != seed["control_count"]
        or width != seed["movement_width"]
    ):
        raise ValueError("The controlled probe changed its incoming basis or movement width")
    if purpose == "baseline_probe":
        if marker.get("basis_relation") != "unchanged":
            raise ValueError("The baseline probe must preserve the incoming ordered basis")
        return points, spacing, None
    if marker.get("basis_relation") != "nested":
        raise ValueError("The control-point probe must declare a nested basis")
    _, red, _ = _regions(info, marker["contract"])
    additions, fine_spacing, coverage = controls(
        np.asarray(source, float), np.asarray(target, float), list(red.values()), width, limit=2000
    )
    seen = {tuple(value) for value in points}
    extra = []
    for value in additions:
        key = tuple(value)
        if key not in seen:
            seen.add(key)
            extra.append(value)
    if not extra or len(points) + len(extra) > 2000:
        raise ValueError("A complete nested CP probe cannot fit the declared 2,000-point ceiling")
    nested = np.vstack((points, np.asarray(extra, dtype=np.float64)))
    # Keep every old value and its exact row order, including signed zero.
    if not np.array_equal(nested[: len(points)].view(np.uint64), points.view(np.uint64)):
        raise ValueError("The nested probe changed the incoming coefficient basis")
    coverage = dict(
        coverage,
        adaptive_version=VERSION,
        controls=len(nested),
        incoming_controls=len(points),
        added_controls=len(extra),
        parent_basis_sha256=row["basis_sha256"],
        basis_sha256=basis_sha256(nested),
        unchanged_incoming_order=True,
    )
    return nested, fine_spacing, coverage
