from __future__ import annotations

from pathlib import Path

import pytest

from diffeoforge.cli import main
from diffeoforge.config import ConfigurationError
from diffeoforge.report import collect_preflight, render_preflight_html, write_preflight_report

REPOSITORY_ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = REPOSITORY_ROOT / "examples" / "minimal-atlas.yaml"


def test_preflight_report_contains_geometry_parameters_and_boundary() -> None:
    result = collect_preflight(EXAMPLE_CONFIG)

    html = render_preflight_html(result)

    assert "Engineering preflight passed" in html
    assert "Subject meshes</span><strong>5" in html
    assert "Attachment kernel width / template diagonal" in html
    assert result.template.sha256 in html
    assert "does not establish biological validity" in html
    assert "<script" not in html
    assert "https://" not in html


def test_preflight_report_is_write_once_by_default(tmp_path: Path) -> None:
    result = collect_preflight(EXAMPLE_CONFIG)
    report_path = tmp_path / "preflight.html"

    written = write_preflight_report(result, report_path)

    assert written == report_path
    assert report_path.is_file()
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_preflight_report(result, report_path)


def test_preflight_report_does_not_replace_unrelated_html(tmp_path: Path) -> None:
    result = collect_preflight(EXAMPLE_CONFIG)
    report_path = tmp_path / "owned.html"
    report_path.write_text("<p>user content</p>\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not recognized"):
        write_preflight_report(result, report_path, overwrite=True)

    assert report_path.read_text(encoding="utf-8") == "<p>user content</p>\n"


def test_validate_cli_writes_requested_report(capsys, tmp_path: Path) -> None:
    report_path = tmp_path / "validation.html"

    return_code = main(["validate", str(EXAMPLE_CONFIG), "--report", str(report_path)])

    captured = capsys.readouterr()
    assert return_code == 0
    assert report_path.is_file()
    assert f"Preflight report: {report_path}" in captured.out


def test_schema_only_rejects_report_request(capsys, tmp_path: Path) -> None:
    return_code = main(
        [
            "validate",
            str(EXAMPLE_CONFIG),
            "--schema-only",
            "--report",
            str(tmp_path / "invalid.html"),
        ]
    )

    captured = capsys.readouterr()
    assert return_code == 2
    assert "cannot be combined" in captured.err
