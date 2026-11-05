"""Finish/reopen/native-XML budget transfer with real journals and fake execution."""

import ast
import copy

import pytest
from test_pilot_completion import _approve_preview
from test_pilot_native_continuation import _fixture

from diffeoforge import iteration_budget
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_completion as completion
from diffeoforge import reference_pilot_continuation as continuation
from diffeoforge.config import ConfigurationError, load_config, validate_schema
from diffeoforge.runs import prepare_run


def ready(tmp_path, monkeypatch, count=1):
    runner, original, identifier, calls = _fixture(tmp_path, monkeypatch)
    _approve_preview(original, identifier)
    source = next(c for c in original.candidates if c.candidate_id == identifier)
    protected = {p: p.read_bytes() for p in source.run_directory.rglob("*") if p.is_file()}
    reviews = original.study_directory / "visual-reviews.json"
    protected[reviews] = reviews.read_bytes()
    for _ in range(count):
        continued = continuation.run(runner, identifier)
    return continued, identifier, calls, protected


@pytest.mark.parametrize("count,expected", [(1, 700), (2, 1000)])
def test_kept_approved_fit_transfers_continued_budget_to_config_manifest_and_native_xml(
    tmp_path,
    monkeypatch,
    count,
    expected,
):
    continued, identifier, calls, protected = ready(tmp_path, monkeypatch, count)
    dispatched = list(calls)
    final, _ = completion.finish(continued.study_directory, identifier)
    config = load_config(final.final_config_path)
    result = config["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
    assert config["optimization"]["max_iterations"] == expected
    assert result["iteration_budget_recommendation"]["version"] == "2"
    assert len(result["iteration_budget_recommendation"]["continuation_evidence"]) == count
    assert result["full_cohort_initialization"]["individual_max_iterations"] == expected
    assert final.selected_candidate_ids["timepoints"] == identifier
    assert calls == dispatched  # Finishing a pilot must never fit again.
    restored = study.completed_pilot_refinement_view(final.study_directory)
    assert restored.visual_reviews[identifier] is True
    assert all(p.read_bytes() == value for p, value in protected.items())
    run = prepare_run(final.final_config_path, run_id="budget-preparation-only")
    assert (
        f"<max-iterations>{expected}</max-iterations>"
        in (run / "engine/optimization_parameters.xml").read_text()
    )
    adapter = ast.parse((run / "engine/sitecustomize.py").read_text())
    plan = next(
        ast.literal_eval(node.value)
        for node in ast.walk(adapter)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_DF_ATLAS_PLAN"
            for target in node.targets
        )
    )
    assert plan["individual_max_iterations"] == expected
    assert calls == dispatched
    assert all(p.read_bytes() == value for p, value in protected.items())
    for bad in ("missing-proof", "wrong-version"):
        changed = copy.deepcopy(config)
        budget = changed["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
            "iteration_budget_recommendation"
        ]
        if bad == "missing-proof":
            budget.pop("continuation_evidence")
        else:
            budget["version"] = "1"
        with pytest.raises(ConfigurationError):
            validate_schema(changed)


@pytest.mark.parametrize("tamper", [False, True])
def test_legacy_pending_finish_keeps_exact_config_and_rejects_other_changes(
    tmp_path,
    monkeypatch,
    tamper,
):
    continued, identifier, calls, protected = ready(tmp_path, monkeypatch)
    current = iteration_budget.recommend_pilot_iteration_budget
    monkeypatch.setattr(
        iteration_budget,
        "recommend_pilot_iteration_budget",
        lambda cap, rows, selected, events, **kw: iteration_budget.recommend_iteration_budget(
            cap, rows, selected.values()
        ),
    )
    report = study._write_calibration_report
    monkeypatch.setattr(
        study,
        "_write_calibration_report",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Report interrupted")),
    )
    with pytest.raises(RuntimeError, match="Report interrupted"):
        completion.finish(continued.study_directory, identifier)
    path = continued.study_directory / "selected/atlas-calibrated.yaml"
    before = path.read_bytes()
    config = load_config(path)
    assert (
        config["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
            "iteration_budget_recommendation"
        ]["version"]
        == "1"
    )
    if tamper:
        import yaml

        config["optimization"]["initial_step_size"] *= 2
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(iteration_budget, "recommend_pilot_iteration_budget", current)
    monkeypatch.setattr(study, "_write_calibration_report", report)
    dispatched = list(calls)
    if tamper:
        with pytest.raises(study.ReferenceCalibrationStudyError, match="Existing final"):
            completion.finish(continued.study_directory, identifier)
    else:
        final, _ = completion.finish(continued.study_directory, identifier)
        assert final.status == "completed"
        assert path.read_bytes() == before
        old = {p: p.read_bytes() for p in final.study_directory.rglob("*") if p.is_file()}
        assert completion.finish(final.study_directory, identifier)[0] == final
        assert all(p.read_bytes() == value for p, value in old.items())
    assert calls == dispatched
    assert all(p.read_bytes() == value for p, value in protected.items())


def test_finalization_does_not_use_an_explicitly_rejected_continuation(tmp_path, monkeypatch):
    continued, identifier, calls, protected = ready(tmp_path, monkeypatch)
    child = continued.candidates[-1]
    name = continued.plan.selected_pilot_subjects[0].filename
    study.record_reference_calibration_candidate_review(
        continued.study_directory,
        candidate_id=child.candidate_id,
        approved=False,
        reviewed_subjects=(name,),
        subject_decisions={name: "fail"},
        display_scopes={name: "preview"},
    )
    dispatched = list(calls)
    final, _ = completion.finish(continued.study_directory, identifier)
    config = load_config(final.final_config_path)
    budget = config["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
        "iteration_budget_recommendation"
    ]
    assert budget["version"] == "1"
    assert not any(row["candidate_id"] == child.candidate_id for row in budget["observations"])
    assert config["optimization"]["max_iterations"] < 700
    assert calls == dispatched
    # The new explicit rejection is intentionally added to the synthetic review
    # journal; all original fitted run bytes remain untouched.
    assert all(
        p.read_bytes() == value for p, value in protected.items() if p.name != "visual-reviews.json"
    )
