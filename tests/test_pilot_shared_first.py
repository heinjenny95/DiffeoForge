"""New pilot correction and early shared-model handoffs; synthetic data only."""

from test_guided_pilot import approve, run_batch
from test_guided_suitable_dialog import panel as panel
from test_pilot_form_progress import regional_fit
from test_pilot_region_feedback import reject
from test_reference_calibration_study import _project
from test_regional_protected_capture import setup_data

from diffeoforge import guided_strategy, regional_pilot
from diffeoforge import pilot_common_capacity as capacity
from diffeoforge import pilot_form_progress as progress
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_feedback import reference
from diffeoforge.reference_attachment_comparison import VERSION


def new_pilot(tmp_path):
    path = _project(tmp_path)
    config = load_config(path)
    config["project"]["parameter_provenance"]["attachment_selection"] = dict(
        version=VERSION, mode="auto", state="pending", workflow=guided.ADAPTIVE_VERSION)
    study._write_yaml(path, config, overwrite=True)
    source = study.create_reference_calibration_study(path, tmp_path / "study")
    return guided.prepare(source.study_directory)


def test_new_pilot_uses_one_grid_on_distinct_representative_forms(tmp_path, monkeypatch):
    first = new_pilot(tmp_path)
    source_config = load_config(first.candidates[0].config_path)
    assert guided.record(first)["strategy"]["correction_policy"] == guided.ATLAS_FIRST
    grid = source_config["model"]["deformation"]
    assert grid["use_rk2"] and grid["timepoints"] >= regional_pilot.MINIMUM_NEW_NATIVE_TIMEPOINTS
    accepted = approve(run_batch(first, monkeypatch), "guided-varifold")
    following = guided_strategy.state(accepted)["next_forms"]["guided-varifold"]
    assert following["action"] == "next_form" and following["checked"] == 1
    second = guided.next_action(accepted.study_directory, "adaptive_next_form", "guided-varifold")
    assert guided.record(second)["target"] != guided.record(first)["target"]
    assert second.attachment_comparison["controls"]["sha256"] == first.attachment_comparison[
        "controls"]["sha256"]
    assert progress.marker(second)["reviews"] == [
        guided._approved_record(accepted, "guided-varifold")]
    assert second.candidates[0].attempts == 0 and not second.visual_reviews
    settings = load_config(second.candidates[0].config_path)
    assert settings["model"]["deformation"]["timepoints"] == grid["timepoints"]
    assert "initial_momenta" not in settings["model"]["deformation"]


