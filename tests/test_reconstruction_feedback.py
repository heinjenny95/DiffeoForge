"""Extra fitted material can be marked without inventing missing original faces."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pilot_regions import EDIT_VERSION, measure, validate
from diffeoforge.reconstruction_feedback import bind, material_mask, verify_review_regions


def bridge(tmp_path):
    coordinates = np.linspace(-1, 1, 21)
    vertices = np.asarray([(x, y, 0) for y in coordinates for x in coordinates])
    triangles = []
    for y in range(20):
        for x in range(20):
            a = y * 21 + x
            triangles.extend(((a, a + 1, a + 21), (a + 1, a + 22, a + 21)))
    faces = np.asarray(triangles)
    original_faces = faces[np.linalg.norm(vertices[faces].mean(1), axis=1) > .45]
    original_path, fit_path = tmp_path / "original.vtk", tmp_path / "fit.vtk"
    write_vtk_polydata(original_path, vertices, original_faces)
    write_vtk_polydata(fit_path, vertices, faces)
    original = SimpleNamespace(vertices=vertices, triangles=original_faces)
    fit = SimpleNamespace(vertices=vertices, triangles=faces,
                          sha256=sha256_file(fit_path), path=fit_path)
    row = dict(version=EDIT_VERSION, source_sha256=sha256_file(original_path),
               space="original_mesh_coordinates", center=[0, 0, 0], radius=.2,
               symptom="distortion", purpose="problem")
    row["reconstruction"] = bind(row, fit)
    return original_path, fit_path, original, fit, row


def test_extra_surface_has_reverse_measurement_and_missing_forward_stays_unknown(tmp_path):
    a, _, original, fit, row = bridge(tmp_path)
    validate({a.name: [row]}, {a.name: sha256_file(a)})
    result, = measure(original, fit, [row])
    assert result["selected_faces"] == 0
    assert result["reverse_selected_faces"] == len(row["reconstruction"]["face_ids"])
    assert all(r["forward_count"] == 0 and r["original_to_fit_p95"] is None
               and r["fit_to_original_p95"] > .2 for r in result["repeats"])
    moved = SimpleNamespace(vertices=fit.vertices + [0, 0, .1], triangles=fit.triangles)
    assert (material_mask(moved.vertices, moved.triangles, [row]).sum()
            == result["reverse_selected_faces"])
    changed = deepcopy(row)
    changed["reconstruction"]["topology_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="connectivity changed"):
        material_mask(fit.vertices, fit.triangles, [changed])
    changed = deepcopy(row)
    changed["purpose"] = "fixed"
    with pytest.raises(ValueError, match="Retain areas"):
        validate({a.name: [changed]}, {a.name: sha256_file(a)})


def test_reconstruction_correction_prepares_explicit_target_support_on_copy(tmp_path):
    from diffeoforge.regional_fit import prepare, read_plan

    a, b, original, fit, row = bridge(tmp_path)
    protected = {p: p.read_bytes() for p in (a, b)}
    declaration = prepare(tmp_path / "regional", b, a, [row], focus_width=.2,
                          focus_noise=.1, protection_noise=.1, retained_path=b)
    plan = read_plan(dict(project=dict(parameter_provenance=dict(regional_fit=declaration))))
    assert plan["material_selection"]["source_faces"] == row["reconstruction"]["face_ids"]
    assert plan["reconstruction_target_support"][0]["biological_correspondence_claim"] is False
    assert plan["reconstruction_target_support"][0]["topology_change_claim"] is False
    assert len(plan["focus_target_face_ids"]) > 0
    assert not plan["anatomical_approval"] and plan["execution_scope"] == "single_specimen_probe"
    assert all(p.read_bytes() == value for p, value in protected.items())
    from diffeoforge.regional_quality import _distances

    measured = _distances(original.vertices, original.triangles, fit.vertices, fit.triangles,
                           [row], target_face_ids=plan["focus_target_face_ids"])
    assert len(measured) == 2 and all(r["fit_to_original_p95"] > .2 for r in measured)


def test_reverse_only_measurements_reach_a_complete_recovery_proposal(tmp_path, monkeypatch):
    from test_regional_fit import proposal_data

    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.regional_pilot import proposal
    from diffeoforge.regional_search import capture_rows

    _, _, original, fit, row = bridge(tmp_path)
    measured = measure(original, fit, [row])
    captured = capture_rows(measured)
    assert captured[0]["original_to_fit_p95"] is None
    assert captured[0]["symmetric_tail"] > .2
    monkeypatch.setattr(guided, "record", lambda _: dict(goal="regional", pilot_order=[1]))
    data = proposal_data()
    data["regions"] = [row]
    data["regional_capture"] = dict(original_to_fit_p95=None,
                                    symmetric_tail=captured[0]["symmetric_tail"],
                                    per_region=captured)
    result = proposal(None, "x", data, symptom="distortion")
    assert result["goal"] == "regional" and result["available"]
    assert result["regional_recipe"]["guide_noise"] is None
    assert "cannot remove a true topological connection" in result["reason"]
    assert result["regions"] == [row]
    for symptom in ("gap", "position"):
        altered = deepcopy(data)
        altered["regions"][0]["symptom"] = symptom
        result = proposal(None, "x", altered, symptom=symptom)
        assert not result["available"] and "original-surface goal" in result["blocked_reason"]


@pytest.mark.parametrize("protection", ["fixed", "preserve"])
def test_reconstruction_red_and_existing_original_green_prepare_together(tmp_path, protection):
    from diffeoforge.regional_fit import prepare, read_plan

    a, b, original, _, row = bridge(tmp_path)
    green = dict(version=EDIT_VERSION, source_sha256=sha256_file(a),
                 space="original_mesh_coordinates", center=[-.75, -.75, 0], radius=.3,
                 symptom="shape", purpose=protection)
    declaration = prepare(tmp_path / "regional", b, a,
        [green] if protection == "preserve" else [row], focus_regions=[row],
        fixed_regions=[green] if protection == "fixed" else [],
        guide_noise=.1 if protection == "preserve" else None,
        focus_width=.2, focus_noise=.1, protection_noise=.1, retained_path=b)
    plan = read_plan(dict(project=dict(parameter_provenance=dict(regional_fit=declaration))))
    assert plan["reconstruction_target_support"]
    if protection == "fixed":
        assert plan["fixed_vertex_ids"] and plan["fixed_protection"]["vertices"] >= 3
    else:
        assert plan["guidance"] and any(o["id"] == "featureguides" for o in plan["objects"])
    assert len(plan["focus_target_face_ids"]) < len(original.triangles)


def test_new_marks_must_bind_to_the_exact_inspected_reconstruction(tmp_path, monkeypatch):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import regional_evaluation, result_report

    a, b, _, _, row = bridge(tmp_path)
    candidate = SimpleNamespace(candidate_id="example")
    snapshot = SimpleNamespace(problem_regions={}, attachment_comparison={})
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _c: tmp_path)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _p: SimpleNamespace(
        manifest=dict(effective_config=dict(model=dict(object_id="surface")))))
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda *_a, **_k: dict(
        path=str(b), sha256=sha256_file(b)))
    verify_review_regions(snapshot, candidate, {a.name: [row]})
    changed = deepcopy(row)
    changed["reconstruction"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="exact inspected reconstruction"):
        verify_review_regions(snapshot, candidate, {a.name: [changed]})
    changed = deepcopy(row)
    changed["reconstruction"]["face_ids"] = [0]
    with pytest.raises(ValueError, match="differ from the marked brush"):
        verify_review_regions(snapshot, candidate, {a.name: [changed]})
    b.write_text("changed")
    with pytest.raises((ValueError, RuntimeError)):
        verify_review_regions(snapshot, candidate, {a.name: [row]})


def test_only_diagnosis_can_change_without_reselecting_saved_material(tmp_path, monkeypatch):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import regional_evaluation, result_report
    from diffeoforge.pilot_regions import BOX_VERSION
    from diffeoforge.reconstruction_feedback import same_saved_material_mark

    original, _, _, fit, saved = bridge(tmp_path)
    saved.update(version=BOX_VERSION, shape="box", bounds=[-.2, .2] * 3)
    saved["reconstruction"] = bind(saved, fit)
    current = tmp_path / "next.vtk"
    write_vtk_polydata(current, fit.vertices + [0, 0, .1], fit.triangles)
    candidate = SimpleNamespace(candidate_id="saved")
    snapshot = SimpleNamespace(problem_regions={"saved": {original.name: [deepcopy(saved)]}},
                               attachment_comparison={})
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _: tmp_path)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _: SimpleNamespace(
        manifest=dict(effective_config=dict(model=dict(object_id="surface")))))
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda *_a, **_k: dict(
        path=str(current), sha256=sha256_file(current)))

    edited = dict(saved, symptom="unsure")
    verified = validate({original.name: [edited]}, {original.name: sha256_file(original)})
    verify_review_regions(snapshot, candidate, verified)
    assert saved["symptom"] == "distortion" and saved["reconstruction"] == edited["reconstruction"]
    for changes in (
        dict(center=[.01, 0, 0]), dict(bounds=[-.3, .2] * 3), dict(radius=.3),
        dict(source_sha256="1" * 64), dict(reconstruction=dict(saved["reconstruction"],
                                                               face_ids=[0])),
        dict(reconstruction=dict(saved["reconstruction"], topology_sha256="2" * 64)),
        dict(reconstruction=dict(saved["reconstruction"], sha256="3" * 64)),
    ):
        altered = dict(edited, **changes)
        assert not same_saved_material_mark(altered, [saved])
        with pytest.raises(ValueError, match="exact inspected reconstruction"):
            verify_review_regions(snapshot, candidate, {original.name: [altered]})
    protected = dict(edited, purpose="fixed")
    assert not same_saved_material_mark(protected, [saved])
    with pytest.raises(ValueError, match="Retain areas"):
        validate({original.name: [protected]}, {original.name: sha256_file(original)})


@pytest.mark.parametrize("route", ["feedback", "working"])
def test_feedback_and_selected_earlier_fit_reject_stale_or_forged_material_before_append(
    tmp_path, monkeypatch, route,
):
    from diffeoforge import guided_feedback, guided_working_fit, regional_evaluation, result_report
    from diffeoforge import reference_calibration_study as study

    a, b, _, _, row = bridge(tmp_path)
    candidate = SimpleNamespace(candidate_id="example")
    snapshot = SimpleNamespace(problem_regions={}, attachment_comparison={},
                               study_directory=tmp_path, candidates=[candidate])
    ref = dict(target=a.name, candidate_id="example")
    appended = []
    monkeypatch.setattr(study, "load_reference_calibration_study", lambda _: snapshot)
    monkeypatch.setattr(study, "_verify_manifest", lambda _: dict(inputs=dict(subjects=[
        dict(filename=a.name, sha256=sha256_file(a))])))
    monkeypatch.setattr(study, "_append_event", lambda *args: appended.append(args))
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _c: tmp_path)
    monkeypatch.setattr(result_report, "collect_run_report", lambda _p: SimpleNamespace(
        manifest=dict(effective_config=dict(model=dict(object_id="surface")))))
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda *_a, **_k: dict(
        path=str(b), sha256=sha256_file(b)))
    monkeypatch.setattr(guided_feedback, "reference", lambda *_: ref)
    monkeypatch.setattr(guided_feedback, "_same_source", lambda *_: None)
    monkeypatch.setattr(guided_feedback, "verify_reference", lambda *_: snapshot)
    monkeypatch.setattr(guided_feedback, "region_state", lambda *_: ([], False))
    monkeypatch.setattr(guided_feedback, "choices", lambda *_: [dict(reference=ref)])
    decision = dict(reference=ref, comparison=dict(ref, candidate_id="other"), outcome="better",
                    inspected_subjects=[a.name], display_scopes={a.name: "preview"},
                    problem_regions={a.name: [row]})
    save = guided_feedback.save_feedback if route == "feedback" else guided_working_fit.save
    for key, value, message in (("sha256", "f" * 64, "exact inspected reconstruction"),
                                ("face_ids", [0], "differ from the marked brush")):
        invalid = deepcopy(decision)
        invalid["problem_regions"][a.name][0]["reconstruction"][key] = value
        with pytest.raises(ValueError, match=message):
            save(tmp_path, "example", invalid)
        assert not appended
    save(tmp_path, "example", decision)
    assert len(appended) == 1


def test_editor_saves_and_reopens_reco_only_mark_and_responsive_panel(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh

    app = QApplication.instance() or QApplication([])
    a, b, _, _, _ = bridge(tmp_path)
    original = load_region_marking_mesh(a, sha256_file(a))
    fit = load_region_marking_mesh(b, sha256_file(b))
    dialog = RegionFeedbackDialog(original, fit_preview=fit.model)
    try:
        dialog._fit_ready(fit.model.sha256, fit)
        dialog.pick_surface.setCurrentIndex(1)
        dialog.size.setValue(7)
        dialog._picked([0, 0, 0])
        assert dialog._rows[0].get("reconstruction")
        assert dialog.marking.count(dialog._rows[0]) == 0
        assert dialog.save.isEnabled() and "reconstruction faces" in dialog.status.text()
        dialog._save()
        assert dialog.regions == dialog._rows
        reopened = RegionFeedbackDialog(original, fit_preview=fit.model, regions=dialog.regions)
        try:
            reopened._fit_ready(fit.model.sha256, fit)
            assert reopened.save.isEnabled()
            reopened.resize(1024, 768)
            reopened.show()
            app.processEvents()
            assert reopened.body.orientation() == Qt.Orientation.Horizontal
            assert reopened.canvas.geometry().right() < reopened.side.geometry().left()
            assert reopened.action.geometry().right() < reopened.side.widget().width()
            reopened.resize(700, 650)
            app.processEvents()
            assert reopened.body.orientation() == Qt.Orientation.Vertical
            assert reopened.canvas.geometry().bottom() < reopened.side.geometry().top()
        finally:
            reopened.close()
    finally:
        dialog.close()
        app.processEvents()
