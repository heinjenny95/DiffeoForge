from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from diffeoforge import __version__, cli
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
    assert "modern-benchmark-matrix-design" in help_result.stdout
    assert "modern-benchmark-matrix-design-verify" in help_result.stdout
    assert "modern-benchmark-study-verify" in help_result.stdout
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
