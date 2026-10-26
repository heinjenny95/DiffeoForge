"""User-gated, retained-field regional trials and history-driven local recipes."""

from pathlib import Path

from diffeoforge.mesh import sha256_file

MINIMUM_NEW_NATIVE_TIMEPOINTS = 37


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
        or plan.get('protection_close_distance') != recipe.get('protection_close_distance')
        or plan.get('protection_tolerance') != recipe.get('protection_tolerance')
    ):
        raise ValueError("Regional fitting recipe changed")


def proposal(snapshot, identifier, data, *, symptom=None):
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.regional_continuation import proposal as numerical_proposal
    from diffeoforge.regional_resolution import response as resolution_response

    numerical = numerical_proposal(snapshot, identifier, data, symptom=symptom)
    resolution = resolution_response(data, guided.record(snapshot), numerical, symptom)
    if numerical and not resolution:
        return numerical
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
    previous_recipe = (info.get('strategy') or {}).get('regional_recipe') or {}
    retry_global = None
    retained_surface = None
    if (previous_recipe.get('phase') == 'whole_recovery'
            and feedback.get('outcome') in {'same', 'worse'}
            and reference != data['current_reference'] and data['current_reference']):
        from diffeoforge.guided_feedback import verify_reference

        retained = verify_reference(reference)
        candidate = next(c for c in retained.candidates
                         if c.candidate_id == reference['candidate_id'])
        row = ((candidate.metrics or {}).get('attachment_comparison', {})
               .get('subjects', {}).get(reference['target'], {}))
        current_row = ((data['current'].metrics or {}).get('attachment_comparison', {})
                       .get('subjects', {}).get(reference['target'], {}))
        old_tail = max((r['p95'] for r in row.get('repeats', [])), default=0)
        new_tail = max((r['p95'] for r in current_row.get('repeats', [])), default=0)
        trusted = row.get('regional_quality') or {}
        if (trusted.get('numerical_selection_suitable')
                and trusted.get('marked_regions') == marked
                and (feedback['outcome'] == 'worse'
                     or not quality.get('numerical_selection_suitable')
                     or new_tail >= old_tail*.95)):
            retry_global = dict(reference=data['current_reference'],
                                values=dict(data['current_reference']['values']),
                                recipe=dict(previous_recipe),
                                global_progress=0 < new_tail < old_tail*.95)
            def marked_tail(q):
                return max((max(r['original_to_fit_p95'], r.get('fit_to_original_p95', 0))
                            for r in q.get('active_surface', [])), default=0)
            before_local, after_local = marked_tail(trusted), marked_tail(quality)
            retry_global['local_noise_ratio'] = (
                max(.5, min(1., before_local/after_local)) if after_local > 0 else 1.)
            quality = trusted
            retained_surface = row
            previous_recipe = ((guided.record(retained).get('strategy') or {})
                               .get('regional_recipe') or {})
    if (
        info.get("goal") == "regional"
        and not retry_global
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
    # These are explicit hypotheses. Native controlled-case parity does not
    # qualify the full automatic search; each new result is checked again.
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
    evidence = data.get('regional_capture')
    if evidence:
        tail = evidence['original_to_fit_p95']
        if seed == data['current_reference'] and quality.get('active_surface'):
            tail = max(r['original_to_fit_p95'] for r in quality['active_surface'])
        capture = tail > recipe['focus_width'] * 2
        if capture:
            recipe['focus_width'] = max(recipe['focus_width'], tail * .5)
            recipe['focus_noise'] = values['noise_std'] * max(noise_factor, .15)
        recipe.update(version='protected-local-v2',
            phase='capture' if capture else 'detail', capture_evidence=evidence,
            protection_close_distance=values['noise_std']*.5,
            protection_tolerance=values['noise_std']*.25,
            control_support='source-target-coverage-v1')
        for key in ('protection_close_distance', 'protection_tolerance', 'protection_halo'):
            if key in previous_recipe:
                recipe[key] = previous_recipe[key]
    ratios = dict(snapshot.plan.baseline_parameter_ratios) if snapshot is not None else {}
    ratio = ratios.get("attachment_kernel_width")
    diagonal = data.get('spatial_diagonal')
    if diagonal is None and ratio:
        diagonal = reference["values"]["attachment_kernel_width"] / ratio
    if diagonal:
        recipe["protection_halo"] = min(recipe["protection_halo"], diagonal * 0.1)
    # Changing a movement kernel cannot reuse its old momenta as if the basis
    # were identical. Preserve that deformation as the prefix of a residual.
    recipe["residual"] = (
        symptom not in {"gap", "position"}
        or any(r["symptom"] == "curvature" for r in problem)
        or level >= 2
    ) and not (quality and seed == data["current_reference"] and quality.get("local_improved"))
    initial_warm = bool(evidence and not cases and not quality)
    initial_case = next((r for r in reversed(data['context']['cases'])
        if r.get('family') == 'regional' and r['target'] == reference['target']
        and r.get('regions', marked) == marked and r.get('reference')
        and (r.get('regional_recipe') or {}).get('phase') == 'initial_warm'), None)
    coarse_other = bool(not resolution and evidence
                        and previous_recipe.get('phase') == 'initial_warm'
                        and initial_case
                        and not any((r.get('regional_recipe') or {}).get('phase')
                                    == 'coarse_method_check'
                                    and r['target'] == reference['target']
                                    and r.get('regions', marked) == marked
                                    for r in data['context']['cases']))
    finer = bool(evidence and previous_recipe.get('focus_width')
                 and recipe['focus_width'] < previous_recipe['focus_width']*.8)
    method = reference['method']
    other = 'varifold' if method == 'current' else 'current'
    tested_other = any(r.get('family') == 'regional' and r.get('method') == other
                       and r['target'] == reference['target'] and r.get('regions') == marked
                       for r in data['context']['cases'])
    contrast = bool(evidence and len(cases) >= 2 and not tested_other
                    and any(r.get('outcome') in {'same', 'worse', 'rejected'} for r in cases))
    current_surface = retained_surface or (
        (data['current'].metrics or {}).get('attachment_comparison', {})
        .get('subjects', {}).get(reference['target'], {}))
    whole_tail = max((r['p95'] for r in current_surface.get('repeats', [])), default=0)
    # A useful local field can leave the rest underweighted. Rebalance that same
    # field before adding still finer controls; use only this fit's measurements.
    balance = bool(evidence and seed == data['current_reference']
                   and (quality.get('local_improved')
                        or quality.get('numerical_selection_suitable'))
                   and (previous_recipe.get('whole_surface_contrast')
                        or previous_recipe.get('whole_surface_balance')
                        or previous_recipe.get('whole_surface_capture'))
                   and whole_tail > 2*tail)
    spatial_tail = max((r.get('regional_tail', r.get('p99', r['p95']))
                        for r in current_surface.get('repeats', [])), default=0)
    whole_capture = bool(balance and spatial_tail > 2*values['attachment_kernel_width'])
    if balance:
        finer = contrast = False
        recipe.update(version='protected-local-v4', phase='balance', residual=False,
            focus_width=previous_recipe['focus_width'],
            focus_noise=min(previous_recipe.get('focus_noise', values['noise_std']*.5),
                            values['noise_std']*.5),
            protection_noise=previous_recipe['protection_noise'],
            protection_close_distance=previous_recipe['protection_close_distance'],
            protection_tolerance=previous_recipe['protection_tolerance'],
            whole_surface_balance=dict(whole_p95=whole_tail, marked_p95=tail,
                noise_factor=.5, existing_field_and_prefix_retained=True))
        values['noise_std'] *= .5
    if whole_capture:
        # Existing spatial-bin tails expose a missed small feature even when
        # its area is too small to dominate the global percentile. Keep the
        # learned field/local objective; change the whole-surface capture only.
        balance = finer = contrast = False
        original_noise = seed['values']['noise_std']
        old_width = seed['values']['attachment_kernel_width']
        width = max(old_width*1.5, spatial_tail*.5)
        values['attachment_kernel_width'] = width
        values['noise_std'] = original_noise*width/old_width
        recipe.update(version='protected-local-v5', phase='whole_capture', residual=False,
            focus_noise=previous_recipe['focus_noise'],
            whole_surface_capture=dict(spatial_tail=spatial_tail, before_width=old_width,
                after_width=width, noise_scale=width/old_width,
                existing_field_and_local_objective_retained=True))
        recipe.pop('whole_surface_balance', None)
    if initial_warm or coarse_other:
        # The first protected fit must be able to improve the original broad
        # field itself. Freezing an already-wrong broad field as an immutable
        # prefix is not equivalent to warm optimization of that same basis.
        finer = contrast = balance = whole_capture = False
        if coarse_other:
            # Both models must start from the same saved field. Chaining the
            # second model after the first model confounds this comparison.
            seed = initial_case['reference']
            values = dict(seed['values'])
        recipe.update(version='protected-local-v7', residual=False,
            phase='initial_warm' if initial_warm else 'coarse_method_check',
            protection_noise=values['noise_std'], protection_reference=seed)
        if coarse_other:
            method = other
            recipe.update(focus_width=previous_recipe['focus_width'],
                focus_noise=previous_recipe['focus_noise'],
                whole_surface_contrast=dict(from_method=reference['method'], to_method=method,
                    scale_factor=1., noise_factor=1., existing_broad_basis_retained=True))
    if resolution:
        # A substantial inspected pass improved the broad fit, but the human
        # still rejects its detail. Test finer independent movement first.
        finer = True
        contrast = balance = whole_capture = False
        recipe.update(residual=True, phase='local_resolution', control_scope='marked_halo',
            focus_width=resolution['next_focus_width'],
            focus_noise=previous_recipe['focus_noise'],
            local_resolution_response=resolution)
    if finer or contrast:
        recipe['version'] = 'protected-local-v3'
        recipe['residual'] = True
        recipe['control_scope'] = 'full_surface' if contrast else 'marked_halo'
        if symptom not in {'gap', 'position'}:
            recipe['protection_noise'] = values['noise_std']*.5
    if finer:
        # Isolate the movement/detail-scale hypothesis: a new basis must not
        # simultaneously jump to a hundreds-fold stronger local surface term.
        previous_noise = previous_recipe.get('focus_noise', values['noise_std']*.3)
        next_noise = max(previous_noise, values['noise_std']*.15)
        recipe.update(version='protected-local-v7',
            focus_noise=next_noise,
            weight_continuation=dict(basis_changed=True, before_noise=previous_noise,
                after_noise=next_noise, minimum_noise_fraction=.15,
                local_weight_held=next_noise == previous_noise))
    if contrast:
        method = other
        values['attachment_kernel_width'] = min(values['attachment_kernel_width']*.5,
                                                recipe['focus_width'])
        values['noise_std'] *= .5
        recipe['whole_surface_contrast'] = dict(from_method=reference['method'], to_method=method,
            scale_factor=.5, noise_factor=.5, retained_prefix_unchanged=True)
    if resolution:
        recipe['protection_noise'] = min(recipe['protection_noise'],
                                         previous_recipe['protection_noise'])
    if recipe["residual"]:
        values["deformation_kernel_width"] = max(
            values['deformation_kernel_width']*.5,
            2*recipe['focus_width'] if evidence else 0)
    recovery = False
    if evidence and (seed == data['current_reference'] or retry_global):
        from diffeoforge.regional_search import recover_whole

        recovery = recover_whole(recipe, values, seed['values'], previous_recipe, quality,
                                 whole_tail, spatial_tail, explicit_fixed=bool(_fixed))
        if recovery:
            finer = contrast = balance = whole_capture = False
            if retry_global:
                failed = retry_global['values']
                progress = retry_global['global_progress']
                factor = 1. if progress else .5
                values.update(attachment_kernel_width=failed['attachment_kernel_width']*factor,
                              noise_std=failed['noise_std']*(1. if progress else .5))
                values['deformation_kernel_width'] = max(
                    failed['deformation_kernel_width']*factor,
                    2*recipe['focus_width'], 2*values['attachment_kernel_width'])
                recipe['version'] = 'protected-local-v11' if progress else 'protected-local-v9'
                if progress:
                    # Earlier settings helped, but the correction lost local fidelity.
                    # Keep global settings; do not weaken the retained relative
                    # local weight while increasing absolute fidelity elsewhere.
                    relative = previous_recipe['focus_noise']/seed['values']['noise_std']
                    desired = min(previous_recipe['focus_noise']*.5,
                                  values['noise_std']*relative)*retry_global['local_noise_ratio']
                    recipe['focus_noise'] = max(desired,
                        retry_global['recipe']['focus_noise']*.25)
                    recipe['protection_noise'] = retry_global['recipe']['protection_noise']
                    recipe['whole_surface_recovery'].update(
                        retained_local_global_noise_ratio=relative,
                        desired_focus_noise=desired,maximum_noise_decrease_factor=4.)
                recipe['whole_surface_recovery'].update(
                    discarded_trial=retry_global['reference'],
                    before_width=failed['attachment_kernel_width'],
                    after_width=values['attachment_kernel_width'],
                    failed_global_field_reused=False,
                    kernel_widths_changed=not progress,
                    control_support_rebuilt=True,
                    measured_global_progress=progress,
                    local_noise_ratio=retry_global['local_noise_ratio'],
                    hypothesis=('Restore marked fidelity with the tested global settings'
                                if progress else
                                'Finer global resolution from the retained good field'))
    if recipe['residual'] and recipe.get('control_scope') == 'full_surface':
        recipe['control_budget_policy'] = 'bounded-full-surface-v1'
    changed = False
    if evidence:
        from diffeoforge.regional_search import distinct

        available_contrast, changed = distinct(recipe, values, method, seed,
                                               data['context']['cases'], quality)
        available &= available_contrast
        if not available_contrast:
            blocked = ('This contrast reached its numerical weight guard. Keep the saved '
                       'fit and review the inputs, marked areas or movement scale.')
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
    if evidence:
        reason += ("First reach missing original surfaces, then refine their detail. "
                   "The measured mismatch determines the next capture scale; "
                   "new residual controls cover source and target. "
                   "Protect already-close unmarked positions and explicit fixed areas, "
                   "and check previously good original surfaces separately. ")
    if finer:
        reason += ('The earlier capture is retained; add a finer independent field '
                   'instead of forcing detail through the same broad movement. ')
    if resolution:
        reason += ('Details still need work after the longer inspected test. Keep the '
                   'improved overall shape and test smaller, more local changes in the '
                   'marked areas. The remaining distance in each marked area determines '
                   'capture; protection stays at least as strong. ')
    if contrast:
        reason += (f'Earlier local tests still needed improvement. Check {method.title()} '
                   'on the whole original at this finer scale, keeping the saved shape '
                   'as the unchanged starting deformation. ')
    if balance:
        reason += ('The marked area improved more than the whole surface. Continue the '
                   'same field with stronger global surface weight, retaining useful local '
                   'weight and strengthening '
                   'whole-surface agreement while keeping the earlier capture and controls. ')
    if whole_capture:
        reason += ('A spatially supported whole-surface miss still lies beyond capture. '
                   'Broaden whole-surface capture and scale its noise with that width; '
                   'retain the local detail settings, controls and learned deformation. ')
    if recovery:
        reason += ('The marked area has reached the measured detail tolerance, but the '
                   'whole surface still has larger errors. Retain all earlier fields and '
                   'the local objective; test a whole-surface correction with source and '
                   'target control coverage. Keep preservation tolerances and explicit '
                   'fixed regions, and check the marked area again after this correction. ')
        if retry_global:
            reason += ('The earlier whole-surface trial did not pass the measured comparison. '
                       'Return to the retained fit; the discarded correction remains in history. ')
            reason += ('The earlier settings reduced measured whole-surface error. Keep their '
                       'kernel widths and global surface weight; test stronger marked-area '
                       'fidelity, keeping protection weight and physical preservation limits. '
                       if retry_global['global_progress'] else
                       'Test finer whole-surface resolution from the retained fit. ')
    if initial_warm or coarse_other:
        reason += ('First optimize the saved broad field itself with the marked-area '
                   'objective and soft unmarked protection. Preserve its controls and movement '
                   'scale; add a residual only when independent finer movement is needed. ')
        if coarse_other:
            reason += (f'Check {method.title()} on that same broad basis before freezing '
                       'the broad field for finer corrections. Both models use the same '
                       'original starting field and protection frame; keep the earlier '
                       'model result as a separate comparison. ')
    if changed:
        reason += ('The exact earlier settings already have a saved result; '
                   'use a distinct feedback-driven weight contrast. ')
    if seed != reference:
        reason += (
            "Keep your preferred comparison; reuse the last local field only "
            "as the numerical starting point for correcting its transitions. "
        )
    if recipe["residual"]:
        reason += (
            "Keep the saved deformation as a fixed prefix and add a correction "
            "at the chosen movement scale, then evaluate their true forward composition. "
        )
    from diffeoforge.pilot_iteration_effort import regional_allowance

    effort = regional_allowance(
        recipe, marked, getattr(snapshot, "attachment_comparison", {}).get("iterations", 120)
    )
    reason += (
        f"Allow up to {effort['maximum_iterations']} iterations for this local test; "
        "the solver can finish earlier. This is separate from the short method screen. "
        "An improving capped field can be continued with the same settings and marks. "
    )
    return dict(
        goal="regional",
        title=("Improve remaining areas while retaining local detail" if recovery else
               "Improve marked areas and protect the rest"),
        reason=reason,
        target=reference["target"],
        method=method,
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
    from diffeoforge.regional_continuation import bind as bind_numerical
    from diffeoforge.regional_continuation import marker

    if marker(record):
        return bind_numerical(root, manifest, record)
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
    ref = recipe.get('protection_reference') or record["guided"]["strategy"]["anchor"]
    if recipe.get('protection_reference') and (
        ref != record['refinement']['reference'] or ref['target'] != feedback['target']
    ):
        raise ValueError('Common-start protection must match the bound initialization reference')
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
    from diffeoforge.regional_frame import compatible, qualify, verify_source

    parent_evaluation = record.get("refinement", {}).get("parent_evaluation")
    if (parent_evaluation and Path(parent_evaluation["source_run"]).resolve() == run.resolve()):
        anchor_evaluation = parent_evaluation
    if not compatible(anchor_evaluation):
        original = (parent_evaluation or {}).get("reference_source")
        anchor_evaluation = qualify(run, root / "comparison-frame-qualification",
                                   source=original["path"] if original else None)
    verify_source(anchor_evaluation)
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
        protection_close_distance=recipe.get('protection_close_distance'),
        protection_tolerance=recipe.get('protection_tolerance'),
    )
    import json
    import shutil

    path = Path(declaration["manifest"])
    data = json.loads(path.read_text())
    data["retained_run"] = dict(path=str(run), manifest_sha256=sha256_file(run / "manifest.json"))
    data["numerical_protocol"] = dict(
        version="regional-rk2-v1", integration="rk2",
        minimum_native_timepoints=MINIMUM_NEW_NATIVE_TIMEPOINTS,
        retained_comparison=anchor_evaluation, field_parameters_unchanged=True)
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


def configure_numerics(config):
    """Set the minimum for newly prepared regional candidates, not saved renders.

    Same-objective successors bypass this policy and retain their exact old grid.
    """
    config["optimization"]["convergence_tolerance"] = min(
        config["optimization"]["convergence_tolerance"], 1e-6)
    config["model"]["deformation"].update(
        use_rk2=True, timepoints=max(MINIMUM_NEW_NATIVE_TIMEPOINTS,
                                   config["model"]["deformation"]["timepoints"]))


def configure(config, record):
    from diffeoforge.regional_continuation import configure as configure_numerical

    if configure_numerical(config, record):
        return
    declaration = record.get("regional_objective")
    if not declaration:
        config["project"]["parameter_provenance"].pop("regional_fit", None)
        return
    config["project"]["parameter_provenance"]["regional_fit"] = declaration
    config["optimization"].update(
        method="lbfgs", max_line_search_iterations=30, save_every_n_iterations=1_000_000
    )
    configure_numerics(config)
