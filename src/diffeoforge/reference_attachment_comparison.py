"""Matched Current/Varifold pilot trials and geometry-only recommendations.

Preparation and inspection never execute a backend. Only an explicit pilot run
dispatches trials. Every method uses one common pilot cohort and fresh fields;
method selection never grants anatomical approval.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import CalibrationCandidate, _canonical_hash

VERSION = "attachment-comparison-v1"
METHODS = ("current", "varifold")
ITERATIONS = 120
SAMPLES = 8192
# Engineering warning only, not a biological size constraint or acceptance gate.
SHRINK_WARNING = 0.1
_TARGET_EVIDENCE = {}  # Bounded scalar/sample cache; never retain whole meshes.


def selection(config):
    return config["project"].get("parameter_provenance", {}).get("attachment_selection", {})


def pending(config):
    return selection(config).get("mode") == "auto" and selection(config).get("state") == "pending"


def prepare(directory):
    """Create separate immutable trials without executing any of them."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.reference_sequential_fit import _fingerprint
    from diffeoforge.surface_io import load_surface_mesh

    source = study.load_reference_calibration_study(directory)
    manifest = study._verify_manifest(source.study_directory)
    config = copy.deepcopy(load_config(source.study_directory / manifest["source_config"]["copy"]))
    from diffeoforge.reference_guided_pilot import enabled
    from diffeoforge.reference_guided_pilot import prepare as prepare_guided

    if enabled(config):
        return prepare_guided(directory)
    if not pending(config) or manifest.get("fit_search") or source.selected_candidate_ids:
        raise ValueError("Automatic method comparison requires a new, unselected pilot")
    cohort = manifest["inputs"]["full_cohort"]
    config["input"].update(
        directory=cohort["directory"],
        template=cohort["template"],
        subject_pattern=cohort["subject_pattern"],
    )
    config["project"]["parameter_provenance"]["attachment_selection"]["state"] = "comparing"
    # No field or learned template is transferred into this comparison.
    for key in ("initial_momenta", "initial_momenta_subjects", "initial_control_points"):
        config["model"]["deformation"].pop(key, None)
    template = load_surface_mesh(source.study_directory / manifest["inputs"]["template"]["copy"])
    _, spacing = control_grid(template.metadata.bounds)
    center = dict(source.plan.effective_values, initial_control_point_spacing=spacing)
    candidates, method_by_id = [], {}
    for method in METHODS:
        for index, (width, noise) in enumerate(((1, 1), (0.5, 0.5), (2, 1)), 1):
            cid = f"method-{method}-{index}"
            method_by_id[cid] = method
            values = dict(
                center,
                attachment_kernel_width=center["attachment_kernel_width"] * width,
                noise_std=center["noise_std"] * noise,
            )
            candidates.append(
                CalibrationCandidate(
                    cid,
                    f"{method.title()} · setting {index}",
                    tuple(sorted(values.items())),
                    "Matched full-original pilot; fresh field, common template and controls",
                )
            )
    stage = replace(
        source.plan.stages[0],
        title="Compare surface-matching methods",
        candidates=tuple(candidates),
    )
    plan = _fingerprint(
        replace(
            source.plan,
            stages=(stage, *source.plan.stages[1:]),
            baseline_effective_values=tuple(sorted(center.items())),
            baseline_parameter_ratios=tuple(
                sorted(
                    (key, value / manifest["template_diagonal"]) for key, value in center.items()
                )
            ),
        )
    )
    config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"] = (
        plan.provenance
    )
    destination = source.study_directory.parent / f"reference-method-comparison-{uuid4().hex[:12]}"
    config_path = destination.with_suffix(".yaml")
    study._write_yaml(config_path, config, overwrite=False)
    return study.create_reference_calibration_study(
        config_path,
        destination,
        plan_override=plan,
        pilot_max_iterations=ITERATIONS,
        attachment_comparison=dict(
            version=VERSION,
            methods=method_by_id,
            source_directory=str(source.study_directory),
            source_manifest_sha256=sha256_file(source.study_directory / study.STUDY_MANIFEST),
            iterations=ITERATIONS,
            samples_per_repeat=SAMPLES,
            repeats=2,
            region_grid=4,
            shrink_warning_fraction=SHRINK_WARNING,
            confirmation_freeze_settings={
                key: config["optimization"][key]
                for key in ("freeze_template", "freeze_control_points")
            },
            scope="All selected pilot originals; one method/settings candidate "
            "for the whole cohort",
        ),
    )


