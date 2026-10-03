"""Human checkpoints between fixed-template specimen fits, before joint fitting."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_fit_search as search
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import CalibrationCandidate, _canonical_hash

STATE = "specimen-sequence.json"
VERSION = "specimen-fit-checkpoints-v1"


def sequence_info(directory):
    """Small UI descriptor; the enclosing study load verifies its binding."""
    if not (Path(directory) / study.STUDY_MANIFEST).exists():
        return None
    manifest = study._read_json(Path(directory) / study.STUDY_MANIFEST, "study")
    return manifest.get("fit_search", {}).get("sequence")


def sequence_progress(directory):
    """Cheap persisted UI summary; action dispatch verifies all referenced runs."""
    info = sequence_info(directory)
    if not info:
        return None
    root = Path(info["root"])
    envelope = study._read_json(root / STATE, "specimen sequence")
    state = envelope["payload"]
    if envelope["sha256"] != _canonical_hash(state) or state["version"] != VERSION:
        raise ValueError("Specimen sequence checkpoint changed")
    if sha256_file(root / study.STUDY_MANIFEST) != info["root_sha256"]:
        raise ValueError("Specimen sequence source changed")
    count = len(state["approved"])
    return dict(
        approved=count,
        total=len(state["order"]),
        remaining=len(state["order"]) - count,
        fallback=state.get("fallbacks", {}).get(str(count)),
        fresh_review_required=_needs_fresh_review(root, state),
    )


def _needs_fresh_review(root, state):
    pending = state.get("restored_review")
    if not pending or pending["study"] != state["current"]:
        return False
    return (
        _review_fingerprint(root / state["current"], pending["candidate_id"])
        == pending["review_sha256"]
    )


def _review_fingerprint(child, candidate_id):
    series_root, _ = study._search_extension_series(child)
    events = study._load_events(child) + study._read_review_journal(series_root)
    return _canonical_hash(
        [
            event
            for event in events
            if event.get("event") == "candidate_visual_review"
            and event.get("candidate_id") == candidate_id
        ]
    )


def _fallback_snapshot(root, state, record):
    child = (root / record["study"]).resolve()
    if not child.is_relative_to(root.resolve()):
        raise ValueError("Plan B leaves its saved sequence")
    snapshot = study.load_reference_calibration_study(child)
    info = sequence_info(child)
    candidate = next(
        (c for c in snapshot.candidates if c.candidate_id == record["candidate_id"]), None
    )
    if (
        info["phase"] != "individual"
        or Path(info["root"]).resolve() != root.resolve()
        or info["index"] != record["index"]
        or info["filename"] != state["order"][record["index"]]
        or sha256_file(child / study.STUDY_MANIFEST) != record["study_sha256"]
        or candidate is None
        or candidate.status != "completed"
        or not np.isfinite(search.fit_key(candidate)[0])
        or sha256_file(study.calibration_candidate_run_directory(candidate) / "manifest.json")
        != record["run_sha256"]
        or _basis(_values(snapshot, candidate.candidate_id)) != record["basis"]
    ):
        raise ValueError("Saved Plan B identity or deformation basis changed")
    if (
        record["index"] == len(state["approved"])
        and state["values"] is not None
        and record["basis"] != _basis(state["values"])
    ):
        raise ValueError("Plan B belongs to a different common deformation model")
    return snapshot


def verify_sequence(directory, manifest):
    info = manifest["fit_search"]["sequence"]
    root = Path(info["root"]).resolve()
    if info.get("version") != VERSION or not directory.resolve().is_relative_to(root):
        raise ValueError("Invalid specimen sequence location/version")
    if sha256_file(root / study.STUDY_MANIFEST) != info["root_sha256"]:
        raise ValueError("Specimen sequence source changed")
    parent = study._verify_manifest(root)
    if Path(manifest["fit_search"]["budget_directory"]).resolve() != root:
        raise ValueError("Specimen sequence differs from its bound source")
    members = parent["inputs"]["subjects"]
    if info["total"] != len(members):
        raise ValueError("Specimen sequence count differs from its original pilot")
    expected = {r["filename"]: r["sha256"] for r in members}
    actual = {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]}
    if info["phase"] == "individual":
        if not 0 <= info["index"] < len(members) or actual != {
            info["filename"]: expected[info["filename"]]
        }:
            raise ValueError("Individual fit is not bound to exactly one pilot specimen")
    elif info["phase"] != "joint" or actual != expected:
        raise ValueError("Joint confirmation does not contain the complete pilot")


def _save(root, state):
    study._write_json(
        root / STATE, dict(payload=state, sha256=_canonical_hash(state)), overwrite=True
    )


def _read(root):
    envelope = study._read_json(root / STATE, "specimen sequence")
    state = envelope["payload"]
    if envelope["sha256"] != _canonical_hash(state) or state["version"] != VERSION:
        raise ValueError("Specimen sequence checkpoint changed")
    parent = study._verify_manifest(root)
    names = {r["filename"] for r in parent["inputs"]["subjects"]}
    if len(state["order"]) != len(names) or set(state["order"]) != names:
        raise ValueError("Specimen sequence lost or duplicated a pilot member")
    if not (root / state["current"]).resolve().is_relative_to(root):
        raise ValueError("Specimen sequence pointer leaves its project")
    for index, record in enumerate(state["approved"]):
        child = (root / record["study"]).resolve()
        if not child.is_relative_to(root) or index >= len(state["order"]):
            raise ValueError("Individual approval leaves its bound sequence")
        snapshot = study.load_reference_calibration_study(child)
        info = sequence_info(child)
        if (
            info["phase"] != "individual"
            or Path(info["root"]).resolve() != root.resolve()
            or info["index"] != index
            or info["filename"] != state["order"][index]
            or snapshot.visual_reviews.get(record["candidate_id"]) is not True
        ):
            raise ValueError("A recorded individual approval is missing or was withdrawn")
        candidate = next(c for c in snapshot.candidates if c.candidate_id == record["candidate_id"])
        if (
            candidate.status != "completed"
            or sha256_file(study.calibration_candidate_run_directory(candidate) / "manifest.json")
            != record["run_sha256"]
        ):
            raise ValueError("Approved individual run changed")
        if _basis(_values(snapshot, candidate.candidate_id)) != _basis(state["values"]):
            raise ValueError("Individual approvals use different deformation bases")
    for key, record in state.get("fallbacks", {}).items():
        if str(record["index"]) != key or not 0 <= record["index"] < len(state["order"]):
            raise ValueError("Invalid saved Plan B specimen")
        _fallback_snapshot(root, state, record)
    return state


def _fingerprint(plan):
    plan = replace(plan, fingerprint="")
    payload = plan.provenance
    for key in ("fingerprint", "status", "pilot_subject_count"):
        payload.pop(key)
    return replace(plan, fingerprint=_canonical_hash(payload))


def _values(snapshot, candidate_id):
    candidate = next(c for c in snapshot.current_stage.candidates if c.candidate_id == candidate_id)
    return {**snapshot.plan.effective_values, **candidate.values}


def _basis(values):
    # Matching weights may differ for initialization. The deformation metric,
    # fixed template and control basis must remain common to all approved fields.
    return {k: v for k, v in values.items() if k not in {"attachment_kernel_width", "noise_std"}}


def _next_attempt(root, state):
    """Retain the short common-basis probes, then recover progressively."""
    from diffeoforge import reference_progressive_fit as progressive
    from diffeoforge.reference_pca import ReferencePCAError

    parent = study.load_reference_calibration_study(root)
    index = len(state["approved"])
    observations = []
    for relative in state.get("trials", []):
        child = (root / relative).resolve()
        if not child.is_relative_to(root):
            raise ValueError("Recorded trial leaves its sequence")
        info = sequence_info(child)
        if info["phase"] != "individual" or info["index"] != index:
            continue
        snapshot = study.load_reference_calibration_study(child)
        manifest = study._verify_manifest(child)
        for candidate in snapshot.candidates:
            values = _values(snapshot, candidate.candidate_id)
            fits = (candidate.metrics or {}).get("original_surface_fit", {})
            observation = dict(
                values=values,
                progressive=manifest["fit_search"].get("progressive", {}),
                p95=max((f["p95"] for f in fits.values()), default=0),
                seed=None,
                key=search.fit_key(candidate),
            )
            observation["snapshot"] = snapshot
            observation["candidate_id"] = candidate.candidate_id
            observations.append(observation)
    recorded = [o for o in observations if o["progressive"]]
    if recorded:
        latest = recorded[-1]
        try:
            latest["seed"] = progressive.seed_request(
                latest["snapshot"], latest["candidate_id"], root, latest["values"]
            )
        except (ValueError, OSError, ReferencePCAError) as error:
            # Invalid fields start a separate cold branch, never propagate.
            latest["seed_failure"] = str(error)
    attempted = [o["values"] for o in observations]
    if index == 0 and state["values"] is None and not any(o["progressive"] for o in observations):
        for candidate in parent.current_stage.candidates:
            values = {**parent.plan.effective_values, **candidate.values}
            if values not in attempted:
                return dict(values=values)
    valid = [o for o in observations if np.isfinite(o["key"][0])]
    center = (
        state.setdefault("centers", {}).get(str(index))
        or state["values"]
        or (
            min(valid, key=lambda o: o["key"])["values"]
            if valid
            else {**parent.plan.effective_values, **parent.current_stage.candidates[0].values}
        )
    )
    state["centers"][str(index)] = center
    if not attempted:
        return dict(values=center)
    manifest = study._verify_manifest(root)
    diagonal = manifest["template_diagonal"]
    # The template extent is in the aligned working units of the complete cohort.
    return progressive.next_attempt(center, observations, diagonal)


def _next_parameters(root, state):
    return _next_attempt(root, state)["values"]


def _make_child(
    root,
    state,
    *,
    retry_iterations=None,
    joint_seed=None,
    trial_values=None,
    warm_seed=None,
    progressive=None,
):
    parent = study.load_reference_calibration_study(root)
    manifest = study._verify_manifest(root)
    index = len(state["approved"])
    joint = index == len(state["order"])
    number = state.get("creation_count", 0) + 1
    destination = root / (
        f"joint-{number:02d}" if joint else f"specimen-{index + 1:02d}-{number:02d}"
    )
    if destination.exists():
        # A failed/crashed preparation is retained, never overwritten.
        while destination.exists():
            number += 1
            destination = root / (
                f"joint-{number:02d}" if joint else f"specimen-{index + 1:02d}-{number:02d}"
            )
    plan = parent.plan
    if joint:
        plan = replace(plan, execution_scope="joint_fit_confirmation")
    if not joint:
        filename = state["order"][index]
        selected = tuple(s for s in plan.selected_pilot_subjects if s.filename == filename)
        declarations = tuple(d for d in plan.pilot_subject_declarations if d.filename == filename)
        plan = replace(
            plan,
            selected_pilot_subjects=selected,
            requested_pilot_subject_count=1,
            pilot_subject_declarations=declarations,
            required_subject_filenames=(filename,),
            version="0.5" if declarations else "0.3",
            execution_scope="single_specimen_probe",
        )
    attempt = {} if joint or trial_values else _next_attempt(root, state)
    values = state["values"] if joint else (trial_values or attempt["values"])
    warm_seed = warm_seed or attempt.get("seed")
    progressive = progressive or attempt.get("progressive")
    candidate = CalibrationCandidate(
        "fit-joint" if joint else "fit-specimen",
        "Joint original-target confirmation" if joint else "Fit current specimen",
        tuple(sorted(values.items())),
        "One attempt before human feedback; independent fields only initialize joint confirmation",
    )
    plan = replace(
        plan, stages=(replace(plan.stages[0], candidates=(candidate,)), *plan.stages[1:])
    )
    plan = _fingerprint(plan)
    config = copy.deepcopy(load_config(root / manifest["source_config"]["copy"]))
    cohort = manifest["inputs"]["full_cohort"]
    config["input"].update(
        directory=cohort["directory"],
        template=cohort["template"],
        subject_pattern=cohort["subject_pattern"],
    )
    config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"] = (
        plan.provenance
    )
    config_path = root / (destination.name + ".yaml")
    study._write_yaml(config_path, config, overwrite=False)
    info = dict(
        version=VERSION,
        root=str(root),
        root_sha256=sha256_file(root / study.STUDY_MANIFEST),
        phase="joint" if joint else "individual",
        index=index,
        total=len(state["order"]),
        filename=None if joint else state["order"][index],
        fit_phase=(progressive or {}).get("phase", "probe"),
    )
    search_settings = dict(
        sequence=info,
        confirmation_freeze_settings=manifest["fit_search"]["confirmation_freeze_settings"],
        confirmation_ids=["fit-joint"] if joint else [],
        joint_seed=joint_seed,
        warm_seed=warm_seed,
        progressive=progressive,
        iterations=200
        if joint
        else (retry_iterations or attempt.get("iterations") or (40 if index == 0 else 120)),
    )
    child = study.create_reference_calibration_study(
        config_path,
        destination,
        plan_override=plan,
        pilot_max_iterations=search_settings["iterations"],
        fit_search=search_settings,
    )
    state.update(current=destination.relative_to(root).as_posix(), creation_count=number)
    state.setdefault("trials", []).append(state["current"])
    _save(root, state)
    return child


def _joint_seed(root, state):
    """Use common-basis individual fields only as initialization of a new joint run."""
    from diffeoforge.reference_pca import load_reference_momenta
    from diffeoforge.reference_pca_deformations import _write_momenta

    parent = study._verify_manifest(root)
    controls = np.loadtxt(root / parent["fit_search"]["controls"]["copy"])
    fields = {}
    records = []
    for record in state["approved"]:
        child = study.load_reference_calibration_study(root / record["study"])
        candidate = next(c for c in child.candidates if c.candidate_id == record["candidate_id"])
        inputs = load_reference_momenta(
            study.calibration_candidate_run_directory(candidate), allow_singleton=True
        )
        child_manifest = study._verify_manifest(child.study_directory)
        config = inputs.run_report.manifest["effective_config"]
        if (
            inputs.subject_labels != (sequence_info(child.study_directory)["filename"],)
            or not config["optimization"]["freeze_template"]
            or not config["optimization"]["freeze_control_points"]
            or child_manifest["fit_search"]["controls"]["sha256"]
            != parent["fit_search"]["controls"]["sha256"]
            or inputs.control_points.shape != controls.shape
            # Deformetrica 4.3 serializes fixed controls with six decimal places.
            or not np.allclose(inputs.control_points, controls, rtol=0, atol=5.000001e-7)
        ):
            raise ValueError("Individual fields do not share the fixed template/control basis")
        fields[inputs.subject_labels[0]] = inputs.momenta[0]
        records.append(dict(record, momenta_sha256=sha256_file(inputs.momenta_path)))
    labels = sorted(state["order"], key=Path)
    values = np.stack([fields[n] for n in labels])
    destination = root / "joint-initialization"
    destination.mkdir(exist_ok=True)
    file = destination / "momenta.txt"
    if file.exists():
        from diffeoforge.reference_pca import read_deformetrica_momenta

        if not np.array_equal(read_deformetrica_momenta(file), values):
            raise ValueError("Existing joint initialization differs")
    else:
        _write_momenta(file, values)
    return dict(
        path=str(file),
        sha256=sha256_file(file),
        subject_labels=labels,
        individual_sources=records,
        purpose="Initialization only; shared-template outputs need new joint optimization and QC",
    )


def _run_specimen_sequence(
    runner,
    *,
    action=None,
    event_callback=None,
    center_values=None,
    control_target=200,
    working_source=None,
    first_filename=None,
):
    """Run only the current specimen; advancement requires its recorded human QC."""
    origin = runner.study_directory
    if event_callback:
        event_callback(
            dict(
                event="specimen_sequence_preparing",
                message="Checking saved fits and preparing the next attempt…",
            )
        )
    manifest = study._verify_manifest(runner.study_directory)
    info = manifest.get("fit_search", {}).get("sequence")
    if info:
        root = Path(info["root"])
        state = _read(root)
        snapshot = study.load_reference_calibration_study(root / state["current"])
        if snapshot.study_directory != runner.study_directory:
            if action:
                raise ValueError("This checkpoint is no longer current; reopen the saved sequence")
            runner.study_directory = snapshot.study_directory
    else:
        if action:
            raise ValueError("No individual checkpoint exists to advance")
        parent = search.create_search(
            runner.study_directory,
            center_values=center_values,
            control_target=control_target,
            working_source=working_source,
        )
        root = parent.study_directory
        ordered = sorted(
            parent.plan.selected_pilot_subjects,
            key=lambda s: (s.filename != first_filename, -s.descriptor_distance, s.selection_order),
        )
        state = dict(version=VERSION, order=[s.filename for s in ordered], approved=[], values=None)
        snapshot = _make_child(root, state)
        runner.study_directory = snapshot.study_directory
        study._write_json(
            origin / "fit-search-latest.json",
            dict(directory=str(root), manifest_sha256=sha256_file(root / study.STUDY_MANIFEST)),
            overwrite=True,
        )
    if action:
        kind, candidate_id, iterations = action
        info = sequence_info(snapshot.study_directory)
        if info["phase"] != "individual":
            raise ValueError("Joint confirmation follows the ordinary pilot review workflow")
        if kind == "restore":
            record = state.get("fallbacks", {}).get(str(len(state["approved"])))
            if record is None:
                raise ValueError("No Plan B is saved for this specimen")
            snapshot = _fallback_snapshot(root, state, record)
            state["current"] = record["study"]
            state["restored_review"] = dict(
                study=record["study"],
                candidate_id=record["candidate_id"],
                review_sha256=_review_fingerprint(snapshot.study_directory, record["candidate_id"]),
            )
            _save(root, state)
            runner.study_directory = snapshot.study_directory
            if event_callback:
                event_callback(dict(event="specimen_sequence_changed", snapshot=snapshot))
            return snapshot  # Explicit restoration never launches a fit or grants QC.
        candidate = next((c for c in snapshot.candidates if c.candidate_id == candidate_id), None)
        if candidate is None:
            raise ValueError("Choose a completed fit before continuing this specimen")
        values = _values(snapshot, candidate_id)
        if candidate.status != "completed" or (
            kind not in {"reject", "improve"} and not np.isfinite(search.fit_key(candidate)[0])
        ):
            raise ValueError("Only a completed geometrically valid individual fit can be used")
        if kind == "advance":
            if _needs_fresh_review(root, state):
                raise ValueError("Review and explicitly approve the restored Plan B first")
            if state["values"] is not None and _basis(values) != _basis(state["values"]):
                raise ValueError("Changing the common deformation basis requires a new sequence")
            if snapshot.visual_reviews.get(candidate_id) is not True:
                raise ValueError("Approve this specimen visually before fitting the next")
            if state["values"] is None:
                state["values"] = values
            state["approved"].append(
                dict(
                    study=snapshot.study_directory.relative_to(root).as_posix(),
                    candidate_id=candidate_id,
                    run_sha256=sha256_file(
                        study.calibration_candidate_run_directory(candidate) / "manifest.json"
                    ),
                )
            )
            seed = (
                _joint_seed(root, state) if len(state["approved"]) == len(state["order"]) else None
            )
            snapshot = _make_child(root, state, joint_seed=seed)
        elif kind == "maybe":
            if not np.isfinite(search.fit_key(candidate)[0]):
                raise ValueError("Only a geometrically valid completed fit can be kept as Plan B")
            state.setdefault("fallbacks", {})[str(info["index"])] = dict(
                study=snapshot.study_directory.relative_to(root).as_posix(),
                candidate_id=candidate_id,
                index=info["index"],
                study_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
                run_sha256=sha256_file(
                    study.calibration_candidate_run_directory(candidate) / "manifest.json"
                ),
                basis=_basis(values),
            )
            _save(root, state)  # Keep the fallback even if preparing the next fit fails.
            snapshot = _make_child(root, state)
        elif kind == "reject":
            if snapshot.visual_reviews.get(candidate_id) is not False:
                raise ValueError("Record the rejected fit before trying the next parameters")
            snapshot = _make_child(root, state)
        elif kind == "improve":
            snapshot = _make_child(root, state)
        elif kind == "retry":
            if type(iterations) is not int or not 1 <= iterations <= 20_000:
                raise ValueError("Invalid longer-fit iteration budget")
            from diffeoforge.reference_progressive_fit import seed_request

            seed = seed_request(snapshot, candidate_id, root, values)
            from diffeoforge.reference_progressive_fit import VERSION as PROGRESSIVE_VERSION

            prior = (
                study._verify_manifest(snapshot.study_directory)["fit_search"].get("progressive")
                or {}
            )
            if state["values"] is None:
                state.setdefault("centers", {})[str(info["index"])] = values
            snapshot = _make_child(
                root,
                state,
                retry_iterations=iterations,
                trial_values=values,
                warm_seed=seed,
                progressive=dict(
                    version=PROGRESSIVE_VERSION,
                    phase="continue",
                    branch=prior.get("branch", 0),
                    step=prior.get("step", 0),
                ),
            )
        else:
            raise ValueError("Unknown individual checkpoint action")
        runner.study_directory = snapshot.study_directory
    if event_callback:
        event_callback(dict(event="specimen_sequence_changed", snapshot=snapshot))
    result = search.run_fit_search(
        runner,
        event_callback=event_callback,
        single_stage=True,
    )
    if event_callback:
        event_callback(
            dict(
                event="specimen_sequence_paused",
                snapshot=result,
                sequence=sequence_info(result.study_directory),
            )
        )
    return result


def _dispatch_sequence(runner, *, action=None, event_callback=None):
    info = sequence_info(runner.study_directory)
    if action and action[0] == "denser":
        if not info or info["phase"] != "individual":
            raise ValueError("Select an individual fit before testing a denser common model")
        root = Path(info["root"])
        state = _read(root)
        if (root / state["current"]).resolve() != runner.study_directory.resolve():
            raise ValueError("Reopen the current saved checkpoint before changing the model")
        manifest = study._verify_manifest(root)
        target = min(1000, max(600, manifest["fit_search"]["controls"]["count"] * 3))
        from diffeoforge.surface_io import load_surface_mesh

        template = load_surface_mesh(root / manifest["inputs"]["template"]["copy"])
        grid, _ = search.control_grid(template.metadata.bounds, target)
        if len(grid) <= manifest["fit_search"]["controls"]["count"]:
            raise ValueError(
                "The supported denser-grid limit is reached. Saved searches "
                "and fit continuation remain available."
            )
        runner.study_directory = root
        # This is a new common basis: never carry approvals or fields across it.
        return _run_specimen_sequence(
            runner,
            event_callback=event_callback,
            center_values=state["values"],
            control_target=target,
            working_source=dict(
                directory=str(root), sha256=sha256_file(root / study.STUDY_MANIFEST)
            ),
            first_filename=info["filename"],
        )
    if action and action[0] == "restart":
        if not info:
            raise ValueError("No earlier sequence exists to restart")
        snapshot = study.load_reference_calibration_study(runner.study_directory)
        candidate_id = action[1]
        if not candidate_id:
            available = [
                c
                for c in snapshot.candidates
                if c.status == "completed" and np.isfinite(search.fit_key(c)[0])
            ]
            if available:
                candidate_id = min(available, key=search.fit_key).candidate_id
        center = _values(snapshot, candidate_id) if candidate_id else None
        runner.study_directory = Path(info["root"])
        return _run_specimen_sequence(runner, event_callback=event_callback, center_values=center)
    if not info:
        return _run_specimen_sequence(runner, action=action, event_callback=event_callback)
    return _run_specimen_sequence(runner, action=action, event_callback=event_callback)


def run_specimen_sequence(runner, *, action=None, event_callback=None):
    info = sequence_info(runner.study_directory)
    if not info:
        return _dispatch_sequence(runner, action=action, event_callback=event_callback)
    lock = Path(info["root"]) / "specimen-sequence-active.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError(
            "This specimen sequence is already running or needs crash recovery"
        ) from error
    try:
        return _dispatch_sequence(runner, action=action, event_callback=event_callback)
    finally:
        lock.rmdir()


def resume_directory(directory, _seen=None):
    """Follow only content-bound saved pointers; never launch a computation."""
    directory = Path(directory).resolve()
    seen = set() if _seen is None else _seen
    if directory in seen:
        raise ValueError("Saved fit-search pointers form a cycle")
    seen.add(directory)
    pointer = directory / "fit-search-latest.json"
    if pointer.exists():
        record = study._read_json(pointer, "latest fit search")
        root = Path(record["directory"]).resolve()
        if (
            not root.is_relative_to(directory.parent)
            or sha256_file(root / study.STUDY_MANIFEST) != record["manifest_sha256"]
        ):
            raise ValueError("Saved fit-search pointer changed")
        if (root / "fit-search-latest.json").exists():
            return resume_directory(root, seen)
    else:
        info = sequence_info(directory)
        if info and info["phase"] == "joint":
            return directory
        root = Path(info["root"]) if info else directory
    if not (root / STATE).exists():
        return directory
    state = _read(root)
    current = root / state["current"]
    if sequence_info(current)["phase"] == "joint":
        return study.latest_reference_calibration_search_extension_directory(current)
    return current


def _cohort_identity(manifest):
    return (
        manifest["inputs"]["template"]["sha256"],
        sorted((r["filename"], r["sha256"]) for r in manifest["inputs"]["subjects"]),
    )


def current_sequence_directory(directory):
    """UI-only resume of the chosen series; historical study reads stay explicit."""
    info = sequence_info(directory)
    if not info:
        return Path(directory)
    root = Path(info["root"]).resolve()
    envelope = study._read_json(root / STATE, "specimen sequence")
    state = envelope["payload"]
    if (envelope["sha256"] != _canonical_hash(state) or state["version"] != VERSION
            or sha256_file(root / study.STUDY_MANIFEST) != info["root_sha256"]):
        raise ValueError("Saved sequence binding changed")
    selected = study._safe_study_path(root, state["current"])
    child_info = sequence_info(selected)
    if (not child_info or Path(child_info["root"]).resolve() != root
            or child_info["root_sha256"] != info["root_sha256"]):
        raise ValueError("Saved checkpoint belongs to another sequence")
    return study.latest_reference_calibration_search_extension_directory(selected)


def saved_sequences(directory):
    """Cheap descriptors for the chooser; full evidence is checked on selection."""
    info = sequence_info(directory)
    current_root = Path(info["root"]) if info else Path(directory)
    current = study._read_json(current_root / study.STUDY_MANIFEST, "study")
    result = []
    for root in current_root.parent.glob("reference-fit-search-*"):
        if not root.is_dir() or not (root / STATE).exists():
            continue
        try:
            manifest = study._read_json(root / study.STUDY_MANIFEST, "study")
            envelope = study._read_json(root / STATE, "sequence")
            state = envelope["payload"]
            if envelope["sha256"] != _canonical_hash(state) or _cohort_identity(
                manifest
            ) != _cohort_identity(current):
                continue
            selected = root / state["current"]
            selected = study.latest_reference_calibration_search_extension_directory(selected)
            child = study._read_json(selected / study.STUDY_MANIFEST, "saved checkpoint")
            events = study._load_events(selected)
            selections = study._selected_state(events)[1]
            order = min(len(selections) + 1, 4)
            phase = child.get("fit_search", {}).get("sequence", {}).get("phase", "joint")
            stage_id = child["plan"]["stages"][order - 1]["stage_id"]
            reviews = {
                e["candidate_id"]: e.get("approved")
                for e in (*events, *study._read_review_journal(
                    study._search_extension_series(selected)[0]
                )) if e["event"] == "candidate_visual_review" and e.get("stage_id") == stage_id
            }
            retained = any(e["event"] == "stage_retained" and e.get("stage_id") == stage_id
                           for e in events)
            joint_status = (
                "complete" if any(e["event"] == "study_completed" for e in events)
                else "approved option available" if True in reviews.values()
                else "prior approved fit available" if retained
                else "reviewed options rejected" if reviews
                else "not yet reviewed"
            )
            modified = max((root / STATE).stat().st_mtime,
                           (selected / study.STUDY_EVENTS).stat().st_mtime)
            result.append(
                dict(
                    directory=str(root),
                    approved=len(state["approved"]),
                    total=len(state["order"]),
                    current=state["current"],
                    current_directory=str(selected), stage=order, phase=phase,
                    joint_status=joint_status, modified=modified,
                    is_current=root.resolve() == current_root.resolve(),
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda r: (-r["modified"], r["directory"]))


def saved_sequence_label(row):
    """Compact labels separate individual approvals from the current joint attempt."""
    from datetime import datetime

    saved = datetime.fromtimestamp(row["modified"]).strftime("%Y-%m-%d %H:%M")
    phase = (f"joint stage {row['stage']}: {row['joint_status']}"
             if row["phase"] == "joint" else "individual fitting")
    return (
        f"{saved} · {row['approved']}/{row['total']} individual approved · {phase} · "
        f"{Path(row['directory']).name[-6:]}" + (" · current" if row["is_current"] else "")
    )


def restore_saved_sequence(directory, selected_root):
    """Explicit selection ignores forward restart pointers; no calculations or writes."""
    info = sequence_info(directory)
    current_root = Path(info["root"]) if info else Path(directory)
    root = Path(selected_root).resolve()
    if root.parent != current_root.resolve().parent:
        raise ValueError("Saved sequence is outside this project's calibration folder")
    if _cohort_identity(study._verify_manifest(root)) != _cohort_identity(
        study._verify_manifest(current_root)
    ):
        raise ValueError("Saved sequence uses different original inputs")
    state = _read(root)
    selected = root / state["current"]
    if sequence_info(selected)["phase"] == "joint":
        selected = study.latest_reference_calibration_search_extension_directory(selected)
    return study.load_reference_calibration_study(selected)
