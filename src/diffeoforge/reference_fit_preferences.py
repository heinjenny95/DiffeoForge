"""Human relative fit preferences, separate from anatomical approval."""

from pathlib import Path

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import _canonical_hash

VERSION = "human-ranked-fit-v1"


def fit_record(snapshot, candidate_id):
    from diffeoforge.reference_sequential_fit import _basis, _values, sequence_info

    info = sequence_info(snapshot.study_directory)
    if not info or info["phase"] != "individual":
        raise ValueError("Relative feedback needs an individual specimen fit")
    candidate = next(c for c in snapshot.candidates if c.candidate_id == candidate_id)
    if (
        candidate.status != "completed"
        or not candidate.metrics
        or candidate.metrics.get("invalid_face_count") != 0
    ):
        raise ValueError("A starting point must be a completed geometrically valid fit")
    run = study.calibration_candidate_run_directory(candidate)
    root = Path(info["root"]).resolve()
    return dict(
        study=snapshot.study_directory.resolve().relative_to(root).as_posix(),
        candidate_id=candidate_id,
        index=info["index"],
        study_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        run_sha256=sha256_file(run / "manifest.json"),
        basis=_basis(_values(snapshot, candidate_id)),
    )


def verified_fit(root, state, record):
    from diffeoforge.reference_sequential_fit import _fallback_snapshot

    if record["study"] not in state.get("trials", []):
        raise ValueError("Compared fit is not a recorded attempt in this sequence")
    snapshot = _fallback_snapshot(root, state, record)
    if fit_record(snapshot, record["candidate_id"]) != record:
        raise ValueError("Compared fit evidence changed")
    return snapshot


def verify_preferences(root, state):
    for key, record in state.get("best_fits", {}).items():
        if str(record["index"]) != key or not 0 <= record["index"] < len(state["order"]):
            raise ValueError("Invalid best-fit specimen identity")
        verified_fit(root, state, record)
    previous = None
    selected = {}
    for index, event in enumerate(state.get("fit_preferences", [])):
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        if (
            event["sequence"] != index
            or event["previous_hash"] != previous
            or event["event_hash"] != _canonical_hash(payload)
        ):
            raise ValueError("Relative fit feedback history changed")
        previous = event["event_hash"]
        selected[str(event["best_after"]["index"])] = event["best_after"]
    if selected != state.get("best_fits", {}):
        raise ValueError("Best starting point differs from its relative feedback history")


def comparison_choices(directory):
    """Read immutable attempt descriptors off the GUI thread; never run a fit."""
    from diffeoforge.reference_sequential_fit import _read, sequence_info

    directory = Path(directory).resolve()
    info = sequence_info(directory)
    if not info or info["phase"] != "individual":
        raise ValueError("Choose an individual fit for relative comparison")
    root = Path(info["root"]).resolve()
    state = _read(root)
    if state["current"] != directory.relative_to(root).as_posix():
        raise ValueError("This checkpoint is no longer current")
    snapshot = study.load_reference_calibration_study(directory)
    current = next(c for c in snapshot.candidates if c.status == "completed")
    current_record = fit_record(snapshot, current.candidate_id)
    choices = []
    for relative in reversed(state.get("trials", [])):
        if relative == state["current"]:
            continue
        child = study._safe_study_path(root, relative)
        child_info = sequence_info(child)
        if (
            not child_info
            or child_info["phase"] != "individual"
            or child_info["index"] != info["index"]
        ):
            continue
        other = study.load_reference_calibration_study(child)
        for candidate in other.candidates:
            if (
                candidate.status == "completed"
                and candidate.metrics
                and candidate.metrics.get("invalid_face_count") == 0
            ):
                choices.append(fit_record(other, candidate.candidate_id))
    best = state.get("best_fits", {}).get(str(info["index"]))
    return dict(root=str(root), current=current_record, choices=choices, best=best)


