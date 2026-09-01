from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from diffeoforge import __version__, cli
from diffeoforge.analysis.landmarks import read_landmark_csv
from diffeoforge.cli import main
from diffeoforge.diagnostics import DoctorCheck, DoctorReport


def test_example_passes_schema_only_validation(capsys) -> None:
    example = Path(__file__).parents[1] / "examples" / "minimal-atlas.yaml"

    return_code = main(["validate", str(example), "--schema-only"])

    captured = capsys.readouterr()
    assert return_code == 0
    assert "Configuration schema valid" in captured.out


def test_missing_config_returns_user_error(capsys, tmp_path: Path) -> None:
    return_code = main(["validate", str(tmp_path / "missing.yaml")])

    captured = capsys.readouterr()
    assert return_code == 2
    assert "does not exist" in captured.err


def test_package_module_entrypoint_exposes_the_same_cli(tmp_path: Path) -> None:
    version = subprocess.run(
        [sys.executable, "-m", "diffeoforge", "--version"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    help_result = subprocess.run(
        [sys.executable, "-m", "diffeoforge", "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert version.returncode == 0
    assert version.stdout == f"diffeoforge {__version__}\n"
    assert version.stderr == ""
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("usage: diffeoforge ")
    assert "modern-private-status" in help_result.stdout
    assert "modern-benchmark-matrix-design" in help_result.stdout
    assert "modern-optimizer-benchmark" in help_result.stdout
    assert "modern-optimizer-benchmark-verify" in help_result.stdout
    assert "modern-checkpoint-recovery-init" in help_result.stdout
    assert "modern-checkpoint-recovery-verify-run" in help_result.stdout
    assert "modern-benchmark-matrix-design-verify" in help_result.stdout
    assert "modern-benchmark-matrix-study-status" in help_result.stdout
    assert "modern-benchmark-matrix-study-verify" in help_result.stdout
    assert "modern-benchmark-study-verify" in help_result.stdout
    assert "modern-pca-stability" in help_result.stdout
    assert "modern-pca-stability-verify" in help_result.stdout
    assert help_result.stderr == ""


def test_package_module_entrypoint_preserves_parser_errors(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "diffeoforge", "not-a-command"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("usage: diffeoforge ")
    assert "invalid choice: 'not-a-command'" in result.stderr


def test_package_module_can_be_imported_without_executing_cli(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import diffeoforge.__main__; print('imported')"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "imported\n"
    assert result.stderr == ""


def test_landmark_txt_import_cli_creates_canonical_csv(capsys, tmp_path: Path) -> None:
    meshes = tmp_path / "meshes"
    txt = tmp_path / "txt"
    meshes.mkdir()
    txt.mkdir()
    for name, offset in (("first", 0), ("second", 10)):
        (meshes / f"{name}.ply").write_text("placeholder\n", encoding="utf-8")
        (txt / f"{name}.txt").write_text(
            "[individuals]\n1\n[dimensions]\n3\n[landmarks]\n3\n"
            "[rawpoints]\n'#1\n"
            f"{offset + 1} 2 3\n{offset + 4} 5 6\n{offset + 7} 8 9\n",
            encoding="utf-8",
        )
    output = tmp_path / "landmarks.csv"

    return_code = main(
        [
            "landmarks-import-txt",
            str(meshes),
            str(txt),
            "--mesh-pattern",
            "*.ply",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    labels, values = read_landmark_csv(output, ("first.ply", "second.ply"))
    assert return_code == 0
    assert labels == ("LM1", "LM2", "LM3")
    assert values.dtype == np.float64
    assert values[1, 0].tolist() == [11.0, 2.0, 3.0]
    assert "Matched meshes/TXT files: 2" in captured.out
    assert "no unit conversion or sliding" in captured.out


def test_reference_calibration_plan_cli_exports_reproducible_methods_bundle(
    capsys,
    tmp_path: Path,
) -> None:
    meshes = Path(__file__).parents[1] / "examples" / "synthetic" / "meshes"
    output = tmp_path / "calibration"

    return_code = main(
        [
            "reference-calibration-plan",
            str(meshes),
            "--units",
            "unitless",
            "--surface-detail",
            "fine",
            "--deformation-scale",
            "local",
            "--pilot-subjects",
            "4",
            "--smallest-relevant-feature",
            "0.1",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert return_code == 0
    assert "Status: planned, not executed" in captured.out
    assert "Pilot cohort: 4" in captured.out
    assert (output / "parameter-calibration-plan.json").is_file()
    assert (output / "parameter-calibration-plan.html").is_file()
    assert (output / "parameter-calibration-plan.sha256").is_file()
    assert (output / "aligned-mesh-recommendation.json").is_file()

    blocked_code = main(
        [
            "reference-calibration-plan",
            str(meshes),
            "--units",
            "unitless",
            "--surface-detail",
            "fine",
            "--deformation-scale",
            "local",
            "--output",
            str(output),
        ]
    )
    blocked = capsys.readouterr()
    assert blocked_code == 2
    assert "will not be overwritten" in blocked.err


def test_reference_calibration_plan_cli_binds_pilot_declarations(
    capsys,
    tmp_path: Path,
) -> None:
    meshes = Path(__file__).parents[1] / "examples" / "synthetic" / "meshes"
    subjects = sorted(meshes.glob("subject-*.vtk"), key=lambda path: path.name.casefold())
    declarations = tmp_path / "pilot-declarations.csv"
    declarations.write_text(
        "filename,stratum,is_extreme\n"
        f"{subjects[0].name},stratum-a,true\n"
        f"{subjects[1].name},stratum-b,false\n",
        encoding="utf-8",
    )
    output = tmp_path / "calibration-stratified"

    return_code = main(
        [
            "reference-calibration-plan",
            str(meshes),
            "--units",
            "unitless",
            "--surface-detail",
            "coarse",
            "--deformation-scale",
            "global",
            "--pilot-subjects",
            "3",
            "--pilot-declarations",
            str(declarations),
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert return_code == 0
    assert "2 strata; 1 explicit extremes" in captured.out
    plan = json.loads(
        (output / "parameter-calibration-plan.json").read_text(encoding="utf-8")
    )
    assert plan["version"] == "0.5"
    assert len(plan["pilot_subject_declarations"]) == 2


def test_doctor_json_uses_distinct_blocked_exit_code(capsys, monkeypatch, tmp_path: Path) -> None:
    report = DoctorReport(
        status="blocked",
        workspace=str(tmp_path),
        engine="docker",
        image="test-image",
        checks=(
            DoctorCheck(
                check_id="container_cli",
                label="Container command",
                status="fail",
                summary="missing",
            ),
        ),
    )
    monkeypatch.setattr(cli, "run_doctor", lambda *_args, **_kwargs: report)

    return_code = main(["doctor", "--workspace", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert return_code == 1
    assert '"status": "blocked"' in captured.out
