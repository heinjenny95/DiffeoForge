"""User-gated, retained-field regional trials and history-driven local recipes."""

from pathlib import Path

from diffeoforge.mesh import sha256_file


def split_regions(regions):
    problem = [r for r in regions if r.get("purpose", "problem") == "problem"]
    shape = [r for r in regions if r.get("purpose") == "preserve"]
    fixed = [r for r in regions if r.get("purpose") == "fixed"]
    guides = [*shape, *(r for r in problem if r["symptom"] in {"gap", "position"})]
    return problem or shape, guides, fixed


def verify(root, manifest, record):
    declaration = record.get("regional_objective")
    recipe = (record.get("guided", {}).get("strategy") or {}).get("regional_recipe")
    if bool(declaration) != bool(recipe):
        raise ValueError("Regional objective and guided recipe disagree")
    if not declaration:
        return
    from diffeoforge.regional_fit import read_plan

    plan = read_plan(dict(project=dict(parameter_provenance=dict(regional_fit=declaration))))
    feedback = record["guided"]["feedback"]
    target = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == feedback["target"])
    if (
        plan.get("residual", {}).get("original_template_sha256", plan["template_sha256"])
        != manifest["inputs"]["template"]["sha256"]
        or plan["target_sha256"] != target["sha256"]
        or not Path(declaration["manifest"]).resolve().is_relative_to(Path(root).resolve())
    ):
        raise ValueError("Regional objective source or study binding changed")
    focus = next(r for r in plan["objects"] if r["id"] == "focus")
    protect = next(r for r in plan["objects"] if r["id"] == "protect")
    if (
        focus["noise_std"] != recipe["focus_noise"]
        or focus["kernel_width"] != recipe["focus_width"]
        or protect["noise_std"] != recipe["protection_noise"]
        or plan["protection_halo"] != recipe["protection_halo"]
    ):
        raise ValueError("Regional fitting recipe changed")


