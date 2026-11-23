"""Transfer state, integrity and guided adoption using controlled synthetic outputs."""

from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace

import pytest
from test_guided_pilot import approve
from test_reference_calibration_study import _CompletedController
from test_reviewed_start_progress import selected_local_after_common_failure

from diffeoforge import pilot_common_projection as transfer
from diffeoforge import pilot_projection_worker, regional_evaluation
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def source_project(tmp_path, monkeypatch):
    """An existing approved synthetic local, a rejected common and a known endpoint."""
    approved, context = selected_local_after_common_failure(tmp_path, monkeypatch)
    candidate = approved.candidates[0]
    manifest = study._verify_manifest(approved.study_directory)
    target = manifest["inputs"]["subjects"][0]
    path = approved.study_directory / target["copy"]
    # The receipt-only controller supplies a known material endpoint here.
    monkeypatch.setattr(transfer, "_has_composed_endpoint", lambda c: c == candidate)
    monkeypatch.setattr(
        regional_evaluation,
        "endpoint",
        lambda c, *, subject: (
            dict(path=str(path), sha256=sha256_file(path))
            if c == candidate and subject == target["filename"]
            else None
        ),
    )
    return approved, context


class Controller(_CompletedController):
    def run(self, *, event_callback=None):
        super().run(event_callback=event_callback)
        return SimpleNamespace(completed=True, interrupted=False)


def synthetic_evidence(directory, run, stage, data):
    output = run / "output"
    output.mkdir(exist_ok=True)
    mesh = output / "reconstruction.vtk"
    momentum = output / "momenta.txt"
    origin = data["assets"]
    copyfile(directory / origin["original"]["copy"], mesh)
    copyfile(directory / origin["initial"]["copy"], momentum)
    return dict(
        stage=stage,
        approved_reference=data["choice"]["approved_reference"],
        basis_reference=data["choice"]["basis_reference"],
        target=data["choice"]["target"],
        original_sha256=origin["original"]["sha256"],
        template_sha256=origin["template"]["sha256"],
        control_points_sha256=origin["controls"]["sha256"],
        run_directory=str(run),
        path=str(mesh),
        sha256=sha256_file(mesh),
        momenta_path=str(momentum),
        momenta_sha256=sha256_file(momentum),
        manifest_sha256=sha256_file(run / "manifest.json"),
    )


