"""Earlier fields are working sources, with workspace-only region edits."""

from copy import deepcopy

import pytest
from test_guided_feedback import attempted, decision
from test_pilot_region_feedback import patch

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import guided_working_fit as working
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def payload(base, trial):
    form = trial.plan.selected_pilot_subjects[0]
    rows = [dict(patch(form.sha256), purpose="problem", version="surface-region-v2"),
            dict(patch(form.sha256), purpose="fixed", version="surface-region-v2",
                 center=[.5, .5, .5])]
    return dict(reference=feedback.reference(base, "guided-varifold"),
                inspected_subjects=[form.filename], display_scopes={form.filename: "preview"},
                problem_regions={form.filename: rows})


def test_working_edits_and_trial_use_selected_field_not_latest_bad_fit(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    from test_interactive_pilot import geometry_receipt

    geometry_receipt(base, "guided-varifold", monkeypatch)
    before = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    trial = feedback.save_feedback(trial.study_directory, "guided-varifold",
                                   decision(base, trial, "worse"))
    data = payload(base, trial)
    saved = guided.next_action(trial.study_directory, "adaptive_working_start",
                              "guided-varifold", goal=data)
    target = data["reference"]["target"]
    assert feedback.regions(saved, "guided-varifold", target) == data["problem_regions"][target]
    assert feedback.selection(saved, "guided-varifold") == data["reference"]
    assert not saved.visual_reviews
    # A compatible ordinary adjustment is explicitly selected for this source test;
    # the real planner and real staging run, but no optimizer is started.
    result = guided.next_action(saved.study_directory, "adaptive_recover_start",
                               "guided-varifold", goal="goal:weight")
    assert result.attachment_comparison["refinement"]["reference"] == data["reference"]
    assert guided.record(result)["strategy"]["baseline"] == data["reference"]
    assert result.candidates[0].attempts == 0 and not result.visual_reviews
    assert all(sha256_file(p) == digest for p, digest in before.items())
    assert trial.candidates[0].run_directory.exists()


@pytest.mark.parametrize("change", ["scope", "source", "other_form"])
def test_working_edits_require_inspection_and_original_identity(tmp_path, monkeypatch, change):
    base, trial = attempted(tmp_path, monkeypatch)
    data = payload(base, trial)
    if change == "scope":
        data["display_scopes"] = {}
    elif change == "source":
        next(iter(data["problem_regions"].values()))[0]["source_sha256"] = "x" * 64
    else:
        data["reference"] = dict(data["reference"], target="other.vtk")
    events = (trial.study_directory / study.STUDY_EVENTS).read_bytes()
    with pytest.raises(ValueError):
        working.save(trial.study_directory, "guided-varifold", data)
    assert (trial.study_directory / study.STUDY_EVENTS).read_bytes() == events


def test_reopen_clear_and_proposal_source_do_not_fall_back_to_bad_current(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    from test_interactive_pilot import geometry_receipt

    geometry_receipt(base, "guided-varifold", monkeypatch)
    data = payload(base, trial)
    selected = working.save(trial.study_directory, "guided-varifold", data)
    parent, inputs = working.inputs(selected, "guided-varifold", strategy.state(selected))
    assert parent.study_directory == base.study_directory
    assert inputs["current_reference"] == data["reference"]
    assert inputs["current"].run_directory != trial.candidates[0].run_directory
    assert inputs["regions"] == next(iter(data["problem_regions"].values()))
    data = deepcopy(data)
    data["problem_regions"] = {}
    cleared = working.save(trial.study_directory, "guided-varifold", data)
    assert feedback.region_state(
        cleared, "guided-varifold", data["reference"]["target"]) == ([], True)
    proposal = working.trial(cleared, "guided-varifold", "goal:local_motion")
    assert not proposal["available"] and "cannot retain" in proposal["blocked_reason"]
