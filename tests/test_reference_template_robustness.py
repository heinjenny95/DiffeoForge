from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from diffeoforge.cli import main
from diffeoforge.reference_template_robustness import (
    ReferenceTemplateRobustnessError,
    ReferenceTemplateRobustnessRunner,
    create_reference_template_robustness_study,
    load_reference_template_robustness_study,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "examples" / "minimal-atlas.yaml"


def test_template_robustness_study_freezes_three_distinct_starts_without_running(
    tmp_path: Path,
) -> None:
    snapshot = create_reference_template_robustness_study(
        CONFIG,
        tmp_path / "template-robustness",
        start_count=3,
        maximum_iterations=25,
    )

    assert snapshot.status == "ready"
    assert snapshot.completed_run_count == 0
    assert len(snapshot.runs) == 3
    assert {run.status for run in snapshot.runs} == {"pending"}
    manifest = json.loads(
        (snapshot.study_directory / "template-robustness-study.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["design"]["only_intended_difference"] == (
        "initial template geometry"
    )
    assert len({arm["template_sha256"] for arm in manifest["arms"]}) == 3
    configs = [
        yaml.safe_load(run.config_path.read_text(encoding="utf-8"))
        for run in snapshot.runs
    ]
    assert {config["optimization"]["max_iterations"] for config in configs} == {25}
    assert len({config["input"]["template"] for config in configs}) == 3
    assert len({config["model"]["attachment"]["kernel_width"] for config in configs}) == 1
    assert len({config["model"]["deformation"]["kernel_width"] for config in configs}) == 1
    for config, run in zip(configs, snapshot.runs, strict=True):
        subjects = {
            path.name
            for path in (run.config_path.parent / config["input"]["directory"])
            .resolve()
            .glob("*.vtk")
        }
        assert subjects == {f"subject-{index:02d}.vtk" for index in range(1, 6)}


def test_template_robustness_study_rejects_changed_frozen_arm(tmp_path: Path) -> None:
    snapshot = create_reference_template_robustness_study(
        CONFIG,
        tmp_path / "template-robustness",
        start_count=2,
    )
    snapshot.runs[0].config_path.write_text(
        snapshot.runs[0].config_path.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(ReferenceTemplateRobustnessError, match="changed"):
        load_reference_template_robustness_study(snapshot.study_directory)


class _InterruptedController:
    def __init__(self, request) -> None:
        self.request = request

    def request_cancel(self) -> bool:
        return True

    def run(self, *, event_callback=None):
        self.request.destination.mkdir(parents=True)
        return SimpleNamespace(completed=False)


def test_template_robustness_runner_records_safe_interruption_and_resume_state(
    tmp_path: Path,
) -> None:
    snapshot = create_reference_template_robustness_study(
        CONFIG,
        tmp_path / "template-robustness",
        start_count=2,
    )

    interrupted = ReferenceTemplateRobustnessRunner(
        snapshot.study_directory,
        controller_factory=_InterruptedController,
    ).run_all()

    assert interrupted.status == "ready_to_retry"
    assert interrupted.runs[0].status == "failed"
    assert "cancelled safely" in interrupted.runs[0].error
    assert interrupted.runs[0].attempts == 1
    assert interrupted.runs[1].status == "pending"


def test_template_robustness_cli_freezes_design_and_reports_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "cli-template-robustness"

    assert (
        main(
            [
                "reference-template-robustness-init",
                str(CONFIG),
                "--output",
                str(destination),
                "--starts",
                "2",
            ]
        )
        == 0
    )
    assert "No atlas process was started" in capsys.readouterr().out

    assert (
        main(
            [
                "reference-template-robustness-status",
                str(destination),
                "--json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"status": "ready"' in output
    assert '"run_count": 2' in output