def proposal(snapshot, identifier, data, *, symptom=None):
    from diffeoforge import reference_guided_pilot as guided

    reference = data["anchor"] or data["current_reference"]
    marked = data["regions"]
    symptom = symptom or next((r["symptom"] for r in marked if r["symptom"] != "unsure"), "detail")
    info = guided.record(snapshot)
    cases = [
        r
        for r in data["context"]["cases"]
        if r.get("family") == "regional"
        and r["target"] == reference["target"]
        and r.get("method", reference["method"]) == reference["method"]
        and r.get("regions", marked) == marked
        and (r.get("regional_recipe") or {}).get("symptom", symptom) == symptom
    ]
    level = len(cases)
    seed = reference
    feedback = (data["context"].get("feedback", {}).get(identifier) or {}).get("feedback") or {}
    quality = (
        (data["current"].metrics or {})
        .get("attachment_comparison", {})
        .get("subjects", {})
        .get(reference["target"], {})
        .get("regional_quality", {})
    )
    if (
        info.get("goal") == "regional"
        and data["current_reference"]
        and quality.get("outside_preserved")
        and quality.get("shape_preserved")
        and quality.get("no_new_intersection_flags", True)
        and quality.get("temporal_grid_stable", True)
        and quality.get("spatial_resolution_sufficient", True)
        and feedback.get("outcome") != "worse"
    ):
        # A retained comparison is not promoted by using a useful local numerical
        # field to repair its transitions. This distinction is shown in the UI.
        seed = data["current_reference"]
    values = dict(seed["values"])
    problem, guides, _fixed = split_regions(marked)
    available = bool(problem and reference)
    blocked = "Mark the problem area before preparing a protected local test."
    if symptom in {"alignment", "topology", "view"}:
        available = False
        blocked = {
            "alignment": "Review the landmark alignment before a local fit.",
            "topology": "Inspect the source surfaces and openings; local fitting "
            "does not create or remove a topological connection.",
            "view": "Load original detail or change the view before judging the fit.",
        }[symptom]
    # The capture and transition-balancing stages reproduce the qualified method.
    # Subsequent user-authorized trials remain distinct, bounded contrasts.
    noise_factor = 0.3 if level == 0 else 0.015
    width_factor = (2 / 3) * (0.7 ** max(0, level - 1))
    recipe = dict(
        version="protected-local-v1",
        level=level,
        symptom=symptom,
        focus_width=values["attachment_kernel_width"] * width_factor,
        focus_noise=values["noise_std"] * noise_factor,
        protection_noise=values["noise_std"] * 0.15,
        guide_noise=values["noise_std"] * 0.05
        if symptom in {"gap", "position"} or guides
        else None,
        protection_halo=values["deformation_kernel_width"] * 2,
        guide_points=192,
    )
    ratios = dict(snapshot.plan.baseline_parameter_ratios) if snapshot is not None else {}
    ratio = ratios.get("attachment_kernel_width")
    if ratio:
        diagonal = reference["values"]["attachment_kernel_width"] / ratio
        recipe["protection_halo"] = min(recipe["protection_halo"], diagonal * 0.1)
    # Changing a movement kernel cannot reuse its old momenta as if the basis
    # were identical. Preserve that deformation as the prefix of a residual.
    recipe["residual"] = (
        symptom not in {"gap", "position"}
        or any(r["symptom"] == "curvature" for r in problem)
        or level >= 2
    ) and not (quality and seed == data["current_reference"] and quality.get("local_improved"))
    if recipe["residual"]:
        values["deformation_kernel_width"] *= 0.5
    reason = (
        "Fit the marked original surfaces directly and protect the retained shape "
        "outside them. Check the full marked area, its transitions and the rest "
        "separately. "
    )
    if recipe["guide_noise"] is not None:
        reason += (
            "Derive a common movement for each shape-compatible marked part; "
            "do not change its shape merely to correct spacing or position. "
        )
    if level:
        reason += (
            "The next stage strengthens local surface agreement to correct "
            "transition errors; later trials use a distinct detail scale. "
        )
    if seed != reference:
        reason += (
            "Keep your preferred comparison; reuse the last local field only "
            "as the numerical starting point for correcting its transitions. "
        )
    if recipe["residual"]:
        reason += (
            "Keep the saved deformation as a fixed prefix and test a smaller-scale "
            "residual field, then evaluate their true forward composition. "
        )
    return dict(
        goal="regional",
        title="Improve marked areas and protect the rest",
        reason=reason,
        target=reference["target"],
        method=reference["method"],
        values=values,
        anchor=reference,
        initialization_reference=seed,
        from_base=False,
        available=available,
        blocked_reason=blocked,
        regions=marked,
        trials=1,
        symptom=symptom,
        regional_recipe=recipe,
        initialization="residual" if recipe["residual"] else "learned",
        numerical_extension=False,
        optimization_iterations=None,
        remaining_checks=max(0, len(info["pilot_order"]) - 1),
        hypothesis_count=level,
        contrast_level=level,
        response_evidence=[],
    )


