from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
workflow = pytest.importorskip("diffeoforge.modern_workflow")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.config import ConfigurationError  # noqa: E402
from diffeoforge.mesh import read_vtk_polydata, sha256_file, write_vtk_polydata  # noqa: E402

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"
FIXED_TIME = "2026-07-16T12:00:00+00:00"


def _configuration(*, output: str = "unused-run", landmarks: str | None = None) -> dict:
    return {
        "schema_version": "0.1",
        "project": {"name": "workflow-test"},
        "input": {
            "directory": str(MESH_DIRECTORY),
            "subject_pattern": "subject-*.vtk",
            "template": str(MESH_DIRECTORY / "template.vtk"),
            "units": "unitless",
        },
        "preprocessing": {
            "procrustes": {
                "enabled": landmarks is not None,
                "landmarks_file": landmarks,
                "scale_to_unit_centroid_size": True,
                "allow_reflection": False,
                "tolerance": 1e-10,
                "max_iterations": 100,
            }
        },
        "quality_control": {
            "require_no_duplicate_faces": True,
            "require_no_isolated_vertices": True,
            "require_edge_manifold": True,
            "require_consistent_orientation": True,
            "require_single_component": False,
            "require_closed_surface": False,
            "reject_zero_area_faces": True,
            "minimum_triangle_angle_degrees": None,
            "maximum_triangle_edge_ratio": None,
            "minimum_face_area_ratio": None,
            "maximum_face_area_ratio": None,
        },
        "initialization": {
            "control_points": {
                "method": "farthest_template_vertices",
                "count": 9,
            },
            "momenta": "zeros",
        },
        "model": {
            "attachment": {"type": "current", "kernel_width": 0.45},
            "deformation": {
                "kernel_width": 0.6,
                "timepoints": 5,
                "shooting_integrator": "rk2",
                "flow_integrator": "deformetrica_heun",
            },
            "noise_variance": 0.01,
        },
        "optimization": {
            "max_cycles": 1,
            "block_order": ["momenta", "template", "control_points"],
            "momenta_step_size": 0.01,
            "template_step_size": 0.001,
            "control_points_step_size": 0.001,
            "backtracking_factor": 0.5,
            "armijo_constant": 0.0001,
            "gradient_tolerance": 1e-8,
            "minimum_step_size": 1e-12,
            "max_line_search_iterations": 20,
        },
        "analysis": {
            "pca_components": None,
            "deformation_standard_deviations": 2.0,
            "deformation_components": 3,
        },
        "runtime": {
            "device": "cpu",
            "precision": "float64",
            "threads": 1,
            "random_seed": 20260715,
        },
        "output": {"directory": output},
    }


def _write_config(path: Path, **kwargs) -> Path:
    path.write_text(yaml.safe_dump(_configuration(**kwargs), sort_keys=False), encoding="utf-8")
    return path


def _payload_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _write_landmarks(path: Path, *, reverse_one_subject: bool = False) -> Path:
    meshes = [MESH_DIRECTORY / "template.vtk", *sorted(MESH_DIRECTORY.glob("subject-*.vtk"))]
    indices = (0, 40, 80)
    labels = ("anterior", "dorsal", "posterior")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(workflow.LANDMARK_COLUMNS)
        for mesh_index, mesh in enumerate(meshes):
            points = read_vtk_polydata(mesh).vertices
            rows = list(zip(labels, indices, strict=True))
            if reverse_one_subject and mesh_index == 2:
                rows.reverse()
            for label, point_index in rows:
                writer.writerow((mesh.name, label, *points[point_index]))
    return path


def test_example_configuration_is_valid_and_public_schema_is_packaged() -> None:
    loaded = workflow.load_modern_workflow_config(ROOT / "examples/minimal-modern-atlas.yaml")

    assert loaded["runtime"] == {
        "device": "cpu",
        "precision": "float64",
        "threads": 1,
        "random_seed": 20260715,
    }
    assert loaded["analysis"] == {
        "pca_components": None,
        "deformation_standard_deviations": 2.0,
        "deformation_components": 3,
    }
    schema = workflow._schema("modern-workflow-config-v0.1.json")
    assert schema["title"] == "DiffeoForge modern workflow configuration"


def test_farthest_template_initialization_is_repeatable_and_explicit() -> None:
    vertices = np.array(read_vtk_polydata(MESH_DIRECTORY / "template.vtk").vertices)

    first = workflow.farthest_template_vertex_indices(vertices, 9)
    second = workflow.farthest_template_vertex_indices(vertices.copy(), 9)

    assert first == second
    assert len(first) == len(set(first)) == 9
    with pytest.raises(ValueError, match="exceeds"):
        workflow.farthest_template_vertex_indices(vertices, vertices.shape[0] + 1)


