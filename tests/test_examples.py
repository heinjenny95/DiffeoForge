from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from diffeoforge.cli import main
from diffeoforge.mesh import inspect_vtk, sha256_file
from diffeoforge.runs import prepare_run, verify_prepared_run

REPOSITORY_ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = REPOSITORY_ROOT / "examples" / "minimal-atlas.yaml"
SYNTHETIC_DIRECTORY = REPOSITORY_ROOT / "examples" / "synthetic"
MESH_DIRECTORY = SYNTHETIC_DIRECTORY / "meshes"


def test_committed_synthetic_dataset_matches_generator() -> None:
    completed = subprocess.run(
        [sys.executable, str(SYNTHETIC_DIRECTORY / "generate_dataset.py"), "--check"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "matches generator version 1.0" in completed.stdout


def test_synthetic_manifest_and_mesh_inventory_agree() -> None:
    manifest = json.loads(
        (MESH_DIRECTORY / "dataset-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["license"] == "CC0-1.0"
    assert len(manifest["surfaces"]) == 6
    assert [item["role"] for item in manifest["surfaces"]].count("subject") == 5
    for record in manifest["surfaces"]:
        path = MESH_DIRECTORY / record["filename"]
        metadata = inspect_vtk(path)
        assert metadata.sha256 == record["sha256"] == sha256_file(path)
        assert metadata.points == record["points"] == 162
        assert metadata.cells == record["triangles"] == 320
        assert metadata.triangular is True


def test_example_passes_full_geometry_validation(capsys) -> None:
    return_code = main(["validate", str(EXAMPLE_CONFIG)])

    captured = capsys.readouterr()
    assert return_code == 0
    assert "Subject meshes: 5" in captured.out
    assert "Template geometry: 162 points, 320 triangles" in captured.out
    assert "Subject geometry: 162-162 points" in captured.out


def test_open_example_prepares_complete_immutable_run(tmp_path: Path) -> None:
    run_directory = prepare_run(
        EXAMPLE_CONFIG,
        run_id="open-synthetic-smoke",
        output_directory=tmp_path / "runs",
    )
    manifest = verify_prepared_run(run_directory)

    assert manifest["input_count"] == {"templates": 1, "subjects": 5}
    assert len(manifest["inputs"]) == 6
    assert (run_directory / "engine" / "model.xml").is_file()
    dataset_xml = (run_directory / "engine" / "data_set.xml").read_text(
        encoding="utf-8"
    )
    assert dataset_xml.count("<subject id=") == 5
