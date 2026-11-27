from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import build_parser, main  # noqa: E402
from diffeoforge.remote_atlas_job import (  # noqa: E402
    MANIFEST_NAME,
    RemoteAtlasJobError,
    create_remote_atlas_job,
    run_remote_atlas_job,
    verify_remote_atlas_job,
    verify_remote_atlas_result,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-08-26T12:00:00+00:00"


def _write_config(path: Path, *, project_name: str = "remote-test") -> Path:
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    config["project"]["name"] = project_name
    config["input"]["directory"] = str(MESH_DIRECTORY)
    config["input"]["template"] = str(MESH_DIRECTORY / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = "unused-local-result"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _payload(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_remote_job_is_portable_deterministic_and_does_not_upload(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    first = create_remote_atlas_job(config, tmp_path / "request-a", created_at=FIXED_TIME)
    second = create_remote_atlas_job(config, tmp_path / "request-b", created_at=FIXED_TIME)

    manifest = verify_remote_atlas_job(first)
    packaged = yaml.safe_load((first / "config" / "modern-atlas.yaml").read_text("utf-8"))

    assert _payload(first) == _payload(second)
    assert manifest["transfer"] == {
        "contains_raw_meshes": True,
        "contains_specimen_filenames": True,
        "automatic_upload_authorized": False,
    }
    assert manifest["execution"]["device"] == "cpu"
    assert len(manifest["input"]["subjects"]) == 5
    assert packaged["input"]["directory"] == "../inputs/subjects"
    assert packaged["input"]["template"] == "../inputs/initial-template.vtk"
    assert packaged["output"]["directory"] == "."
    assert str(ROOT) not in (first / MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(ROOT) not in (first / "config" / "modern-atlas.yaml").read_text(
        encoding="utf-8"
    )


def test_remote_job_verifier_rejects_changed_mesh(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    job = create_remote_atlas_job(config, tmp_path / "request", created_at=FIXED_TIME)
    subject = next((job / "inputs" / "subjects").glob("*.vtk"))
    subject.write_bytes(subject.read_bytes() + b"\n")

    with pytest.raises(RemoteAtlasJobError, match="size differs|SHA-256 differs"):
        verify_remote_atlas_job(job)


def test_remote_job_verifier_rejects_uninventoried_nested_manifest_name(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    job = create_remote_atlas_job(config, tmp_path / "request", created_at=FIXED_TIME)
    unexpected = job / "extra" / MANIFEST_NAME
    unexpected.parent.mkdir()
    unexpected.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RemoteAtlasJobError, match="exact file inventory differs"):
        verify_remote_atlas_job(job)


def test_cuda_request_can_be_packaged_on_cpu_only_client(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "modern.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["runtime"]["device"] = "cuda"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    job = create_remote_atlas_job(config_path, tmp_path / "request", created_at=FIXED_TIME)

    assert verify_remote_atlas_job(job)["execution"]["device"] == "cuda"


def test_remote_job_runs_on_execution_host_and_binds_result(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    job = create_remote_atlas_job(config, tmp_path / "request", created_at=FIXED_TIME)
    events = []

    result = run_remote_atlas_job(
        job,
        tmp_path / "server-result",
        progress_callback=events.append,
    )
    manifest = verify_remote_atlas_result(job, result)

    assert manifest["engine"]["device"] == "cpu"
    assert len(manifest["input"]["subjects"]) == 5
    assert events[0].phase == "workflow"
    assert events[-1].phase == "verification"
    assert events[-1].status == "completed"


def test_remote_job_refuses_result_inside_immutable_request(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "modern.yaml")
    job = create_remote_atlas_job(config, tmp_path / "request", created_at=FIXED_TIME)

    with pytest.raises(RemoteAtlasJobError, match="outside the immutable job package"):
        run_remote_atlas_job(job, job / "result")


def test_remote_cli_contract_and_read_only_verification(tmp_path: Path, capsys) -> None:
    parsed = build_parser().parse_args(
        ["modern-remote-run", str(tmp_path / "request"), "--output", str(tmp_path / "run")]
    )
    assert parsed.command == "modern-remote-run"

    config = _write_config(tmp_path / "modern.yaml")
    job = tmp_path / "request"
    assert main(["modern-remote-package", str(config), "--output", str(job)]) == 0
    assert main(["modern-remote-package-verify", str(job)]) == 0
    output = capsys.readouterr().out
    assert "No upload" in output
    assert "Subject meshes: 5" in output


def test_remote_manifest_schema_is_packaged() -> None:
    schema = json.loads(
        (
            ROOT
            / "src"
            / "diffeoforge"
            / "schema"
            / "remote-atlas-job-v0.1.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["title"] == "DiffeoForge portable remote atlas job"
