"""Prospectively recorded engineering tolerances for the complete Stage 4 pilot."""

import math

from diffeoforge import reference_calibration_study as study

DEFAULT_TOLERANCES = {
    "atlas_rms_relative": 0.005,
    "objective_relative": 0.01,
    "residual_relative": 0.01,
}


def verified_tolerances(manifest, stage, candidates, events):
    records = [e for e in events if e["event"] == "integration_tolerances_declared"
               and e.get("stage_id") == stage.stage_id]
    if not records:
        return {}
    if len(records) != 1 or stage.order != 4:
        raise ValueError("Invalid numerical tolerance declaration")
    record = records[0]
    values = record["tolerances"]
    if (set(values) != {*DEFAULT_TOLERANCES, "atlas_rms_absolute"}
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v <= 0 for v in values.values())
            or any(values[k] > 1 for k in DEFAULT_TOLERANCES)
            or record["candidate_ids"] != [c.candidate_id for c in candidates]
            or record["subjects"] != [s["filename"] for s in manifest["inputs"]["subjects"]]
            or not math.isclose(values["atlas_rms_absolute"],
                                values["atlas_rms_relative"] * manifest["template_diagonal"])
            or any(e["event"] == "candidate_started" and e.get("stage_id") == stage.stage_id
                   and e["sequence"] < record["sequence"] for e in events)):
        raise ValueError("Numerical tolerances differ from their declared comparison")
    return dict(values)


def declare_tolerances(snapshot, values=None):
    if snapshot.current_stage is None or snapshot.current_stage.order != 4:
        raise ValueError("Numerical tolerances belong to Stage 4")
    if snapshot.integration_tolerances:
        if values is not None and dict(values) != {
            k: snapshot.integration_tolerances[k] for k in DEFAULT_TOLERANCES
        }:
            raise ValueError("Numerical tolerances are already bound to this comparison")
        return snapshot
    if any(c.attempts for c in snapshot.candidates):
        if values is not None:
            raise ValueError("Declare tolerances before running any timepoint option")
        return snapshot  # Preserve the meaning of legacy completed/partial comparisons.
    values = dict(DEFAULT_TOLERANCES if values is None else values)
    if set(values) != set(DEFAULT_TOLERANCES) or any(
        isinstance(v, bool) or not isinstance(v, (int, float))
        or not math.isfinite(v) or not 0 < v <= 1 for v in values.values()
    ):
        raise ValueError("Numerical tolerances must be finite positive fractions up to one")
    manifest = study._verify_manifest(snapshot.study_directory)
    values["atlas_rms_absolute"] = values["atlas_rms_relative"] * manifest["template_diagonal"]
    study._append_event(snapshot.study_directory, "integration_tolerances_declared", dict(
        stage_id=snapshot.current_stage.stage_id, tolerances=values,
        candidate_ids=[c.candidate_id for c in snapshot.candidates],
        subjects=[s.filename for s in snapshot.plan.selected_pilot_subjects],
        basis="RMS / bound template diagonal; relative objective; worst subject residual",
        meaning="Engineering discretization criteria, not anatomical or biological approval",
    ))
    return study.load_reference_calibration_study(snapshot.study_directory)
