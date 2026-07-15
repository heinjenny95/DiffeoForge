from __future__ import annotations

import json
import shutil
from pathlib import Path

from diffeoforge.cli import main
from diffeoforge.reference import compare_reference_run, load_reference_manifest

REPOSITORY_ROOT = Path(__file__).parents[1]
REFERENCE_DIRECTORY = REPOSITORY_ROOT / "reference" / "synthetic-v1"


def materialize_candidate_run(tmp_path: Path) -> Path:
    run_directory = tmp_path / "run"
    manifest = load_reference_manifest(REFERENCE_DIRECTORY)
    for artifact in manifest["artifacts"]:
        source = REFERENCE_DIRECTORY / artifact["fixture_path"]
        destination = run_directory / artifact["run_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return run_directory


def test_reference_manifest_and_fixture_integrity() -> None:
    manifest = load_reference_manifest(REFERENCE_DIRECTORY)

    assert manifest["id"] == "synthetic-v1"
    assert manifest["execution"]["runs"] == 2
    assert manifest["repeatability"]["byte_identical_shared_outputs"] == 60
    assert len(manifest["artifacts"]) == 10


def test_identical_candidate_passes_reference_comparison(tmp_path: Path) -> None:
    report = compare_reference_run(materialize_candidate_run(tmp_path), REFERENCE_DIRECTORY)

    assert report["status"] == "passed"
    assert report["passed_count"] == report["artifact_count"] == 10
    assert all(artifact["byte_identical"] for artifact in report["artifacts"])


def test_coordinate_drift_fails_reference_comparison(tmp_path: Path) -> None:
    run_directory = materialize_candidate_run(tmp_path)
    manifest = load_reference_manifest(REFERENCE_DIRECTORY)
    template = next(
        artifact for artifact in manifest["artifacts"] if artifact["id"] == "estimated-template"
    )
    template_path = run_directory / template["run_path"]
    lines = template_path.read_text(encoding="ascii").splitlines()
    points_line = next(index for index, line in enumerate(lines) if line.startswith("POINTS "))
    coordinates = lines[points_line + 1].split()
    coordinates[0] = str(float(coordinates[0]) + 0.01)
    lines[points_line + 1] = " ".join(coordinates)
    template_path.write_text("\n".join(lines) + "\n", encoding="ascii")

    report = compare_reference_run(run_directory, REFERENCE_DIRECTORY)

    result = next(
        artifact for artifact in report["artifacts"] if artifact["id"] == "estimated-template"
    )
    assert report["status"] == "failed"
    assert result["passed"] is False
    assert result["max_absolute_difference"] > result["tolerances"]["max_absolute"]


def test_compare_reference_cli_returns_machine_readable_report(
    tmp_path: Path, capsys
) -> None:
    return_code = main(
        [
            "compare-reference",
            str(materialize_candidate_run(tmp_path)),
            str(REFERENCE_DIRECTORY),
        ]
    )

    captured = capsys.readouterr()
    assert return_code == 0
    assert json.loads(captured.out)["status"] == "passed"
