"""The accepted-field contrast is bounded and keeps review separate."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from diffeoforge import guided_feedback, pilot_common_diagnosis
from diffeoforge import pilot_common_warm_start as warm


def reviewed_regional_measurements():
    return dict(version="regional-quality-v1", local_improved=True, outside_preserved=True,
                explicit_fixed_preserved=True, shape_preserved=True, transition_preserved=True,
                temporal_grid_stable=True, no_new_intersection_flags=False,
                spatial_resolution_sufficient=False, numerical_selection_suitable=False)


@pytest.mark.parametrize("change", [
    {"explicit_fixed_preserved": False}, {"transition_preserved": False},
    {"outside_preserved": False}, {"shape_preserved": False}, {"temporal_grid_stable": False},
    {"local_improved": False}, {"spatial_resolution_sufficient": None},
    {"no_new_intersection_flags": True, "spatial_resolution_sufficient": True},
])
def test_reviewable_source_warnings_cannot_override_an_unexplained_or_protection_failure(change):
    subject = {"regional_quality": dict(reviewed_regional_measurements(), **change)}
    candidate = SimpleNamespace(metrics={"attachment_comparison": {"subjects": {"A": subject}}})
    assert warm.reviewed_warnings(candidate, "A", regional=True) is None


@pytest.mark.parametrize(("history_kind", "review", "losses", "warnings", "mode", "kind"), [
    (None, None, [], [], "accepted_warm", "warm"),
    ("warm", None, [], [], "review", "warm"),
    ("warm", True, [], [], "approved", "warm"),
    ("warm", False, [{"region": "mark:0"}], [], "accepted_warm", "detail"),
    ("warm", False, [], [], "stalled", "warm"),
    ("warm", False, [{"region": "mark:0"}], ["invalid"], "stalled", "warm"),
    ("detail", False, [{"region": "mark:0"}], [], "stalled", "warm"),
    ("detail", True, [], [], "adopt", "warm"),
])
def test_choose_once_from_the_saved_accepted_field(
        monkeypatch, history_kind, review, losses, warnings, mode, kind):
    candidate = SimpleNamespace(candidate_id="varifold", status="completed")
    prior = SimpleNamespace(candidates=[candidate],
                            visual_reviews={} if review is None else {"varifold": review})
    monkeypatch.setattr(warm, "trials", lambda *_: [(prior, history_kind)] if history_kind else [])
    monkeypatch.setattr(warm, "review_event", lambda *_: {
        "approved": review, "event_hash": "bound-rejection"})
    monkeypatch.setattr(guided_feedback, "reference", lambda *_: {"directory": "common"})
    monkeypatch.setattr(pilot_common_diagnosis, "diagnose", lambda *_: {
        "local_losses": losses, "warnings": warnings})
    seed = {"directory": "accepted"}
    shared = {"attachment_kernel_width": .1, "deformation_kernel_width": .4,
              "initial_control_point_spacing": .4, "noise_std": .025}
    protocol = {"reference": {"values": shared}}
    choice = warm.preview(None, {"protocol": protocol}, "target.vtk", seed)
    assert (choice["mode"], choice["kind"]) == (mode, kind)
    if mode == "accepted_warm":
        plan = warm.apply({"strategy": {}}, choice, protocol)
        marker = plan["strategy"]["common_basis_step"]
        assert marker["reference"] is seed
        assert marker["additional_iterations"] == 120
        assert marker["approval_transferred"] is False
        expected = dict(shared)
        if kind == "detail":
            expected["attachment_kernel_width"] *= .9
            assert marker["review_hash"] == "bound-rejection"
        assert plan["values"] == expected
        assert shared["attachment_kernel_width"] == .1


def approved_forms_for_common_check(tmp_path, monkeypatch, *, different_width=False, warnings=True):
    import test_guided_pilot as pilot
    from test_pilot_shared_first import new_pilot
    from test_regional_fit import prepare_marked_individual

    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge import regional_pilot
    from diffeoforge.config import load_config
    from diffeoforge.regional_fit import read_plan

    identifier = "guided-varifold"
    if different_width:
        # Exercise a saved regional contrast whose global attachment width
        # differed from that of its ordinary ancestor on the same fixed field.
        proposal = regional_pilot.proposal

        def local_contrast(*args, **kwargs):
            result = proposal(*args, **kwargs)
            values = dict(result["values"])
            values["attachment_kernel_width"] *= 0.8
            return dict(result, values=values)

        monkeypatch.setattr(regional_pilot, "proposal", local_contrast)
    baseline, local, _ = prepare_marked_individual(tmp_path, monkeypatch, "detail", new_pilot)
    target = guided.record(local)["target"]
    plan = read_plan(load_config(local.candidates[0].config_path))
    assert plan and not plan.get("residual")
    quality = reviewed_regional_measurements()
    if not warnings:
        quality.update(numerical_selection_suitable=True, no_new_intersection_flags=True,
                       spatial_resolution_sufficient=True)
    geometry = pilot._detail

    def regional_measurement(names):
        sample = geometry(names)
        sample["subjects"][target]["regional_quality"] = quality
        return sample

    # Only the native optimizer, its tensors and its measured output are
    # synthetic. Persist the anatomy decision and traverse the actual pilot.
    with monkeypatch.context() as regional:
        regional.setattr(pilot, "_detail", regional_measurement)
        completed = pilot.run_batch(local, regional)
    approved = pilot.approve(completed, identifier)
    field_ref = guided_feedback.reference(approved, identifier)
    width = field_ref["values"]["attachment_kernel_width"]
    assert (width != baseline.plan.effective_values["attachment_kernel_width"]) == different_width
    assert approved.visual_reviews[identifier] is True
    assert approved.candidates[0].metrics["attachment_comparison"]["subjects"][
        target]["regional_quality"] == quality
    latest = approved
    for _ in guided.record(approved)["pilot_order"][1:]:
        other = guided.next_action(latest.study_directory, "adaptive_next_form", identifier)
        assert guided.record(other)["target"] != target
        other_config = load_config(other.candidates[0].config_path)
        assert "initial_momenta" not in other_config["model"]["deformation"]
        assert other_config["model"]["attachment"]["kernel_width"] == width
        latest = pilot.approve(pilot.run_batch(other, monkeypatch), identifier)
    return approved, latest


@pytest.mark.parametrize("different_width", [False, True])
def test_common_model_prepares_native_inputs_from_approved_field_on_its_own_specimen(
        tmp_path, monkeypatch, different_width):
    from diffeoforge import guided_refinement, guided_strategy
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_fit import read_plan
    from diffeoforge.runs import prepare_run, verify_prepared_run

    approved, latest = approved_forms_for_common_check(
        tmp_path, monkeypatch, different_width=different_width)
    identifier = approved.candidates[0].candidate_id
    field_ref = guided_feedback.reference(approved, identifier)
    target = field_ref["target"]
    original_controls = approved.attachment_comparison["controls"]
    field_run = study.calibration_candidate_run_directory(approved.candidates[0])
    following = guided_strategy.state(latest)["next_forms"][identifier]
    assert following["target"] == target and following["action"] == "form_model_check"
    assert following["common_reuse"]["mode"] == "accepted_warm"
    assert following["common_reuse"]["reference"] == field_ref
    common = guided.next_action(latest.study_directory, "adaptive_form_model_check", identifier)
    assert common.candidates[0].attempts == 0 and not common.visual_reviews
    assert guided.record(common)["target"] == target
    record = common.attachment_comparison
    common_config = load_config(common.candidates[0].config_path)
    assert not read_plan(common_config)
    assert common_config["model"]["attachment"]["kernel_width"] == (
        field_ref["values"]["attachment_kernel_width"])
    assert record["refinement"]["initialization"] == "learned"
    assert record["refinement"]["reference"] == field_ref
    assert record["refinement"]["source_run_sha256"] == sha256_file(field_run / "manifest.json")
    assert record["controls"]["sha256"] == original_controls["sha256"]
    step = guided.record(common)["strategy"]["common_basis_step"]
    assert step["approval_transferred"] is False and step["additional_iterations"] == 120
    assert set(step["reviewed_warnings"]) == {
        "no_new_intersection_flags", "spatial_resolution_sufficient"}

    prepared = prepare_run(common.candidates[0].config_path, run_id="test-start")
    verify_prepared_run(prepared)
    engine = prepared / "engine"
    model = ET.parse(engine / "model.xml")
    assert sha256_file(engine / model.findtext("initial-control-points")) == (
        original_controls["sha256"])
    assert sha256_file(engine / model.findtext("initial-momenta")) == (
        sha256_file(field_run / "synthetic-final-momenta.txt"))
    reopened = study.load_reference_calibration_study(approved.study_directory)
    assert reopened.visual_reviews == approved.visual_reviews
    assert guided_feedback.reference(reopened, identifier) == field_ref

    # Warnings allow a new check. Neither dropping its warnings nor a
    # nonfinite coefficient can create a valid numerical starting field.
    manifest = study._verify_manifest(common.study_directory)
    info = guided.record(common)
    assert warm.seed_evidence(info["strategy"]["form_progress"], target, legacy=True) is None
    cleared = dict(info["strategy"], common_basis_step=dict(step, reviewed_warnings=[]))
    with pytest.raises(ValueError, match="accepted field"):
        warm.verify(dict(info, strategy=cleared), record, manifest, common.study_directory)
    coefficients = guided_refinement.load_field(field_run)
    coefficients.momenta[0, 0, 0] = float("nan")
    monkeypatch.setattr(guided_refinement, "load_field", lambda _: coefficients)
    with pytest.raises(ValueError, match="fixed refinement basis"):
        guided_refinement.bind(common.study_directory, manifest, record)


def test_reopen_sealed_v1_common_field_check_with_its_original_qc_rules(tmp_path, monkeypatch):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.mesh import sha256_file

    approved, latest = approved_forms_for_common_check(tmp_path, monkeypatch, warnings=False)
    identifier = approved.candidates[0].candidate_id
    current_writer = warm.apply

    def write_v1(plan, choice, protocol):
        plan = current_writer(plan, choice, protocol)
        marker = plan["strategy"]["common_basis_step"]
        marker["version"] = "accepted-direct-common-start-v1"
        del marker["reviewed_warnings"]
        return plan

    # Seal the real manifest with the historical schema. Reopen it with the
    # current verifier; no migration or rewriting of the saved record is allowed.
    with monkeypatch.context() as old_writer:
        old_writer.setattr(warm, "apply", write_v1)
        legacy = guided.next_action(latest.study_directory, "adaptive_form_model_check", identifier)
    manifest = legacy.study_directory / study.STUDY_MANIFEST
    before = sha256_file(manifest)
    reopened = study.load_reference_calibration_study(legacy.study_directory)
    strategy = guided.record(reopened)["strategy"]
    marker = strategy["common_basis_step"]
    assert marker["version"] == "accepted-direct-common-start-v1"
    assert "reviewed_warnings" not in marker
    exact_source = guided_feedback.reference(approved, identifier)
    assert marker["reference"] == reopened.attachment_comparison["refinement"]["reference"]
    assert marker["reference"] == exact_source
    assert warm.seed_evidence(strategy["form_progress"], exact_source["target"], legacy=True)[
        "reference"] == exact_source
    assert sha256_file(manifest) == before
