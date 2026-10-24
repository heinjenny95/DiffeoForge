"""Explicit residual fields, always evaluated by forward composition from the source."""

from pathlib import Path

from diffeoforge.mesh import sha256_file


def bind(root, manifest, record, recipe):
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
    source = load_surface_mesh(path)
    copied = root / "residual-source.vtk"
    _save(copied, source.geometry.vertices, source.geometry.triangles)
    controls, spacing = control_grid(source.metadata.bounds, target=1000)
    control_path = root / "residual-controls.txt"
    np.savetxt(control_path, controls, fmt="%.17g")
    residual = dict(
        parent_run=str(run),
        parent_manifest_sha256=sha256_file(run / "manifest.json"),
        source=dict(copy=copied.name, sha256=sha256_file(copied), bytes=copied.stat().st_size),
        original_template_sha256=manifest["inputs"]["template"]["sha256"],
        inherited_fields_unchanged=True,
        evaluation="original-source-forward-composition",
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
            reason="Retain the parent field; fit a smaller-scale zero-initialized residual. "
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
