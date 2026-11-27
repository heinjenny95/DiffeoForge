"""Compare a common field with the explicitly accepted shape; never approve anatomy.

Only completed, identity-bound geometry is read in preparation workers. Scores
rank bounded experiments, not unique causes or permission to change a protocol.
"""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock

VERSION = "accepted-shape-common-diagnosis-v4"
_CACHE = OrderedDict()
_LOCK = RLock()


def _geometry(parent, candidate, target):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_evaluation import endpoint
    from diffeoforge.result_report import collect_run_report
    from diffeoforge.surface_io import load_surface_mesh

    manifest = study._verify_manifest(parent.study_directory)
    original = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == target)
    run = study.calibration_candidate_run_directory(candidate)
    report = collect_run_report(run)
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    rows = [r for r in report.inventory
            if ("__Reconstruction__" + object_id + "__subject_") in r["path"]
            and r["path"].endswith("__subject_" + target + ".vtk")]
    if not rows:
        return None  # Explicitly unavailable; never substitute a proxy or an old field.
    if len(rows) != 1:
        raise ValueError("Common diagnosis requires one bound reconstruction")
    row = endpoint(candidate, subject=target) or dict(
        path=str(study._safe_study_path(run / "output", rows[0]["path"])),
        sha256=rows[0]["sha256"])
    path = Path(row["path"])
    if sha256_file(path) != row["sha256"]:
        raise ValueError("Common diagnosis reconstruction changed")
    loaded = load_surface_mesh(path)
    if loaded.metadata.sha256 != row["sha256"]:
        raise ValueError("Common diagnosis geometry changed while loading")
    return loaded.geometry, original, manifest["inputs"]["template"]["sha256"], report


def _compare(accepted_ref, current_ref, *, regions=None):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_density import controls_for
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_attachment_comparison import compare_geometry
    from diffeoforge.reference_calibration import _canonical_hash
    from diffeoforge.surface_io import load_surface_mesh

    accepted, current = (verify_reference(r) for r in (accepted_ref, current_ref))
    if (accepted_ref["target"] != current_ref["target"]
            or accepted.attachment_comparison["guided"]["origin"]
            != current.attachment_comparison["guided"]["origin"]
            or accepted.visual_reviews.get(accepted_ref["candidate_id"]) is not True):
        raise ValueError("Common diagnosis requires this cohort's approved individual shape")
    regions = deepcopy(accepted.problem_regions.get(accepted_ref["candidate_id"], {}).get(
        accepted_ref["target"], []) if regions is None else regions)
    pairs = []
    for parent, ref in ((accepted, accepted_ref), (current, current_ref)):
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        pair = _geometry(parent, candidate, ref["target"])
        if pair is None:
            return None
        pairs.append((parent, candidate, pair))
    first, second = pairs[0][2], pairs[1][2]
    if first[1]["sha256"] != second[1]["sha256"] or first[2] != second[2]:
        raise ValueError("Common diagnosis original or template identity differs")
    original_path = study._safe_study_path(accepted.study_directory, first[1]["copy"])
    original = load_surface_mesh(original_path)
    if original.metadata.sha256 != first[1]["sha256"]:
        raise ValueError("Common diagnosis original changed")
    from diffeoforge.pilot_regions import validate

    validate({accepted_ref["target"]: regions} if regions else {},
             {accepted_ref["target"]: first[1]["sha256"]})
    key = _canonical_hash(dict(version=VERSION, accepted=accepted_ref, current=current_ref,
                               regions=regions))
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return deepcopy(_CACHE[key])
    evidence = []
    for _, candidate, pair in pairs:
        saved = (candidate.metrics or {}).get("attachment_comparison", {}).get(
            "subjects", {}).get(accepted_ref["target"])
        evidence.append(saved if saved and saved.get("repeats") else compare_geometry(
            original.geometry, pair[0], original_key=first[1]["sha256"]))
    from diffeoforge.pilot_common_capacity import count

    result = dict(accepted=evidence[0], current=evidence[1],
        agreement=compare_geometry(first[0], second[0]),
        original_sha256=first[1]["sha256"], template_sha256=first[2],
        objective_tail=[r.log_likelihood for r in second[3].convergence[-6:]],
        accepted_local=bool(accepted.attachment_comparison.get("regional_objective")),
        accepted_controls=count(accepted_ref),
        current_controls=controls_for(current.attachment_comparison,
                                      current_ref["candidate_id"])["count"])
    if regions:
        from diffeoforge.guided_response import measured

        result["marked_accepted"] = measured(accepted_ref, regions)["baseline"]
        result["marked_current"] = measured(current_ref, regions)["baseline"]
    with _LOCK:
        _CACHE[key] = deepcopy(result)
        while len(_CACHE) > 32:
            _CACHE.popitem(last=False)
    return result


