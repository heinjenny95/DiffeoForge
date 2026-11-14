"""Explicit recovery of an owner-approved singleton after a joint-fit setback."""

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


def preview(snapshot, identifier, cases):
    """Read-only suggestion; never infer approval or choose a numerical winner."""
    from diffeoforge.guided_feedback import reference, selection, verify_reference

    info = guided.record(snapshot)
    target = info["target"]
    if target is None:
        target = next((name for name, outcome in snapshot.subject_decisions.get(
            identifier, {}).items() if outcome in {"fail", "uncertain"}), None)
    if target is None:
        return None
    method = snapshot.attachment_comparison["methods"][identifier]
    for case in reversed(cases):
        row = case.get("approval")
        if not row or row["filename"] != target or row["method"] != method:
            continue
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        parent = verify_reference(ref)
        if (parent.plan.pilot_subject_count != 1
                or Path(guided.record(parent)["origin"]).resolve()
                != Path(info["origin"]).resolve()):
            continue
        if guided._approved_record(parent, ref["candidate_id"]) != row:
            raise ValueError("The accepted single-form fit changed")
        current = reference(snapshot, identifier, target)
        if ref == current:
            return None
        selected = selection(snapshot, identifier)
        return dict(reference=ref, target=target,
                    label=f"Test {guided.record(parent)['screen_trials_spent']} · "
                          + next(c.label for c in parent.candidates
                                 if c.candidate_id == ref["candidate_id"]),
                    selected=selected == ref)
    return None


def select(snapshot, identifier, ref):
    """Record an explicit return; no run, copied result or new suitability decision."""
    from diffeoforge.guided_strategy import _context

    offered = preview(snapshot, identifier, _context(snapshot)[0])
    if not offered or offered["reference"] != ref:
        raise ValueError("Choose the verified accepted fit offered for this form")
    if guided.record(snapshot)["phase"] != "joint":
        from diffeoforge.guided_feedback import select as select_local

        return select_local(snapshot.study_directory, identifier, ref)
    from diffeoforge.guided_feedback import reference

    study._append_event(snapshot.study_directory, "guided_joint_starting_fit_selected", dict(
        current=reference(snapshot, identifier, ref["target"]), reference=ref,
        anatomical_approval_created=False, optimizer_started=False))
    return study.load_reference_calibration_study(snapshot.study_directory)


def verify_selection(snapshot, identifier, event):
    """Joint-specific selection does not weaken ordinary same-form selection gates."""
    from diffeoforge.guided_feedback import reference, verify_reference

    ref = event["reference"]
    info = guided.record(snapshot)
    if (info["phase"] != "joint" or event["current"] != reference(
            snapshot, identifier, ref["target"])
            or snapshot.subject_decisions.get(identifier, {}).get(ref["target"])
            not in {"fail", "uncertain"}
            or event["anatomical_approval_created"] is not False
            or event["optimizer_started"] is not False):
        raise ValueError("Joint recovery no longer matches the reviewed failed form")
    parent = verify_reference(ref)
    approved = dict(ref)
    approved["filename"] = approved.pop("target")
    if (parent.plan.pilot_subject_count != 1
            or guided._approved_record(parent, ref["candidate_id"]) != approved
            or Path(guided.record(parent)["origin"]).resolve()
            != Path(info["origin"]).resolve()
            or ref["method"] != snapshot.attachment_comparison["methods"][identifier]):
        raise ValueError("Joint recovery requires the accepted same-form single fit")
    # Membership in the sealed history prevents an unrelated accepted fit from
    # being supplied through a forged UI payload, even within the same cohort.
    if not any(r["directory"] == ref["directory"]
               and r["manifest_sha256"] == ref["manifest_sha256"] for r in info["history"]):
        raise ValueError("The accepted fit is outside this pilot's saved history")
    return ref


def rejected_joint(snapshot, ref, *, proposed_references=None):
    """Do not spend another fit on an identical, already rejected joint setup."""
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.mesh import sha256_file

    source = verify_reference(ref)
    info = guided.record(snapshot)
    from diffeoforge.guided_joint_initialization import VERSION, references

    if proposed_references is None:
        from diffeoforge.guided_strategy import _compatible, _context

        rows = _compatible(snapshot, ref["method"], ref["values"], _context(snapshot)[0])
        row = dict(ref)
        row["filename"] = row.pop("target")
        rows = list({r["filename"]: r for r in [*rows, row]}.values())
        if {r["filename"] for r in rows} != set(info["pilot_order"]):
            return None
        proposed_references = references(rows)
    expected_controls = source.attachment_comparison["controls"]["sha256"]
    flags = snapshot.attachment_comparison["confirmation_freeze_settings"]
    for row in [None, *reversed(info["history"])]:
        root = Path(row["directory"]) if row else snapshot.study_directory
        if row and sha256_file(root / study.STUDY_MANIFEST) != row["manifest_sha256"]:
            raise ValueError("Saved joint-fit history changed")
        parent = study.load_reference_calibration_study(root) if row else snapshot
        record = parent.attachment_comparison
        initialization = record.get("joint_initialization") or {}
        if (guided.record(parent)["phase"] != "joint"
                or initialization.get("version") != VERSION
                or initialization.get("references") != proposed_references
                or record["controls"]["sha256"] != expected_controls
                or record["confirmation_freeze_settings"] != flags
                or parent.plan.effective_values != ref["values"]):
            continue
        if any(parent.visual_reviews.get(c.candidate_id) is False
               and record["methods"][c.candidate_id] == ref["method"]
               for c in parent.candidates if c.status == "completed"):
            return ("These unchanged settings, control basis and accepted starting fields "
                    "already failed the joint check. Inspect the failed joint form and choose "
                    "a different tested setup before another joint run. "
                    "Your accepted individual fits remain saved.")
    return None