def test_verified_projection_requires_separate_original_and_review(tmp_path, monkeypatch):
    from diffeoforge import (
        anatomy_retention,
        guided_feedback,
        guided_strategy,
        ordinary_field_quality,
    )
    from diffeoforge.guided_feedback import region_state
    from diffeoforge.pilot_form_progress import is_common_check, marker, proposal

    local, parent = source_project(tmp_path, monkeypatch)
    choice = transfer.offer(parent)
    assert choice["mode"] == "project_approved"
    root = transfer.default_directory(parent, choice)
    assert transfer.prepare(parent, choice, root) == root
    contract = transfer.verified_inputs(root)
    assert (
        contract["regions"]
        == region_state(local, local.candidates[0].candidate_id, choice["target"])[0]
    )
    assert transfer.default_directory(parent, transfer.offer(parent)) == root
    with monkeypatch.context() as edited:
        edited.setattr(
            guided_feedback,
            "region_state",
            lambda *args, **kwargs: ([dict(name="Later annotation")], False),
        )
        new_choice = transfer.offer(parent)
        assert new_choice["approved_regions_sha256"] != choice["approved_regions_sha256"]
        assert transfer.default_directory(parent, new_choice) != root
        assert transfer.verified_inputs(root)["regions"] == contract["regions"]
        with pytest.raises(ValueError, match="current reviewed references"):
            transfer.prepare(parent, choice, root)
    reviewed = local.study_directory / study.STUDY_MANIFEST
    reviewed_hash = sha256_file(reviewed)
    parent_pointer = parent.study_directory / "fit-search-latest.json"
    native_objectives = []

    def evidence(directory, run, stage, data):
        native_objectives.append(stage)
        return synthetic_evidence(directory, run, stage, data)

    monkeypatch.setattr(transfer, "_evidence", evidence)
    monkeypatch.setattr(transfer, "_check_numerics", lambda *args: dict(passed=True))
    monkeypatch.setattr(
        ordinary_field_quality,
        "qualify",
        lambda *args, **kwargs: dict(numerical_selection_suitable=True),
    )
    monkeypatch.setattr(
        anatomy_retention,
        "compare_approved_endpoint",
        lambda *args, **kwargs: dict(status="comparable", rows=[]),
    )

    runner = transfer.ProjectionRunner(root, controller_factory=Controller)
    seed = runner.run_projection()
    assert transfer.original_directory(root) is None and not parent_pointer.exists()
    assert transfer.status(root)["can_fit_original"]
    assert load_config(root / "projection.yaml")["input"]["directory"] == str(root / "approved")
    result = runner.run_original()
    child = transfer.original_directory(root)
    snapshot = study.load_reference_calibration_study(child)
    candidate = snapshot.candidates[0]
    config = load_config(candidate.config_path)
    original_manifest = study._verify_manifest(child)
    assert (
        original_manifest["inputs"]["subjects"][0]["sha256"]
        == contract["assets"]["original"]["sha256"]
    )
    assert (
        sha256_file(Path(config["model"]["deformation"]["initial_momenta"]))
        == seed["momenta_sha256"]
    )
    assert is_common_check(guided.record(snapshot))
    assert marker(parent) == marker(snapshot)
    assert result["original_sha256"] == seed["original_sha256"]
    assert config["optimization"]["max_iterations"] == transfer.BUDGET
    assert not transfer.status(root)["can_attach"] and not parent_pointer.exists()
    with pytest.raises(ValueError, match="visual approval"):
        transfer.attach_original(root, parent)
    reviewed_child = approve(snapshot, candidate.candidate_id)
    assert transfer.status(root)["can_attach"]
    assert transfer.attach_original(root, parent) == child
    assert transfer.attach_original(root, parent) == child
    assert Path(study._read_json(parent_pointer, "verified successor")["directory"]) == child
    next_step = proposal(
        reviewed_child,
        candidate.candidate_id,
        guided_strategy.state(reviewed_child),
        preview_common=False,
    )
    assert next_step["marker"]["reviews"] == marker(parent)["reviews"]
    assert guided._approved_record(reviewed_child, candidate.candidate_id) in next_step["common"]
    from diffeoforge.reference_sequential_fit import resume_directory

    successor = guided.next_action(child, "adaptive_form_model_check", candidate.candidate_id)
    assert successor.study_directory.parent == root and not successor.candidates[0].attempts
    assert resume_directory(parent.study_directory) == successor.study_directory
    assert sha256_file(reviewed) == reviewed_hash
    assert native_objectives == ["projection", "original"]
    assert runner.run_original() == result
    Path(seed["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="output changed"):
        transfer.verified_endpoint(root, "projection")


@pytest.mark.parametrize(
    ("evidence", "why"),
    [
        (
            dict(
                projection="completed",
                can_fit_original=False,
                projection_retention=dict(status="regression"),
            ),
            "lost anatomy",
        ),
        (
            dict(original="completed", original_retention=dict(status="unmeasured")),
            "could not verify",
        ),
        (
            dict(
                original="completed",
                approved=None,
                original_retention=dict(status="comparable"),
                original_numerical=dict(passed=False),
            ),
            "numerical checks",
        ),
        (dict(original="completed", approved=False), "rejected the fit"),
    ],
)
def test_negative_experiment_shows_other_common_plan_or_retained_result(
    tmp_path, monkeypatch, evidence, why
):
    from diffeoforge import pilot_common_model, pilot_multiscale_choice

    approved_ref = dict(target="subject.vtk")
    action = dict(mode="project_approved", target="subject.vtk", approved_reference=approved_ref)
    monkeypatch.setattr(transfer, "offer", lambda *args, **kwargs: action)
    monkeypatch.setattr(transfer, "default_directory", lambda *args: tmp_path)
    monkeypatch.setattr(transfer, "status", lambda path: evidence)
    monkeypatch.setattr(pilot_common_model, "_preview", lambda *args, **kwargs: None)
    monkeypatch.setattr(pilot_multiscale_choice, "choice", lambda *args: None)
    result = pilot_common_model.preview(None, {}, "subject.vtk", value=dict(stage="model"))
    assert why in result["reason"]
    assert result["mode"] == "stalled" and result["retained_reference"] == approved_ref
    assert result["transfer_experiment"] == action
    monkeypatch.setattr(
        pilot_multiscale_choice,
        "choice",
        lambda *args: dict(mode="capacity", available=True, reason="other model"),
    )
    alternative = pilot_common_model.preview(None, {}, "subject.vtk", value=dict(stage="model"))
    assert alternative["available"] and alternative["mode"] == "capacity"


@pytest.mark.parametrize(
    "status,passed", [("regression", True), ("unmeasured", True), ("comparable", False)]
)
def test_failed_retention_or_numerics_prevents_fitting_original(
    tmp_path, monkeypatch, status, passed
):
    monkeypatch.setattr(transfer, "verified_inputs", lambda root: {})
    monkeypatch.setattr(
        transfer,
        "verified_endpoint",
        lambda *args: dict(retention=dict(status=status), numerical_checks=dict(passed=passed)),
    )
    with pytest.raises(ValueError, match="did not preserve"):
        transfer.ProjectionRunner(tmp_path).run_original()
    assert transfer.original_directory(tmp_path) is None


def test_cancel_and_stage_lease_do_not_dispatch_an_extra_worker(tmp_path, monkeypatch):
    from diffeoforge.pilot_projection_worker import _native_run

    with pilot_projection_worker.stage_lock(tmp_path, "projection"):
        assert pilot_projection_worker.active(tmp_path, "projection")
        with pytest.raises(ValueError, match="already running"):
            transfer.ProjectionRunner(tmp_path).run_projection()
    assert not pilot_projection_worker.active(tmp_path, "projection")
    monkeypatch.setattr(transfer, "verified_inputs", lambda root: {})
    runner = transfer.ProjectionRunner(tmp_path)
    runner.request_cancel()
    with pytest.raises(InterruptedError, match="before native dispatch"):
        runner.run_projection()
    study._write_json(
        tmp_path / "last-projection-attempt.json", dict(name="previous"), overwrite=False
    )
    (tmp_path / "projection-runs" / "previous").mkdir(parents=True)
    with pytest.raises(ValueError, match="no terminal result"):
        _native_run(tmp_path, runner, {}, None)