def prepare_controls(root, manifest, record):
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.surface_io import load_surface_mesh

    template = load_surface_mesh(root / manifest["inputs"]["template"]["copy"])
    controls, spacing = control_grid(template.metadata.bounds)
    path = root / "method-controls.txt"
    np.savetxt(path, controls, fmt="%.17g")
    return dict(
        record,
        controls=dict(
            copy=path.name, sha256=sha256_file(path), count=len(controls), spacing=spacing
        ),
    )


def verify(root, manifest):
    from diffeoforge import reference_calibration_study as study

    record = manifest["attachment_comparison"]
    source = Path(record["source_directory"]).resolve()
    control = study._safe_study_path(root, record["controls"]["copy"])
    if (
        record.get("version") != VERSION
        or source == root.resolve()
        or sha256_file(source / study.STUDY_MANIFEST) != record["source_manifest_sha256"]
        or sha256_file(control) != record["controls"]["sha256"]
        or (not record.get("guided") and set(record["methods"].values()) != set(METHODS))
        or not set(record["methods"].values()) <= set(METHODS)
        or set(record["methods"])
        != {row["candidate_id"] for row in manifest["plan"]["stages"][0]["candidates"]}
    ):
        raise ValueError("Method comparison input/protocol binding changed")
    if record.get("guided"):
        from diffeoforge.reference_guided_pilot import VERSION as GUIDED_VERSION
        from diffeoforge.reference_guided_pilot import verify_approvals

        info = record["guided"]
        original = study._verify_manifest(source)
        expected = {r["filename"]: r["sha256"] for r in original["inputs"]["subjects"]}
        actual = {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]}
        if (info.get("version") != GUIDED_VERSION or Path(info["origin"]).resolve() != source
                or info["phase"] not in {"screen", "validate", "joint"}
                or set(info["pilot_order"]) != set(expected)
                or len(info["pilot_order"]) != len(expected)
                or not 0 <= info["screen_trials_spent"] <= info["screen_trial_limit"]
                == max(12, len(expected) + 2)
                or (info["phase"] == "joint" and actual != expected)
                or (info["phase"] != "joint" and actual != {
                    info["target"]: expected.get(info["target"])})):
            raise ValueError("Guided pilot scope or budget binding changed")
        verify_approvals(info["approved"])
        if info.get("feedback"):
            from diffeoforge.pilot_recovery import verify as verify_feedback

            verify_feedback(info["feedback"], actual)
        if info["phase"] == "joint":
            approved = info["approved"]
            values = manifest["plan"]["baseline_effective_values"]
            if (len(set(record["methods"].values())) != 1
                    or {r["filename"] for r in approved} != set(expected)
                    or any(r["method"] not in record["methods"].values() or r["values"] != values
                           for r in approved)):
                raise ValueError(
                    "Joint pilot lacks complete approved coverage on one configuration"
                )


def context(root, manifest):
    """Retain the categorical choice through ordinary stage extensions."""
    from diffeoforge import reference_calibration_study as study

    if manifest.get("attachment_comparison"):
        return root, manifest["attachment_comparison"]
    source = manifest.get("search_extension_source")
    if source:
        parent = Path(source["study_directory"]).resolve()
        return context(parent, study._verify_manifest(parent))
    return None, None


def selected_method(root, manifest, candidate_id=None):
    from diffeoforge import reference_calibration_study as study

    origin, record = context(root, manifest)
    if record is None:
        return None
    if root == origin and candidate_id in record["methods"]:
        return record["methods"][candidate_id]
    events = study._load_events(origin)
    chosen = next(
        (
            e["candidate_id"]
            for e in events
            if e["event"] == "stage_selected" and e["candidate_id"] in record["methods"]
        ),
        None,
    )
    if chosen is None:
        raise ValueError("Choose and visually review a matching method before continuing")
    return record["methods"][chosen]