def assess(measured, previous=None, *, require_problem_progress=False):
    """Repeat-aware local and whole-shape comparisons; mixed change vetoes continuation."""
    a, b = measured["accepted"], measured["current"]
    floor = a["diagonal"] * 1e-4
    lost = []
    labels = set.intersection(*(set(r.get("regions", {})) for r in b["repeats"]))
    for label in sorted(labels):
        x = [r.get("regions", {}).get(label) for r in a["repeats"]]
        y = [r["regions"][label] for r in b["repeats"]]
        if min(r["count"] for r in y) < 1:
            continue
        # Sparse important features keep their repeat-confirmed maximum. A new
        # reverse-direction cell is compared with the accepted worst envelope.
        baseline = (max(r["tail"] for r in x) if all(x) else
                    max(r["regional_tail"] for r in a["repeats"]))
        if min(r["tail"] for r in y) > baseline * 1.15 + floor:
            lost.append(dict(region=label, accepted=baseline,
                             common=min(r["tail"] for r in y)))
    whole_gap = any(min(r[k] for r in b["repeats"]) >
        max(r[k] for r in a["repeats"]) * 1.15 + floor for k in ("mean", "p95", "p99"))
    for index, (first, second) in enumerate(zip(measured.get("marked_accepted", []),
                                               measured.get("marked_current", []), strict=True)):
        if first["region"] != second["region"]:
            raise ValueError("Accepted/common marked geometry must use the same original areas")
        for key in ("original_to_fit_p95", "original_to_fit_p99",
                    "fit_to_original_p95", "fit_to_original_p99"):
            x = [r[key] for r in first["repeats"] if r.get(key) is not None]
            y = [r[key] for r in second["repeats"] if r.get(key) is not None]
            if len(x) == len(y) == 2 and min(y) > max(x) * 1.15 + floor:
                lost.append(dict(region=f"mark:{index}:{key}", accepted=max(x), common=min(y)))
    direct = measured["agreement"]["repeats"]
    trend = "unknown"
    if previous:
        before = previous["agreement"]["repeats"]
        improved = max(r["p95"] for r in direct) + floor < min(
            r["p95"] for r in before) * .95
        regressed = any(min(r[k] for r in b["repeats"]) > max(
            r[k] for r in previous["current"]["repeats"]) * 1.15 + floor
                        for k in ("p95", "p99", "regional_tail"))
        for label in lost:
            values = [r.get("regions", {}).get(label["region"]) for r in
                      previous["current"]["repeats"]]
            if all(values) and label["common"] > max(r["tail"] for r in values) * 1.15 + floor:
                regressed = True
        for first, second in zip(previous.get("marked_current", []),
                                 measured.get("marked_current", []), strict=True):
            if first["region"] != second["region"]:
                raise ValueError("Common trend must keep the same accepted marked regions")
            for key in ("original_to_fit_p95", "original_to_fit_p99",
                        "fit_to_original_p95", "fit_to_original_p99"):
                x = [r[key] for r in first["repeats"] if r.get(key) is not None]
                y = [r[key] for r in second["repeats"] if r.get(key) is not None]
                if len(x) == len(y) == 2 and min(y) > max(x) * 1.15 + floor:
                    regressed = True
        trend = "worse" if regressed else "improving" if improved else "plateau"
    marked_progress = None
    critical_marks = [r for r in lost if r['region'].startswith('mark:')]
    if previous and critical_marks:
        progress = []
        for loss in critical_marks:
            _, index, key = loss['region'].split(':', 2)
            now = measured['marked_current'][int(index)]['repeats']
            before = previous['marked_current'][int(index)]['repeats']
            old_values = [r[key] for r in before if r.get(key) is not None]
            new_values = [r[key] for r in now if r.get(key) is not None]
            progress.append(len(old_values) == len(new_values) == 2
                            and max(new_values) + floor < min(old_values) * .95)
        marked_progress = all(progress)
    # A newly rejected problem remains a goal even if the accepted reference
    # already missed it. Stable preserve/fixed marks do not require improvement.
    active = [i for i, row in enumerate(measured.get("marked_current", []))
              if require_problem_progress and row["region"].get("purpose", "problem") == "problem"]
    if active:
        outcomes = []
        for index in active:
            useful = worsened = False
            if previous:
                now = measured["marked_current"][index]["repeats"]
                before = previous["marked_current"][index]["repeats"]
                for key in ("original_to_fit_p95", "original_to_fit_p99",
                            "fit_to_original_p95", "fit_to_original_p99"):
                    x = [r[key] for r in before if r.get(key) is not None]
                    y = [r[key] for r in now if r.get(key) is not None]
                    if len(x) != 2 or len(y) != 2:
                        continue
                    useful |= max(y) + floor < min(x) * .95
                    worsened |= min(y) > max(x) * 1.05 + floor
            outcomes.append(useful and not worsened)
        progress = all(outcomes)
        marked_progress = progress if marked_progress is None else marked_progress and progress
    tail = measured.get("objective_tail", [])
    numerical_progress = (len(tail) >= 3 and all(
        y >= x for x, y in zip(tail[:-1], tail[1:], strict=True))
                          and tail[-1] - tail[0] > max(abs(tail[0]), 1.) * 1e-6)
    return dict(local_losses=lost, whole_gap=whole_gap, gap=bool(lost or whole_gap or active),
                trend=trend,
                reviewed_problem_marks=len(active),
                marked_progress=marked_progress,
                accepted_local=measured["accepted_local"], numerical_progress=numerical_progress,
                accepted_controls=measured["accepted_controls"],
                current_controls=measured["current_controls"],
                agreement_p95=max(r["p95"] for r in direct),
                accepted_p95=max(r["p95"] for r in a["repeats"]),
                common_p95=max(r["p95"] for r in b["repeats"]),
                warnings=list(b.get("warnings", [])))


