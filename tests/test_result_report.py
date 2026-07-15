from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffeoforge.cli import main
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.result_report import (
    collect_run_report,
    render_result_html,
    write_result_report,
)
from diffeoforge.runs import prepare_run


def prepared_example_run(tmp_path: Path) -> Path:
    example = Path(__file__).parents[1] / "examples" / "minimal-atlas.yaml"
    return prepare_run(example, run_id="report-test", output_directory=tmp_path)


def completed_example_run(tmp_path: Path) -> Path:
    run_directory = prepared_example_run(tmp_path)
    output_path = run_directory / "output" / "estimated-template.vtk"
    output_path.write_text("synthetic output\n", encoding="utf-8")
    record = {
        "path": output_path.relative_to(run_directory / "output").as_posix(),
        "bytes": output_path.stat().st_size,
        "sha256": sha256_file(output_path),
    }
    inventory_path = run_directory / "output-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "inventory_version": "0.1",
                "created_at": "2026-07-15T12:01:00Z",
                "files": [record],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_directory / "logs" / "convergence.csv").write_text(
        "iteration,log_likelihood,attachment,regularity\n"
        "0,-10,-10,0\n"
        "1,-5,-4.9,-0.1\n"
        "2,-2,-1.8,-0.2\n",
        encoding="utf-8",
    )
    result = {
        "result_version": "0.1",
        "run_id": "report-test",
        "status": "completed",
        "started_at": "2026-07-15T12:00:00Z",
        "ended_at": "2026-07-15T12:01:00Z",
        "duration_seconds": 60.0,
        "return_code": 0,
        "execution_error": None,
        "convergence_rows": 3,
        "outputs": {
            "file_count": 1,
            "total_bytes": record["bytes"],
            "inventory_path": "output-inventory.json",
            "inventory_sha256": sha256_file(inventory_path),
        },
        "backend_environment": {"packages": {"deformetrica": "4.3.0"}},
        "command": {"argv": ["deformetrica", "estimate"], "environment": {}},
    }
    (run_directory / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    with (run_directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": result["started_at"], "event": "started"}) + "\n")
        handle.write(
            json.dumps(
                {
                    "timestamp": result["ended_at"],
                    "event": "completed",
                    "return_code": 0,
                    "duration_seconds": 60.0,
                }
            )
            + "\n"
        )
    return run_directory


def test_collect_and_render_terminal_run_evidence(tmp_path: Path) -> None:
    report = collect_run_report(completed_example_run(tmp_path))

    assert report.final_iteration == 2
    assert len(report.convergence) == 3
    assert all(check.status == "pass" for check in report.checks)
    assert "completed before the requested maximum" in report.stop_interpretation

    html = render_result_html(report)
    assert '<meta name="generator" content="DiffeoForge result report">' in html
    assert "Objective and attachment history" in html
    assert "<svg" in html
    assert "does not establish adequate registration" in html
    assert "estimated-template.vtk" in html


def test_report_requires_a_terminal_run(tmp_path: Path) -> None:
    run_directory = prepared_example_run(tmp_path)

    with pytest.raises(ConfigurationError, match="terminal result.json"):
        collect_run_report(run_directory)


def test_inventory_digest_mismatch_is_visible_not_hidden(tmp_path: Path) -> None:
    run_directory = completed_example_run(tmp_path)
    inventory_path = run_directory / "output-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["created_at"] = "2026-07-15T13:00:00Z"
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    report = collect_run_report(run_directory)

    digest_check = next(
        check for check in report.checks if check.label == "Output inventory digest"
    )
    assert digest_check.status == "fail"
    assert any("Evidence check failed" in notice for notice in report.notices)


def test_writer_only_replaces_recognized_reports(tmp_path: Path) -> None:
    report = collect_run_report(completed_example_run(tmp_path))
    destination = tmp_path / "custom.html"
    destination.write_text("unrelated research notes", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not recognized"):
        write_result_report(report, destination, overwrite=True)

    written = write_result_report(report)
    assert written == report.run_directory / "result-report.html"
    assert write_result_report(report, overwrite=True) == written


def test_report_cli_writes_default_html(capsys, tmp_path: Path) -> None:
    run_directory = completed_example_run(tmp_path)

    return_code = main(["report", str(run_directory)])

    captured = capsys.readouterr()
    assert return_code == 0
    assert "Run status: completed" in captured.out
    assert "Convergence observations: 3" in captured.out
    assert (run_directory / "result-report.html").is_file()


def test_interrupted_run_has_terminal_report_without_claiming_convergence(
    tmp_path: Path,
) -> None:
    run_directory = completed_example_run(tmp_path)
    result_path = run_directory / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update(
        {
            "status": "interrupted",
            "return_code": 130,
            "execution_error": "KeyboardInterrupt: interrupted by user",
            "checkpoint": {
                "available": False,
                "path": "output/deformetrica-state.p",
            },
        }
    )
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    event_path = run_directory / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    events[-1].update({"event": "interrupted", "return_code": 130})
    event_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    report = collect_run_report(run_directory)

    assert "interruption is not convergence" in report.stop_interpretation
    assert any("cannot be resumed" in notice for notice in report.notices)
    assert "Run interrupted" in render_result_html(report)


def test_resume_report_discloses_reinitialized_optimizer_state(tmp_path: Path) -> None:
    run_directory = completed_example_run(tmp_path)
    result_path = run_directory / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["resume"] = {
        "semantics": {"trajectory_continuity": "not_guaranteed"},
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    report = collect_run_report(run_directory)

    assert any("line-search step sizes" in notice for notice in report.notices)
    assert any("not guaranteed" in notice for notice in report.notices)