def record_preference(root, state, snapshot, candidate_id, outcome, comparison):
    """Record a relative decision; never alter any anatomical review or run."""
    if outcome not in {"better", "worse", "same", "starting_point", "not_compared"}:
        raise ValueError("Unknown relative fit feedback")
    current = fit_record(snapshot, candidate_id)
    verified_fit(root, state, current)
    key = str(current["index"])
    best = state.get("best_fits", {}).get(key)
    reference = None
    if outcome == "not_compared":
        if (not isinstance(comparison, dict) or comparison.get("current") != current
                or comparison.get("best") != best or comparison.get("reference") is not None):
            raise ValueError("Independent inspection binding changed")
        selected = best or current
    elif outcome != "starting_point":
        if not isinstance(comparison, dict) or comparison.get("current") != current:
            raise ValueError("Displayed current fit changed; reopen the comparison")
        if comparison.get("best") != best:
            raise ValueError("Best starting point changed; reopen the comparison")
        reference = comparison.get("reference")
        if not reference or reference == current or reference["index"] != current["index"]:
            raise ValueError("Relative feedback must compare two attempts for the same specimen")
        verified_fit(root, state, reference)
        if best and reference != best:
            raise ValueError("Compare against the best starting point before guiding the next fit")
        selected = current if outcome == "better" else (best or reference)
    else:
        if best and best != current:
            raise ValueError("Use relative feedback to replace the saved best fit")
        if isinstance(comparison, dict) and (
            comparison.get("current") != current or comparison.get("best") != best
        ):
            raise ValueError("Displayed starting point changed; reopen the inspection")
        selected = current
    events = state.setdefault("fit_preferences", [])
    event = dict(
        version=VERSION,
        sequence=len(events),
        previous_hash=events[-1]["event_hash"] if events else None,
        outcome=outcome,
        current=current,
        reference=reference,
        best_before=best,
        best_after=selected,
        anatomical_approval=False,
    )
    event["event_hash"] = _canonical_hash(event)
    events.append(event)
    state.setdefault("best_fits", {})[key] = selected


def save_inspection_preference(directory, decision):
    """Persist the final inspection's ranking without launching or granting QC."""
    from diffeoforge.reference_sequential_fit import _read, _save, sequence_info

    directory = Path(directory).resolve()
    info = sequence_info(directory)
    if not info or info["phase"] != "individual":
        raise ValueError("Relative inspection needs an individual fit")
    root = Path(info["root"]).resolve()
    state = _read(root)
    if state["current"] != directory.relative_to(root).as_posix():
        raise ValueError("This fit is no longer current; reopen the inspection")
    outcome, candidate_id, comparison = decision
    if not isinstance(comparison, dict):
        raise ValueError("Inspection must bind its displayed comparison")
    snapshot = study.load_reference_calibration_study(directory)
    record_preference(root, state, snapshot, candidate_id, outcome, comparison)
    _save(root, state)
    return state["best_fits"][str(info["index"])]


def next_from_best(root, state, record):
    """Try bounded local changes, always initializing from the human-selected fit."""
    from diffeoforge.reference_progressive_fit import seed_request
    from diffeoforge.reference_sequential_fit import _values

    snapshot = verified_fit(root, state, record)
    center = _values(snapshot, record["candidate_id"])
    used = set()
    for relative in state.get("trials", []):
        manifest = study._verify_manifest(study._safe_study_path(root, relative))
        p = manifest.get("fit_search", {}).get("progressive") or {}
        if p.get("version") == VERSION and p.get("best_study_sha256") == record["study_sha256"]:
            used.add(p["proposal"])
    factors = [
        (2**-0.5, 1),
        (1, 2**-0.5),
        (2**0.5, 1),
        (1, 2**0.5),
        (0.5, 1),
        (1, 0.5),
        (2, 1),
        (1, 2),
        (2**-0.5, 2**-0.5),
        (2**0.5, 2**-0.5),
        (2**-0.5, 2**0.5),
        (2**0.5, 2**0.5),
    ]
    proposal = next((i for i in range(len(factors)) if i not in used), None)
    if proposal is None:
        raise ValueError(
            "Local changes around your best fit are exhausted. Your best is saved. "
            "Continue that fit or test a denser model with fresh QC."
        )
    attachment, noise = factors[proposal]
    values = dict(
        center,
        attachment_kernel_width=center["attachment_kernel_width"] * attachment,
        noise_std=center["noise_std"] * noise,
    )
    if not all(np.isfinite(v) and v > 0 for v in values.values()):
        raise ValueError("Invalid parameter neighborhood around the saved best fit")
    seed = seed_request(snapshot, record["candidate_id"], root, values)
    return dict(
        values=values,
        seed=seed,
        iterations=120,
        progressive=dict(
            version=VERSION,
            phase="guided",
            proposal=proposal,
            best_study=record["study"],
            best_study_sha256=record["study_sha256"],
        ),
    )