def test_five_subject_workflow_is_verified_and_byte_repeatable(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    first = workflow.run_modern_workflow(
        config, destination=tmp_path / "first", created_at=FIXED_TIME
    )
    second = workflow.run_modern_workflow(
        config, destination=tmp_path / "second", created_at=FIXED_TIME
    )

    first_manifest = workflow.verify_modern_workflow(first)
    second_manifest = workflow.verify_modern_workflow(second)
    assert first_manifest == second_manifest
    assert _payload_bytes(first) == _payload_bytes(second)
    assert len(first_manifest["input"]["subjects"]) == 5
    assert first_manifest["preprocessing"]["id"] == "none"
    assert first_manifest["initialization"]["control_points"]["count"] == 9
    assert first_manifest["quality"]["assessed_meshes"] == 12
    input_quality = json.loads(
        (first / first_manifest["quality"]["report_path"]).read_text(encoding="utf-8")
    )
    assert {record["stage"] for record in input_quality["meshes"]} == {
        "raw",
        "effective",
    }
    assert all(record["comparison_to_reference"] is None for record in input_quality["meshes"])
    assert first_manifest["result_bundle"]["bundle_version"] == "0.1"
    assert (
        first / first_manifest["result_bundle"]["path"] / "analysis" / "pca-scores.csv"
    ).is_file()
    bundle = first / first_manifest["result_bundle"]["path"]
    bundle_manifest = workflow.verify_modern_atlas_bundle(bundle)
    assert (bundle / bundle_manifest["pca"]["plots"]["scree_path"]).is_file()
    assert (bundle / bundle_manifest["pca"]["plots"]["scores_path"]).is_file()
    assert bundle_manifest["pca"]["deformations"]["standard_deviations"] == 2.0
    assert bundle_manifest["quality"]["assessed_meshes"] > len(
        first_manifest["input"]["subjects"]
    )
    for source, record in zip(
        sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
        first_manifest["input"]["subjects"],
        strict=True,
    ):
        assert record["label"] == source.name
        assert record["sha256"] == sha256_file(source)


def test_optional_labelled_landmarks_align_complete_meshes_and_are_recorded(
    tmp_path: Path,
) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    config = _write_config(
        tmp_path / "workflow.yaml",
        landmarks=str(landmarks),
    )

    run = workflow.run_modern_workflow(
        config, destination=tmp_path / "aligned-run", created_at=FIXED_TIME
    )
    manifest = workflow.verify_modern_workflow(run)

    assert manifest["preprocessing"] == {
        "id": "generalized_procrustes",
        "landmarks_path": "input/landmarks.csv",
        "alignment_path": "preprocessing/procrustes.json",
        "converged": True,
        "termination_reason": "tolerance",
    }
    evidence = json.loads(
        (run / manifest["preprocessing"]["alignment_path"]).read_text(encoding="utf-8")
    )
    assert evidence["landmark_labels"] == ["anterior", "dorsal", "posterior"]
    assert len(evidence["specimens"]) == 6
    assert all(record["aligned_path"] is not None for record in evidence["specimens"])
    assert all(
        record["aligned_path"] is not None
        for record in [manifest["input"]["template"], *manifest["input"]["subjects"]]
    )


def test_inconsistent_landmark_order_fails_without_publishing(tmp_path: Path) -> None:
    landmarks = _write_landmarks(tmp_path / "landmarks.csv", reverse_one_subject=True)
    config = _write_config(tmp_path / "workflow.yaml", landmarks=str(landmarks))
    destination = tmp_path / "rejected"

    with pytest.raises(ConfigurationError, match="same row order"):
        workflow.run_modern_workflow(config, destination=destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".rejected.tmp-*"))


def test_modern_init_rejects_invalid_mesh_topology_before_writing_config(
    tmp_path: Path,
) -> None:
    mesh_directory = tmp_path / "meshes"
    mesh_directory.mkdir()
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    triangles = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    write_vtk_polydata(mesh_directory / "template.vtk", vertices, triangles)
    write_vtk_polydata(mesh_directory / "subject-01.vtk", vertices, triangles)
    write_vtk_polydata(
        mesh_directory / "subject-02.vtk",
        vertices,
        [*triangles, triangles[0]],
    )
    config = tmp_path / "modern.yaml"

    with pytest.raises(ConfigurationError, match="Mesh quality gate failed"):
        workflow.initialize_modern_workflow(
            mesh_directory,
            units="unitless",
            config_path=config,
            control_point_count=4,
        )

    assert not config.exists()


def test_bundle_failure_is_atomic_and_existing_destination_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "failed"

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected bundle failure")

    monkeypatch.setattr(workflow, "write_modern_atlas_bundle", fail)
    with pytest.raises(RuntimeError, match="injected"):
        workflow.run_modern_workflow(config, destination=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".failed.tmp-*"))

    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("user data", encoding="utf-8")
    with pytest.raises(FileExistsError):
        workflow.run_modern_workflow(config, destination=destination)
    assert marker.read_text(encoding="utf-8") == "user data"


