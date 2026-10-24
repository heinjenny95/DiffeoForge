"""Bound field initialization and independent geometry guards for guided refinement."""

from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file

VERSION = "guided-refinement-v1"


def load_field(run):
    from diffeoforge.reference_pca import load_reference_momenta

    return load_reference_momenta(run, allow_singleton=True)


def bind(root, manifest, record):
    """Copy only a compatible frozen singleton field; never run an optimizer."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference

    request = record.get("refinement")
    if not request:
        return record
    ref = request["reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    old = study._verify_manifest(parent.study_directory)
    expected = {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]}
    previous = {r["filename"]: r["sha256"] for r in old["inputs"]["subjects"]}
    if (
        not expected.items() <= previous.items()
        or len(expected) != 1
        or manifest["inputs"]["template"]["sha256"] != old["inputs"]["template"]["sha256"]
    ):
        raise ValueError("Refinement must retain the exact template and original target")
    values = manifest["plan"]["baseline_effective_values"]
    method = next(iter(record["methods"].values()))
    nested = (record.get("guided", {}).get("goal") == "density"
              and values["initial_control_point_spacing"]
              == ref["values"]["initial_control_point_spacing"] * .8)
    compatible = (
        len(previous) == 1
        and method == ref["method"]
        and all(
            values[k] == ref["values"][k]
            for k in (("deformation_kernel_width",) if nested else
                      ("deformation_kernel_width", "initial_control_point_spacing"))
        )
    )
    if not compatible:
        return dict(
            record,
            refinement=dict(
                request,
                initialization="fresh",
                reason="No compatible saved single-form field for this basis and method; "
                "a fresh initialization needs visual review.",
            ),
        )
    run = study.calibration_candidate_run_directory(candidate)
    inputs = load_field(run)
    config = inputs.run_report.manifest["effective_config"]
    from diffeoforge.regional_fit import read_plan

    regional = read_plan(config)
    recipe = (record.get("guided", {}).get("strategy") or {}).get("regional_recipe")
    if regional and regional.get("residual") and not recipe:
        return dict(record, refinement=dict(request, initialization="fresh",
            reason="This field is a residual after a preserved prefix. An ordinary global "
                   "trial cannot reuse that residual alone on the original template. "
                   "Use protected regional refinement to retain the full field chain."))
    requested = load_config(root / manifest["source_config"]["copy"])
    controls = old["attachment_comparison"]["controls"]
    source = study._safe_study_path(parent.study_directory, controls["copy"])
    original = np.loadtxt(source).reshape(-1, 3)
    run_subjects = {
        Path(r["staged_path"]).name: r["geometry"]["sha256"]
        for r in inputs.run_report.manifest["inputs"]
        if r["role"] == "subject"
    }
    templates = [
        r["geometry"]["sha256"]
        for r in inputs.run_report.manifest["inputs"]
        if r["role"] == "template"
    ]
    if (
        sha256_file(source) != controls["sha256"]
        or run_subjects != expected
        or templates != [manifest["inputs"]["template"]["sha256"]]
        or inputs.subject_labels != (ref["target"],)
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
        or config["model"]["attachment"]["type"] != ref["method"]
        or config["model"]["deformation"]["kernel_width"] != values["deformation_kernel_width"]
        or any(
            config["model"]["deformation"][k] != requested["model"]["deformation"][k]
            for k in ("timepoints", "use_rk2")
        )
        or config["runtime"]["precision"] != requested["runtime"]["precision"]
        or inputs.control_points.shape != original.shape
        or not np.allclose(inputs.control_points, original, rtol=0, atol=5.000001e-7)
        or inputs.momenta.shape != (1, len(original), 3)
        or not np.isfinite(inputs.momenta).all()
    ):
        raise ValueError("Saved fitted field does not match the fixed refinement basis")
    if nested:
        from diffeoforge.guided_density import write

        return dict(record, **write(root, request, controls, original, inputs.momenta, source,
                                    inputs.momenta_path))
    point_path, momentum_path = root / "refinement-controls.txt", root / "refinement-momenta.txt"
    study._copy_bound(source, point_path, controls["sha256"])
    digest = sha256_file(inputs.momenta_path)
    study._copy_bound(inputs.momenta_path, momentum_path, digest)
    return dict(
        record,
        controls=dict(controls, copy=point_path.name),
        refinement=dict(
            request,
            initialization="learned",
            reason="Same frozen deformation basis and target; "
            "retain the fitted field, restart optimizer history, require fresh visual review.",
            momenta=dict(copy=momentum_path.name, sha256=digest),
            source_run_sha256=sha256_file(run / "manifest.json"),
        ),
    )


def verify(root, manifest, record):
    request = record.get("refinement")
    if not request:
        return
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_calibration_study import _safe_study_path

    verify_reference(request["reference"])
    if request.get("version") != VERSION or request.get("initialization") not in {
        "learned",
        "fresh",
        "nested",
        "residual",
    }:
        raise ValueError("Unknown refinement initialization")
    if request["initialization"] == "learned":
        row = request["momenta"]
        if sha256_file(_safe_study_path(root, row["copy"])) != row["sha256"]:
            raise ValueError("Refinement field bytes changed")
    elif request["initialization"] == "nested":
        from diffeoforge.guided_density import verify as verify_nested

        verify_nested(root, manifest, record)
    elif request["initialization"] == "residual":
        from diffeoforge.regional_residual import verify as verify_residual

        verify_residual(record)


def geometry_guard(baseline, current):
    """Independent sampled-distance warning; never automatic anatomical approval."""
    floor = max(baseline["diagonal"] * 1e-4, 1e-12)
    keys = ("p95", "p99", "mean")
    old = {k: max(r[k] for r in baseline["repeats"]) for k in keys}
    new = {k: max(r[k] for r in current["repeats"]) for k in keys}
    worsened = [k for k in keys if new[k] > old[k] + max(floor, abs(old[k]) * 0.15)]
    severe = any(new[k] > max(old[k] * 2, old[k] + floor * 10) for k in keys) or bool(
        current.get("warnings")
    )
    return dict(
        outcome="regression" if worsened or severe else "no_measured_regression",
        severe=severe,
        worsened=worsened,
        baseline=old,
        current=new,
        relative_margin=0.15,
        absolute_margin=floor,
        scope="Sampled geometry warning only; visual suitability remains the user's decision",
    )
