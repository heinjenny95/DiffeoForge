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


def test_working_density_retains_the_selected_fit_integration_grid(tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET

    import numpy as np
    from guided_field_fixture import field_fixture
    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import reject

    from diffeoforge import reference_attachment_comparison as methods
    from diffeoforge.config import load_config
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.regional_pilot import configure_numerics
    from diffeoforge.runs import prepare_run, verify_prepared_run

    identifier = "guided-varifold"
    base = reject(run_batch(initial(tmp_path), monkeypatch), identifier)
    configure_method = methods.configure

    def configure_saved_grid(config, *args):
        configure_method(config, *args)
        configure_numerics(config)

    # Model a saved regional grid using the production integration policy.
    # Synthetic optimizer receipts keep the test independent of a native run.
    with monkeypatch.context() as legacy:
        legacy.setattr(methods, "configure", configure_saved_grid)
        retained = guided.next_action(
            base.study_directory, "adaptive_recover", identifier, goal="goal:detail"
        )
    retained = run_batch(retained, monkeypatch)
    retained = feedback.save_feedback(
        retained.study_directory, identifier, decision(base, retained, "worse")
    )
    newer = guided.next_action(
        retained.study_directory, "adaptive_recover", identifier, goal="goal:weight"
    )
    newer = run_batch(newer, monkeypatch)
    retained_field = field_fixture(retained.candidates[0].run_directory)
    retained_grid = load_config(retained.candidates[0].config_path)["model"]["deformation"]
    newer_grid = load_config(newer.candidates[0].config_path)["model"]["deformation"]
    assert retained_grid["timepoints"] == 37 and retained_grid["use_rk2"]
    assert not newer_grid["use_rk2"]
    before = {p: sha256_file(p) for p in retained.study_directory.rglob("*") if p.is_file()}
    choice = payload(retained, newer)
    choice["problem_regions"] = {}
    selected = guided.next_action(
        newer.study_directory, "adaptive_working_start", identifier, goal=choice
    )

    trial = guided.next_action(
        selected.study_directory, "adaptive_recover_start", identifier, goal="goal:density"
    )
    refinement = trial.attachment_comparison["refinement"]
    assert refinement["reference"] == choice["reference"]
    assert refinement["initialization"] == "nested"
    assert not trial.visual_reviews and trial.candidates[0].attempts == 0
    config = load_config(trial.candidates[0].config_path)
    deformation = config["model"]["deformation"]
    assert deformation["timepoints"] == 37 and deformation["use_rk2"]
    assert "regional_fit" not in config["project"]["parameter_provenance"]
    controls = np.loadtxt(deformation["initial_control_points"], ndmin=2)
    momenta = read_deformetrica_momenta(deformation["initial_momenta"], allow_singleton=True)
    keep = len(retained_field.control_points)
    assert len(controls) > keep
    np.testing.assert_array_equal(controls[:keep], retained_field.control_points)
    np.testing.assert_array_equal(momenta[:, :keep], retained_field.momenta)
    assert not momenta[:, keep:].any()
    run = prepare_run(trial.candidates[0].config_path, run_id="density-with-saved-grid")
    verify_prepared_run(run)
    model = ET.parse(run / "engine/model.xml")
    optimizer = ET.parse(run / "engine/optimization_parameters.xml")
    assert model.findtext("deformation-parameters/number-of-timepoints") == "37"
    assert optimizer.findtext("use-rk2") == "On"
    assert all(sha256_file(path) == digest for path, digest in before.items())


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
