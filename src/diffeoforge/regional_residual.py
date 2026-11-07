"""Explicit residual fields, always evaluated by forward composition from the source."""

from pathlib import Path

from diffeoforge.mesh import sha256_file


def retained_evaluation(record, run, target):
    """Find a bound current-grid evaluation of the requested unchanged field."""
    from diffeoforge import reference_calibration_study as study

    previous = record.get("guided", {}).get("strategy", {}).get("previous")
    if not previous:
        return None
    if (
        sha256_file(Path(previous["directory"]) / study.STUDY_MANIFEST)
        != previous["manifest_sha256"]
    ):
        raise ValueError("Regional predecessor changed")
    latest = study.load_reference_calibration_study(previous["directory"])
    for row in latest.candidates:
        q = (
            (row.metrics or {})
            .get("attachment_comparison", {})
            .get("subjects", {})
            .get(target, {})
            .get("regional_quality", {})
        )
        for entry in (q.get("evaluation"), q.get("baseline_evaluation")):
            from diffeoforge.regional_frame import compatible

            if (compatible(entry)
                    and Path(entry["source_run"]).resolve() == Path(run).resolve()):
                if sha256_file(Path(entry["endpoint"]["path"])) != entry["endpoint"]["sha256"]:
                    raise ValueError("Retained original-grid endpoint changed")
                return entry
    return None


def bind(root, manifest, record, recipe, *, source_grid=None):
    """Preserve the parent deformation and fit only a new residual field."""
    import numpy as np

    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_fit_search import control_grid
    from diffeoforge.regional_evaluation import endpoint
    from diffeoforge.regional_fit import _save
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    ref = record["refinement"]["reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    evaluated = endpoint(candidate)
    quality = (
        (candidate.metrics or {})
        .get("attachment_comparison", {})
        .get("subjects", {})
        .get(ref["target"], {})
        .get("regional_quality", {})
    )
    evaluation = quality.get("evaluation")
    # A rejected attempt may still have supplied a better original reference
    # grid and a fresh evaluation of the unchanged preferred field on it.
    previous = record.get("guided", {}).get("strategy", {}).get("previous")
    if previous:
        latest = study.load_reference_calibration_study(previous["directory"])
        for row in latest.candidates:
            q = (
                (row.metrics or {})
                .get("attachment_comparison", {})
                .get("subjects", {})
                .get(ref["target"], {})
                .get("regional_quality", {})
            )
            base = q.get("baseline_evaluation")
            if base and Path(base["source_run"]).resolve() == run.resolve():
                evaluation, evaluated = base, base["endpoint"]
                if sha256_file(Path(evaluated["path"])) != evaluated["sha256"]:
                    raise ValueError("Refined retained-field evaluation changed")
                break
    if evaluated:
        path = Path(evaluated["path"])
    else:
        object_id = report.manifest["effective_config"]["model"]["object_id"]
        rows = [
            r
            for r in report.inventory
            if f"__Reconstruction__{object_id}__subject_" in r["path"]
            and r["path"].endswith("__subject_" + ref["target"] + ".vtk")
        ]
        if len(rows) != 1:
            raise ValueError("Residual fitting needs the verified complete retained surface")
        path = study._safe_study_path(run / "output", rows[0]["path"])
        if sha256_file(path) != rows[0]["sha256"]:
            raise ValueError("Residual starting surface changed")
    from diffeoforge.regional_frame import compatible, qualify, verify_source

    if source_grid and sha256_file(Path(source_grid['path'])) != source_grid['sha256']:
        raise ValueError('Requested original material grid changed')
    if (not compatible(evaluation) or (source_grid
            and evaluation.get('reference_source', {}).get('sha256') != source_grid['sha256'])):
        original = source_grid or (evaluation or {}).get("reference_source")
        evaluation = qualify(run, root / "retained-frame-qualification",
                             source=original["path"] if original else None)
    verify_source(evaluation)
    if source_grid and Path(evaluation['source_run']).resolve() != run.resolve():
        raise ValueError('Requested material frame belongs to a different retained field')
    if source_grid and evaluation['reference_source']['sha256'] != source_grid['sha256']:
        raise ValueError('Residual source did not use the requested original material grid')
    path = Path(evaluation["endpoint"]["path"])
    source = load_surface_mesh(path)
    copied = root / "residual-source.vtk"
    _save(copied, source.geometry.vertices, source.geometry.triangles)
    controls, spacing = control_grid(source.metadata.bounds, target=1000)
    coverage = None
    if recipe.get('control_support') == 'source-target-coverage-v1':
        from diffeoforge.regional_search import controls as supported_controls

        target = next(r for r in manifest['inputs']['subjects'] if r['filename'] == ref['target'])
        original = load_surface_mesh(root / target['copy'])
        width = manifest['plan']['baseline_effective_values']['deformation_kernel_width']
        options = dict(full_surface=recipe.get('control_scope') == 'full_surface')
        if recipe.get('control_budget_policy'):
            options['budget_policy'] = recipe['control_budget_policy']
        from diffeoforge.regional_protected_capture import active_regions

        regions = active_regions(recipe, record['guided']['feedback']['regions'])
        controls, spacing, coverage = supported_controls(
            source.geometry.vertices, original.geometry.vertices,
            regions, width, **options)
    control_path = root / "residual-controls.txt"
    np.savetxt(control_path, controls, fmt="%.17g")
    residual = dict(
        parent_run=str(run),
        parent_manifest_sha256=sha256_file(run / "manifest.json"),
        source=dict(copy=copied.name, sha256=sha256_file(copied), bytes=copied.stat().st_size),
        original_template_sha256=manifest["inputs"]["template"]["sha256"],
        inherited_fields_unchanged=True,
        evaluation="original-source-forward-composition",
        control_coverage=coverage,
    )
    if evaluation and evaluation.get("reference_source"):
        import shutil

        grid = evaluation["reference_source"]
        origin = Path(grid["path"])
        if sha256_file(origin) != grid["sha256"]:
            raise ValueError("Retained original-source grid changed")
        copied_grid = root / "original-source-grid.vtk"
        shutil.copyfile(origin, copied_grid)
        residual["original_source_grid"] = dict(
            copy=copied_grid.name, sha256=sha256_file(copied_grid), bytes=copied_grid.stat().st_size
        )
    return dict(
        record,
        controls=dict(
            copy=control_path.name,
            sha256=sha256_file(control_path),
            count=len(controls),
            spacing=spacing,
        ),
        refinement=dict(
            record["refinement"],
            initialization="residual",
            residual=residual,
            parent_evaluation=evaluation,
            reason="Retain the parent field; fit a zero-initialized residual "
            "at the declared scale. "
            "Evaluate the entire field chain from the original source.",
        ),
    )


def verify(record):
    info = record.get("refinement", {})
    if info.get("initialization") == "residual":
        residual = info["residual"]
        if (
            sha256_file(Path(residual["parent_run"]) / "manifest.json")
            != residual["parent_manifest_sha256"]
        ):
            raise ValueError("The retained residual parent changed")
