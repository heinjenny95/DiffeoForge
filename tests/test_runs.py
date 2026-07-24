from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
import yaml

from diffeoforge.backends import CommandSpec
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.runs import (
    execute_run,
    parse_convergence,
    prepare_resume_run,
    prepare_run,
    recover_run,
    run_status,
    verify_prepared_run,
)


def write_tetrahedron(path: Path) -> Path:
    path.write_text(
        """# vtk DataFile Version 3.0
tetrahedron
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0
1 0 0
0 1 0
0 0 1
POLYGONS 4 16
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""",
        encoding="ascii",
    )
    return path


def write_run_config(tmp_path: Path) -> Path:
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    write_tetrahedron(mesh_directory / "template.vtk")
    write_tetrahedron(mesh_directory / "subject-a.vtk")
    write_tetrahedron(mesh_directory / "subject-b.vtk")
    config = {
        "schema_version": "0.1",
        "project": {"name": "immutable-test"},
        "input": {
            "directory": "./meshes",
            "subject_pattern": "subject-*.vtk",
            "template": "./meshes/template.vtk",
            "units": "unitless",
        },
        "model": {
            "type": "deterministic_atlas",
            "dimension": 3,
            "object_id": "surface",
            "attachment": {"type": "current", "kernel_width": 0.1},
            "deformation": {
                "kernel_width": 0.1,
                "timepoints": 5,
                "initial_control_point_spacing": 0.1,
                "use_rk2": False,
            },
            "noise_std": 0.05,
        },
        "optimization": {
            "method": "gradient_ascent",
            "max_iterations": 2,
            "initial_step_size": 0.01,
            "convergence_tolerance": 0.0001,
            "downsampling_factor": 1,
            "max_line_search_iterations": 10,
            "save_every_n_iterations": 100,
            "print_every_n_iterations": 1,
            "scale_initial_step_size": True,
            "use_sobolev_gradient": True,
            "sobolev_kernel_width_ratio": 1.0,
            "freeze_template": False,
            "freeze_control_points": False,
        },
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cpu",
            "threads": 2,
            "processes": 1,
            "precision": "float32",
            "random_seed": 20260715,
            "kernel_backend": "keops",
            "verbosity": "INFO",
            "launcher": {"type": "native", "executable": "deformetrica"},
        },
        "output": {"directory": "./runs", "retain_flow_meshes": True},
    }
    config_path = tmp_path / "atlas.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def abandon_prepared_run(run_directory: Path, *, checkpoint: bytes | None = None) -> None:
    with (run_directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-07-15T10:00:00Z",
                    "event": "started",
                    "command": {
                        "argv": ["deformetrica", "estimate"],
                        "working_directory": str(run_directory),
                        "environment": {},
                    },
                    "backend_environment": {
                        "probe_status": "verified",
                        "packages": {"deformetrica": "4.3.0"},
                    },
                }
            )
            + "\n"
        )
    (run_directory / "logs" / "deformetrica.log").write_text(
        "Log-likelihood = -10 ; attachment = -8 ; regularity = -2\n",
        encoding="utf-8",
    )
    if checkpoint is not None:
        (run_directory / "output" / "deformetrica-state.p").write_bytes(checkpoint)


def test_prepare_creates_verifiable_immutable_run(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)

    run_directory = prepare_run(config_path, run_id="fixed-run")
    manifest = verify_prepared_run(run_directory)

    assert run_directory == tmp_path / "runs" / "fixed-run"
    assert manifest["input_count"] == {"templates": 1, "subjects": 2}
    assert (run_directory / "engine" / "model.xml").is_file()
    assert (run_directory / "engine" / "data_set.xml").is_file()
    assert (run_directory / "engine" / "optimization_parameters.xml").is_file()
    assert not any((run_directory / "output").iterdir())
    model_xml = (run_directory / "engine" / "model.xml").read_text(encoding="utf-8")
    optimization_xml = (
        run_directory / "engine" / "optimization_parameters.xml"
    ).read_text(encoding="utf-8")
    assert "<initial-cp-spacing>0.1</initial-cp-spacing>" in model_xml
    assert "<dtype>float32</dtype>" in model_xml
    assert "<convergence-tolerance>0.0001</convergence-tolerance>" in optimization_xml
    assert "<max-line-search-iterations>10</max-line-search-iterations>" in optimization_xml
    assert "<state-file>" not in optimization_xml
    assert manifest["backend"]["engine_constants"] == {
        "line_search_expand": 1.5,
        "line_search_shrink": 0.5,
        "state_file": "output/deformetrica-state.p",
    }
    expected_manifest_hash = (run_directory / "manifest.sha256").read_text().split()[0]
    assert sha256_file(run_directory / "manifest.json") == expected_manifest_hash
    assert run_status(run_directory)["status"] == "prepared"


