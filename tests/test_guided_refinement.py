"""Field-preserving refinement with honest incompatible starts and rollback."""

import copy

import numpy as np
import pytest
from test_guided_feedback import attempted, decision
from test_guided_pilot import run_batch
from test_interactive_pilot import initial
from test_pilot_region_feedback import reject
from test_reference_attachment_comparison import _detail

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.guided_refinement import geometry_guard
from diffeoforge.mesh import sha256_file


def test_detail_probe_keeps_nonzero_field_basis_and_original_files(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    values = base.plan.effective_values
    before = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    child = guided.next_action(
        base.study_directory, "adaptive_recover", "guided-varifold", goal="detail"
    )
    record = child.attachment_comparison["refinement"]
    assert record["initialization"] == "learned"
    candidate = child.candidates[0]
    config = load_config(candidate.config_path)
    inputs = validate_input_paths(config, candidate.config_path)
    assert inputs.initial_momenta is not None
    assert np.any(np.loadtxt(inputs.initial_momenta, skiprows=1) != 0)
    assert config["model"]["deformation"]["kernel_width"] == values["deformation_kernel_width"]
    assert (
        config["model"]["deformation"]["initial_control_point_spacing"]
        == values["initial_control_point_spacing"]
    )
    assert config["model"]["attachment"]["kernel_width"] == values["attachment_kernel_width"] * 0.9
    assert all(
        sha256_file(p) == digest for p, digest in before.items() if p.name != study.STUDY_EVENTS
    )
    assert not child.visual_reviews and candidate.attempts == 0
    with inputs.initial_momenta.open("a") as handle:
        handle.write("0 0 0\n")
    with pytest.raises(ValueError, match="field bytes"):
        study.load_reference_calibration_study(child.study_directory)


def test_explicit_basis_change_is_declared_fresh_and_has_no_momenta(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    child = guided.next_action(
        base.study_directory, "adaptive_recover", "guided-varifold", goal="goal:local_motion"
    )
    assert child.attachment_comparison["refinement"]["initialization"] == "fresh"
    config = load_config(child.candidates[0].config_path)
    assert "initial_momenta" not in config["model"]["deformation"]
    assert child.candidates[0].attempts == 0 and not child.visual_reviews


def test_protected_method_check_keeps_momenta_but_still_rejects_changed_movement_basis(
    tmp_path, monkeypatch,
):
    import shutil

    import yaml

    from diffeoforge.guided_refinement import bind

    base = reject(run_batch(initial(tmp_path), monkeypatch), 'guided-varifold')
    child = guided.next_action(base.study_directory, 'adaptive_recover',
        'guided-varifold', goal='detail')
    manifest = copy.deepcopy(study._verify_manifest(child.study_directory))
    record = copy.deepcopy(child.attachment_comparison)
    root = tmp_path/'same-field-method-check'
    root.mkdir()
    source = child.study_directory/manifest['source_config']['copy']
    destination = root/manifest['source_config']['copy']
    destination.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config(source)
    cfg['model']['attachment']['type'] = 'current'
    destination.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    manifest['source_config']['sha256'] = sha256_file(destination)
    record['methods'] = {'guided-current': 'current'}
    record['guided']['strategy']['regional_recipe'] = dict(phase='coarse_method_check',
        residual=False, whole_surface_contrast=dict(existing_broad_basis_retained=True))
    result = bind(root, manifest, record)
    assert result['refinement']['initialization'] == 'learned'
    contrast = result['refinement']['attachment_contrast']
    assert contrast['from_method'] == 'varifold' and contrast['to_method'] == 'current'
    assert contrast['deformation_basis_unchanged'] and contrast['initial_momenta_unchanged']
    assert sha256_file(root/result['refinement']['momenta']['copy']) == (
        child.attachment_comparison['refinement']['momenta']['sha256'])
    changed = tmp_path/'changed-basis-method-check'
    changed.mkdir()
    target = changed/manifest['source_config']['copy']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destination, target)
    manifest['plan']['baseline_effective_values']['deformation_kernel_width'] *= .8
    assert bind(changed, manifest, record)['refinement']['initialization'] == 'fresh'


def test_global_alternative_cannot_reinterpret_a_residual_without_its_prefix(tmp_path, monkeypatch):
    from diffeoforge import guided_refinement, regional_fit

    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    original_load, original_plan = guided_refinement.load_field, regional_fit.read_plan
    field_configs = []

    def residual_field(run):
        loaded = original_load(run)
        field_configs.append(loaded.run_report.manifest["effective_config"])
        return loaded

    monkeypatch.setattr(guided_refinement, "load_field", residual_field)
    monkeypatch.setattr(regional_fit, "read_plan", lambda config:
        dict(residual=dict(prefix=True)) if any(config is c for c in field_configs)
        else original_plan(config))
    child = guided.next_action(base.study_directory, "adaptive_recover", "guided-varifold",
                               goal="goal:weight")
    record = child.attachment_comparison["refinement"]
    assert record["initialization"] == "fresh" and "preserved prefix" in record["reason"]
    config = load_config(child.candidates[0].config_path)
    assert "initial_momenta" not in config["model"]["deformation"]
    assert all(c.attempts == 0 for c in child.candidates)


def test_worse_detail_keeps_first_reference_and_next_probe_same_basis(tmp_path, monkeypatch):
    base, trial = attempted(tmp_path, monkeypatch)
    selected = feedback.save_feedback(
        trial.study_directory, "guided-varifold", decision(base, trial, "worse")
    )
    proposal = strategy.trial_proposal(selected, "guided-varifold", "detail")
    assert proposal["goal"] in {"detail", "weight"}
    assert proposal["anchor"] == feedback.reference(base, "guided-varifold")
    assert (
        proposal["values"]["deformation_kernel_width"]
        == base.plan.effective_values["deformation_kernel_width"]
    )
    assert (
        proposal["values"]["initial_control_point_spacing"]
        == base.plan.effective_values["initial_control_point_spacing"]
    )
    assert not selected.visual_reviews


def test_guard_exposes_global_regression_without_auto_approving():
    before = _detail(["test.vtk"], 0.01)["subjects"]["test.vtk"]
    after = copy.deepcopy(before)
    for row in after["repeats"]:
        row.update(p95=0.08, p99=0.1, mean=0.05)
    guard = geometry_guard(before, after)
    assert guard["outcome"] == "regression" and guard["severe"]
    assert set(guard["worsened"]) == {"p95", "p99", "mean"}
    assert geometry_guard(before, before)["outcome"] == "no_measured_regression"


def test_better_feedback_alone_does_not_promote_a_severe_regression(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    trial = guided.next_action(
        base.study_directory, "adaptive_recover", "guided-varifold", goal="detail"
    )
    trial = run_batch(trial, monkeypatch, refinement_guard=dict(severe=True, outcome="regression"))
    selected = feedback.save_feedback(
        trial.study_directory, "guided-varifold", decision(base, trial, "better")
    )
    assert feedback.selection(selected, "guided-varifold") == feedback.reference(
        base, "guided-varifold"
    )
    assert not selected.visual_reviews