def bind(root, manifest, record):
    recipe = (record.get("guided", {}).get("strategy") or {}).get("regional_recipe")
    if not recipe:
        return record
    if recipe.get("residual"):
        from diffeoforge.regional_residual import bind as bind_residual

        record = bind_residual(root, manifest, record, recipe)
    if record.get("refinement", {}).get("initialization") not in {"learned", "residual"}:
        raise ValueError(
            "Protected local fitting requires the compatible retained field; "
            "a fresh global restart is not prepared"
        )
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.regional_fit import prepare

    feedback = record["guided"]["feedback"]
    regions = feedback["regions"]
    problem, guides, fixed = split_regions(regions)
    if not problem:
        raise ValueError("Mark a problem area as well as already good protected areas")
    guides = guides or problem
    target = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == feedback["target"])
    ref = record["guided"]["strategy"]["anchor"]
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.result_report import collect_run_report

    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    rows = [
        r
        for r in report.inventory
        if f"__Reconstruction__{object_id}__subject_" in r["path"]
        and r["path"].endswith("__subject_" + feedback["target"] + ".vtk")
    ]
    if len(rows) != 1:
        raise ValueError("The retained full reconstruction is missing or ambiguous")
    retained = study._safe_study_path(run / "output", rows[0]["path"])
    if sha256_file(retained) != rows[0]["sha256"]:
        raise ValueError("Retained reconstruction bytes changed")
    from diffeoforge.regional_evaluation import endpoint

    evaluated = endpoint(candidate)
    if evaluated:
        retained = Path(evaluated["path"])
    from diffeoforge.regional_residual import retained_evaluation

    anchor_evaluation = retained_evaluation(record, run, feedback["target"])
    if anchor_evaluation:
        retained = Path(anchor_evaluation["endpoint"]["path"])
    fit_source = root / manifest["inputs"]["template"]["copy"]
    residual = record["refinement"].get("residual")
    if not residual:
        from diffeoforge.config import load_config
        from diffeoforge.regional_fit import read_plan

        seed_ref = record["refinement"]["reference"]
        seed_parent = verify_reference(seed_ref)
        seed_candidate = next(
            c for c in seed_parent.candidates if c.candidate_id == seed_ref["candidate_id"]
        )
        previous = read_plan(load_config(seed_candidate.config_path))
        if previous and previous.get("residual"):
            import shutil

            residual = previous["residual"]
            previous_path = Path(
                load_config(seed_candidate.config_path)["project"]["parameter_provenance"][
                    "regional_fit"
                ]["manifest"]
            ).parent
            for row in [
                residual["source"],
                *(
                    [residual["original_source_grid"]]
                    if residual.get("original_source_grid")
                    else []
                ),
            ]:
                shutil.copyfile(previous_path / row["copy"], root / row["copy"])
            seed_run = study.calibration_candidate_run_directory(seed_candidate)
            fine = retained_evaluation(record, seed_run, feedback["target"])
            if fine and fine.get("prefix"):
                original = Path(fine["reference_source"]["path"])
                prefix = Path(fine["prefix"]["endpoint"]["path"])
                for name, source_path in [
                    ("original-source-grid.vtk", original),
                    ("residual-source.vtk", prefix),
                ]:
                    shutil.copyfile(source_path, root / name)
                residual = dict(
                    residual,
                    source=dict(
                        copy="residual-source.vtk",
                        sha256=sha256_file(root / "residual-source.vtk"),
                        bytes=(root / "residual-source.vtk").stat().st_size,
                    ),
                    original_source_grid=dict(
                        copy="original-source-grid.vtk",
                        sha256=sha256_file(root / "original-source-grid.vtk"),
                        bytes=(root / "original-source-grid.vtk").stat().st_size,
                    ),
                )
    if residual:
        fit_source = root / residual["source"]["copy"]
    declaration = prepare(
        root / "regional-objective",
        fit_source,
        root / target["copy"],
        guides if recipe["guide_noise"] is not None else problem,
        focus_regions=problem,
        fixed_regions=fixed,
        retained_path=retained,
        focus_width=recipe["focus_width"],
        focus_noise=recipe["focus_noise"],
        protection_noise=recipe["protection_noise"],
        protection_halo=recipe["protection_halo"],
        guide_noise=recipe["guide_noise"],
        guide_points=recipe["guide_points"],
    )
    import json
    import shutil

    path = Path(declaration["manifest"])
    data = json.loads(path.read_text())
    data["retained_run"] = dict(path=str(run), manifest_sha256=sha256_file(run / "manifest.json"))
    if residual:
        for row in [
            residual["source"],
            *([residual["original_source_grid"]] if residual.get("original_source_grid") else []),
        ]:
            shutil.copyfile(root / row["copy"], path.parent / row["copy"])
        data["residual"] = residual
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    declaration["sha256"] = sha256_file(path)
    return dict(record, regional_objective=declaration)


def configure(config, record):
    declaration = record.get("regional_objective")
    if not declaration:
        config["project"]["parameter_provenance"].pop("regional_fit", None)
        return
    config["project"]["parameter_provenance"]["regional_fit"] = declaration
    config["optimization"].update(
        method="lbfgs", max_line_search_iterations=30, save_every_n_iterations=1_000_000
    )