def test_prepare_preserves_parameter_provenance_in_effective_config(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    provenance = {
        "profile": "advanced",
        "scale_reference": "template_bounding_box_diagonal",
        "ratios": {
            "attachment_kernel_width": 0.1,
            "deformation_kernel_width": 0.1,
            "initial_control_point_spacing": 0.1,
            "noise_std": 0.05,
        },
        "sources": {
            "attachment_kernel_width": "template_diagonal_ratio",
            "deformation_kernel_width": "template_diagonal_ratio",
            "initial_control_point_spacing": "template_diagonal_ratio",
            "noise_std": "template_diagonal_ratio",
        },
    }
    config["project"]["parameter_provenance"] = provenance
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    run_directory = prepare_run(config_path, run_id="parameter-provenance")
    manifest = verify_prepared_run(run_directory)

    assert manifest["project"] == {"name": "immutable-test"}
    assert manifest["effective_config"]["project"]["parameter_provenance"] == provenance


def test_convergence_parser_preserves_backend_iteration_numbers(tmp_path: Path) -> None:
    log_path = tmp_path / "deformetrica.log"
    csv_path = tmp_path / "convergence.csv"
    log_path.write_text(
        "------------------------------------- Iteration: 6 "
        "-------------------------------------\n"
        ">> Log-likelihood = -8.181E+00 [ attachment = -8.128E+00 ; "
        "regularity = -5.328E-02 ]\n"
        "------------------------------------- Iteration: 7 "
        "-------------------------------------\n"
        ">> Log-likelihood = -6.831E+00 [ attachment = -6.770E+00 ; "
        "regularity = -6.049E-02 ]\n",
        encoding="utf-8",
    )

    assert parse_convergence(log_path, csv_path) == 2
    assert csv_path.read_text(encoding="utf-8").splitlines() == [
        "iteration,log_likelihood,attachment,regularity",
        "6,-8.181,-8.128,-0.05328",
        "7,-6.831,-6.77,-0.06049",
    ]


def test_prepare_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    prepare_run(config_path, run_id="fixed-run")

    with pytest.raises(ConfigurationError, match="already exists"):
        prepare_run(config_path, run_id="fixed-run")


def test_tampered_staged_input_is_detected_before_execution(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    subject = next(item for item in manifest["inputs"] if item["role"] == "subject")
    staged = run_directory.joinpath(*Path(subject["staged_path"]).parts)
    staged.write_bytes(staged.read_bytes() + b"tampered")

    with pytest.raises(ConfigurationError, match="checksum mismatch"):
        verify_prepared_run(run_directory)


def test_manifest_schema_is_checked_even_with_updated_checksum(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["backend"]["engine_constants"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_directory / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="manifest schema validation failed"):
        run_status(run_directory)


def test_manifest_optional_constant_is_backward_compatible(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="fixed-run")
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["backend"]["engine_constants"]["state_file"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_directory / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  manifest.json\n",
        encoding="utf-8",
    )

    assert run_status(run_directory)["status"] == "prepared"


def test_recover_requires_confirmation_and_records_partial_evidence(tmp_path: Path) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="abandoned")
    abandon_prepared_run(run_directory, checkpoint=b"opaque-checkpoint-bytes")

    with pytest.raises(ConfigurationError, match="confirm-process-stopped"):
        recover_run(run_directory, reason="test interruption")

    result = recover_run(
        run_directory,
        reason="test interruption",
        confirm_process_stopped=True,
    )

    assert result["status"] == "interrupted"
    assert result["return_code"] is None
    assert result["duration_seconds"] is None
    assert result["convergence_rows"] == 1
    assert result["checkpoint"]["available"] is True
    assert result["checkpoint"]["bytes"] == len(b"opaque-checkpoint-bytes")
    assert run_status(run_directory)["status"] == "interrupted"
    inventory = json.loads(
        (run_directory / "output-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["files"][0]["path"] == "deformetrica-state.p"


def test_prepare_resume_creates_immutable_successor(tmp_path: Path) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    checkpoint = b"opaque-checkpoint-bytes"
    abandon_prepared_run(source, checkpoint=checkpoint)
    recover_run(source, reason="power loss", confirm_process_stopped=True)

    successor = prepare_resume_run(source, run_id="successor")
    manifest = verify_prepared_run(successor)

    assert successor == source.parent / "successor"
    assert not any((successor / "output").iterdir())
    assert (successor / "resume" / "source-checkpoint.p").read_bytes() == checkpoint
    provenance = json.loads(
        (successor / "resume" / "resume.json").read_text(encoding="utf-8")
    )
    assert provenance["source_run"] == {
        "run_id": "source",
        "path": str(source),
        "terminal_status": "interrupted",
    }
    assert provenance["semantics"] == {
        "backend_id": "deformetrica_reference",
        "backend_version": "4.3.0",
        "restored": ["current_parameters", "current_iteration"],
        "reinitialized": [
            "objective_baseline",
            "gradient",
            "line_search_step_sizes",
        ],
        "trajectory_continuity": "not_guaranteed",
    }
    optimization_xml = (
        successor / "engine" / "optimization_parameters.xml"
    ).read_text(encoding="utf-8")
    assert "<state-file>../output/deformetrica-state.p</state-file>" in optimization_xml
    protected = {record["path"] for record in manifest["protected_artifacts"]}
    assert "resume/resume.json" in protected
    assert "resume/source-checkpoint.p" in protected


def test_prepare_resume_rejects_checkpoint_changed_after_inventory(tmp_path: Path) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    abandon_prepared_run(source, checkpoint=b"original")
    recover_run(source, reason="power loss", confirm_process_stopped=True)
    (source / "output" / "deformetrica-state.p").write_bytes(b"tampered")

    with pytest.raises(ConfigurationError, match="differs from its inventory"):
        prepare_resume_run(source, run_id="successor")


def test_prepare_resume_explains_missing_checkpoint(tmp_path: Path) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    abandon_prepared_run(source)
    recover_run(source, reason="stopped before first save", confirm_process_stopped=True)

    with pytest.raises(ConfigurationError, match="stopped before its first save"):
        prepare_resume_run(source, run_id="successor")


def test_prepare_resume_requires_frozen_source_backend_evidence(tmp_path: Path) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    abandon_prepared_run(source, checkpoint=b"checkpoint")
    recover_run(source, reason="power loss", confirm_process_stopped=True)
    result_path = source / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["backend_environment"]["packages"]["deformetrica"] = "5.0.0"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="source evidence from Deformetrica 4.3.0"):
        prepare_resume_run(source, run_id="successor")


def test_prepare_resume_rejects_completed_lifecycle(tmp_path: Path) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    abandon_prepared_run(source, checkpoint=b"checkpoint")
    recover_run(source, reason="power loss", confirm_process_stopped=True)
    with (source / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-07-15T10:01:00Z",
                    "event": "completed",
                    "return_code": 0,
                }
            )
            + "\n"
        )

    with pytest.raises(ConfigurationError, match="failed or interrupted"):
        prepare_resume_run(source, run_id="successor")


def test_keyboard_interrupt_becomes_terminal_interrupted_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="interruptible")

    class InterruptingOutput:
        def __iter__(self) -> InterruptingOutput:
            return self

        def __next__(self) -> str:
            raise KeyboardInterrupt

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = InterruptingOutput()
            self.terminated = False

        def poll(self) -> int | None:
            return 143 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: int | None = None) -> int:
            return 143

        def kill(self) -> None:
            self.terminated = True

    monkeypatch.setattr("diffeoforge.runs.ensure_launcher_available", lambda config: None)
    monkeypatch.setattr(
        "diffeoforge.runs._probe_backend_environment",
        lambda config: {"probe_status": "verified"},
    )
    fake_process = FakeProcess()
    monkeypatch.setattr(
        "diffeoforge.runs.subprocess.Popen",
        lambda *args, **kwargs: fake_process,
    )

    assert execute_run(run_directory) == 130
    snapshot = run_status(run_directory)
    assert snapshot["status"] == "interrupted"
    assert snapshot["result"]["checkpoint"]["available"] is False
    assert snapshot["result"]["return_code"] == 130
    assert fake_process.terminated is True


