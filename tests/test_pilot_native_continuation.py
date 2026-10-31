"""Cumulative pilot dispatch with synthetic controllers and real study journals."""

import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_pilot_completion import _checked

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_continuation as continuation
from diffeoforge import reference_pilot_qualification as qualification
from diffeoforge.config import load_config
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.mesh import sha256_file


def _fixture(tmp_path, monkeypatch):
    runner, snapshot, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    root = snapshot.study_directory
    # The ordinary fixture prohibits new runs after its fixed-state check. Only
    # synthetic controllers are re-enabled here; no native optimizer is used.
    monkeypatch.setattr(runner, "run_current_stage",
                        study.ReferenceCalibrationStudyRunner.run_current_stage.__get__(runner))
    calls = []

    def checkpoint(source):
        config = copy.deepcopy(load_config(source.config_path))
        maximum = source.metrics["maximum_iterations"]
        config["optimization"]["max_iterations"] = maximum
        run = study.calibration_candidate_run_directory(source)
        return SimpleNamespace(manifest=dict(effective_config=config)), dict(
            version=continuation.VERSION, source_run=str(run),
            source_manifest_sha256=sha256_file(run / "manifest.json"),
            checkpoint_sha256="a" * 64, initial_iteration=maximum,
            additional_iterations=300, maximum_iterations=maximum + 300,
            history="Synthetic checkpoint dispatch fixture",
        )

    def request(source, *, request_id, run_id, additional_iterations):
        source = Path(source)
        calls.append((source, additional_iterations))
        event = next(e for e in reversed(study._load_events(root))
                     if e["event"] == "pilot_qualification_declared")
        path = root / event["config"]
        return DesktopReferenceLaunchRequest(
            request_id, path, source.parent / run_id, run_id, sha256_file(path),
            None, None, launcher_type="native", resume_source=source,
            additional_iterations=additional_iterations, launcher_executable="deformetrica",
        )

    collect = study.collect_reference_calibration_run_metrics

    def metrics(run):
        result = collect(run)
        event = next(e for e in reversed(study._load_events(root))
                     if e["event"] == "pilot_qualification_declared")
        maximum = event["checkpoint_continuation"]["maximum_iterations"]
        return replace(result, final_iteration=maximum, maximum_iterations=maximum)

    zero = dict(rms=0.0, p95=0.0, maximum=0.0)
    names = [s.filename for s in snapshot.plan.selected_pilot_subjects]
    monkeypatch.setattr(continuation, "_checkpoint", checkpoint)
    monkeypatch.setattr("diffeoforge.desktop.reference_prelaunch.build_reference_resume_launch_request",
                        request)
    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", metrics)
    monkeypatch.setattr(qualification, "optimizer_check", lambda *a: dict(
        template=zero, subjects={n: zero for n in names},
        velocity_relative={n: 0.0 for n in names},
    ))
    from diffeoforge import reference_adaptive_calibration, reference_pilot_completion

    monkeypatch.setattr(qualification, "shoot", reference_pilot_completion.shoot)
    monkeypatch.setattr(qualification, "bind_learned_seed",
                        reference_adaptive_calibration.bind_learned_seed)
    return runner, snapshot, identifier, calls


def test_two_additional_budgets_chain_latest_checkpoint_and_preserve_source(tmp_path, monkeypatch):
    runner, before, identifier, calls = _fixture(tmp_path, monkeypatch)
    root = before.study_directory
    original = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    source = next(c for c in before.candidates if c.candidate_id == identifier)
    initial = load_config(source.config_path)
    first = continuation.run(runner, identifier)
    one = first.candidates[-1]
    second = continuation.run(runner, identifier)  # Same old card must select its latest child.
    two = second.candidates[-1]
    assert one.metrics["final_iteration"] == 350
    assert two.metrics["final_iteration"] == 650
    assert calls == [(study.calibration_candidate_run_directory(source), 300),
                     (one.run_directory, 300)]
    assert two.metrics["pilot_continuation"]["source_candidate_id"] == one.candidate_id
    assert continuation.latest(second, identifier) == two
    for candidate in (one, two):
        config = load_config(candidate.config_path)
        assert config["optimization"]["convergence_tolerance"] == initial["optimization"][
            "convergence_tolerance"]
        assert config["runtime"]["precision"] == initial["runtime"]["precision"]
        assert config["optimization"]["freeze_template"] == initial["optimization"][
            "freeze_template"]
        assert candidate.candidate_id not in second.visual_reviews
    assert all(p.read_bytes() == data for p, data in original.items()
               if p.name != study.STUDY_EVENTS)
    assert (root / study.STUDY_EVENTS).read_bytes().startswith(original[root / study.STUDY_EVENTS])
    assert study.load_reference_calibration_study(root).candidates == second.candidates


def test_changed_continuation_checkpoint_is_rejected_before_dispatch(tmp_path, monkeypatch):
    _, snapshot, identifier, calls = _fixture(tmp_path, monkeypatch)
    prepared, _ = continuation.prepare(snapshot, identifier)
    events = study._load_events(snapshot.study_directory)
    event = copy.deepcopy(qualification.declarations(events)[-1])
    event["checkpoint_continuation"]["checkpoint_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="settings or checkpoint changed"):
        continuation.verify(prepared.study_directory, event, events)
    assert not calls
