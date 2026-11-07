"""Regional feedback and the reported dead-end route. Synthetic fixtures only."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from test_guided_pilot import approve, origin, run_batch
from test_shape_descriptor import cube

from diffeoforge import pilot_regions as regions
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.pilot_recovery import proposal


def patch(source_hash, **changes):
    return dict(
        dict(
            version=regions.VERSION,
            source_sha256=source_hash,
            space="original_mesh_coordinates",
            center=[0, 0, 0],
            radius=1,
            symptom="detail",
        ),
        **changes,
    )


def reject(snapshot, identifier=None, *, marked=False):
    identifier = identifier or snapshot.candidates[0].candidate_id
    subjects = snapshot.plan.selected_pilot_subjects
    return study.record_reference_calibration_candidate_review(
        snapshot.study_directory,
        candidate_id=identifier,
        approved=False,
        reviewed_subjects=tuple(s.filename for s in subjects),
        subject_decisions={s.filename: "fail" for s in subjects},
        problem_regions={subjects[0].filename: [patch(subjects[0].sha256)]} if marked else {},
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(source_sha256="x" * 64),
        dict(radius=0),
        dict(radius=True),
        dict(radius=float("inf")),
        dict(center=[0, 1, float("nan")]),
        dict(center=[True, 1, 2]),
        dict(space="screen"),
        dict(symptom="tooth_count"),
    ],
)
def test_reject_stale_or_invalid_3d_feedback(change):
    with pytest.raises(ValueError):
        regions.validate({"shape.vtk": [patch("a" * 64, **change)]}, {"shape.vtk": "a" * 64})


def test_feedback_is_bound_to_reviewed_source_and_reopens_without_notes_parsing(
    tmp_path, monkeypatch
):
    child = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    child = reject(child, marked=True)
    name = child.plan.selected_pilot_subjects[0].filename
    expected = child.problem_regions
    assert expected["guided-current"][name][0]["symptom"] == "detail"
    assert study.load_reference_calibration_study(child.study_directory).problem_regions == expected
    with pytest.raises(ValueError, match="inspected"):
        study.record_reference_calibration_candidate_review(
            child.study_directory,
            candidate_id="guided-current",
            approved=False,
            reviewed_subjects=(name,),
            subject_decisions={name: "fail"},
            problem_regions={"unknown.vtk": [patch("a" * 64)]},
        )
    assert study.load_reference_calibration_study(child.study_directory).problem_regions == expected


def test_tie_preference_then_bad_contrasting_form_has_bounded_recovery(tmp_path, monkeypatch):
    first = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    first = approve(approve(first, "guided-current"), "guided-varifold")
    second = run_batch(guided.next_action(first.study_directory, "both_good"), monkeypatch)
    second = reject(approve(second, "guided-varifold"), "guided-current")
    third = run_batch(
        guided.next_action(second.study_directory, "choose", "guided-varifold"), monkeypatch
    )
    assert guided.record(third)["phase"] == "validate"
    third = reject(third)
    assert proposal(third, "guided-varifold", "unsure")["goal"] == "other_method"
    protected = {p: p.read_bytes() for p in third.study_directory.rglob("*") if p.is_file()}
    follow = guided.next_action(third.study_directory, "recover", "guided-varifold", goal="detail")
    assert guided.record(follow)["target"] == guided.record(third)["target"]
    assert len(follow.candidates) == follow.plan.pilot_subject_count == 1
    assert not follow.visual_reviews and not guided.record(follow)["approved"]
    assert follow.plan.effective_values["attachment_kernel_width"] == (
        third.plan.effective_values["attachment_kernel_width"] / 2
    )
    assert all(c.attempts == 0 for c in follow.candidates)
    assert all(
        p.read_bytes() == value for p, value in protected.items() if p.name != study.STUDY_EVENTS
    )
    assert (
        (third.study_directory / study.STUDY_EVENTS)
        .read_bytes()
        .startswith(protected[third.study_directory / study.STUDY_EVENTS])
    )
    # A changed setting cannot reuse old cross-check approvals.
    accepted = approve(run_batch(follow, monkeypatch), "guided-varifold")
    next_form = guided.next_action(accepted.study_directory, "choose", "guided-varifold")
    assert guided.record(next_form)["target"] != guided.record(follow)["target"]
    assert guided.record(next_form)["phase"] == "validate"


def test_uncertain_recovery_changes_only_method_on_same_target(tmp_path, monkeypatch):
    first = approve(run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch))
    single = run_batch(
        guided.next_action(first.study_directory, "choose", "guided-current"), monkeypatch
    )
    single = reject(single)
    follow = guided.next_action(single.study_directory, "recover", "guided-current", goal="unsure")
    assert follow.attachment_comparison["methods"] == {"guided-varifold": "varifold"}
    assert follow.plan.effective_values == single.plan.effective_values
    assert guided.record(follow)["target"] == guided.record(single)["target"]
    assert all(c.attempts == 0 for c in follow.candidates)


def test_region_scale_changes_the_hypothesis_but_never_control_density(tmp_path, monkeypatch):
    child = reject(
        run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch), marked=True
    )
    small_matching = replace(
        child.plan,
        baseline_effective_values=tuple(
            sorted(dict(child.plan.effective_values, attachment_kernel_width=0.01).items())
        ),
    )
    child = replace(child, plan=small_matching)
    assert proposal(child, "guided-current", "detail")["goal"] == "local_motion"
    assert child.plan.effective_values["initial_control_point_spacing"] > 0
    with pytest.raises(ValueError, match="reject"):
        proposal(replace(child, visual_reviews={}), "guided-current", "detail")


def test_marked_patch_is_sampled_even_when_reverse_surface_is_absent(monkeypatch):
    from diffeoforge import reference_fit_search as search

    v, f = cube()
    original = SimpleNamespace(vertices=v, triangles=f)
    fitted = SimpleNamespace(vertices=v + [10, 0, 0], triangles=f)
    face_center = v[f[0]].mean(axis=0)
    row = patch("a" * 64, center=face_center.tolist(), radius=0.01)
    # Analytical separation for this sampling contract; geometric distances are tested separately.
    monkeypatch.setattr(search, "distances_to_surface", lambda p, *_: np.full(len(p), 10.0))
    measured = regions.measure(original, fitted, [row])
    assert measured[0]["selected_faces"] == 1
    assert all(
        r["original_to_fit_p95"] == 10
        and r["fit_to_original_p95"] is None
        and r["reverse_count"] == 0
        for r in measured[0]["repeats"]
    )
    with pytest.raises(ValueError, match="no original face"):
        regions.measure(original, fitted, [patch("a" * 64, center=[100, 0, 0], radius=0.01)])


def test_local_improvement_cannot_hide_a_regression_in_another_global_region():
    def local(value):
        return [
            dict(
                region=patch("a" * 64),
                diagonal=1,
                repeats=[
                    dict(
                        original_to_fit_p95=value,
                        original_to_fit_p99=value,
                        fit_to_original_p95=value,
                    )
                ]
                * 2,
            )
        ]

    def global_(tail):
        return dict(
            repeats=[dict(p95=1, p99=1, regional_tail=1, regions={"other": dict(tail=tail)})] * 2,
            warnings=[],
        )

    assert regions.comparison(local(0.5), local(0.2), global_(0.1), global_(0.5)) == "regression"
    assert regions.comparison(local(0.5), local(0.2), global_(0.1), global_(0.1)) == "improved"
    assert regions.comparison(local(0.5), local(0.5), global_(0.1), global_(0.1)) == "unclear"


def test_visible_recovery_and_both_bound_method_actions_survive_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from pilot_view_helpers import wait_pilot_view
    from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    child = run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch)
    child = reject(reject(child, "guided-current"), "guided-varifold")
    dialog = ReferenceCalibrationDialog(child.study_directory)
    dialog.show()
    try:
        wait_pilot_view(dialog)
        buttons = [
            b
            for b in dialog.content.findChildren(QPushButton)
            if "as starting method" in b.text()
        ]
        assert len(buttons) == 2 and all(b.isVisible() for b in buttons)
        assert all(b.objectName() == "primary" for b in buttons)
        assert not [
            c
            for c in dialog.content.findChildren(QComboBox)
            if c.accessibleName() == "Fit to inspect"
        ]
        queued = []
        monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: queued.append(kw))
        buttons[1].click()
        assert queued == [
            dict(adaptive=False, guided_action=("adaptive_prefer", "guided-varifold", None))
        ]
    finally:
        dialog.close()
        app.processEvents()


def test_brush_highlights_actual_original_faces_and_cancel_does_not_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.mesh_preview import load_mesh_preview
    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.mesh import write_vtk_polydata

    app = QApplication.instance() or QApplication([])
    v, f = cube()
    path = tmp_path / "original.vtk"
    write_vtk_polydata(path, v, f, title="Synthetic region")
    dialog = RegionFeedbackDialog(load_mesh_preview(path))
    assert not dialog.save.isEnabled() and dialog.region is None
    dialog.size.setValue(20)
    dialog._picked(v[f[0]].mean(axis=0))
    layer = dialog.canvas._surface_layer(v, f)
    assert np.array_equal(
        layer.face_colors[:, 0] == 242,
        regions.face_mask(v, f, dialog.center, dialog.diagonal * 0.2),
    )
    assert dialog.save.isEnabled()
    dialog._save()
    assert dialog.region["source_sha256"] == dialog.model.sha256
    assert dialog.region["radius"] == pytest.approx(dialog.diagonal * 0.2)
    # The navigation-state flag stays last, preserving existing picking readiness.
    assert dialog.canvas._frame_key()[-1] is False
    dialog.close()
    app.processEvents()


def test_recovery_carries_measured_regions_and_rejects_changed_source_receipts(
    tmp_path, monkeypatch
):
    import shutil

    from diffeoforge import reference_attachment_comparison as methods
    from diffeoforge import result_report
    from diffeoforge.mesh import sha256_file
    from diffeoforge.pilot_recovery import capture

    real_measure = methods.measure
    child = reject(
        run_batch(guided.prepare(origin(tmp_path).study_directory), monkeypatch), marked=True
    )
    candidate = child.candidates[0]
    target = child.plan.selected_pilot_subjects[0]
    output = candidate.run_directory / "output"
    output.mkdir()
    name = "Fixture__Reconstruction__subject_" + target.filename + ".vtk"
    source = child.study_directory / "inputs" / "subjects" / target.filename
    shutil.copyfile(source, output / name)
    monkeypatch.setattr(
        result_report,
        "collect_run_report",
        lambda _: SimpleNamespace(inventory=[dict(path=name, sha256=sha256_file(output / name))]),
    )
    # The real region sampling and distance worker execute; the run receipts are synthetic.
    baseline = capture(child, candidate.candidate_id, target.filename)
    assert baseline["baseline"] and baseline["global_baseline"]["repeats"]
    follow = guided.next_action(
        child.study_directory, "recover", candidate.candidate_id, goal="detail"
    )
    feedback = guided.record(follow)["feedback"]
    assert feedback == baseline
    assert not follow.visual_reviews and all(c.attempts == 0 for c in follow.candidates)
    measured = real_measure(
        follow.study_directory,
        study._verify_manifest(follow.study_directory),
        follow.candidates[0],
        candidate.run_directory,
    )
    result = measured["attachment_comparison"]["subjects"][target.filename]["marked_regions"]
    assert result["measurements"] and result["outcome"] == "unclear"
    original_result = candidate.run_directory / "result.json"
    original_result.write_bytes(original_result.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="evidence changed|settings changed"):
        study.load_reference_calibration_study(follow.study_directory)