def test_child_reported_keyboard_interrupt_is_terminal_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="child-interrupt")

    class CompletedOutput:
        def __iter__(self):
            return iter(("Traceback (most recent call last):\n", "KeyboardInterrupt\n"))

    class FakeProcess:
        stdout = CompletedOutput()

        def poll(self) -> int:
            return 2

        def wait(self, timeout: int | None = None) -> int:
            return 2

    monkeypatch.setattr("diffeoforge.runs.ensure_launcher_available", lambda config: None)
    monkeypatch.setattr(
        "diffeoforge.runs._probe_backend_environment",
        lambda config: {"probe_status": "verified"},
    )
    monkeypatch.setattr(
        "diffeoforge.runs.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    assert execute_run(run_directory) == 2
    snapshot = run_status(run_directory)
    assert snapshot["status"] == "interrupted"
    assert snapshot["result"]["return_code"] == 2
    assert snapshot["result"]["execution_error"] == (
        "Backend process reported KeyboardInterrupt"
    )


def test_execute_run_tails_native_deformetrica_log_and_reports_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="native-log")
    script = (
        "from pathlib import Path; import time; "
        "p=Path('output')/'test_info.log'; "
        "h=p.open('w', encoding='utf-8'); "
        "h.write('------------------------------------- Iteration: 0 "
        "-------------------------------------\\n'); h.flush(); time.sleep(0.08); "
        "h.write('>> Log-likelihood = -8.0 [ attachment = -7.0 ; "
        "regularity = -1.0 ]\\n'); h.flush(); time.sleep(0.20); h.close()"
    )
    monkeypatch.setattr("diffeoforge.runs.ensure_launcher_available", lambda config: None)
    monkeypatch.setattr(
        "diffeoforge.runs._probe_backend_environment",
        lambda config: {"probe_status": "verified"},
    )
    monkeypatch.setattr(
        "diffeoforge.runs.build_command",
        lambda config, run_path: CommandSpec(
            argv=(sys.executable, "-c", script),
            working_directory=str(run_path),
            environment={},
        ),
    )
    monkeypatch.setattr(
        "diffeoforge.runs.REFERENCE_ACTIVITY_INTERVAL_SECONDS",
        0.05,
    )
    observed_lines: list[str] = []
    activities: list[tuple[float, str | None, str | None]] = []

    assert (
        execute_run(
            run_directory,
            line_callback=observed_lines.append,
            activity_callback=lambda elapsed, latest, source: activities.append(
                (elapsed, latest, source)
            ),
        )
        == 0
    )

    assert any("Iteration: 0" in line for line in observed_lines)
    assert any("Log-likelihood = -8.0" in line for line in observed_lines)
    assert activities
    assert activities[-1][2] == "output/test_info.log"
    assert parse_convergence(
        run_directory / "logs" / "deformetrica.log",
        run_directory / "logs" / "test-convergence.csv",
    ) == 1


