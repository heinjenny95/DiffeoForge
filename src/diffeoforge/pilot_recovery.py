"""Explainable, bounded hypotheses after a visually rejected guided fit."""

from pathlib import Path

from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_regions import validate

DESCRIPTIONS = {
    "regional": (
        "Improve marked areas and protect the rest",
        "Fit the marked surfaces directly, retain useful deformation, protect already "
        "good areas, and check both the local result and its transitions.",
    ),
    "density": (
        "Test additional control points",
        "The deformation may need more independent controls. Add 50% more points while "
        "keeping the saved starting deformation and the other fitting settings.",
    ),
    "optimize": (
        "Optimize longer with the same settings",
        "The saved fit stopped at its iteration limit. Give its existing deformation more "
        "optimization time before changing another parameter.",
    ),
    "detail": (
        "Test finer surface matching",
        "Make smaller surface differences more visible to fitting.",
    ),
    "local_motion": ("Test more local movement", "Allow nearby parts to move more independently."),
    "motion": (
        "Test broader movement",
        "Test whether a larger coordinated movement reaches the missed area.",
    ),
    "weight": ("Test stronger surface matching", "Give agreement with the original more weight."),
    "smooth": ("Test gentler deformation", "Reduce pressure to follow every surface difference."),
    "other_method": (
        "Check the other method on this form",
        "The earlier method preference may not hold for this form.",
    ),
}


def proposal(snapshot, identifier, symptom, *, adaptive=False, starting_from_saved=False,
             regions_override=None):
    """A heuristic hypothesis, not a diagnosis or promise of anatomical recovery."""
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    if not info or (snapshot.visual_reviews.get(identifier) is not False
                    and not starting_from_saved):
        raise ValueError("Inspect and reject this fit before preparing a recovery test")
    from diffeoforge.pilot_regions import SYMPTOMS

    if symptom not in {*SYMPTOMS, "other_method"}:
        raise ValueError("Choose the visible problem, or say you are unsure")
    names = [s.filename for s in snapshot.plan.selected_pilot_subjects]
    rejected = [
        n
        for n, v in snapshot.subject_decisions.get(identifier, {}).items()
        if v in {"fail", "uncertain"}
    ]
    target = info["target"] or next(iter(rejected), names[0])
    regions = (regions_override if regions_override is not None
               else snapshot.problem_regions.get(identifier, {}).get(target, []))
    method = snapshot.attachment_comparison["methods"][identifier]
    count = len(snapshot.candidates)
    if symptom == "detail":
        last = info.get("goal")
        width = snapshot.plan.effective_values["attachment_kernel_width"]
        # Physical patch size narrows the hypothesis; it cannot identify the cause.
        small_scale = bool(regions and width <= min(r["radius"] for r in regions) / 2)
        goal = (
            "weight"
            if last == "local_motion"
            else "local_motion"
            if last == "detail" or small_scale
            else "detail"
        )
    else:
        goal = {
            "missing": "motion",
            "shape": "other_method" if count == 1 else "motion",
            "distortion": "smooth",
            "unsure": "other_method" if count == 1 else "weight",
            "other_method": "other_method",
            "thickness": "regional", "position": "regional", "curvature": "regional",
            "gap": "regional", "alignment": "regional", "topology": "regional",
            "view": "regional",
        }[symptom]
    title, reason = DESCRIPTIONS[goal]
    remaining = (info["screen_trial_limit"] - info["screen_trials_spent"]
                 if info["screen_trial_limit"] is not None else None)
    note = ""
    if (candidate.metrics or {}).get("converged") is False:
        note = "The previous trial reached its iteration limit; its result is provisional. "
    return dict(
        goal=goal,
        title=title,
        reason=reason,
        target=target,
        method=("varifold" if method == "current" else "current")
        if goal == "other_method"
        else method,
        trials=1,
        available=adaptive or (remaining is not None and remaining >= 1
                               and not info.get("coverage_extension")),
        symptom=symptom,
        note=note
        + "This tests a possible cause. Earlier fits stay saved; no fit starts until Run.",
        regions=regions,
    )


def capture(snapshot, identifier, target, *, regions=None):
    """Called in transition preparation, away from the GUI thread."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.pilot_regions import measure
    from diffeoforge.reference_attachment_comparison import compare_geometry
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    regions = (regions if regions is not None
               else snapshot.problem_regions.get(identifier, {}).get(target, []))
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    if not regions:
        measured = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
        if target in measured:
            return dict(directory=str(snapshot.study_directory), candidate_id=identifier,
                manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
                binding=study._candidate_review_binding(candidate), target=target, regions=[],
                baseline=[], global_baseline=measured[target])
    manifest = study._verify_manifest(snapshot.study_directory)
    row = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == target)
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    regional = manifest.get("attachment_comparison", {}).get("regional_objective")
    rows = [
        r
        for r in report.inventory
        if "__Reconstruction__" in r["path"]
        and (not regional or ("__Reconstruction__"
            + report.manifest["effective_config"]["model"]["object_id"]
            + "__subject_") in r["path"])
        and r["path"].endswith("__subject_" + target + ".vtk")
    ]
    if len(rows) != 1:
        raise ValueError("Regional feedback requires one verified reconstruction of the original")
    fitted_path = study._safe_study_path(run / "output", rows[0]["path"])
    if sha256_file(fitted_path) != rows[0]["sha256"]:
        raise ValueError("Region feedback reconstruction bytes changed")
    from diffeoforge.regional_evaluation import endpoint

    evaluated = endpoint(candidate)
    fitted_hash = rows[0]["sha256"]
    if evaluated:
        fitted_path, fitted_hash = Path(evaluated["path"]), evaluated["sha256"]
    validate({target: regions} if regions else {}, {target: row["sha256"]})
    original_source = load_surface_mesh(snapshot.study_directory / row["copy"])
    fitted_source = load_surface_mesh(fitted_path)
    if (original_source.metadata.sha256 != row["sha256"]
            or fitted_source.metadata.sha256 != fitted_hash):
        raise ValueError("Regional feedback geometry changed while loading")
    original, fitted = original_source.geometry, fitted_source.geometry
    return dict(
        directory=str(snapshot.study_directory),
        candidate_id=identifier,
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        binding=study._candidate_review_binding(candidate),
        target=target,
        regions=regions,
        baseline=measure(original, fitted, regions),
        global_baseline=(candidate.metrics or {}).get("attachment_comparison", {}).get(
            "subjects", {}).get(target) or compare_geometry(
                original, fitted, original_key=row["sha256"]),
    )


def verify(feedback, subjects):
    from diffeoforge import reference_calibration_study as study

    root = Path(feedback["directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != feedback["manifest_sha256"]:
        raise ValueError("Region feedback source manifest changed")
    snapshot = study.load_reference_calibration_study(root)
    candidate = next(c for c in snapshot.candidates if c.candidate_id == feedback["candidate_id"])
    if study._candidate_review_binding(candidate) != feedback["binding"]:
        raise ValueError("Region feedback reconstruction or settings changed")
    validate({feedback["target"]: feedback["regions"]} if feedback["regions"] else {}, subjects)
