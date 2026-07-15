from __future__ import annotations

from pathlib import Path

from diffeoforge.cli import main


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