def comparison_regions(snapshot, current, current_ref):
    """Use later verified working edits without overwriting the saved fit's journal."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import local_region_edit, region_state
    from diffeoforge.mesh import sha256_file

    identifier, target = current_ref["candidate_id"], current_ref["target"]
    rows, cleared = region_state(current, identifier, target)
    fallback = rows if rows or cleared else None
    if snapshot is None or snapshot.study_directory == current.study_directory:
        return fallback
    info = guided.record(snapshot) or {}
    history = info.get("history", [])
    positions = [i for i, row in enumerate(history)
                 if Path(row["directory"]).resolve() == current.study_directory.resolve()]
    if not positions:
        return fallback  # An older/unrelated context cannot supersede this saved field.
    if any(history[i]["manifest_sha256"] != current_ref["manifest_sha256"] for i in positions):
        raise ValueError("Working annotation history changed")
    parents, seen = [current], {current.study_directory.resolve()}
    for row in history[positions[-1] + 1:]:
        root = Path(row["directory"])
        if sha256_file(root / study.STUDY_MANIFEST) != row["manifest_sha256"]:
            raise ValueError("Working annotation history changed")
        if root.resolve() not in seen:
            parents.append(study.load_reference_calibration_study(root))
            seen.add(root.resolve())
    if snapshot.study_directory.resolve() not in seen:
        parents.append(snapshot)
    origin = Path(guided.record(current)["origin"]).resolve()
    edits = []
    for order, parent in enumerate(parents):
        other = guided.record(parent) or {}
        if Path(other["origin"]).resolve() != origin:
            raise ValueError("Working annotations belong to another cohort")
        if other.get("target") != target:
            continue
        methods = parent.attachment_comparison["methods"]
        identifiers = ([identifier] if methods.get(identifier) == current_ref["method"] else
                       [key for key, method in methods.items() if method == current_ref["method"]])
        if len(identifiers) != 1:
            continue
        edit = local_region_edit(parent, identifiers[0], target)
        if edit is not None:
            recorded_at, regions, clear = edit
            edits.append((recorded_at, order, regions, clear))
    if not edits:
        return fallback
    _, _, regions, _ = max(edits, key=lambda row: row[:2])
    return regions  # Explicit Clear remains [], including a newer edit on an older field.


def alignment_advice(snapshot, parent, ref, feedback, value):
    """An explicit pose concern warrants inspecting the unchanged input overlay."""
    marked = comparison_regions(snapshot, parent, ref) or []
    if (not (feedback and feedback[-1].get("symptom") == "alignment")
            and not any(row.get("purpose", "problem") == "problem"
                        and row.get("symptom") == "alignment" for row in marked)):
        return None
    return dict(mode="inspect_alignment", available=False, target=ref["target"], reference=ref,
                review_reference=ref, accepted_reference=accepted_reference(value, ref["target"]),
                label="Inspect template and alignment · " + ref["target"],
                reason="You flagged the overall alignment. Open the original and template in "
                       "their saved coordinate frame. If the alignment checks out, update your "
                       "fit feedback to choose the next test.")


def accepted_reference(value, target):
    row = next((r for r in value["reviews"] if r["filename"] == target), None)
    if not row:
        return None
    ref = dict(row)
    ref["target"] = ref.pop("filename")
    return ref


def diagnose(snapshot, value, current_ref, previous_ref=None):
    from diffeoforge.guided_feedback import reference, verify_reference

    ref = accepted_reference(value, current_ref["target"])
    if not ref:
        return None
    parent = verify_reference(ref)
    accepted = reference(parent, ref["candidate_id"])
    current = verify_reference(current_ref)
    regions = comparison_regions(snapshot, current, current_ref)
    measured = _compare(accepted, current_ref, regions=regions)
    if measured is None:
        return None
    previous = _compare(accepted, previous_ref, regions=regions) if previous_ref else None
    rejected = getattr(current, "visual_reviews", {}).get(current_ref["candidate_id"]) is False
    accepted_width = accepted.get("values", {}).get("attachment_kernel_width")
    current_width = current_ref.get("values", {}).get("attachment_kernel_width")
    return dict(version=VERSION, accepted=accepted, current=current_ref,
                previous=previous_ref, original_sha256=measured["original_sha256"],
                accepted_test_number=parent.attachment_comparison["guided"]["screen_trials_spent"],
                template_sha256=measured["template_sha256"],
                accepted_finer_attachment=(accepted_width is not None and current_width is not None
                                           and accepted_width < current_width),
                **assess(measured, previous, require_problem_progress=rejected))


def detail_evidence(diagnosis):
    return (bool(diagnosis.get("local_losses")) or diagnosis.get("reviewed_problem_marks", 0) > 0
            or diagnosis.get("accepted_finer_attachment", False))


def experiment(kind, diagnosis):
    """Describe the particular contrast and how its result can support the hypothesis."""
    if kind == "iterations":
        return dict(reason="The fit is still getting closer to the accepted shape.",
                    expected="Look for smaller errors in the open areas and stable fitted areas.")
    if kind == "detail":
        reason = ("The accepted fit used a finer attachment scale." if
                  diagnosis.get("accepted_finer_attachment") else
                  "The comparison points to a remaining local shape mismatch.")
        return dict(reason=reason + " Test a finer attachment width with the saved control basis.",
                    expected="Look for better agreement at the same feature in both directions.")
    if kind == "weight":
        return dict(reason="A residual surface mismatch remains on the saved control basis. "
                           "Test stronger surface matching at the same width.",
                    expected="Surface distances should shrink without distortion in fitted areas.")
    return dict(reason="The accepted shape exposes a remaining mismatch. Test whether a "
                       "denser shared control basis lets the field reach that shape.",
                expected="Look for closer agreement with the accepted fit and stable fitted areas.")


def recommend(diagnosis, *, capped, iteration_tests=0, density_tested=False, veto=False):
    """A bounded experiment choice, explicitly separate from anatomical acceptance."""
    if not diagnosis:
        return None
    if not diagnosis["gap"]:
        return dict(kind="inspect", reason="Sampled surfaces are close to the accepted fit. "
            "Inspect the remaining feature difference; these samples cannot approve anatomy.")
    improving = (diagnosis["trend"] == "improving" or diagnosis.get("marked_progress") is True
                 and diagnosis["trend"] == "plateau")
    # A numerical trend can support an unmarked first comparison, while an
    # open mark always needs a same-area geometric comparison.
    improving |= (diagnosis["trend"] == "unknown" and diagnosis["numerical_progress"]
                  and not detail_evidence(diagnosis) and not diagnosis["accepted_local"])
    if (capped and improving and diagnosis.get('marked_progress') is not False
            and iteration_tests < 2 and not veto and not diagnosis["warnings"]):
        evidence = experiment("iterations", diagnosis)
        if diagnosis["trend"] == "unknown":
            evidence["reason"] = ("The objective improved up to the cap. This unmarked first "
                                  "comparison has a single surface measurement.")
        return dict(kind="iterations", **evidence)
    if (not diagnosis["warnings"] and detail_evidence(diagnosis)
            and diagnosis["accepted_controls"] <= diagnosis["current_controls"]):
        return dict(kind="detail", **experiment("detail", diagnosis))
    if not density_tested and not diagnosis["warnings"]:
        return dict(kind="capacity", **experiment("capacity", diagnosis))
    return dict(kind="stalled", reason="The bounded comparison has not resolved this model. "
        "Keep all accepted fits; review a shared-model revision or another fitting scale "
        "rather than repeating identical tests.")