def configure(config, root, manifest, candidate_id):
    if selection(config).get("mode") != "auto":
        return
    method = selected_method(root, manifest, candidate_id)
    if method is None:
        return
    config["model"]["attachment"]["type"] = method
    policy = config["project"]["parameter_provenance"]["attachment_selection"]
    policy.update(state="selected", selected_method=method)
    record = manifest.get("attachment_comparison")
    if record and candidate_id in record["methods"]:
        controls = record["controls"]
        config["optimization"].update(
            freeze_template=True, freeze_control_points=True, max_iterations=record["iterations"]
        )
        if record.get("guided", {}).get("phase") == "joint":
            config["optimization"].update(record["confirmation_freeze_settings"])
        deformation = config["model"]["deformation"]
        for key in ("initial_momenta", "initial_momenta_subjects"):
            deformation.pop(key, None)
        deformation.update(
            initial_control_points=str(root / controls["copy"]),
            initial_control_point_spacing=controls["spacing"],
        )
    else:
        _, comparison = context(root, manifest)
        config["optimization"].update(comparison["confirmation_freeze_settings"])


def _area_volume(geometry):
    vertices = np.asarray(geometry.vertices, float)
    faces = np.asarray(geometry.triangles, int)
    triangles = vertices[faces]
    area = (
        np.linalg.norm(
            np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
        ).sum()
        / 2
    )
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    signs = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    _, inverse, counts = np.unique(
        np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True
    )
    closed = bool(np.all(counts == 2) and np.all(np.bincount(inverse, weights=signs) == 0))
    volume = (
        np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6
    )
    return float(area), float(volume) if closed else None


def compare_geometry(original, reconstruction, *, original_key=None):
    """Independent area samples, regional tails and geometry diagnostics."""
    from diffeoforge.reference_fit_search import distances_to_surface, surface_samples

    av, af = np.asarray(original.vertices, float), np.asarray(original.triangles, int)
    bv, bf = np.asarray(reconstruction.vertices, float), np.asarray(reconstruction.triangles, int)
    low, span = av.min(axis=0), np.ptp(av, axis=0)
    diagonal = float(np.linalg.norm(span))
    if not diagonal > 0:
        raise ValueError("Original has no spatial extent")
    cache_key = (original_key, VERSION, SAMPLES)
    cached = _TARGET_EVIDENCE.get(cache_key) if original_key else None
    if cached is None:
        cached = dict(
            stats=_area_volume(original),
            samples={
                seed: surface_samples(av, af, SAMPLES, seed=seed) for seed in (20261021, 20261022)
            },
        )
        if original_key:
            if len(_TARGET_EVIDENCE) >= 32:
                _TARGET_EVIDENCE.pop(next(iter(_TARGET_EVIDENCE)))
            _TARGET_EVIDENCE[cache_key] = cached
    repeats = []
    for seed in (20261021, 20261022):
        ap = cached["samples"][seed]
        bp = surface_samples(bv, bf, SAMPLES, seed=seed)
        directions = [
            (ap, distances_to_surface(ap, bv, bf)),
            (bp, distances_to_surface(bp, av, af)),
        ]
        tails, regions = [], {}
        for direction, (points, distances) in enumerate(directions):
            cells = np.clip(
                ((points - low) / np.maximum(span, diagonal * 1e-12) * 4).astype(int), 0, 3
            )
            labels = cells[:, 0] * 16 + cells[:, 1] * 4 + cells[:, 2]
            for label in np.unique(labels):
                values = distances[labels == label]
                # Sparse regions retain their maximum rather than disappearing.
                value = float(np.quantile(values, 0.95) if len(values) >= 8 else values.max())
                regions[f"{direction}:{int(label)}"] = dict(tail=value, count=len(values))
                tails.append(value)
        repeats.append(
            dict(
                p95=max(float(np.quantile(d, 0.95)) for _, d in directions),
                p99=max(float(np.quantile(d, 0.99)) for _, d in directions),
                mean=max(float(d.mean()) for _, d in directions),
                regional_tail=max(tails),
                regions=regions,
            )
        )
    aa, va = cached["stats"]
    ab, vb = _area_volume(reconstruction)
    area_ratio = ab / aa
    volume_ratio = abs(vb / va) if va is not None and vb is not None and abs(va) > 1e-15 else None
    warnings = []
    if area_ratio < SHRINK_WARNING or (volume_ratio is not None and volume_ratio < SHRINK_WARNING):
        warnings.append("Extreme shrinkage relative to original; inspect for collapse")
    if va is not None and vb is not None and va * vb < 0:
        warnings.append("Reconstructed signed volume reverses orientation")
    return dict(
        diagonal=diagonal,
        repeats=repeats,
        area_ratio=area_ratio,
        volume_ratio=volume_ratio,
        warnings=warnings,
    )


