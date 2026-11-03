"""One explicit finite hypothesis after a stalled common-model comparison."""

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def trials(snapshot, target, value):
    from diffeoforge.pilot_multiscale_study import marker

    result, seen = [], set()
    for entry in [*guided.record(snapshot)["history"], None]:
        parent = snapshot
        if entry:
            root = Path(entry["directory"])
            if sha256_file(root / study.STUDY_MANIFEST) != entry["manifest_sha256"]:
                raise ValueError("Common capture/detail history changed")
            parent = study.load_reference_calibration_study(root)
        if parent.study_directory in seen:
            continue
        seen.add(parent.study_directory)
        declaration = marker(parent.attachment_comparison)
        if (
            declaration
            and declaration["target"] == target
            and declaration["accepted_marker"]["reviews"] == value["reviews"]
        ):
            result.append(parent)
    return result


def choice(snapshot, value, target, previous):
    from diffeoforge.guided_feedback import inspected, reference
    from diffeoforge.pilot_multiscale_study import adopted_family, marker

    diagnosis = (previous or {}).get("diagnosis") or {}
    eligible = (
        previous
        and previous["mode"] == "stalled"
        and diagnosis.get("gap")
        and not diagnosis.get("warnings")
    )
    info = guided.record(snapshot)
    has_family = marker(snapshot.attachment_comparison) or any(
        entry.get("outcome", "").startswith("common_multiscale") for entry in info["history"]
    )
    if not has_family and not eligible:
        return previous
    found = trials(snapshot, target, value) if has_family else []
    model = adopted_family(value)
    if found:
        parent = found[-1]
        declaration = marker(parent.attachment_comparison)
        candidate = parent.candidates[0]
        if candidate.status != "completed":
            return dict(
                mode="prepared",
                available=False,
                target=target,
                label="Complete the prepared capture/detail test · " + target,
                reason="Use its Run/check controls. No duplicate test is prepared; "
                "your accepted individual shapes remain saved.",
            )
        if declaration["stage"] != "detail":
            from diffeoforge.pilot_multiscale_study import _capture_field

            try:
                _capture_field(parent)
            except ValueError:
                pass
            else:
                return dict(
                    mode="detail_pending",
                    available=True,
                    target=target,
                    label="Prepare the declared detail stage · " + target,
                    reason="The checked capture is saved. Prepare its second and final "
                    "stage from the complete same-form field. Fitting starts only "
                    "with Run; the capture is not repeated.",
                )
            return dict(
                mode="stalled",
                available=False,
                target=target,
                label="Inspect capture checks · " + target,
                reason="This capture has no qualified detail result. Inspect its checks; "
                "no recovery, repeated capture or additional iterations are automatic.",
            )
        try:
            ref = reference(parent, candidate.candidate_id)
        except ValueError:
            return dict(
                mode="stalled",
                available=False,
                target=target,
                label="Inspect failed detail checks · " + target,
                reason="Keep your accepted shapes. This detail result did not pass its "
                "completion checks and is not repeated automatically.",
            )
        base = dict(
            target=target,
            reference=ref,
            review_reference=ref,
            test_number=guided.record(parent)["screen_trials_spent"],
        )
        if not inspected(parent, candidate.candidate_id) or candidate.candidate_id not in (
            parent.visual_reviews
        ):
            return dict(
                base,
                mode="review",
                available=True,
                label="Review completed broad/detail common fit · " + target,
                reason="Review this detail result against your accepted individual fit. "
                "Both stages are saved; suitability and adoption remain your decisions.",
            )
        if parent.visual_reviews[candidate.candidate_id] is True:
            return dict(
                base,
                mode="approved" if model else "adopt",
                available=False,
                label=(
                    "Common fit approved · "
                    if model
                    else "Use approved broad/detail settings → next form · "
                )
                + target,
                reason="Your review is saved. Continue to the next missing common check "
                "using the approved model; no identical repeat is needed.",
            )
        return dict(
            base,
            mode="stalled",
            available=False,
            label="Compare this completed detail result · " + target,
            reason="This bounded two-stage hypothesis remains unsuitable. Keep the accepted "
            "individual fit and review the remaining mismatch. More unchanged "
            "iterations or a fresh copy of the same experiment are not proposed.",
        )
    if model or eligible:
        if len(value["reviews"]) != len(info["pilot_order"]):
            return previous
        return dict(
            mode="broad_detail",
            available=True,
            target=target,
            label="Prepare broad/detail common test · 2,000 CP · " + target,
            reason="One explicit two-stage hypothesis: capture the whole form, then match "
            "detail on the same original template and 2,000 control sites. Up to "
            "120 native iterations per stage, fresh optimizer history, no timed "
            "review pauses or automatic recovery. Checks follow each stage. "
            "Your accepted individual fits and all previous decisions stay saved.",
            model_family=str(model.study_directory) if model else None,
        )
    return previous
