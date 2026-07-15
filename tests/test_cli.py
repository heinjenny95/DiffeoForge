from __future__ import annotations

from pathlib import Path

from diffeoforge import cli
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
