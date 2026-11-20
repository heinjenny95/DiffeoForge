from pathlib import Path

import pytest

from diffeoforge.desktop.app import build_parser


def test_presentation_mode_is_not_a_desktop_entry_point():
    parser = build_parser()
    assert "--demo" not in parser.format_help()
    with pytest.raises(SystemExit) as exit:
        parser.parse_args(["--demo"])
    assert exit.value.code == 2


def test_installer_removes_old_demo_shortcut_and_packages_no_demo_assets():
    root = Path(__file__).parents[1]
    installer = (root / "distribution/windows/DiffeoForge.iss").read_text(encoding="utf-8")
    assert 'Parameters: "--demo"' not in installer
    assert 'Type: files; Name: "{group}\\DiffeoForge Demo.lnk"' in installer
    spec = (root / "distribution/windows/DiffeoForge.spec").read_text(encoding="utf-8")
    assert "demo_data" not in spec
