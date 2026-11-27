"""Adopt a finer evaluation of a saved field, without claiming a new fit.

The original optimizer evidence and reviews stay immutable. Only the missing
nested grid is shot; the evaluated endpoints get a distinct candidate and QC.
"""

from __future__ import annotations

import copy
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config, validate_schema
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.mesh_quality import assess_triangle_mesh
from diffeoforge.reference_calibration import CalibrationCandidate
from diffeoforge.reference_fixed_shooting import movement, shoot

VERSION = "fixed-state-resolution-adoption-v1"
KEY = "fixed_state_resolution"


def records(events):
    return tuple(e for e in events if e["event"] == "candidate_completed" and KEY in e)


def superseded_checks(events):
    """An explicit alternative may retire a declared check that never started."""
    result = set()
    for event in events:
        if event["event"] != "pilot_check_superseded":
            continue
        declaration = next(e for e in events if e["event_hash"] == event["declaration_event_hash"])
        identifier = event["candidate_id"]
        if (
            declaration["event"] != "pilot_qualification_declared"
            or declaration["candidate"]["candidate_id"] != identifier
            or declaration["sequence"] >= event["sequence"]
            or event["version"] != VERSION
            or identifier in result
            or any(
                e.get("candidate_id") == identifier
                and e["event"]
                in {
                    "candidate_started",
                    "candidate_completed",
                    "pilot_qualification_finished",
                    "pilot_refinement_finished",
                }
                for e in events
            )
        ):
            raise ValueError("Only an unstarted declared pilot check can be superseded")
        result.add(identifier)
    return result


def _supersede_pending(root, source_id, replacement):
    events = study._load_events(root)
    ignored = superseded_checks(events)
    for declaration in events:
        if declaration["event"] != "pilot_qualification_declared":
            continue
        identifier = declaration["candidate"]["candidate_id"]
        if identifier in ignored or any(
            e.get("candidate_id") == identifier
            and e["event"]
            in {
                "pilot_qualification_finished",
                "pilot_refinement_finished",
            }
            for e in events
        ):
            continue
        if declaration["source"]["candidate_id"] != source_id or any(
            e["event"] == "candidate_started" and e.get("candidate_id") == identifier
            for e in events
        ):
            raise ValueError(
                "A started or different saved check needs an explicit separate decision"
            )
        study._append_event(
            root,
            "pilot_check_superseded",
            dict(
                version=VERSION,
                stage_id=declaration["stage_id"],
                candidate_id=identifier,
                declaration_event_hash=declaration["event_hash"],
                replacement=replacement,
                reason="Researcher chose finer saved evaluation "
                "without the queued optimizer refit.",
            ),
        )


def overlay_plan(plan, events):
    superseded_checks(events)
    for event in records(events):
        row = event[KEY]["candidate"]
        stage = plan.stages[-1]
        if (
            stage.order != 4
            or event["stage_id"] != stage.stage_id
            or any(c.candidate_id == row["candidate_id"] for c in stage.candidates)
        ):
            raise ValueError("Invalid resolution adoption identity")
        candidate = CalibrationCandidate(
            row["candidate_id"],
            row["label"],
            tuple(sorted(row["parameter_values"].items())),
            row["rationale"],
        )
        plan = replace(
            plan,
            stages=(
                *plan.stages[:-1],
                replace(
                    stage,
                    candidates=(*stage.candidates, candidate),
                ),
            ),
        )
    if records(events):
        payload = plan.provenance
        for key in ("fingerprint", "status", "pilot_subject_count"):
            payload.pop(key)
        plan = replace(plan, fingerprint=study._canonical_hash(payload))
    return plan


def _configuration(source, seed, root, folder, count):
    from diffeoforge.reference_adaptive_calibration import apply_seed

    config = copy.deepcopy(load_config(source.config_path))
    config["input"]["directory"] = str(
        (source.config_path.parent / config["input"]["directory"]).resolve()
    )
    apply_seed(config, root=root, candidate_directory=folder, seed=seed, initialization="warm")
    config["model"]["deformation"]["timepoints"] = count
    validate_schema(config)
    return config