def test_execute_run_polls_cancellation_when_backend_emits_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_directory = prepare_run(write_run_config(tmp_path), run_id="silent-cancel")
    monkeypatch.setattr("diffeoforge.runs.ensure_launcher_available", lambda config: None)
    monkeypatch.setattr(
        "diffeoforge.runs._probe_backend_environment",
        lambda config: {"probe_status": "verified"},
    )
    monkeypatch.setattr(
        "diffeoforge.runs.build_command",
        lambda config, run_path: CommandSpec(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            working_directory=str(run_path),
            environment={},
        ),
    )
    cancel_checks = 0

    def cancel_requested() -> bool:
        nonlocal cancel_checks
        cancel_checks += 1
        return cancel_checks >= 3

    started = time.monotonic()
    assert execute_run(run_directory, cancel_requested=cancel_requested) == 130

    assert time.monotonic() - started < 5
    assert cancel_checks >= 3
    assert run_status(run_directory)["status"] == "interrupted"


def test_resume_execution_uses_copy_and_preserves_protected_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = prepare_run(write_run_config(tmp_path), run_id="source")
    checkpoint = b"protected-opaque-checkpoint"
    abandon_prepared_run(source, checkpoint=checkpoint)
    recover_run(source, reason="power loss", confirm_process_stopped=True)
    successor = prepare_resume_run(source, run_id="successor")

    class InterruptingOutput:
        def __iter__(self) -> InterruptingOutput:
            return self

        def __next__(self) -> str:
            raise KeyboardInterrupt

    class FakeProcess:
        stdout = InterruptingOutput()
        stopped = False

        def poll(self) -> int | None:
            return 143 if self.stopped else None

        def terminate(self) -> None:
            self.stopped = True

        def wait(self, timeout: int | None = None) -> int:
            return 143

        def kill(self) -> None:
            self.stopped = True

    monkeypatch.setattr("diffeoforge.runs.ensure_launcher_available", lambda config: None)
    monkeypatch.setattr(
        "diffeoforge.runs._probe_backend_environment",
        lambda config: {"probe_status": "verified"},
    )
    monkeypatch.setattr(
        "diffeoforge.runs.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    assert execute_run(successor) == 130
    assert (successor / "output" / "deformetrica-state.p").read_bytes() == checkpoint
    assert (successor / "resume" / "source-checkpoint.p").read_bytes() == checkpoint
    assert run_status(successor)["result"]["resume"]["source_run"]["run_id"] == "source"
