"""A single optimized joint fit can be retained and finished without recomputing."""

import shutil

import pytest
from test_pilot_completion import _approve_preview
from test_reference_adaptive_calibration import seed_stub
from test_reference_calibration_study import _afk_runner

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_completion as completion
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_stage_retention import keep_previous_fit


def _retained_checked(tmp_path, monkeypatch):
    runner = _afk_runner(tmp_path, monkeypatch)
    initial = study.load_reference_calibration_study(runner.study_directory)
    identifier = initial.candidates[0].candidate_id
    first = runner.run_current_stage(candidate_ids={identifier})
    # The guided one-option joint path marks this stage reviewable; this generic
    # synthetic fixture still has unused alternatives which must never be run.
    study._append_event(first.study_directory, "stage_awaiting_review", {"stage_id": "attachment"})
    _approve_preview(first, identifier)
    second, _ = study.record_reference_calibration_stage_review(
        first.study_directory, selected_candidate_id=identifier, visual_approvals={}
    )
    keep_previous_fit(second.study_directory)
    fourth = keep_previous_fit(second.study_directory)
    template = next((fourth.study_directory / "inputs/template").glob("*.vtk"))
    names = [s.filename for s in fourth.plan.selected_pilot_subjects]

    def bind(snapshot, center_id, destination):
        seed = seed_stub(snapshot, center_id, destination)
        candidate = next(c for c in snapshot.candidates if c.candidate_id == center_id)
        seed["source_manifest_sha256"] = sha256_file(
            study.calibration_candidate_run_directory(candidate) / "manifest.json"
        )
        return seed

    def shoot(config, folder, seed, destination, count, **kwargs):
        destination.mkdir(parents=True)
        paths = {name: destination / name for name in names}
        for path in paths.values():
            shutil.copyfile(template, path)
        return paths, {}

    monkeypatch.setattr("diffeoforge.reference_adaptive_calibration.bind_learned_seed", bind)
    monkeypatch.setattr(completion, "shoot", shoot)
    monkeypatch.setattr(completion.legacy, "_reconstructions",
                        lambda *a: (None, {n: template for n in names}))
    checked = completion.run(runner)
    assert checked.visual_reviews["timepoints-retained"] is True
    monkeypatch.setattr(runner, "run_current_stage", lambda **kw: pytest.fail("No new fit"))
    return checked


@pytest.mark.parametrize("failure", [None, "schema", "html", "completion_event"])
def test_one_joint_run_retains_review_finishes_and_recovers_partial_finalization(
    tmp_path, monkeypatch, failure
):
    checked = _retained_checked(tmp_path, monkeypatch)
    root = checked.study_directory
    saved = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    attempts = set(root.rglob("pilot-attempt-*"))
    if failure:
        original_schema, original_write, original_append = (
            study.validate_schema, study.write_text_safely, study._append_event
        )

        def fail_schema(*a, **kw):
            raise RuntimeError("Injected final schema failure")

        def fail_html(path, *a, **kw):
            if path == root / study.CALIBRATION_REPORT_HTML:
                raise RuntimeError("Injected HTML write failure")
            return original_write(path, *a, **kw)

        def fail_event(folder, event, *a, **kw):
            if event == "study_completed":
                raise RuntimeError("Injected completion ledger failure")
            return original_append(folder, event, *a, **kw)

        monkeypatch.setattr(study, "validate_schema", fail_schema if failure == "schema"
                            else original_schema)
        monkeypatch.setattr(study, "write_text_safely", fail_html if failure == "html"
                            else original_write)
        monkeypatch.setattr(study, "_append_event", fail_event if failure == "completion_event"
                            else original_append)
        with pytest.raises(RuntimeError, match="Injected"):
            completion.finish(root, "timepoints-retained")
        pending = study.load_reference_calibration_study(root)
        assert pending.status == "awaiting_review"
        assert pending.visual_reviews["timepoints-retained"] is True
        monkeypatch.setattr(study, "validate_schema", original_schema)
        monkeypatch.setattr(study, "write_text_safely", original_write)
        monkeypatch.setattr(study, "_append_event", original_append)
    final, _ = completion.finish(root, "timepoints-retained")
    assert final.status == "completed"
    config = load_config(final.final_config_path)
    observations = config["project"]["parameter_provenance"]["recommendation"][
        "calibration_result"]["runtime_calibration"]["observations"]
    assert len(observations) == 1
    assert observations[0]["stage_id"] == "attachment"
    assert set(root.rglob("pilot-attempt-*")) == attempts
    assert all(p.read_bytes() == value for p, value in saved.items()
               if p.name != study.STUDY_EVENTS)
    assert (root / study.STUDY_EVENTS).read_bytes().startswith(saved[root / study.STUDY_EVENTS])
    events = study._load_events(root)
    assert len([e for e in events if e.get("final_pilot_completion")]) == 1
    assert study.load_reference_calibration_study(root).status == "completed"
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert completion.finish(root, "timepoints-retained")[0] == final
    assert all(p.read_bytes() == value for p, value in after.items())
    # A retained selection summary cannot invent the original human approval.
    journal = root / "visual-reviews.json"
    journal.unlink()
    with pytest.raises(ValueError, match="approval"):
        study.load_reference_calibration_study(root)


def test_sparse_runtime_evidence_does_not_claim_calibrated_estimate():
    from copy import deepcopy
    from dataclasses import replace
    from pathlib import Path

    from diffeoforge.desktop.reference_runtime_estimate import estimate_reference_runtime
    from diffeoforge.report import collect_preflight

    preflight = collect_preflight(
        Path(__file__).parents[1] / "examples/minimal-atlas-container.yaml"
    )
    baseline = estimate_reference_runtime(preflight)
    config = deepcopy(preflight.config)
    config["project"].setdefault("parameter_provenance", {}).setdefault("recommendation", {})[
        "calibration_result"] = {"runtime_calibration": {
            "pilot_subject_count": 2,
            "observations": [{"runtime_seconds": 163, "final_iteration": 117}],
        }}
    assert estimate_reference_runtime(replace(preflight, config=config)) == baseline