def _grid(root, receipt, labels, count):
    """Resolve exact, hash-bound runtime grid receipts, never a filename guess."""
    paths = {}
    for index, label in enumerate(labels):
        prefix = "Shooting" if len(labels) == 1 else f"Shooting_{index}"
        suffix = f"/{count}/output/{prefix}__grid.json"
        matches = [p for p in receipt["artifacts"] if p.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("Saved grid identity is absent or ambiguous")
        relative = matches[0]
        grid = study._safe_study_path(root, relative)
        endpoint = grid.with_name(prefix + "__endpoint.vtk")
        endpoint_relative = study._relative_path(root, endpoint)
        if (
            sha256_file(grid) != receipt["artifacts"][relative]
            or endpoint_relative not in receipt["artifacts"]
            or sha256_file(endpoint) != receipt["artifacts"][endpoint_relative]
            or study._read_json(grid, "saved grid")
            != dict(
                root=prefix,
                timepoints=count,
                tmin=0,
                tmax=1,
            )
        ):
            raise ValueError("Saved grid or endpoint changed")
        paths[label] = endpoint
    return paths


def available(snapshot, identifier, *, checked=None):
    """Offer adoption only when the already checked finer pair passes for everyone."""
    from diffeoforge import reference_pilot_completion as completion

    if not snapshot.current_stage or snapshot.current_stage.order != 4:
        return None
    source = next((c for c in snapshot.candidates if c.candidate_id == identifier), None)
    checked = completion.evidence(snapshot) if checked is None else checked
    record = checked.get(identifier)
    if (
        not source
        or not record
        or not completion._valid(source, snapshot)
        or not (completion.capped(source) or (source.metrics or {}).get("converged") is True)
    ):
        return None
    if snapshot.visual_reviews.get(identifier) is False:
        return None
    n = int(load_config(source.config_path)["model"]["deformation"]["timepoints"])
    finer, highest = 2 * n - 1, 4 * n - 3
    receipt = record["receipt"]
    rows = receipt["integration"].get(f"{finer}->{highest}")
    names = {s.filename for s in snapshot.plan.selected_pilot_subjects}
    if receipt.get("valid_geometry") is not True or not rows or set(rows) != names:
        return None
    # The original endpoint reproduction must also have passed.
    if any(r.startswith("roundtrip") for r in completion.integration_failures(receipt)):
        return None
    for row in rows.values():
        for key in ("rms", "p95", "maximum"):
            value = row[key]
            if isinstance(value, bool) or not np.isfinite(value) or value < 0:
                return None
            if value > completion.CRITERIA["integration_" + key]:
                return None
    return finer


def _source(root, declaration, events):
    from diffeoforge.reference_stage_retention import _candidate

    source, completed = _candidate(
        root,
        declaration["stage_id"],
        declaration["source_id"],
        events=tuple(e for e in events if e["sequence"] < declaration["sequence"]),
    )
    if (
        completed["sequence"] >= declaration["sequence"]
        or completed["event_hash"] != declaration["source_completed_hash"]
        or study._candidate_review_binding(source) != declaration["source_binding"]
    ):
        raise ValueError("Resolution adoption source changed")
    receipt_path = study._safe_study_path(root, declaration["source_receipt"])
    if not any(
        e["sequence"] < declaration["sequence"]
        and e["event"] in {"pilot_qualification_finished", "pilot_integration_check_finished"}
        and e.get("candidate_id") == source.candidate_id
        and e.get("receipt") == declaration["source_receipt"]
        and e.get("receipt_sha256") == declaration["source_receipt_sha256"]
        for e in events
    ):
        raise ValueError("Resolution adoption source receipt is not recorded for this field")
    if sha256_file(receipt_path) != declaration["source_receipt_sha256"]:
        raise ValueError("Resolution adoption source receipt changed")
    receipt = study._read_json(receipt_path, "source integration receipt")
    if receipt["checkpoint_binding"] != declaration["source_binding"]:
        raise ValueError("Resolution adoption field differs from its checked field")
    for relative, digest in receipt["artifacts"].items():
        if sha256_file(study._safe_study_path(root, relative)) != digest:
            raise ValueError("Resolution adoption source artifact changed")
    return source, receipt


def verify(root, event, events):
    # Scope reuse to one verified study read. A later read rechecks every byte.
    cache = getattr(study._LOAD_CONTEXT, "resolution_checks", None)
    key = root, event["event_hash"]
    if cache is not None and key in cache:
        return cache[key]
    value = _verify(root, event, events)
    if cache is not None:
        cache[key] = value
    return value


def _verify(root, event, events):
    """Reopening checks provenance and bytes, without re-running any Shooting."""
    from diffeoforge import reference_pilot_completion as completion

    record = event[KEY]
    declaration = next(e for e in events if e["event_hash"] == record["declaration_event_hash"])
    if (
        declaration["event"] != "resolution_evaluation_declared"
        or declaration["version"] != VERSION
        or record["version"] != VERSION
        or declaration["sequence"] >= event["sequence"]
        or declaration["candidate_id"] != event["candidate_id"]
        or event["candidate_id"] != record["candidate"]["candidate_id"]
        or event["stage_id"] != declaration["stage_id"]
        or declaration["criteria"] != completion.CRITERIA
    ):
        raise ValueError("Resolution adoption declaration changed")
    source, original = _source(root, declaration, events)
    if not (completion.capped(source) or (source.metrics or {}).get("converged") is True):
        raise ValueError("Resolution adoption cannot hide an unknown optimizer stop")
    n = int(load_config(source.config_path)["model"]["deformation"]["timepoints"])
    count = 2 * n - 1
    if declaration["counts"] != [count, 2 * count - 1, 4 * count - 3]:
        raise ValueError("Resolution adoption nested grids changed")
    expected_labels = sorted(
        (r["filename"] for r in study._verify_manifest(root)["inputs"]["subjects"]),
        key=Path,
    )
    expected_names = set(expected_labels)
    pair = original["integration"][f"{count}->{2 * count - 1}"]
    if set(pair) != expected_names or any(
        row[key] > completion.CRITERIA["integration_" + key]
        for row in pair.values()
        for key in ("rms", "p95", "maximum")
    ):
        raise ValueError("Previously checked finer grid is not adequate for the complete cohort")
    for bound in record["seed"]["files"].values():
        if sha256_file(study._safe_study_path(root, bound["copy"])) != bound["sha256"]:
            raise ValueError("Resolution adoption learned field changed")
        original_hashes = {
            digest
            for path, digest in original["artifacts"].items()
            if Path(path).parent.name == "adaptive-seed"
            and Path(path).name == Path(bound["copy"]).name
        }
        if original_hashes != {bound["sha256"]}:
            raise ValueError("Resolution adoption differs from the checked learned field")
    seed = record["seed"]
    if (
        Path(seed["source_run_directory"]) != study.calibration_candidate_run_directory(source)
        or seed["source_manifest_sha256"] != declaration["source_binding"]["run_manifest_sha256"]
        or seed["candidate_id"] != source.candidate_id
        or seed["subject_labels"] != expected_labels
    ):
        raise ValueError("Resolution adoption native source changed")
    config = study._safe_study_path(root, record["config"])
    if load_config(config) != _configuration(source, seed, root, config.parent, count):
        raise ValueError("Resolution adoption configuration changed")
    if sha256_file(config) != record["config_sha256"] or record["candidate"][
        "parameter_values"
    ] != {
        "timepoints": float(count),
    }:
        raise ValueError("Resolution adoption time resolution changed")
    run = study._safe_study_path(root, event["run_directory"])
    receipt_path = study._safe_study_path(root, record["receipt"])
    if sha256_file(receipt_path) != record["receipt_sha256"]:
        raise ValueError("Resolution adoption receipt changed")
    receipt = study._read_json(receipt_path, "resolution adoption receipt")
    candidate = study.CalibrationStudyCandidateState(
        event["candidate_id"],
        record["candidate"]["label"],
        "completed",
        config,
        run,
        event["metrics"],
        None,
        0,
    )
    if (
        receipt["version"] != VERSION
        or receipt["declaration_event_hash"] != declaration["event_hash"]
        or receipt["criteria"] != completion.CRITERIA
        or receipt["checkpoint_binding"] != study._candidate_review_binding(candidate)
        or set(receipt["roundtrip"]) != expected_names
        or set(receipt["integration"])
        != {f"{count}->{2 * count - 1}", f"{2 * count - 1}->{4 * count - 3}"}
        or any(set(rows) != expected_names for rows in receipt["integration"].values())
        or receipt["valid_geometry"]
        != (
            candidate.metrics["invalid_face_count"] == 0
            and candidate.metrics["subject_reconstruction_count"] == len(expected_names)
        )
        or receipt["integration_pass"] != (not completion.integration_failures(receipt))
        or candidate.metrics.get("converged") is not False
        or candidate.metrics.get("optimizer_stop_signal") != "not_run_fixed_state_evaluation"
        or candidate.metrics.get("final_iteration") is not None
        or candidate.metrics.get("source_optimizer") != source.metrics
    ):
        raise ValueError("Resolution adoption evidence or optimizer meaning changed")
    for relative, digest in receipt["artifacts"].items():
        if sha256_file(study._safe_study_path(root, relative)) != digest:
            raise ValueError("Resolution adoption artifact changed")
    return source, receipt


def source_run(root, candidate):
    """Resolve the actual optimizer run for seed extraction; never fake its grid."""
    events = study._load_events(root)
    event = next(e for e in records(events) if e["candidate_id"] == candidate.candidate_id)
    source, _ = verify(root, event, events)
    return study.calibration_candidate_run_directory(source)


def inventory(root, candidate):
    events = study._load_events(root)
    event = next(e for e in records(events) if e["candidate_id"] == candidate.candidate_id)
    verify(root, event, events)
    return study._read_json(
        candidate.run_directory / "output-inventory.json", "evaluation inventory"
    )["files"]


def run(runner, *, candidate_id, event_callback=None):
    from diffeoforge import reference_pilot_completion as completion
    from diffeoforge.reference_adaptive_calibration import bind_learned_seed
    from diffeoforge.reference_stage_retention import _candidate

    snapshot = study.load_reference_calibration_study(runner.study_directory)
    root = snapshot.study_directory
    checked = completion.evidence(snapshot)
    count = available(snapshot, candidate_id, checked=checked)
    if count is None:
        raise ValueError("The complete-cohort finer grid must already pass before adopting it")
    # A repeated explicit action reuses the immutable completed evaluation.
    for event in records(study._load_events(root)):
        declaration = next(
            e
            for e in study._load_events(root)
            if e["event_hash"] == event[KEY]["declaration_event_hash"]
        )
        if declaration["source_id"] == candidate_id:
            return snapshot
    source, completed = _candidate(root, snapshot.current_stage.stage_id, candidate_id)
    folder = root / "resolution-adoptions" / uuid4().hex
    identifier = "resolution-" + folder.name
    _supersede_pending(root, candidate_id, identifier)
    seed = bind_learned_seed(snapshot, candidate_id, folder)
    labels = seed["subject_labels"]
    original = checked[candidate_id]
    grids = {n: _grid(root, original["receipt"], labels, n) for n in (count, 2 * count - 1)}
    for bound in seed["files"].values():
        bound["copy"] = study._relative_path(root, folder / bound["copy"])
    declaration = study._append_event(
        root,
        "resolution_evaluation_declared",
        dict(
            version=VERSION,
            stage_id=snapshot.current_stage.stage_id,
            candidate_id=identifier,
            source_id=candidate_id,
            source_completed_hash=completed["event_hash"],
            source_binding=study._candidate_review_binding(source),
            source_receipt=original["receipt_path"],
            source_receipt_sha256=original["receipt_sha256"],
            counts=[count, 2 * count - 1, 4 * count - 3],
            criteria=dict(completion.CRITERIA),
        ),
    )
    started = time.monotonic()
    try:
        grids[4 * count - 3], _ = shoot(
            load_config(source.config_path),
            root,
            seed,
            folder / str(4 * count - 3),
            4 * count - 3,
            cancelled=lambda: runner._cancel_requested,
            event_callback=event_callback,
        )
        if runner._cancel_requested:
            raise InterruptedError("Resolution evaluation cancelled; original fit retained")
        config = _configuration(source, seed, root, folder, count)
        config_path = folder / "atlas.yaml"
        study._write_yaml(config_path, config, overwrite=False)
        run_directory = folder / "evaluation"
        output = run_directory / "output"
        output.mkdir(parents=True, exist_ok=False)
        atlas = output / "Evaluation__EstimatedParameters__Template_surface.vtk"
        template = study._safe_study_path(root, seed["files"]["template"]["copy"])
        study._copy_bound(template, atlas, sha256_file(template))
        endpoints = {}
        for name, path in grids[count].items():
            target = output / ("Evaluation__Reconstruction__subject_" + name + ".vtk")
            study._copy_bound(path, target, sha256_file(path))
            endpoints[name] = target
        invalid = 0
        for path in (atlas, *endpoints.values()):
            mesh = read_vtk_polydata(path)
            quality = assess_triangle_mesh(mesh.vertices, mesh.triangles)
            invalid += (
                quality.zero_area_faces
                + quality.zero_length_edge_faces
                + quality.undefined_angle_faces
            )
        files = [
            dict(path=p.name, bytes=p.stat().st_size, sha256=sha256_file(p))
            for p in sorted(output.iterdir())
        ]
        study._write_json(
            run_directory / "manifest.json",
            dict(
                kind=VERSION,
                effective_config=config,
                optimizer_executed=False,
                source_binding=declaration["source_binding"],
                source_id=candidate_id,
                timepoints=count,
                subject_labels=labels,
            ),
            overwrite=False,
        )
        study._write_json(
            run_directory / "output-inventory.json", dict(files=files), overwrite=False
        )
        study._write_json(
            run_directory / "result.json",
            dict(
                kind=VERSION,
                status="completed",
                optimizer_executed=False,
                converged=False,
                source_optimizer=source.metrics,
            ),
            overwrite=False,
        )
        metrics = dict(
            metric_version=VERSION,
            completed=True,
            converged=False,
            optimizer_stop_signal="not_run_fixed_state_evaluation",
            final_iteration=None,
            maximum_iterations=source.metrics["maximum_iterations"],
            source_optimizer=source.metrics,
            residual_p95=None,
            deformation_energy=None,
            distortion_p95=None,
            resampling_sensitivity=None,
            runtime_seconds=time.monotonic() - started,
            invalid_face_count=invalid,
            fit_scope="full_targets",
            subject_reconstruction_count=len(endpoints),
            atlas_path=str(atlas),
            subject_residual_p95={},
            notes=[
                "Same saved field evaluated on a finer grid; no optimizer ran at this grid.",
                "Fresh anatomy review and explicit provisional completion are required.",
            ],
        )
        candidate = study.CalibrationStudyCandidateState(
            identifier,
            f"Saved field at {count} time steps (no refit)",
            "completed",
            config_path,
            run_directory,
            metrics,
            None,
            0,
        )
        manifest = study._verify_manifest(root)
        scales = {
            r["filename"]: study._bound_subject_diagonal(
                study._safe_study_path(root, r["copy"]),
                r["sha256"],
            )
            for r in manifest["inputs"]["subjects"]
        }
        receipt = dict(
            version=VERSION,
            declaration_event_hash=declaration["event_hash"],
            checkpoint_binding=study._candidate_review_binding(candidate),
            criteria=dict(completion.CRITERIA),
            valid_geometry=invalid == 0,
            roundtrip={
                name: movement(path, grids[count][name], scales[name])
                for name, path in endpoints.items()
            },
            integration={
                f"{a}->{b}": {
                    name: movement(grids[a][name], grids[b][name], scales[name]) for name in labels
                }
                for a, b in zip(declaration["counts"][:-1], declaration["counts"][1:], strict=True)
            },
            artifacts={
                study._relative_path(root, p): sha256_file(p)
                for p in folder.rglob("*")
                if p.is_file()
            },
        )
        receipt["artifacts"].update(original["receipt"]["artifacts"])
        receipt["integration_pass"] = not completion.integration_failures(receipt)
        path = folder / "receipt.json"
        study._write_json(path, receipt, overwrite=False)
        record = dict(
            version=VERSION,
            declaration_event_hash=declaration["event_hash"],
            seed=seed,
            config=study._relative_path(root, config_path),
            config_sha256=sha256_file(config_path),
            candidate=dict(
                candidate_id=identifier,
                label=candidate.label,
                parameter_values={"timepoints": float(count)},
                rationale="Finer evaluation of the same learned field; "
                "fresh QC, no re-optimization.",
            ),
            receipt=study._relative_path(root, path),
            receipt_sha256=sha256_file(path),
        )
        # One event registers the plan addition AND its completed evaluation.
        study._append_event(
            root,
            "candidate_completed",
            dict(
                stage_id=snapshot.current_stage.stage_id,
                candidate_id=identifier,
                run_directory=study._relative_path(root, run_directory),
                metrics=metrics,
                attempt=0,
                **{KEY: record},
            ),
        )
        study._append_event(
            root, "stage_awaiting_review", dict(stage_id=snapshot.current_stage.stage_id)
        )
    except Exception as error:
        study._append_event(
            root,
            "resolution_evaluation_failed",
            dict(
                candidate_id=identifier,
                declaration_event_hash=declaration["event_hash"],
                error=f"{type(error).__name__}: {error}",
            ),
        )
        raise
    return study.load_reference_calibration_study(root)