def test_final_outer_verification_failure_removes_temporary_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    destination = tmp_path / "unpublished"

    def fail(_directory):
        raise workflow.ModernWorkflowError("injected final verification failure")

    monkeypatch.setattr(workflow, "verify_modern_workflow", fail)
    with pytest.raises(workflow.ModernWorkflowError, match="final verification"):
        workflow.run_modern_workflow(config, destination=destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".unpublished.tmp-*"))


def test_verifier_rejects_extra_or_tampered_files(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    run = workflow.run_modern_workflow(config, destination=tmp_path / "run", created_at=FIXED_TIME)
    extra = run / "nested" / workflow.MANIFEST_NAME
    extra.parent.mkdir()
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(workflow.ModernWorkflowError, match="extra"):
        workflow.verify_modern_workflow(run)
    extra.unlink()

    raw = next((run / "input" / "raw").glob("subject-*.vtk"))
    raw.write_bytes(raw.read_bytes() + b"\n")
    with pytest.raises(workflow.ModernWorkflowError, match="size differs"):
        workflow.verify_modern_workflow(run)


def test_workflow_verifier_recomputes_input_mesh_quality(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "workflow.yaml")
    run = workflow.run_modern_workflow(
        config,
        destination=tmp_path / "run",
        created_at=FIXED_TIME,
    )
    manifest_path = run / workflow.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality_path = run / manifest["quality"]["report_path"]
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["meshes"][0]["metrics"]["boundary_edges"] += 1
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact = next(
        record
        for record in manifest["artifacts"]
        if record["path"] == manifest["quality"]["report_path"]
    )
    artifact["bytes"] = quality_path.stat().st_size
    artifact["sha256"] = sha256_file(quality_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run / workflow.MANIFEST_SIDECAR_NAME).write_text(
        f"{sha256_file(manifest_path)}  {workflow.MANIFEST_NAME}\n",
        encoding="ascii",
    )

    with pytest.raises(workflow.ModernWorkflowError, match="recomputed geometry"):
        workflow.verify_modern_workflow(run)


def test_artifact_resolver_rejects_traversal_and_windows_drive_paths(tmp_path: Path) -> None:
    with pytest.raises(workflow.ModernWorkflowError, match="Unsafe"):
        workflow._resolve_artifact(tmp_path, "../outside.txt")
    with pytest.raises(workflow.ModernWorkflowError, match="Unsafe"):
        workflow._resolve_artifact(tmp_path, "C:/outside.txt")


def test_modern_init_and_cli_run_form_a_public_folder_to_bundle_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "modern.yaml"
    init_code = main(
        [
            "modern-init",
            str(MESH_DIRECTORY),
            "--units",
            "unitless",
            "--template",
            str(MESH_DIRECTORY / "template.vtk"),
            "--subject-pattern",
            "subject-*.vtk",
            "--config",
            str(config),
            "--output-directory",
            str(tmp_path / "cli-run"),
            "--control-points",
            "9",
            "--attachment-kernel-width",
            "0.45",
            "--deformation-kernel-width",
            "0.6",
            "--noise-variance",
            "0.01",
            "--max-cycles",
            "1",
            "--threads",
            "1",
        ]
    )
    init_output = capsys.readouterr()
    assert init_code == 0
    assert "configuration created" in init_output.out
    assert config.read_text(encoding="utf-8").startswith(workflow.CONFIG_MARKER)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["analysis"] == {
        "pca_components": None,
        "deformation_standard_deviations": 2.0,
        "deformation_components": 3,
    }

    return_code = main(["modern-run", str(config)])
    captured = capsys.readouterr()

    assert return_code == 0
    assert "Modern workflow completed" in captured.out
    assert "Subject meshes: 5" in captured.out
    assert "PCA scree plot:" in captured.out
    assert "PCA scores plot:" in captured.out
    assert "PCA deformation meshes:" in captured.out
    assert workflow.verify_modern_workflow(tmp_path / "cli-run")["project"]["name"]

    verify_code = main(["modern-verify", str(tmp_path / "cli-run")])
    verify_output = capsys.readouterr()
    assert verify_code == 0
    assert "Modern workflow verified" in verify_output.out
    assert "PCA scree plot:" in verify_output.out


def test_schema_requires_landmarks_exactly_when_procrustes_is_enabled() -> None:
    invalid = _configuration()
    invalid["preprocessing"]["procrustes"]["enabled"] = True

    with pytest.raises(ConfigurationError, match="landmarks_file"):
        workflow.validate_modern_workflow_config(invalid)
