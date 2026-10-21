"""Synthetic software qualification. No native optimizer or owner data."""

from dataclasses import replace
from pathlib import Path

import pytest
from test_reference_attachment_comparison import _detail
from test_reference_calibration import _recommendation
from test_reference_calibration_study import (
    _approve_for_test,
    _CompletedController,
    _metrics,
    _project,
    _stub_learned_seed,
)
from test_shape_descriptor import cube

from diffeoforge import reference_attachment_comparison as methods
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pilot_design import coverage_suggestion, suggest_templates
from diffeoforge.reference_recommendation import MeshGeometryObservation
from diffeoforge.reference_sequential_fit import resume_directory
from diffeoforge.shape_descriptor import surface_shape_descriptor


def origin(tmp_path):
    config_path = _project(tmp_path)
    config = load_config(config_path)
    config["project"]["parameter_provenance"]["attachment_selection"] = dict(
        version=methods.VERSION, mode="auto", state="pending", workflow=guided.VERSION
    )
    study._write_yaml(config_path, config, overwrite=True)
    return study.create_reference_calibration_study(config_path, tmp_path / "pilot")


def run_batch(snapshot, monkeypatch, *, controller=_CompletedController):
    _stub_learned_seed(monkeypatch)

    def metric(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("synthetic receipt")
        return replace(
            _metrics(atlas), subject_reconstruction_count=snapshot.plan.pilot_subject_count
        )

    def measured(root, manifest, candidate, run):
        names = [r["filename"] for r in manifest["inputs"]["subjects"]]
        return dict(
            attachment_comparison=_detail(names),
            fit_scope="full_targets",
            original_surface_fit={
                n: dict(p95=0.01, p99=0.02, mean=0.005, diagonal=1) for n in names
            },
        )

    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", metric)
    monkeypatch.setattr(methods, "measure", measured)
    runner = study.ReferenceCalibrationStudyRunner(
        snapshot.study_directory, controller_factory=controller
    )
    return runner.run_current_stage()


def approve(snapshot, identifier=None):
    identifier = identifier or snapshot.candidates[0].candidate_id
    _approve_for_test(snapshot.study_directory, identifier)
    return study.load_reference_calibration_study(snapshot.study_directory)


def test_new_protocol_prepares_only_two_single_target_trials_and_cannot_approve(
    tmp_path, monkeypatch
):
    parent = origin(tmp_path)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("Preparation ran an optimizer"),
    )
    protected = {p: sha256_file(p) for p in parent.study_directory.rglob("*") if p.is_file()}
    child = methods.prepare(parent.study_directory)
    assert len(child.candidates) == 2
    assert child.plan.pilot_subject_count == 1
    assert child.plan.execution_scope == "single_specimen_probe"
    assert not child.visual_reviews and not child.selected_candidate_ids
    a, b = [load_config(c.config_path) for c in child.candidates]
    assert a["model"]["attachment"]["type"] == "current"
    assert b["model"]["attachment"]["type"] == "varifold"
    assert a["model"]["attachment"]["kernel_width"] == b["model"]["attachment"]["kernel_width"]
    assert a["model"]["deformation"] == b["model"]["deformation"]
    assert a["model"]["noise_std"] == b["model"]["noise_std"]
    assert all(c.status == "pending" and c.attempts == 0 for c in child.candidates)
    assert {p: sha256_file(p) for p in protected} == protected
    with pytest.raises(ValueError, match="Complete or resolve"):
        guided.next_action(child.study_directory, "choose", "guided-current")


def test_visual_tie_prepares_another_form_with_both_methods_and_no_fits(tmp_path, monkeypatch):
    child = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    child = approve(approve(child, "guided-current"), "guided-varifold")
    assert methods.recommendation(child)["recommended_candidate_id"] is None
    next_batch = guided.next_action(child.study_directory, "both_good")
    assert next_batch.plan.pilot_subject_count == 1 and len(next_batch.candidates) == 2
    assert guided.record(next_batch)["target"] != guided.record(child)["target"]
    assert guided.record(next_batch)["screen_trials_spent"] == 4
    assert all(c.attempts == 0 for c in next_batch.candidates)
    assert not next_batch.visual_reviews
    assert resume_directory(child.study_directory) == next_batch.study_directory
    with pytest.raises(ValueError, match="newer"):
        guided.next_action(child.study_directory, "choose", "guided-current")


def test_rejection_is_not_a_method_win_and_changes_one_parameter_only(tmp_path, monkeypatch):
    child = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    names = [s.filename for s in child.plan.selected_pilot_subjects]
    for c in child.candidates:
        study.record_reference_calibration_candidate_review(
            child.study_directory,
            candidate_id=c.candidate_id,
            approved=False,
            reviewed_subjects=names,
            subject_decisions={n: "fail" for n in names},
        )
    child = study.load_reference_calibration_study(child.study_directory)
    with pytest.raises(ValueError, match="Check alignment"):
        guided.next_action(child.study_directory, "both_bad")
    follow = guided.next_action(child.study_directory, "both_bad", goal="detail")
    before, after = child.plan.effective_values, follow.plan.effective_values
    assert after["attachment_kernel_width"] == before["attachment_kernel_width"] / 2
    assert {k: v for k, v in after.items() if k != "attachment_kernel_width"} == {
        k: v for k, v in before.items() if k != "attachment_kernel_width"
    }
    assert not follow.visual_reviews and guided.record(follow)["approved"] == []


