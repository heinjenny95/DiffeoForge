"""Recovery choices use sealed capture/detail evidence, with no native dispatch."""

from types import SimpleNamespace

import pytest

from diffeoforge import guided_feedback
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_qualification_resume as qualification
from diffeoforge.pilot_multiscale_failure import EXECUTION_CANCELLED, diagnose


def scenario(tmp_path, *, stage="capture", status="failed", error=None, code=None):
    candidate = SimpleNamespace(
        candidate_id="varifold",
        status=status,
        run_directory=None,
        error=error,
        failure={"code": code} if code else None,
    )
    declaration = dict(stage=stage, target="one.vtk", accepted_marker=dict(
        reviews=[dict(filename="one.vtk", candidate_id="approved")]))
    record = dict(guided=dict(strategy=dict(common_multiscale=declaration)))
    snapshot = SimpleNamespace(
        study_directory=tmp_path, attachment_comparison=record, status="awaiting_review",
        current_stage=SimpleNamespace(order=1), candidates=(candidate,), early_screening=None,
    )
    return snapshot, candidate


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("Original source geometry must be reviewed before this ordinary check", None),
        ("The template shared.vtk has 3 faces with self-intersections. Inspect it first.",
         "template_geometry"),
    ],
)
def test_shared_template_failures_diagnose_input_and_block_rerun(
    tmp_path, monkeypatch, error, code,
):
    snapshot, candidate = scenario(tmp_path, error=error, code=code)
    failure = diagnose(snapshot, candidate)
    assert failure["action"] == "inspect_template" and failure["detail"] == error

    manifest = dict(source_config=dict(copy="config.yml"),
                    attachment_comparison=snapshot.attachment_comparison)
    monkeypatch.setattr(study, "load_reference_calibration_study", lambda _: snapshot)
    monkeypatch.setattr(study, "_read_json", lambda *_: manifest)
    monkeypatch.setattr(study, "_verify_manifest", lambda *_: manifest)
    monkeypatch.setattr(study, "load_config", lambda _: {})
    snapshot.current_stage.stage_id = "01-attachment"
    study._append_event(tmp_path, "study_created", {})
    study._append_event(tmp_path, "candidate_failed", dict(
        stage_id=snapshot.current_stage.stage_id, candidate_id=candidate.candidate_id,
        attempt=1, run_directory=None, phase="template_preflight", error=error,
    ))
    monkeypatch.setattr(study, "_launch_request", lambda *_: pytest.fail("Native launch attempted"))
    monkeypatch.setattr(study, "_append_event", lambda *_: pytest.fail("Attempt was recorded"))

    runner = study.ReferenceCalibrationStudyRunner(tmp_path)
    runner._method_comparison_dispatch = True
    with pytest.raises(study.ReferenceCalibrationStudyError, match="template.*has"):
        runner.run_current_stage()


def test_unknown_common_failure_reports_retained_fit_without_retry(tmp_path, monkeypatch):
    error = "Reference worker event stream ended without a terminal event"
    snapshot, candidate = scenario(tmp_path, stage="detail", error=error)
    monkeypatch.setattr(guided_feedback, "_same_source",
                        lambda *_: SimpleNamespace(visual_reviews={"approved": True}))
    result = diagnose(snapshot, candidate)
    assert result["title"] == "Detail did not finish"
    assert result["action"] == "inspect" and result["detail"] == error
    assert result["reference"] == dict(candidate_id="approved", target="one.vtk")


@pytest.mark.parametrize(
    ("error", "code"),
    [(EXECUTION_CANCELLED, None), ("Template check cancelled before fitting.",
                                   "template_preflight_cancelled")],
)
def test_verified_cancellation_offers_exact_stage_retry(tmp_path, monkeypatch, error, code):
    snapshot, candidate = scenario(tmp_path, stage="detail", status="interrupted",
                                   error=error, code=code)
    monkeypatch.setattr(qualification, "verified_run", lambda *_: None)
    diagnosis = diagnose(snapshot, candidate)
    assert diagnosis["action"] == "retry" and diagnosis["label"] == "Retry saved detail stage"


def test_completed_native_evidence_keeps_checks_separate_from_retry(tmp_path, monkeypatch):
    snapshot, candidate = scenario(tmp_path, status="interrupted", error=EXECUTION_CANCELLED)
    monkeypatch.setattr(qualification, "verified_run", lambda *_: tmp_path)
    assert diagnose(snapshot, candidate)["action"] == "checks"

    def changed(*_):
        raise ValueError("Changed saved native result")

    monkeypatch.setattr(qualification, "verified_run", changed)
    report = diagnose(snapshot, candidate, include_reference=False)
    assert report["action"] == "inspect" and report["detail"] == "Changed saved native result"


def test_completed_capture_that_fails_checks_cannot_advance(tmp_path):
    snapshot, candidate = scenario(tmp_path, status="completed")
    reason = ValueError("Capture checks did not pass; no detail stage or recovery was started")
    report = diagnose(snapshot, candidate, capture_check_error=reason, include_reference=False)
    assert report["action"] == "inspect"
    assert report["title"] == "Capture checks did not pass" and report["detail"] == str(reason)
