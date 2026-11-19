import json

import pytest
import yaml
from test_runs import write_run_config

from diffeoforge.config import ConfigurationError
from diffeoforge.convergence_advice import Observation, observations, run_advice, summarize
from diffeoforge.runs import iteration_extension_limit, parse_convergence, prepare_run


def test_rounded_equal_values_do_not_establish_plateau():
    rows = tuple(Observation(i, -100.0, 0.05) for i in range(51))
    text = summarize(rows)
    assert "plateau is not established" in text
    assert "Last 50 iterations" in text
    assert "rounding (±0.1)" in text


def test_advice_uses_maximizing_native_objective_and_declared_denominator():
    text = summarize(tuple(Observation(i, -100.0 + i, 0.0001) for i in range(51)))
    assert "still improving" in text
    assert "50.00% of |window-start objective|" in text
    assert "Consider +300" in text


def test_sparse_reset_and_nonmonotone_histories_are_not_pooled():
    assert "Too few" in summarize((Observation(0, -100, 0.1), Observation(500, -90, 0.1)))
    text = "\n".join(
        f"--- Iteration: {i} ---\nLog-likelihood = {x} attachment = -1 regularity = -2"
        for i, x in [(0, "-1.000E+02"), (10, "-9.000E+01"), (0, "-8.000E+01")]
    )
    rows = observations(text)
    assert len(rows) == 1 and rows[0].iteration == 0
    assert rows[0].rounding == 0.005
    values = [Observation(i, -100 + i, 0.001) for i in range(51)]
    values[48] = Observation(48, -80, 0.001)
    assert "decreased" in summarize(tuple(values))


def test_recent_slowing_is_an_explicit_heuristic_not_convergence():
    rows = tuple(
        Observation(i, -100 + min(i, 40) + max(0, i - 40) * 0.05, 0.0001) for i in range(51)
    )
    text = summarize(rows)
    assert "flattening" in text and "quarter-rate cutoff is a heuristic" in text
    assert "11 observations" in text and "51 observations" in text
    assert "+300 is optional" in text
    # Coarse output precision cannot establish the apparent rate reduction.
    coarse = tuple(Observation(r.iteration, r.objective, 5.0) for r in rows)
    assert "flattening" not in summarize(coarse)


def _history(tmp_path, log_text, *, terminal_event="completed"):
    config_path = write_run_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["optimization"]["max_iterations"] = 100
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    source = prepare_run(config_path, run_id="diagnosis")
    log = source / "logs/deformetrica.log"
    log.write_text(log_text, encoding="utf-8")
    count = parse_convergence(log, source / "logs/convergence.csv")
    (source / "result.json").write_text(json.dumps({
        "status": "completed", "return_code": 0, "run_id": source.name,
        "convergence_rows": count,
    }), encoding="utf-8")
    with (source / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": terminal_event, "return_code": 0}) + "\n")
    return source


def _logged(iteration, objective, attachment):
    return (
        f"----- Iteration: {iteration} -----\n"
        f"Log-likelihood = {objective:.3E} [ attachment = {attachment:.3E} "
        f"; regularity = {objective - attachment:.3E} ]\n"
    )


def test_completed_tolerance_stop_reports_progress_without_extension(tmp_path):
    # A falling regularity cost can outweigh a worsening fit contribution.
    logs = "".join(_logged(i, -200 + i, -100 - i) * 2 for i in range(51))
    source = _history(tmp_path, logs + "Tolerance threshold met. Stopping.\n" * 2)
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    maximum, text = run_advice(source)
    assert maximum is None
    assert "Deformetrica met its objective-change tolerance" in text
    assert "last logged state" in text and "accepted step that triggers this stop" in text
    assert "Last 10 iterations (40–50, 11 observations)" in text
    assert "Last 50 iterations (0–50, 51 observations)" in text
    assert "Total objective +50 (approx. +25.00%" in text
    assert "Weighted fit error +50 (approx. +50.00%" in text
    assert "+300" not in text and "Visual QC" in text
    with pytest.raises(ConfigurationError, match="only after the iteration limit"):
        iteration_extension_limit(source)
    assert before == {p.relative_to(source): p.read_bytes()
                      for p in source.rglob("*") if p.is_file()}


def test_tolerance_stop_with_sparse_history_keeps_stop_and_caveat(tmp_path):
    logs = _logged(0, -200, -190) + _logged(70, -100, -90)
    source = _history(tmp_path, logs + "Tolerance threshold met. Stopping.\n")
    assert run_advice(source)[0] is None
    text = run_advice(source)[1]
    assert "met its objective-change tolerance" in text
    assert "Too few closely spaced log entries" in text
    assert "Last 50" not in text


def test_tolerance_diagnosis_requires_a_matching_terminal_lifecycle(tmp_path):
    source = _history(tmp_path, "Tolerance threshold met.\n", terminal_event="failed")
    with pytest.raises(ConfigurationError, match="normally completed"):
        run_advice(source)


def test_earlier_tolerance_marker_does_not_label_a_newer_logging_phase(tmp_path):
    logs = "Tolerance threshold met.\n" + _logged(30, -100, -90)
    source = _history(tmp_path, logs + "Number of line search loops exceeded.\n")
    with pytest.raises(ConfigurationError, match="not a distinct terminal stop"):
        run_advice(source)


def test_window_never_crosses_an_earlier_stop_with_increasing_iteration_numbers(tmp_path):
    first = "".join(_logged(i, -200 + i, -190 + i) for i in range(51))
    last = "".join(_logged(i, -200 + i, -190 + i) for i in range(51, 57))
    stop = "Tolerance threshold met.\n"
    source = _history(tmp_path, first + stop + last + stop)
    maximum, text = run_advice(source)
    assert maximum is None
    assert "Too few closely spaced log entries" in text


def test_completed_iteration_limit_keeps_the_existing_extension_budget(tmp_path):
    source = _history(tmp_path, "".join(_logged(i, -200 + i, -190 + i) for i in range(101)))
    maximum, text = run_advice(source)
    assert maximum == iteration_extension_limit(source) == 100
    assert "Iteration limit reached (100)" in text and "Consider +300" in text


def test_iteration_extension_still_rejects_an_invalid_utf8_log(tmp_path):
    source = _history(tmp_path, _logged(100, -100, -90))
    with (source / "logs/deformetrica.log").open("ab") as handle:
        handle.write(b"\xff\n")
    with pytest.raises(UnicodeDecodeError):
        iteration_extension_limit(source)


def test_attachment_change_within_rounding_is_reported_as_unresolved():
    rows = tuple(Observation(i, -100 + i, .05, 10, .5) for i in range(51))
    text = summarize(rows, at_iteration_limit=False)
    assert "Weighted fit error change within log rounding (±1)" in text
    assert "Total objective +50" in text and "+300" not in text
