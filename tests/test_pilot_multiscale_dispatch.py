"""Finite stage dispatch/cancellation and explicit review, no native simulation claims."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from diffeoforge import pilot_multiscale_study as pipeline
from diffeoforge.pilot_multiscale import specification


def declaration():
    values = dict(
        attachment_kernel_width=0.1,
        deformation_kernel_width=0.4,
        initial_control_point_spacing=0.4,
        noise_std=0.025,
    )
    return dict(
        stage="capture",
        specification=specification(
            values, precision="float32", tolerance=1e-6, required_controls=50
        ),
        target="one.vtk",
        family=None,
    )


def test_configuration_removes_old_runtime_but_keeps_source_update_choices_outside_trial():
    old = dict(
        project=dict(parameter_provenance=dict(regional_fit={}, pilot_review={})),
        optimization=dict(
            method="gradient_ascent", freeze_template=False, freeze_control_points=False
        ),
        model=dict(deformation={}),
        runtime=dict(precision="float32"),
    )
    cfg = deepcopy(old)
    pipeline.configure_source(cfg, declaration())
    assert old["optimization"]["method"] == "gradient_ascent"
    assert not old["optimization"]["freeze_template"]
    assert cfg["optimization"]["method"] == "lbfgs"
    assert cfg["optimization"]["max_iterations"] == 120
    assert cfg["optimization"]["convergence_tolerance"] == 1e-6
    assert cfg["model"]["deformation"] == dict(timepoints=37, use_rk2=True)
    assert not {"regional_fit", "pilot_review"} & cfg["project"]["parameter_provenance"].keys()


def scenario(tmp_path, monkeypatch):
    root = tmp_path / "capture"
    root.mkdir()
    request = declaration()
    info = dict(
        strategy=dict(common_multiscale=request, form_progress={}),
        target="one.vtk",
        history=[],
        screen_trials_spent=9,
    )
    capture = SimpleNamespace(
        study_directory=root,
        candidates=[SimpleNamespace(status="completed")],
        attachment_comparison=dict(guided=info),
    )
    detail = SimpleNamespace(study_directory=tmp_path / "detail")
    calls = []
    runner = SimpleNamespace(
        study_directory=root,
        _cancel_requested=False,
        _method_comparison_dispatch=True,
        run_current_stage=lambda **kwargs: calls.append(("run", kwargs)) or detail,
    )
    monkeypatch.setattr(
        pipeline,
        "binding",
        lambda s: dict(directory=str(s.study_directory), manifest_sha256="sealed"),
    )
    monkeypatch.setattr(pipeline, "_capture_field", lambda s: calls.append(("checked", s)))
    monkeypatch.setattr(pipeline, "request", lambda *a, **k: dict(request, stage="detail"))
    monkeypatch.setattr(pipeline.guided, "_origin", lambda r: ("origin", None))

    def prepare(*args, **kwargs):
        calls.append(("prepare", kwargs))
        return detail

    monkeypatch.setattr(pipeline.guided, "_batch", prepare)
    return runner, capture, detail, calls


def test_capture_only_prepares_one_detail_with_local_destination_and_no_fake_review(
    tmp_path, monkeypatch
):
    runner, capture, detail, calls = scenario(tmp_path, monkeypatch)
    assert pipeline.followup(runner, capture, None) is detail
    assert [c[0] for c in calls] == ["checked", "prepare", "run"]
    plan = calls[1][1]
    assert plan["approved"] == [] and plan["goal"] == "common_multiscale"
    assert plan["destination_parent"] == capture.study_directory.parent
    assert plan["strategy"]["common_multiscale"]["stage"] == "detail"
    assert not runner._method_comparison_dispatch
    assert runner.study_directory == detail.study_directory


def test_cancel_before_followup_does_not_prepare_or_launch_another_stage(tmp_path, monkeypatch):
    runner, capture, _, calls = scenario(tmp_path, monkeypatch)
    runner._cancel_requested = True
    assert pipeline.followup(runner, capture, None) is capture
    assert calls == []


def test_cancel_during_preparation_retains_pending_detail_without_launch(tmp_path, monkeypatch):
    runner, capture, detail, calls = scenario(tmp_path, monkeypatch)

    def prepare(*args, **kwargs):
        runner._cancel_requested = True
        return detail

    monkeypatch.setattr(pipeline.guided, "_batch", prepare)
    assert pipeline.followup(runner, capture, None) is detail
    assert [c[0] for c in calls] == ["checked"]
    assert runner.study_directory == detail.study_directory


def test_failed_capture_check_cannot_prepare_detail_or_automatic_recovery(tmp_path, monkeypatch):
    runner, capture, _, calls = scenario(tmp_path, monkeypatch)

    def failed(*args):
        raise ValueError("Capture checks did not pass")

    monkeypatch.setattr(pipeline, "_capture_field", failed)
    with pytest.raises(ValueError, match="Capture checks"):
        pipeline.followup(runner, capture, None)
    assert calls == []


def test_detail_has_no_third_stage(tmp_path, monkeypatch):
    runner, capture, _, calls = scenario(tmp_path, monkeypatch)
    request = pipeline.marker(capture.attachment_comparison)
    request["stage"] = "detail"
    assert pipeline.followup(runner, capture, None) is capture
    assert calls == []


@pytest.mark.parametrize("fault", ["quality", "nan", "far", "warning", "other_form", "endpoint"])
def test_failed_quality_or_geometry_or_identity_never_becomes_a_capture_seed(
    tmp_path, monkeypatch, fault
):
    from diffeoforge import guided_refinement
    from diffeoforge.mesh import sha256_file

    path = tmp_path / "bound.vtk"
    path.write_text("A hash-bound synthetic endpoint; no geometry evaluation in this test")
    row = dict(
        diagonal=1.0,
        repeats=[dict(p95=0.1)],
        warnings=[],
        ordinary_quality=dict(
            passed=True, evaluation=dict(endpoint=dict(path=str(path), sha256=sha256_file(path)))
        ),
    )
    if fault == "quality":
        row["ordinary_quality"]["passed"] = False
    if fault == "nan":
        row["repeats"][0]["p95"] = float("nan")
    if fault == "far":
        row["repeats"][0]["p95"] = 0.151
    if fault == "warning":
        row["warnings"] = ["surface collapsed"]
    if fault == "endpoint":
        path.write_text("changed after qualification")
    c = SimpleNamespace(
        status="completed",
        run_directory=tmp_path,
        metrics=dict(attachment_comparison=dict(subjects={"one.vtk": row})),
    )
    snapshot = SimpleNamespace(
        candidates=[c],
        attachment_comparison=dict(guided=dict(strategy=dict(common_multiscale=declaration()))),
    )
    monkeypatch.setattr(pipeline.study, "calibration_candidate_run_directory", lambda c: tmp_path)
    monkeypatch.setattr(
        guided_refinement,
        "load_field",
        lambda run: SimpleNamespace(
            subject_labels=("other.vtk",) if fault == "other_form" else ("one.vtk",)
        ),
    )
    with pytest.raises(ValueError):
        pipeline._capture_field(snapshot)
