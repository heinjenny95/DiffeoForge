"""Saved surface distances can guide review without starting or approving a fit."""

from dataclasses import replace

import pytest
from test_pilot_control_capacity import origin
from test_pilot_region_feedback import reject
from test_reference_attachment_comparison import _detail
from test_reference_calibration_study import _CompletedController, _metrics, _stub_learned_seed

from diffeoforge import guided_fit_direction as direction
from diffeoforge import guided_strategy
from diffeoforge import reference_attachment_comparison as comparison
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def _complete(snapshot, monkeypatch, values):
    _stub_learned_seed(monkeypatch)

    def metrics(run):
        atlas = run / "atlas.vtk"
        atlas.write_text("synthetic receipt")
        return replace(_metrics(atlas), subject_reconstruction_count=1)

    def measure(_root, manifest, candidate, _run, **_options):
        target = manifest["inputs"]["subjects"][0]["filename"]
        value = values[candidate.candidate_id]
        detail = _detail([target], value)
        for repeat in detail["subjects"][target]["repeats"]:
            repeat["regions"] = {
                "0:1": {"count": 12, "tail": value * 1.1},
                "1:3": {"count": 12, "tail": value * .9},
                "1:4": {"count": 2, "tail": value * 10},
            }
        return dict(attachment_comparison=detail, fit_scope="full_targets",
                    original_surface_fit={target: dict(p95=value, p99=value * 2,
                                                        mean=value / 2, diagonal=1)})

    monkeypatch.setattr(study, "collect_reference_calibration_run_metrics", metrics)
    monkeypatch.setattr(comparison, "measure", measure)
    return study.ReferenceCalibrationStudyRunner(
        snapshot.study_directory, controller_factory=_CompletedController).run_current_stage()


def test_comparison_reuses_exact_saved_other_method_and_density_arm(tmp_path, monkeypatch):
    start = guided.prepare(origin(tmp_path, "extreme").study_directory)
    start = _complete(start, monkeypatch, {"guided-current": .27, "guided-varifold": .23})
    start = reject(start, "guided-current")
    pair = guided.next_action(start.study_directory, "adaptive_density_comparison",
                              "guided-current")
    start = reject(start, "guided-varifold")
    pair = _complete(pair, monkeypatch, {"density-reference": .27, "guided-current": .266})
    pair = reject(reject(pair, "density-reference"), "guided-current")
    # A direction is a read operation, including when it points across stages.
    witnesses = {path: sha256_file(path) for parent in (start, pair)
                 for path in parent.study_directory.rglob("*") if path.is_file()}
    result = direction.preview(pair, guided_strategy.state(pair))
    assert result["mode"] == "compare"
    assert result["identifier"] == result["current"]["candidate_id"] == "guided-current"
    assert result["alternative"]["candidate_id"] == "guided-varifold"
    assert result["current"]["directory"] == str(pair.study_directory)
    assert result["alternative"]["directory"] == str(start.study_directory)
    assert result["current_cp"] == pair.attachment_comparison["controls"]["count"]
    assert result["alternative_cp"] == start.attachment_comparison["controls"]["count"]
    assert result["current_p95"] == pytest.approx(26.6)
    assert result["alternative_p95"] == pytest.approx(23)
    assert [(row["direction"], row["cell"], row["change"]) for row in result["regions"]] == [
        (0, [0, 0, 1], "improved"), (1, [0, 0, 3], "remaining")]
    assert all(sha256_file(path) == digest for path, digest in witnesses.items())


def test_absent_inspection_source_mismatch_and_uncertain_benefit(tmp_path, monkeypatch):
    start = guided.prepare(origin(tmp_path, "extreme").study_directory)
    start = _complete(start, monkeypatch, {"guided-current": .27, "guided-varifold": .23})
    start = reject(start, "guided-current")
    assert direction.preview(start, guided_strategy.state(start)) is None
    start = reject(start, "guided-varifold")
    context = guided_strategy.state(start)
    result = direction.preview(start, context)
    assert result["mode"] == "compare"
    current_case, other_case = context["cases"]
    mismatched = dict(other_case, fit=dict(other_case["fit"], target="unrelated.vtk"))
    assert direction.preview(start, dict(context, cases=[current_case, mismatched])) is None

    diagonal = 1
    current = dict(diagonal=diagonal, repeats=[dict(mean=.05, p95=.27, p99=.39)] * 2)
    other = dict(diagonal=diagonal, warnings=[], outcome="same",
                 repeats=[dict(mean=.04, p95=.21, p99=.36),
                          dict(mean=.04, p95=.27, p99=.36)])
    assert not direction._better(current, other)
    other["repeats"][1] = dict(mean=.04, p95=.22, p99=.47)
    other["repeats"][0]["p99"] = .48
    assert not direction._better(current, other)


def test_input_check_requires_separate_stalled_trials_and_respects_improvement():
    def row(stage, outcome, method="current"):
        return dict(reference=dict(directory=stage, method=method), outcome=outcome,
                    goal="density")

    pair = row("matched-test", "same")
    assert not direction._progress_stalled([pair, pair], pair)
    later = row("another-test", "worse")
    assert direction._progress_stalled([pair, pair, later], later)
    assert not direction._progress_stalled([pair, row("other-method", "same", "varifold"),
                                           row("better-test", "better"), later], later)


@pytest.mark.parametrize(
    "outcome, measured, marks_match, expected",
    [
        ("same", [], False, True),
        ("worse", ["improved"], True, True),
        ("better", ["regression"], True, False),
        ("rejected", ["regression"], True, True),
        ("rejected", ["unclear"], True, True),
        ("rejected", ["improved"], True, False),
        ("rejected", ["regression"], False, False),
        ("rejected", [], True, False),
    ],
)
def test_input_check_separates_reported_progress_from_unchanged_mark_measurements(
    outcome, measured, marks_match, expected,
):
    marks = [{"source_sha256": "source", "radius": 0.42}]
    active = marks if marks_match else [{"source_sha256": "source", "radius": 0.63}]
    case = dict(outcome=outcome, regions=marks, region_outcomes=measured)
    assert direction._no_gain(case, active) is expected
