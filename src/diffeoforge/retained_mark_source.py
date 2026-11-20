"""Bind Retain instructions to the inspected fit on which they were introduced.

This is a numerical starting reference, never anatomical or cohort approval.
Existing journals are read without rewriting prior preferences or reviews.
"""

import json
from pathlib import Path


def _key(row):
    geometry = {k: row[k] for k in ("source_sha256", "space", "center", "radius")}
    geometry["center"] = [float(v) for v in geometry["center"]]
    geometry["radius"] = float(geometry["radius"])
    if row.get("shape") == "box":
        geometry.update(shape="box", bounds=[float(v) for v in row["bounds"]])
    return json.dumps(geometry, sort_keys=True, separators=(",", ":"))


def context(snapshot, identifier, *, rows=None):
    from diffeoforge import guided_feedback as feedback
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.mesh import sha256_file

    info = guided.record(snapshot)
    if not info or not info.get("target") or info.get("phase") == "joint":
        return None
    target = info["target"]
    rows = feedback.regions(snapshot, identifier, target) if rows is None else rows
    fixed = {_key(r) for r in rows if r.get("purpose") == "fixed"}
    if not fixed:
        return None
    origins, previous, explicit = {}, set(), None
    position = 0
    for history in [*info.get("history", []), None]:
        root = Path(history["directory"]) if history else snapshot.study_directory
        if history and sha256_file(root / study.STUDY_MANIFEST) != history["manifest_sha256"]:
            raise ValueError("Retain-mark source history changed")
        for event in study._load_events(root):
            position += 1
            kind = event["event"]
            if kind not in {"guided_fit_feedback", "guided_starting_fit_selected"}:
                continue
            reference = (event.get("current") if kind == "guided_fit_feedback"
                         else event["reference"])
            if not reference or reference["target"] != target:
                continue
            if kind == "guided_starting_fit_selected":
                explicit = position, reference
            marked = event.get("problem_regions", {}).get(target)
            cleared = target in event.get("region_edit", {}).get("cleared", [])
            if not marked and not cleared:
                continue  # Missing payloads cannot clear inherited marks.
            if (event.get("inspected_subjects") != [target]
                    or not event.get("display_scopes", {}).get(target)
                    or event.get("anatomical_approval_created") is not False):
                raise ValueError("Retain instructions need the exact inspected source fit")
            current = {_key(r) for r in marked or [] if r.get("purpose") == "fixed"}
            for key in current:
                if key not in previous or kind == "guided_starting_fit_selected":
                    origins[key] = (position, reference, kind == "guided_starting_fit_selected"
                                    or event.get("outcome") == "better")
            previous = current
    choices = []
    for key in fixed:
        origin = origins.get(key)
        if explicit and (origin is None or explicit[0] > origin[0]):
            origin = (*explicit, True)
        if origin is None:
            return dict(available=False, automatic_start_allowed=False, reference=None,
                reason="Choose an inspected saved starting fit for the Retain areas, "
                       "then confirm their instructions there.")
        feedback._same_source(snapshot, origin[1])
        choices.append(origin)
    reference = choices[0][1]
    if any(r[1] != reference for r in choices[1:]):
        return dict(available=False, automatic_start_allowed=False, reference=None,
            reason="These Retain areas refer to different saved fits. Choose one "
                   "working fit and confirm the areas together before preparing a test.")
    automatic = all(r[2] for r in choices)
    return dict(available=True, automatic_start_allowed=automatic, reference=reference,
        fixed_areas=len(fixed), anatomical_approval=False,
        reason="Retain areas use this inspected working starting fit. Newer attempts "
               "do not change their reference automatically." if automatic else
               "The Retain areas were marked on a fit not preferred as a whole. "
               "Choose its working-fit view to confirm that starting point.")


def current_is_bound(data):
    """A newer seed must protect the same inspected field, not an old fallback."""
    retention = data.get("retention_context")
    if not retention:
        return True
    if not retention["available"] or not retention["automatic_start_allowed"]:
        return False
    reference = retention["reference"]
    if reference == data.get("current_reference"):
        return True
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory
    from diffeoforge.regional_fit import read_plan

    plan = read_plan(load_config(data["current"].config_path))
    retained = (plan or {}).get("retained_run")
    if not retained or not plan.get("fixed_protection"):
        return False
    parent = data.get("references", {}).get(reference["directory"])
    parent = parent or verify_reference(reference)
    candidate = next(c for c in parent.candidates if c.candidate_id == reference["candidate_id"])
    run = calibration_candidate_run_directory(candidate)
    from diffeoforge.mesh import sha256_file

    return (Path(retained["path"]).resolve() == run.resolve()
            and retained["manifest_sha256"] == sha256_file(run / "manifest.json"))