def test_choice_crosschecks_once_per_new_form_then_prepares_full_joint_check(tmp_path, monkeypatch):
    parent = origin(tmp_path)
    child = run_batch(guided.prepare(parent.study_directory), monkeypatch)
    child = approve(child, "guided-varifold")
    selected = guided.next_action(child.study_directory, "choose", "guided-varifold")
    seen = {guided.record(child)["target"]}
    while guided.record(selected)["phase"] != "joint":
        assert len(selected.candidates) == 1 and selected.plan.pilot_subject_count == 1
        assert guided.record(selected)["target"] not in seen
        seen.add(guided.record(selected)["target"])
        selected = approve(run_batch(selected, monkeypatch))
        selected = guided.next_action(selected.study_directory, "approve", "guided-varifold")
    assert seen == {s.filename for s in parent.plan.selected_pilot_subjects}
    assert selected.plan.pilot_subject_count == parent.plan.pilot_subject_count
    assert len(selected.candidates) == 1 and not selected.visual_reviews
    assert (
        load_config(selected.candidates[0].config_path)["model"]["attachment"]["type"] == "varifold"
    )
    joint = approve(run_batch(selected, monkeypatch))
    checked = guided.next_action(joint.study_directory, "finish_joint", "guided-varifold")
    assert checked.current_stage.order == 4
    assert not any(c.attempts for c in checked.candidates if c.status == "pending")
    assert any(c.status == "completed" for c in checked.candidates)
    manifest = study._verify_manifest(checked.study_directory)
    config = load_config(checked.study_directory / manifest["source_config"]["copy"])
    methods.configure(config, checked.study_directory, manifest, None)
    assert config["model"]["attachment"]["type"] == "varifold"


def test_withdrawn_review_invalidates_dependent_crosscheck(tmp_path, monkeypatch):
    first = approve(run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch))
    following = guided.next_action(first.study_directory, "choose", "guided-current")
    names = [s.filename for s in first.plan.selected_pilot_subjects]
    study.record_reference_calibration_candidate_review(
        first.study_directory,
        candidate_id="guided-current",
        approved=False,
        reviewed_subjects=names,
        subject_decisions={n: "fail" for n in names},
    )
    with pytest.raises(ValueError, match="approve"):
        study.load_reference_calibration_study(following.study_directory)


def test_suggestion_is_cached_and_preserves_all_inputs(tmp_path, monkeypatch):
    vertices, faces = cube()
    paths = []
    for index, stretch in enumerate((1, 1.01, 1.02, 3)):
        path = tmp_path / f"shape-{index}.vtk"
        write_vtk_polydata(path, vertices * [stretch, 1, 1], faces, title="Synthetic")
        paths.append(path)
    before = {p: sha256_file(p) for p in paths}
    result = suggest_templates(paths, cache_directory=tmp_path / "cache")
    assert result["candidates"][0]["filename"] != "shape-3.vtk"
    monkeypatch.setattr(
        "diffeoforge.pilot_design._measure_surface",
        lambda *_args: pytest.fail("Warm suggestion reparsed geometry"),
    )
    assert suggest_templates(paths, cache_directory=tmp_path / "cache") == result
    assert {p: sha256_file(p) for p in paths} == before


def test_coverage_skips_duplicate_extreme_but_retains_new_direction_and_manual_choice():
    vertices, faces = cube()
    shapes = [
        ("middle", [1, 1, 1]),
        ("long", [3, 1, 1]),
        ("long-copy", [3, 1, 1]),
        ("wide", [1, 3, 1]),
    ]
    observations = tuple(
        MeshGeometryObservation(
            filename=name + ".vtk",
            sha256=str(i) * 64,
            points=8,
            triangles=12,
            bounding_box_diagonal=4,
            rms_radius=1,
            median_sampled_edge_length=1,
            shape_descriptor=surface_shape_descriptor(vertices * stretch, faces),
        )
        for i, (name, stretch) in enumerate(shapes)
    )
    recommendation = replace(
        _recommendation(),
        observations=(observations[0], *observations),
        subject_count=4,
        mesh_count=5,
    )
    result = coverage_suggestion(recommendation)
    names = [r["filename"] for r in result["selected"]]
    assert "wide.vtk" in names
    assert not {"long.vtk", "long-copy.vtk"} <= set(names)
    assert result["recommended_count"] == 3
    required = coverage_suggestion(recommendation, required=("long.vtk", "long-copy.vtk"))
    assert {"long.vtk", "long-copy.vtk"} <= {r["filename"] for r in required["selected"]}