def measure(root, manifest, candidate, run):
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    report = collect_run_report(run)
    paths = {
        Path(row["path"]).name: run / "output" / row["path"]
        for row in report.inventory
        if "__Reconstruction__" in row["path"]
    }
    subjects = {}
    for row in manifest["inputs"]["subjects"]:
        matches = [
            path
            for name, path in paths.items()
            if name.endswith("__subject_" + row["filename"] + ".vtk")
        ]
        if len(matches) != 1:
            raise ValueError("Method comparison reconstruction identity mismatch")
        original = load_surface_mesh(root / row["copy"]).geometry
        fitted = load_surface_mesh(matches[0]).geometry
        subjects[row["filename"]] = compare_geometry(
            original, fitted,
            original_key=row["sha256"],
        )
        feedback = manifest["attachment_comparison"].get("guided", {}).get("feedback")
        if feedback and feedback["target"] == row["filename"]:
            from diffeoforge.pilot_regions import comparison
            from diffeoforge.pilot_regions import measure as measure_regions

            regional = measure_regions(original, fitted, feedback["regions"])
            subjects[row["filename"]]["marked_regions"] = dict(
                measurements=regional,
                outcome=comparison(feedback["baseline"], regional,
                                   feedback["global_baseline"], subjects[row["filename"]]),
            )
    return dict(
        attachment_comparison=dict(version=VERSION, subjects=subjects),
        original_surface_fit={
            name: dict(
                diagonal=row["diagonal"],
                **{key: max(rep[key] for rep in row["repeats"]) for key in ("p95", "p99", "mean")},
            )
            for name, row in subjects.items()
        },
        fit_scope="full_targets",
    )


def recommendation(snapshot):
    """One settings candidate per method; never pool away a subject regression."""
    record = snapshot.attachment_comparison
    if not record or snapshot.current_stage.order != 1:
        return None
    expected = {s.filename for s in snapshot.plan.selected_pilot_subjects}
    available, warnings = {}, {}
    for candidate in snapshot.candidates:
        metrics = candidate.metrics or {}
        detail = metrics.get("attachment_comparison", {})
        subjects = detail.get("subjects", {})
        if (
            candidate.status != "completed"
            or metrics.get("invalid_face_count") != 0
            or metrics.get("converged") is not True
            or set(subjects) != expected
            or detail.get("version") != VERSION
            or snapshot.visual_reviews.get(candidate.candidate_id) is False
        ):
            continue
        warnings[candidate.candidate_id] = [
            f"{name}: {warning}" for name, row in subjects.items() for warning in row["warnings"]
        ]
        intervals = {}
        for name, row in subjects.items():
            for key in ("p95", "p99", "regional_tail"):
                values = [rep[key] / row["diagonal"] for rep in row["repeats"]]
                if len(values) != 2 or not np.isfinite(values).all() or min(values) < 0:
                    raise ValueError("Invalid independent method-comparison measurements")
                intervals[name, key] = min(values), max(values)
            # Original-side regions use the same points and spatial bins for
            # every candidate, so an individual missed feature cannot be traded
            # for a better regional maximum elsewhere.
            region_keys = set().union(*(rep["regions"] for rep in row["repeats"]))
            for region in sorted(key for key in region_keys if key.startswith("0:")):
                values = [
                    rep["regions"][region]["tail"] / row["diagonal"]
                    for rep in row["repeats"]
                    if region in rep["regions"]
                ]
                intervals[name, "region-" + region] = min(values), max(values)
        available[candidate.candidate_id] = intervals
    best = {}
    for method in METHODS:
        ids = [cid for cid in available if record["methods"][cid] == method]
        if ids:
            best[method] = min(
                ids,
                key=lambda cid: (
                    bool(warnings[cid]),
                    max(high for _, high in available[cid].values()),
                    cid,
                ),
            )
    winner = None
    # Missing/failed candidates cannot create a default winner by omission.
    complete = all(c.status == "completed" for c in snapshot.candidates)
    if complete and len(best) == 2:
        for method, cid in best.items():
            other = best[next(m for m in METHODS if m != method)]
            first, second = available[cid], available[other]
            if set(first) != set(second):
                continue
            no_regression = all(first[key][1] <= second[key][0] + 1e-6 for key in first)
            better = any(first[key][1] + 1e-6 < second[key][0] for key in first)
            if no_regression and better and not warnings[cid]:
                winner = cid
    return dict(
        version=VERSION,
        recommended_candidate_id=winner,
        recommended_method=record["methods"][winner] if winner else None,
        best_candidates=best,
        warnings=warnings,
        status="recommendation"
        if winner
        else ("no_clear_advantage" if complete and len(best) == 2 else "review_required"),
        limitation="Sampled regional geometry does not establish feature correspondence or anatomy",
    )