def test_off_protocol_approval_checks_transfer_before_more_individual_fits(tmp_path, monkeypatch):
    first = reject(run_batch(new_pilot(tmp_path), monkeypatch), "guided-varifold")
    trial = guided.next_action(first.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:detail")
    accepted = regional_fit(run_batch(trial, monkeypatch), monkeypatch)
    row = guided._approved_record(accepted, "guided-varifold")
    target = row["filename"]
    # This receipt-only fixture emulates a correction that needed more controls.
    monkeypatch.setattr(capacity, "demand", lambda value: {target: 480})
    following = guided_strategy.state(accepted)["next_forms"]["guided-varifold"]
    assert following["shapes"] == 1 < following["total"]
    exact = reference(accepted, "guided-varifold")
    assert progress.marker(accepted) is None
    assert progress.transfer_marker(accepted, target, exact) == following["marker"]
    changed = dict(exact, manifest_sha256="changed")
    assert progress.transfer_marker(accepted, target, changed) is None
    assert following["action"] == "form_model_check" and following["target"] == target
    assert following["common_reuse"]["mode"] in {"capacity", "fresh_capacity"}
    child = guided.next_action(accepted.study_directory, "adaptive_form_model_check",
                               "guided-varifold")
    assert progress.marker(child)["reviews"] == [row]
    assert child.attachment_comparison["controls"]["count"] == 480
    assert not child.visual_reviews and child.candidates[0].attempts == 0
    qualified = approve(run_batch(child, monkeypatch), "guided-varifold")
    next_form = guided.next_action(qualified.study_directory, "adaptive_adopt_common_model",
                                   "guided-varifold")
    assert guided.record(next_form)["target"] != target
    assert progress.marker(next_form)["reviews"] == [row]
    assert next_form.attachment_comparison["controls"]["sha256"] == (
        child.attachment_comparison["controls"]["sha256"])
    assert not next_form.visual_reviews and next_form.candidates[0].attempts == 0


def test_first_far_feature_with_fixed_areas_prefers_direct_shared_field(monkeypatch):
    data, info = setup_data()
    info["strategy"] = {"correction_policy": guided.ATLAS_FIRST}
    data["references"][data["anchor"]["directory"]].attachment_comparison = {}
    data["regional_capture"].update(symmetric_tail=.4, original_to_fit_p95=.4)
    monkeypatch.setattr(guided, "record", lambda _: info)
    first = regional_pilot.proposal(None, "x", data, symptom="detail")
    assert first["available"] and first["initialization"] == "learned"
    width = data["anchor"]["values"]["deformation_kernel_width"]
    assert first["values"]["deformation_kernel_width"] == width
    assert first["regions"] == data["regions"]
    data["context"]["cases"] = [dict(family="regional", target="shape.vtk", method="varifold")]
    later = regional_pilot.proposal(None, "x", data, symptom="detail")
    assert later["initialization"] == "residual"
    assert later["regions"] == data["regions"]


def test_revision_checks_previously_approved_form_before_unseen_one(tmp_path, monkeypatch):
    first = approve(run_batch(new_pilot(tmp_path), monkeypatch), "guided-varifold")
    first_target = guided.record(first)["target"]
    first_approval = guided._approved_record(first, "guided-varifold")
    second = guided.next_action(first.study_directory, "adaptive_next_form", "guided-varifold")
    second = reject(run_batch(second, monkeypatch), "guided-varifold")
    trial = guided.next_action(second.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:detail")
    second = regional_fit(run_batch(trial, monkeypatch), monkeypatch)
    second_target = guided.record(second)["target"]
    second_approval = guided._approved_record(second, "guided-varifold")
    monkeypatch.setattr(capacity, "demand", lambda _: {first_target: 200, second_target: 480})
    transfer = guided.next_action(second.study_directory, "adaptive_form_model_check",
                                  "guided-varifold")
    assert guided.record(transfer)["target"] == second_target
    accepted_transfer = approve(run_batch(transfer, monkeypatch), "guided-varifold")
    check = guided.next_action(accepted_transfer.study_directory, "adaptive_adopt_common_model",
                               "guided-varifold")
    assert guided.record(check)["target"] == first_target
    assert progress.marker(check)["reviews"] == [first_approval, second_approval]
    assert check.attachment_comparison["controls"]["sha256"] == (
        transfer.attachment_comparison["controls"]["sha256"])
    assert "initial_momenta" not in (
        load_config(check.candidates[0].config_path)["model"]["deformation"]
    ) or check.attachment_comparison["refinement"]["reference"]["target"] == first_target
    assert not check.visual_reviews and check.candidates[0].attempts == 0


def test_primary_action_explains_and_prepares_the_early_transfer(panel):
    from PySide6.QtWidgets import QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    identifier = "guided-varifold"
    panel.snapshot.visual_reviews[identifier] = True
    note = "Check this approved anatomy on the shared settings before reviewing another specimen."
    panel.guidance["next_forms"] = {identifier: dict(
        available=True, target="specimen.vtk", label="Test shared controls for accepted shapes",
        action="form_model_check", shapes=1, checked=0, total=3, transfer_note=note)}
    panel.render()
    assert any(label.text() == note and label.isVisible()
               for label in panel.window.findChildren(QLabel))
    assert panel.window.next_step_button.text() == "Test shared controls for accepted shapes"
    panel.window._worker = None
    panel.window._restoring_search = False
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window))
    panel.window.next_step_button.click()
    assert panel.invoked[-1][1]["guided_action"] == ("adaptive_form_model_check", identifier, None)


def test_restored_old_transfer_uses_saved_approval_and_rejects_the_other_fit(tmp_path, monkeypatch):
    from test_reviewed_start_progress import selected_local_after_common_failure

    retained, rejected = selected_local_after_common_failure(tmp_path, monkeypatch)
    exact = reference(retained, "guided-varifold")
    assert progress.transfer_marker(rejected, exact["target"], exact) == progress.marker(rejected)
    different = reference(rejected, "guided-varifold")
    assert progress.transfer_marker(rejected, exact["target"], different) is None


def test_first_approved_projection_opens_its_bounded_workspace(panel, monkeypatch):
    from diffeoforge.desktop import common_projection_dialog
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    identifier = "guided-varifold"
    panel.snapshot.visual_reviews[identifier] = True
    label = "Transfer approved anatomy to shared controls"
    choice = {"mode": "project_approved", "reason": "Check the approved shape on shared controls."}
    panel.guidance["next_forms"] = {identifier: dict(
        available=True, target="specimen.vtk", label=label, action="form_model_check",
        shapes=1, checked=0, total=3, common_reuse=choice)}
    panel.render()
    assert panel.window.next_step_button.text() == label
    opened = []
    monkeypatch.setattr(
        common_projection_dialog, "open_projection", lambda *args: opened.append(args))
    panel.window.snapshot = panel.snapshot
    panel.window.next_step_button.clicked.connect(
        lambda: ReferenceCalibrationDialog._perform_final_next_step(panel.window))
    panel.window.next_step_button.click()
    assert opened == [(panel.window, panel.snapshot, choice)]
    assert not panel.invoked
