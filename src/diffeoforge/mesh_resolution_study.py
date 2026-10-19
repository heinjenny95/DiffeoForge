"""Prospective, read-only comparison of explicitly approved scientific mesh levels.

No mesh is simplified and no native computation is launched by this module.
The frozen design precedes all assigned atlas runs. Missing evidence prevents a
resolution recommendation rather than silently weakening the declared checks.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.reference_calibration_metrics import (
    _collect_reference_calibration_metrics_from_report,
    symmetric_nearest_vertex_distances,
)
from diffeoforge.reference_pca import load_reference_momenta
from diffeoforge.strict_json import load_strict_json_object

VERSION = "0.1"
PLAN = "mesh-resolution-study.json"
THRESHOLDS = {
    "template_p95_mesh_units",
    "residual_p95_change_mesh_units",
    "tangent_distance_relative_error",
    "minimum_score_cka",
    "maximum_score_subspace_angle_degrees",
    "pc_extreme_p95_mesh_units",
}
BOUNDARY = (
    "A recommendation applies only to the declared tested meshes, model and tolerances. "
    "Distances are deterministic sampled nearest-vertex proxies (at most 5,000 vertices "
    "per direction). Numerical stability does not establish anatomical or biological validity. "
    "Display proxies are never scientific simplification levels."
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _read_json(path):
    path = Path(path)
    return load_strict_json_object(path.read_bytes(), path, label="Mesh-resolution evidence")


def _record(path):
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"A regular source file is required: {source.name}")
    source = source.resolve()
    return {"path": str(source), "bytes": source.stat().st_size, "sha256": sha256_file(source)}


def _check(record):
    if _record(record["path"]) != record:
        raise ValueError(f"Frozen source changed: {Path(record['path']).name}")


def _scientific_config(config):
    value = deepcopy(config)
    for key in ("input", "output", "project"):
        value.pop(key, None)
    return value


def _run_config(source, root, key, fingerprint):
    value = deepcopy(load_config(source))
    inputs = validate_input_paths(value, source)
    value["input"].update(directory=str(inputs.input_directory), template=str(inputs.template))
    for name in ("initial_control_points", "initial_momenta"):
        path = getattr(inputs, name)
        if path is not None:
            value["model"]["deformation"][name] = str(path)
    value["output"]["directory"] = str(root / "runs" / key)
    value["project"]["mesh_resolution_study"] = {"fingerprint": fingerprint, "level": key}
    return value


def _thresholds(spec):
    limits = spec["thresholds"]
    if set(limits) != THRESHOLDS:
        raise ValueError("Declare every mesh-resolution stability tolerance")
    for key, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Invalid tolerance: {key}")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Tolerance must be finite and positive: {key}")
    if limits["minimum_score_cka"] > 1 or limits["maximum_score_subspace_angle_degrees"] > 90:
        raise ValueError("CKA must be in (0,1]; subspace angle must be in (0,90]")
    count = spec["components"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise ValueError("Declare 1–10 PCA components before running the study")
    return limits


def freeze_study(spec_path, destination):
    """Freeze approved configs, all source/derived bytes and explicit simplification provenance."""
    spec_path, target = Path(spec_path).resolve(), Path(destination).resolve()
    spec = _read_json(spec_path)
    if spec.get("study_version") != VERSION or spec.get("researcher_approved") is not True:
        raise ValueError("The researcher must explicitly approve the declared mesh levels")
    _thresholds(spec)
    if not 2 <= len(spec["levels"]) <= 10:
        raise ValueError("Declare 2–10 scientific mesh levels")
    levels, common, subjects, units = [], None, None, None
    for level in spec["levels"]:
        key = level["id"]
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", key)
            or key in {row["id"] for row in levels}
        ):
            raise ValueError("Mesh-level IDs must be nonempty and unique")
        path = Path(level["config"]).expanduser()
        path = path if path.is_absolute() else spec_path.parent / path
        config_record = _record(path)
        config = load_config(path)
        if config["runtime"]["backend"] != "deformetrica_reference":
            raise ValueError("This study requires Deformetrica reference configurations")
        inputs = validate_input_paths(config, path)
        signature = _scientific_config(config)
        names = tuple(p.name for p in inputs.subjects)
        current_units = config["input"]["units"]
        if common is not None and (
            signature != common or subjects != names or units != current_units
        ):
            raise ValueError(
                "Levels must retain the same ordered cohort, units and scientific settings"
            )
        common, subjects, units = signature, names, current_units
        declarations = level["provenance"]
        if not isinstance(declarations, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("derived"), str)
            or not isinstance(row.get("source"), str)
            or not Path(row["derived"]).expanduser().is_absolute()
            or not Path(row["source"]).expanduser().is_absolute()
            for row in declarations
        ):
            raise ValueError("Provenance must declare absolute source and derived mesh paths")
        provenance = {Path(row["derived"]).expanduser().resolve(): row for row in declarations}
        if len(provenance) != len(declarations):
            raise ValueError("Duplicate derived mesh in simplification provenance")
        records = []
        for mesh in (inputs.template, *inputs.subjects):
            mesh = mesh.resolve()
            if mesh not in provenance:
                raise ValueError(f"Missing simplification provenance for {mesh.name}")
            declaration = provenance[mesh]
            if not declaration.get("method") or not declaration.get("tool_version"):
                raise ValueError("Every mesh requires a simplification method and tool version")
            if not isinstance(declaration.get("parameters"), dict):
                raise ValueError(
                    "Record explicit simplification parameters, including identity copies"
                )
            derived, origin = _record(mesh), _record(declaration["source"])
            geometry = read_vtk_polydata(mesh)
            _check(derived)
            records.append(
                {
                    "role": "template" if mesh == inputs.template.resolve() else "subject",
                    "name": mesh.name,
                    "derived": derived,
                    "source": origin,
                    "method": declaration["method"],
                    "tool_version": declaration["tool_version"],
                    "parameters": declaration["parameters"],
                    "faces": len(geometry.triangles),
                }
            )
        if len(provenance) != len(records):
            raise ValueError("Provenance must describe exactly the declared cohort and template")
        levels.append(
            {
                "id": key,
                "config": config_record,
                "meshes": records,
                "median_subject_faces": float(
                    np.median([row["faces"] for row in records if row["role"] == "subject"])
                ),
            }
        )
    face_counts = [level["median_subject_faces"] for level in levels]
    if len(set(face_counts)) != len(face_counts):
        raise ValueError("Declare distinct measured face-count levels")
    reference = max(levels, key=lambda level: level["median_subject_faces"])["id"]
    if spec["reference_level"] != reference:
        raise ValueError("The reference must be the highest declared mesh resolution")
    # A derived level must retain each specimen's source identity across all levels.
    origins = [
        {(m["role"], m["name"]): m["source"]["sha256"] for m in level["meshes"]} for level in levels
    ]
    if any(value != origins[0] for value in origins[1:]):
        raise ValueError("Mesh levels do not derive from the same original specimen bytes")
    value = {
        "study_version": VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "researcher_approved": True,
        "reference_level": reference,
        "units": units,
        "components": spec["components"],
        "thresholds": spec["thresholds"],
        "scientific_settings": common,
        "levels": levels,
        "boundary": BOUNDARY,
    }
    for level in levels:
        _check(level["config"])
        for mesh in level["meshes"]:
            _check(mesh["derived"])
            _check(mesh["source"])
    target.mkdir(parents=True, exist_ok=False)
    fingerprint = hashlib.sha256(_json(value).encode()).hexdigest()
    value["design_fingerprint"] = fingerprint
    (target / "levels").mkdir()
    from diffeoforge.initialization import _CONFIG_MARKER

    for level in value["levels"]:
        config = _run_config(Path(level["config"]["path"]), target, level["id"], fingerprint)
        path = target / "levels" / (level["id"] + ".yaml")
        write_text_safely(
            path, _CONFIG_MARKER + "\n" + yaml.safe_dump(config, sort_keys=False), overwrite=False
        )
        load_config(path)
        level["run_config"] = _record(path)
    content = _json(value)
    write_text_safely(target / PLAN, content, overwrite=False)
    write_text_safely(
        target / (PLAN + ".sha256"),
        hashlib.sha256(content.encode()).hexdigest() + "\n",
        overwrite=False,
    )
    return target


def load_study(directory):
    root = Path(directory).resolve()
    path = root / PLAN
    if path.is_symlink() or sha256_file(path) != (root / (PLAN + ".sha256")).read_text().strip():
        raise ValueError("Mesh-resolution study changed")
    value = _read_json(path)
    if value.get("study_version") != VERSION or value.get("researcher_approved") is not True:
        raise ValueError("Unsupported or unapproved mesh-resolution study")
    _thresholds(value)
    core = deepcopy(value)
    fingerprint = core.pop("design_fingerprint")
    for level in core["levels"]:
        level.pop("run_config")
    if hashlib.sha256(_json(core).encode()).hexdigest() != fingerprint:
        raise ValueError("Prospective design fingerprint differs from its frozen contents")
    for level in value["levels"]:
        _check(level["config"])
        _check(level["run_config"])
        expected = _run_config(Path(level["config"]["path"]), root, level["id"], fingerprint)
        if load_config(level["run_config"]["path"]) != expected:
            raise ValueError("Study run configuration differs from the declared design")
        for mesh in level["meshes"]:
            _check(mesh["source"])
            _check(mesh["derived"])
    return value


def _run_inputs(plan, level, run):
    inputs = load_reference_momenta(run)
    manifest = inputs.run_report.manifest
    declared = datetime.fromisoformat(plan["created_at"])
    if (
        datetime.fromisoformat(manifest["created_at"]) < declared
        or datetime.fromisoformat(inputs.run_report.result["started_at"]) < declared
    ):
        raise ValueError("The assigned run predates the prospective mesh-resolution design")
    if manifest["source_config"]["sha256"] != level["run_config"]["sha256"]:
        raise ValueError("The run was prepared from another level configuration")
    if manifest["effective_config"]["project"].get("mesh_resolution_study") != {
        "fingerprint": plan["design_fingerprint"],
        "level": level["id"],
    }:
        raise ValueError("The run has no matching prospective design binding")
    expected = sorted((m["role"], m["name"], m["derived"]["sha256"]) for m in level["meshes"])
    observed = sorted(
        (m["role"], Path(m["source_path"]).name, m["geometry"]["sha256"])
        for m in manifest["inputs"]
        if m["role"] in {"template", "subject"}
    )
    if observed != expected:
        raise ValueError("Run mesh bytes or specimen identities differ from the frozen level")
    return inputs


def _geometry_p95(first, second):
    values = symmetric_nearest_vertex_distances(read_vtk_polydata(first), read_vtk_polydata(second))
    return float(np.quantile(values, 0.95))


def compare_scores(first, second, components):
    """Compare score subspaces in specimen space, allowing PC sign/rotation ambiguity."""
    left, right = (np.asarray(values, dtype=float)[:, :components] for values in (first, second))
    left, right = left - left.mean(0), right - right.mean(0)
    if (
        left.shape != right.shape
        or not np.isfinite(left).all()
        or not np.isfinite(right).all()
        or min(np.linalg.matrix_rank(left), np.linalg.matrix_rank(right)) < components
    ):
        raise ValueError("The declared PCA score subspace is not available at every level")
    denominator = np.linalg.norm(left.T @ left) * np.linalg.norm(right.T @ right)
    cka = float(np.linalg.norm(left.T @ right) ** 2 / denominator)
    ql, qr = np.linalg.qr(left)[0], np.linalg.qr(right)[0]
    cosines = np.linalg.svd(ql.T @ qr, compute_uv=False)
    angle = float(np.degrees(np.arccos(np.clip(cosines.min(), 0, 1))))
    return min(1.0, max(0.0, cka)), angle


def _endpoints(inputs, components):
    from diffeoforge.reference_pca import REFERENCE_PCA_MANIFEST
    from diffeoforge.reference_pca_deformations import (
        DEFAULT_RESULT_DIRECTORY,
        DESIGN_NAME,
        verify_reference_pca_deformation_result,
    )

    root = inputs.run_directory / DEFAULT_RESULT_DIRECTORY
    evidence = verify_reference_pca_deformation_result(root, source_run=inputs.run_directory)
    design = _read_json(root / "design" / DESIGN_NAME)
    bundle = _read_json(Path(design["source"]["pca_bundle"]) / REFERENCE_PCA_MANIFEST)
    if (
        evidence["shooting"]["standard_deviations"] != 2.0
        or bundle["pca"]["method_id"] != "lddmm_deformation_kernel_pca"
    ):
        raise ValueError("This study requires ±2 SD extremes of the fitted LDDMM tangent PCA")
    paths = {
        (row["component"], row["direction"]): root / row["path"]
        for row in evidence["endpoints"]
        if row["role"] == "principal_component_endpoint"
    }
    if any(
        (pc, sign) not in paths for pc in range(1, components + 1) for sign in ("minus", "plus")
    ):
        raise ValueError("Native reconstructed extremes are missing for declared PCA components")
    return paths


def assess_study(directory, assignments, destination, *, progress=None):
    """Assess complete prospective levels and create an immutable JSON/HTML report."""
    from diffeoforge.analysis.shape_space import (
        lddmm_metric_momenta_pca,
        lddmm_momenta_squared_distances,
    )

    root, target = Path(directory).resolve(), Path(destination).resolve()
    plan = load_study(root)
    ids = {row["id"] for row in plan["levels"]}
    if set(assignments) != ids:
        raise ValueError("Assign exactly one completed run to every frozen mesh level")
    if len({Path(value).resolve() for value in assignments.values()}) != len(ids):
        raise ValueError("One run cannot stand in for different mesh resolutions")
    evidence, sources, endpoint_snapshots = {}, {}, {}
    for level in plan["levels"]:
        key = level["id"]
        if progress:
            progress(f"Verifying mesh level: {key}")
        inputs = _run_inputs(plan, level, Path(assignments[key]).resolve())
        metrics = _collect_reference_calibration_metrics_from_report(inputs.run_report)
        width = inputs.run_report.manifest["effective_config"]["model"]["deformation"][
            "kernel_width"
        ]
        pca = lddmm_metric_momenta_pca(
            inputs.momenta,
            inputs.control_points,
            deformation_kernel_width=width,
            subject_labels=inputs.subject_labels,
        )
        distances = np.sqrt(
            lddmm_momenta_squared_distances(
                inputs.momenta, inputs.control_points, deformation_kernel_width=width
            )
        )
        try:
            endpoints = _endpoints(inputs, plan["components"])
            missing = None
        except (OSError, RuntimeError, ValueError) as error:
            endpoints, missing = None, str(error)
        evidence[key] = inputs, metrics, pca, distances, endpoints, missing
        sources[key] = {"run": str(inputs.run_directory), **dict(inputs.source_hashes)}
        if endpoints is not None:
            endpoint_snapshots[key] = [
                {"component": pc, "direction": sign, **_record(path)}
                for (pc, sign), path in sorted(endpoints.items())
            ]
            sources[key]["pc_endpoints"] = endpoint_snapshots[key]
    baseline = evidence[plan["reference_level"]]
    rows = []
    for level in plan["levels"]:
        key = level["id"]
        inputs, metrics, pca, distances, endpoints, missing = evidence[key]
        base_inputs, base_metrics, base_pca, base_distances, base_ends, base_missing = baseline
        if inputs.subject_labels != base_inputs.subject_labels:
            raise ValueError("PCA specimen order differs across mesh levels")
        reasons = []
        if not metrics.converged or not base_metrics.converged:
            reasons.append("Native optimizer tolerance is not established at every compared level")
        if metrics.invalid_face_count or base_metrics.invalid_face_count:
            reasons.append("Invalid output faces require inspection")
        delta = float(
            np.linalg.norm(distances - base_distances) / max(np.linalg.norm(base_distances), 1e-30)
        )
        measured = {
            "template_p95_mesh_units": _geometry_p95(metrics.atlas_path, base_metrics.atlas_path),
            "tangent_distance_relative_error": delta,
        }
        residuals, base_residuals = (
            dict(metrics.subject_residual_p95),
            dict(base_metrics.subject_residual_p95),
        )
        if residuals and residuals.keys() == base_residuals.keys():
            measured["residual_p95_change_mesh_units"] = max(
                abs(value - base_residuals[name]) for name, value in residuals.items()
            )
        else:
            reasons.append("Paired per-specimen registration residuals are unavailable")
        try:
            cka, angle = compare_scores(base_pca.scores, pca.scores, plan["components"])
            measured.update(minimum_score_cka=cka, maximum_score_subspace_angle_degrees=angle)
        except ValueError as error:
            reasons.append(str(error))
        if endpoints is None or base_ends is None:
            reasons.append(
                "Run Show shape changes along PC axes for this and the reference level: "
                + (missing or base_missing or "missing endpoints")
            )
        else:
            pc_errors = []
            for pc in range(1, plan["components"] + 1):
                # PC signs are arbitrary; compare both orientations, preserving each ± pair.
                direct = max(
                    _geometry_p95(endpoints[pc, sign], base_ends[pc, sign])
                    for sign in ("minus", "plus")
                )
                flipped = max(
                    _geometry_p95(endpoints[pc, sign], base_ends[pc, opposite])
                    for sign, opposite in (("minus", "plus"), ("plus", "minus"))
                )
                pc_errors.append(min(direct, flipped))
            measured["pc_extreme_p95_mesh_units"] = max(pc_errors)
        for metric, value in measured.items():
            threshold = plan["thresholds"][metric]
            passed = value >= threshold if metric == "minimum_score_cka" else value <= threshold
            if not passed:
                reasons.append(f"{metric}: {value:.6g}; declared threshold {threshold:.6g}")
        rows.append(
            {
                "level": key,
                "median_subject_faces": level["median_subject_faces"],
                "measurements": measured,
                "passed": not reasons and set(measured) == THRESHOLDS,
                "next_actions": reasons,
            }
        )
    # Every declared level is reported. Incomplete evidence anywhere blocks a face-count claim.
    complete = all(set(row["measurements"]) == THRESHOLDS for row in rows)
    eligible = [row for row in rows if row["passed"]]
    chosen = (
        min(eligible, key=lambda row: row["median_subject_faces"])
        if complete and eligible
        else None
    )
    load_study(root)
    for level in plan["levels"]:
        fresh = _run_inputs(plan, level, Path(assignments[level["id"]]).resolve())
        if dict(fresh.source_hashes) != {
            k: v for k, v in sources[level["id"]].items() if k not in {"run", "pc_endpoints"}
        }:
            raise ValueError("Run evidence changed during mesh-resolution assessment")
        if evidence[level["id"]][4] is not None:
            if _endpoints(fresh, plan["components"]) != evidence[level["id"]][4]:
                raise ValueError("PC endpoint evidence changed during assessment")
            for record in endpoint_snapshots[level["id"]]:
                _check({key: record[key] for key in ("path", "bytes", "sha256")})
    value = {
        "assessment_version": VERSION,
        "study_sha256": sha256_file(root / PLAN),
        "sources": sources,
        "thresholds": plan["thresholds"],
        "levels": rows,
        "smallest_supported_tested_level": chosen["level"] if chosen else None,
        "boundary": BOUNDARY,
        "interpretation": "PCA subspace angles compare score subspaces in specimen space. "
        "They are not feature-space component angles. Near-tied PC axes may rotate; "
        "axis-specific extreme checks can therefore remain inconclusive.",
    }
    headline = (
        f"Smallest numerically stable tested level: {chosen['level']}"
        if chosen
        else "No face-count recommendation is supported"
    )
    content = "<!doctype html><meta charset='utf-8'><title>Mesh resolution study</title>"
    content += "<h1>" + html.escape(headline) + "</h1><p>" + html.escape(BOUNDARY) + "</p>"
    for row in rows:
        content += "<h2>" + html.escape(row["level"]) + "</h2><table>"
        for name, number in row["measurements"].items():
            content += f"<tr><td>{html.escape(name)}</td><td>{number:.8g}</td></tr>"
        content += (
            "</table><ul>"
            + "".join("<li>" + html.escape(reason) + "</li>" for reason in row["next_actions"])
            + "</ul>"
        )
    target.mkdir(parents=True, exist_ok=False)
    write_text_safely(target / "assessment.json", _json(value), overwrite=False)
    write_text_safely(target / "report.html", content, overwrite=False)
    write_text_safely(
        target / "checksums.json",
        _json({name: sha256_file(target / name) for name in ("assessment.json", "report.html")}),
        overwrite=False,
    )
    return target
