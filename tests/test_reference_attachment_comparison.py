"""Public synthetic software checks; no optimizer is launched."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_reference_calibration_study import (
    _approve_for_test,
    _CompletedController,
    _metrics,
    _project,
    _stub_learned_seed,
)

from diffeoforge import reference_attachment_comparison as methods
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_sequential_fit as sequence
from diffeoforge.config import load_config
from diffeoforge.mesh import TriangleMesh, sha256_file


def _origin(tmp_path):
    path = _project(tmp_path)
    config = dict(load_config(path))
    config["project"]["parameter_provenance"]["attachment_selection"] = dict(
        version=methods.VERSION,
        mode="auto",
        state="pending",
    )
    study._write_yaml(path, config, overwrite=True)
    return study.create_reference_calibration_study(path, tmp_path / "auto-pilot")


def _detail(names, value=0.01):
    return dict(
        version=methods.VERSION,
        subjects={
            name: dict(
                diagonal=1,
                area_ratio=1,
                volume_ratio=1,
                warnings=[],
                repeats=[
                    dict(
                        p95=value,
                        p99=value * 2,
                        mean=value / 2,
                        regional_tail=value * 3,
                        regions={},
                    )
                    for _ in range(2)
                ],
            )
            for name in names
        },
    )


def _completed(snapshot, *, current=0.02, varifold=0.01):
    names = [s.filename for s in snapshot.plan.selected_pilot_subjects]
    candidates = []
    for c in snapshot.candidates:
        value = (
            current
            if snapshot.attachment_comparison["methods"][c.candidate_id] == "current"
            else varifold
        )
        candidates.append(
            replace(
                c,
                status="completed",
                metrics=dict(
                    invalid_face_count=0,
                    converged=True,
                    attachment_comparison=_detail(names, value),
                ),
            )
        )
    return replace(snapshot, candidates=tuple(candidates), status="awaiting_review")


def test_preparation_is_inert_matched_fresh_and_preserves_originals(tmp_path, monkeypatch):
    origin = _origin(tmp_path)
    protected = {p: sha256_file(p) for p in origin.study_directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Preparation executed a fit"),
    )
    snapshot = methods.prepare(origin.study_directory)
    assert len(snapshot.candidates) == 6
    assert snapshot.plan.selected_pilot_subjects == origin.plan.selected_pilot_subjects
    assert not snapshot.visual_reviews and not snapshot.selected_candidate_ids
    assert all(c.status == "pending" and c.attempts == 0 for c in snapshot.candidates)
    configs = [load_config(c.config_path) for c in snapshot.candidates]
    assert [c["model"]["attachment"]["type"] for c in configs] == ["current"] * 3 + ["varifold"] * 3
    assert {c["optimization"]["max_iterations"] for c in configs} == {120}
    assert all(c["optimization"]["freeze_template"] for c in configs)
    assert all(c["optimization"]["freeze_control_points"] for c in configs)
    assert len({c["model"]["deformation"]["initial_control_points"] for c in configs}) == 1
    assert all("initial_momenta" not in c["model"]["deformation"] for c in configs)
    assert (
        snapshot.plan.effective_values["initial_control_point_spacing"]
        == configs[0]["model"]["deformation"]["initial_control_point_spacing"]
    )
    for a, b in zip(configs[:3], configs[3:], strict=True):
        assert a["model"]["noise_std"] == b["model"]["noise_std"]
        assert a["model"]["attachment"]["kernel_width"] == b["model"]["attachment"]["kernel_width"]
        assert a["model"]["deformation"] == b["model"]["deformation"]
    assert {p: sha256_file(p) for p in protected} == protected
    control = Path(configs[0]["model"]["deformation"]["initial_control_points"])
    control.write_text("changed")
    with pytest.raises(ValueError, match="binding changed"):
        study.load_reference_calibration_study(snapshot.study_directory)


def test_common_geometry_recommendation_ignores_native_objective_and_cannot_approve(tmp_path):
    snapshot = _completed(methods.prepare(_origin(tmp_path).study_directory))
    result = methods.recommendation(snapshot)
    assert result["recommended_method"] == "varifold"
    changed = tuple(
        replace(
            c,
            metrics=dict(
                c.metrics,
                attachment_objective_magnitude=(
                    1e-30 if c.candidate_id.startswith("method-current") else 1e30
                ),
            ),
        )
        for c in snapshot.candidates
    )
    assert methods.recommendation(replace(snapshot, candidates=changed)) == result
    assert not snapshot.visual_reviews and not snapshot.selected_candidate_ids


@pytest.mark.parametrize("issue", ["tradeoff", "overlap", "missing", "shrink", "rejected", "tie"])
def test_ambiguous_or_incomplete_evidence_never_creates_a_default_winner(tmp_path, issue):
    snapshot = _completed(methods.prepare(_origin(tmp_path).study_directory))
    candidates = []
    for candidate in snapshot.candidates:
        detail = candidate.metrics["attachment_comparison"]
        if candidate.candidate_id.startswith("method-varifold"):
            row = next(iter(detail["subjects"].values()))
            if issue == "tradeoff":
                row["repeats"][0]["regional_tail"] = 0.3
                row["repeats"][1]["regional_tail"] = 0.3
            elif issue == "overlap":
                row["repeats"][1].update(p95=0.03, p99=0.05, regional_tail=0.08)
            elif issue == "shrink":
                row["warnings"] = ["Extreme shrinkage"]
            elif issue == "tie":
                detail = _detail(list(detail["subjects"]), 0.02)
        if issue == "missing" and candidate.candidate_id == "method-current-3":
            candidate = replace(candidate, status="failed")
        candidates.append(
            replace(candidate, metrics=dict(candidate.metrics, attachment_comparison=detail))
        )
    reviews = (
        {c.candidate_id: False for c in candidates if "varifold" in c.candidate_id}
        if issue == "rejected"
        else {}
    )
    result = methods.recommendation(
        replace(snapshot, candidates=tuple(candidates), visual_reviews=reviews)
    )
    assert result["recommended_method"] is None


def test_one_regressing_specimen_cannot_hide_in_the_cohort_average(tmp_path):
    snapshot = _completed(
        methods.prepare(_origin(tmp_path).study_directory), current=0.02, varifold=0.001
    )
    for c in snapshot.candidates:
        if "varifold" in c.candidate_id:
            row = next(iter(c.metrics["attachment_comparison"]["subjects"].values()))
            for rep in row["repeats"]:
                rep.update(p95=0.08, p99=0.12, regional_tail=0.2)
    assert methods.recommendation(snapshot)["recommended_method"] is None


def _runner(tmp_path, monkeypatch, controller=_CompletedController):
    origin = _origin(tmp_path)
    _stub_learned_seed(monkeypatch)

    def metric(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("synthetic receipt")
        return _metrics(atlas)

    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", metric)

    def measured(root, manifest, candidate, run):
        names = [r["filename"] for r in manifest["inputs"]["subjects"]]
        value = 0.02 if "current" in candidate.candidate_id else 0.01
        return dict(
            attachment_comparison=_detail(names, value),
            fit_scope="full_targets",
            original_surface_fit={
                name: dict(p95=value, p99=2 * value, mean=value / 2, diagonal=1) for name in names
            },
        )

    monkeypatch.setattr(methods, "measure", measured)
    return study.ReferenceCalibrationStudyRunner(
        origin.study_directory, controller_factory=controller
    ), origin


def test_normal_find_fit_compares_then_pauses_reopens_without_duplicate_fits(tmp_path, monkeypatch):
    runner, origin = _runner(tmp_path, monkeypatch)
    result = sequence.run_specimen_sequence(runner)
    assert result.attachment_comparison and result.status == "awaiting_review"
    assert len(result.candidates) == 6 and all(c.attempts == 1 for c in result.candidates)
    assert not result.visual_reviews and not result.selected_candidate_ids
    assert methods.recommendation(result)["recommended_method"] == "varifold"
    assert sequence.resume_directory(origin.study_directory) == result.study_directory
    again = sequence.run_specimen_sequence(runner)
    assert all(c.attempts == 1 for c in again.candidates)
    with pytest.raises(study.ReferenceCalibrationStudyError, match="visual QC"):
        study.record_reference_calibration_stage_review(
            result.study_directory,
            selected_candidate_id="method-varifold-1",
            visual_approvals={},
        )


def test_choice_is_bound_to_later_stages_and_final_configuration(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch)
    result = runner.run_current_stage()
    cid = "method-varifold-1"
    _approve_for_test(result.study_directory, cid)
    second, _ = study.record_reference_calibration_stage_review(
        result.study_directory,
        selected_candidate_id=cid,
        visual_approvals={},
    )
    assert second.current_stage.order == 2
    planned_ids = {
        c["candidate_id"]
        for c in study._verify_manifest(second.study_directory)["plan"]["stages"][1]["candidates"]
    }
    planned = [c for c in second.candidates if c.candidate_id in planned_ids]
    assert all(
        load_config(c.config_path)["model"]["attachment"]["type"] == "varifold" for c in planned
    )
    assert all(
        load_config(c.config_path)["optimization"]["freeze_template"] is False for c in planned
    )
    assert all(
        load_config(c.config_path)["optimization"]["freeze_control_points"] is False
        for c in planned
    )
    manifest = study._verify_manifest(result.study_directory)
    config = dict(load_config(result.study_directory / manifest["source_config"]["copy"]))
    methods.configure(config, result.study_directory, manifest, None)
    assert config["model"]["attachment"]["type"] == "varifold"
    assert methods.selection(config)["state"] == "selected"
    assert not methods.pending(config)


def test_cancel_stops_before_next_method_and_releases_lock(tmp_path, monkeypatch):
    class Cancel(_CompletedController):
        def run(self, **kwargs):
            result = super().run(**kwargs)
            runner.request_cancel()
            return result

    runner, _ = _runner(tmp_path, monkeypatch, Cancel)
    result = runner.run_current_stage()
    assert sum(c.attempts for c in result.candidates) == 1
    assert methods.recommendation(result)["recommended_method"] is None
    assert not (runner.study_directory / "method-comparison-active.lock").exists()


def test_legacy_pilot_keeps_its_original_dispatch(tmp_path, monkeypatch):
    path = _project(tmp_path)
    snapshot = study.create_reference_calibration_study(path, tmp_path / "legacy")
    runner = study.ReferenceCalibrationStudyRunner(snapshot.study_directory)
    monkeypatch.setattr(methods, "run", lambda *a, **k: pytest.fail("Converted old pilot"))
    runner.request_cancel()
    result = runner.run_current_stage()
    assert result.study_directory == snapshot.study_directory
    assert not result.attachment_comparison


def test_measured_collapse_is_flagged_and_open_mesh_volume_is_unavailable():
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    original = TriangleMesh(points, faces)
    small = TriangleMesh(points * 0.1, faces)
    a, v = methods._area_volume(original)
    b, w = methods._area_volume(small)
    assert b / a == pytest.approx(0.01)
    assert w / v == pytest.approx(0.001)
    assert methods._area_volume(TriangleMesh(points, faces[:-1]))[1] is None


def test_regional_metric_exposes_a_tiny_missing_structure():
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    # Less than 1% of original area lies in this isolated distant component.
    original = TriangleMesh(
        np.concatenate((points, points * 0.04 + [2, 0, 0])), np.concatenate((faces, faces + 4))
    )
    result = methods.compare_geometry(original, TriangleMesh(points, faces))
    assert all(row["p99"] < 0.001 for row in result["repeats"])
    assert all(row["regional_tail"] > 0.9 for row in result["repeats"])


def test_unselected_placeholder_cannot_reach_native_xml(tmp_path):
    from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes
    from diffeoforge.config import ConfigurationError

    origin = _origin(tmp_path)
    manifest = study._verify_manifest(origin.study_directory)
    config = load_config(origin.study_directory / manifest["source_config"]["copy"])
    with pytest.raises(ConfigurationError, match="method comparison"):
        render_engine_file_bytes(config, Path("template.vtk"), [Path("one.vtk"), Path("two.vtk")])


def test_default_ui_exposes_auto_without_skipping_guided_pilot(tmp_path, monkeypatch):
    from test_desktop_calibration import _prepared_window

    app, window, queued = _prepared_window(monkeypatch, tmp_path)
    try:
        assert window.reference_attachment_type_combo.currentData() == "auto"
        window.analyze_reference_parameters_button.click()
        queued.pop(0).run()
        app.processEvents()
        assert window.reference_parameter_profile_combo.currentData() == "data_assisted"
        assert window._request().reference_attachment_type == "auto"
    finally:
        window.close()
        app.processEvents()


def test_comparison_ui_shows_concise_recommendation_and_never_dispatches_on_open(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "desktop-state"))
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QLabel

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication(["attachment-comparison-ui"])
    runner, _ = _runner(tmp_path, monkeypatch)
    snapshot = runner.run_current_stage()
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Opening the view launched a fit"),
    )
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    try:
        wait_pilot_view(dialog)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert any("Varifold recommended" in label for label in labels)
        assert dialog.find_fit_button.isHidden()
        assert dialog.start_button.isHidden()
        assert all(b.isHidden() for b in dialog._continuation_buttons.values())
        assert not dialog.advance_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("method", ["current", "varifold"])
def test_loading_existing_project_restores_its_method_and_mode_edits_unbind_it(
    tmp_path,
    monkeypatch,
    method,
):
    from test_desktop_calibration import _prepared_window

    from diffeoforge.desktop.project_setup import load_existing_reference_project

    app, window, _ = _prepared_window(monkeypatch, tmp_path)
    path = _project(tmp_path)
    config = dict(load_config(path))
    config["model"]["attachment"]["type"] = method
    study._write_yaml(path, config, overwrite=True)
    path.write_text(
        "# Generated by diffeoforge init.\n" + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    try:
        window._project_succeeded(load_existing_reference_project(path))
        assert window.reference_attachment_type_combo.currentData() == method
        assert window._bound_project_matches_form()
        window.reference_attachment_type_combo.setCurrentIndex(
            window.reference_attachment_type_combo.findData("auto")
        )
        assert not window._bound_project_matches_form()
        assert window._reference_calibration_context() is None
    finally:
        window.close()
        app.processEvents()


def test_automatic_context_never_reuses_or_rewrites_an_existing_current_pilot(
    tmp_path,
    monkeypatch,
):
    from test_desktop_calibration import _prepared_window

    from diffeoforge.desktop.project_review import review_project
    from diffeoforge.desktop.project_setup import load_existing_reference_project

    app, window, _ = _prepared_window(monkeypatch, tmp_path)
    path = _project(tmp_path)
    try:
        loaded = load_existing_reference_project(path)
        window._project_succeeded(loaded)
        window._review = review_project(path, loaded.engine)
        _, manual_root = window._reference_calibration_context()
        study.create_reference_calibration_study(path, manual_root)
        protected = {p: sha256_file(p) for p in manual_root.rglob("*") if p.is_file()}
        config = dict(load_config(path))
        config["project"]["parameter_provenance"]["attachment_selection"] = dict(
            version=methods.VERSION,
            mode="auto",
            state="pending",
        )
        study._write_yaml(path, config, overwrite=True)
        path.write_text(
            "# Generated by diffeoforge init.\n" + path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        window._project_succeeded(load_existing_reference_project(path))
        window._review = review_project(path, loaded.engine)
        _, automatic_root = window._reference_calibration_context()
        assert automatic_root != manual_root
        assert "-methods-" in automatic_root.name
        assert sha256_file(path)[:12] in automatic_root.name
        assert not automatic_root.exists()
        assert {p: sha256_file(p) for p in protected} == protected
        assert window.reference_attachment_type_combo.currentData() == "auto"
    finally:
        window.close()
        app.processEvents()


def test_explicit_trial_selection_cannot_silently_expand_to_the_whole_comparison(
    tmp_path,
    monkeypatch,
):
    runner, origin = _runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="complete automatic method comparison"):
        runner.run_current_stage(candidate_ids={origin.candidates[0].candidate_id})
    assert runner.study_directory == origin.study_directory
    prepared = methods.prepare(origin.study_directory)
    runner.study_directory = prepared.study_directory
    result = runner.run_current_stage(candidate_ids={"method-varifold-1"})
    assert sum(c.attempts for c in result.candidates) == 1
    assert next(c for c in result.candidates if c.candidate_id == "method-varifold-1").attempts == 1
    assert methods.recommendation(result)["recommended_method"] is None
    with pytest.raises(ValueError, match="Unknown automatic comparison trial"):
        runner.run_current_stage(candidate_ids={"foreign-trial"})