def test_guided_dialog_opens_inert_and_tie_prepares_only_the_next_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    child = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    child = approve(approve(child, "guided-current"), "guided-varifold")
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("View/transition dispatched an optimizer"),
    )
    dialog = ReferenceCalibrationDialog(child.study_directory)
    try:
        wait_pilot_view(dialog)
        assert dialog.start_button.isHidden()
        assert dialog.find_fit_button.isHidden()
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert any("Current uses oriented surfaces" in t for t in labels)
        button = next(
            b for b in dialog.findChildren(QPushButton) if b.text().startswith("Both good")
        )
        assert button.isEnabled()
        queued = []
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        button.click()
        assert len(queued) == 1
        queued.pop().run()
        wait_pilot_view(dialog)
        assert dialog.snapshot.study_directory != child.study_directory
        assert dialog.snapshot.plan.pilot_subject_count == 1
        assert all(c.attempts == 0 for c in dialog.snapshot.candidates)
    finally:
        dialog.close()
        app.processEvents()


def test_template_panel_never_changes_a_manual_choice_without_use(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

    from diffeoforge.desktop.template_suggestion import TemplateSuggestionPanel

    app = QApplication.instance() or QApplication([])
    paths = tuple(sorted((Path(__file__).parents[1] / "examples/synthetic/meshes").glob("*.vtk")))
    window = QWidget()
    window.mesh_edit = QLineEdit(str(paths[0].parent))
    window.pattern_edit = QLineEdit("*.vtk")
    window.template_edit = QLineEdit(str(paths[-1]))
    window._worker = None
    window._adopt_template_format_pattern = lambda *_args: None
    panel = TemplateSuggestionPanel(window)
    assert callable(panel.window) and panel.window() is window
    result = suggest_templates(paths)
    panel._loaded(paths, result)
    assert window.template_edit.text() == str(paths[-1])
    panel._apply()
    assert window.template_edit.text() == result["candidates"][0]["path"]
    assert window._template_suggestion_accepted["sha256"] == result["candidates"][0]["sha256"]
    window.close()
    app.processEvents()


def test_legacy_upgrade_is_explicit_inert_separate_and_preserves_old_evidence(
    tmp_path, monkeypatch
):
    from test_reference_attachment_comparison import _origin

    old = methods.prepare(_origin(tmp_path).study_directory)
    protected = {p: sha256_file(p) for p in old.study_directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("Upgrade dispatched an optimizer"),
    )
    child = guided.upgrade(old.study_directory, cache_directory=tmp_path / "cache")
    assert guided.record(child)["version"] == guided.VERSION
    assert len(child.candidates) == 2 and child.plan.pilot_subject_count == 1
    assert child.study_directory != old.study_directory
    assert not child.visual_reviews and not child.selected_candidate_ids
    assert resume_directory(old.study_directory) == child.study_directory
    assert {p: sha256_file(p) for p in protected} == protected


def test_screening_budget_and_transition_lock_cannot_be_silently_bypassed(tmp_path):
    parent = origin(tmp_path)
    with pytest.raises(ValueError, match="budget is exhausted"):
        guided._batch(
            parent,
            None,
            phase="screen",
            target=parent.plan.selected_pilot_subjects[0].filename,
            methods=("current", "varifold"),
            values=parent.plan.effective_values,
            approved=(),
            history=(),
            spent=11,
        )
    child = guided.prepare(parent.study_directory)
    lock = child.study_directory / "guided-transition-active.lock"
    lock.mkdir()
    with pytest.raises(ValueError, match="active or needs explicit recovery"):
        guided.next_action(child.study_directory, "both_good")
    assert lock.exists()


def test_individual_screen_cannot_skip_joint_check_via_legacy_selection_api(tmp_path, monkeypatch):
    first = approve(run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch))
    with pytest.raises(study.ReferenceCalibrationStudyError, match="guided method/coverage"):
        study.record_reference_calibration_stage_review(
            first.study_directory, selected_candidate_id="guided-current", visual_approvals={}
        )
    assert not study.load_reference_calibration_study(first.study_directory).selected_candidate_ids


def test_failed_method_does_not_block_explicitly_approved_alternative(tmp_path, monkeypatch):
    class FailCurrent(_CompletedController):
        def run(self, *, event_callback=None):
            if "guided-current" in str(self.request.config_path):
                raise RuntimeError("Synthetic method failure")
            return super().run(event_callback=event_callback)

    first = run_batch(
        guided.prepare(origin(tmp_path).study_directory), monkeypatch, controller=FailCurrent
    )
    assert {c.status for c in first.candidates} == {"failed", "completed"}
    first = approve(first, "guided-varifold")
    next_batch = guided.next_action(first.study_directory, "choose", "guided-varifold")
    assert guided.record(next_batch)["phase"] == "validate"
    assert not next_batch.visual_reviews