def assess(snapshot, assessment):
    result = recommendation(snapshot)
    if result is None:
        return assessment
    chosen = result["recommended_candidate_id"]
    candidates = tuple(
        replace(
            row,
            balanced_score=None,
            weight_win_fraction=None,
            subject_bootstrap_win_fraction=None,
            score_range=None,
        )
        for row in assessment.candidates
    )
    cautions = (
        "Two methods compared against identical originals; native objective values are not ranked.",
        "No clear advantage: inspect both methods."
        if chosen is None
        else "Stable measured advantage; every specimen still needs visual approval.",
        *[warning for values in result["warnings"].values() for warning in values],
        result["limitation"],
    )
    return replace(
        assessment,
        version=VERSION,
        balanced_candidate_id=chosen,
        candidates=candidates,
        recommendation_confidence="measured" if chosen else "uncertain",
        automatic_selection_allowed=False,
        metric_weights=(),
        weight_stability=None,
        subject_bootstrap_stability=None,
        independent_rank_candidate_id=chosen,
        score_margin=None,
        cautions=cautions,
        fingerprint=_canonical_hash(result),
    )


def run(runner, event_callback=None, *, candidate_ids=None):
    from diffeoforge import reference_calibration_study as study

    origin = runner.study_directory
    manifest = study._verify_manifest(origin)
    config = load_config(origin / manifest["source_config"]["copy"])
    if candidate_ids is not None and pending(config):
        raise ValueError("Start the complete automatic method comparison before selecting trials")
    if candidate_ids is not None and manifest.get("attachment_comparison"):
        if not candidate_ids <= set(manifest["attachment_comparison"]["methods"]):
            raise ValueError("Unknown automatic comparison trial selection")
    pointer = origin / "fit-search-latest.json"
    if runner._cancel_requested:
        return study.load_reference_calibration_study(origin)
    if manifest.get("attachment_comparison"):
        pass
    elif pointer.exists():
        from diffeoforge.reference_sequential_fit import resume_directory

        runner.study_directory = resume_directory(origin)
    else:
        snapshot = prepare(origin)
        runner.study_directory = snapshot.study_directory
        study._write_json(
            pointer,
            dict(
                directory=str(snapshot.study_directory),
                manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
            ),
            overwrite=False,
        )
    if event_callback:
        event_callback(
            dict(
                event="attachment_comparison_started",
                snapshot=study.load_reference_calibration_study(runner.study_directory),
            )
        )
    lock = runner.study_directory / "method-comparison-active.lock"
    lock.mkdir()  # Existing lock requires explicit recovery, never duplicate work.
    try:
        runner._method_comparison_dispatch = True
        result = runner.run_current_stage(
            event_callback=event_callback, candidate_ids=candidate_ids
        )
        if result.current_stage and result.current_stage.order == 1:
            decision = recommendation(result)
            payload = dict(
                decision=decision,
                manifest_sha256=sha256_file(result.study_directory / study.STUDY_MANIFEST),
                candidate_events=[
                    e["event_hash"]
                    for e in study._load_events(result.study_directory)
                    if e["event"]
                    in {"candidate_completed", "candidate_failed", "candidate_interrupted"}
                ],
                anatomical_approval=False,
            )
            study._write_json(
                result.study_directory / "method-comparison.json",
                dict(payload=payload, sha256=_canonical_hash(payload)),
                overwrite=True,
            )
        return result
    finally:
        runner._method_comparison_dispatch = False
        lock.rmdir()
