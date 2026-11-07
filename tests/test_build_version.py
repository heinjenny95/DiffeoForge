from __future__ import annotations

import json
import tomllib
from pathlib import Path

from diffeoforge import __version__, display_version
from diffeoforge.desktop.installer_plan import _compiler_arguments, _output_version

ROOT = Path(__file__).resolve().parents[1]


def test_current_number_matches_package_runtime_handoff_and_installer():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
    label = _output_version(__version__)
    assert label.startswith("v") and int(label[1:]) >= 78
    assert display_version() == f"{label} (Private Alpha)"
    filename = f"DiffeoForge-{label}-Windows-CPU-x86_64-Setup.exe"
    contract = json.loads(
        (ROOT / "distribution/windows/private-alpha-handoff-contract-v0.1.json")
        .read_text(encoding="utf-8")
    )
    assert contract["output"]["exact_files"][0] == filename
    wrapper = (ROOT / "tools/package_private_alpha.ps1").read_text(encoding="utf-8")
    assert f'$SetupName = "{filename}"' in wrapper
    arguments = _compiler_arguments(
        version=__version__, source_commit="a" * 40, bundle=ROOT,
        evidence=ROOT, license_file=ROOT / "LICENSE", output=ROOT,
        output_basename=filename.removesuffix(".exe"),
        script=ROOT / "distribution/windows/DiffeoForge.iss",
    )
    assert f"/DAppDisplayVersion={display_version()}" in arguments
    assert f"/DAppVersion={__version__}" in arguments


def test_legacy_and_release_versions_keep_their_identifiers():
    for version in ("0.0.0.dev0", "1.2.3", "1.2.3rc1"):
        assert display_version(version) == version
        assert _output_version(version) == version


def test_version_visible_in_main_window_and_landmark_editor(monkeypatch, tmp_path):
    import pytest

    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    app = QApplication.instance() or QApplication(["version-test"])
    window = DiffeoForgeWindow()
    assert display_version() in window.windowTitle()
    meshes = ROOT / "examples/synthetic/meshes"
    editor = LandmarkEditorDialog(
        (meshes / "template.vtk", meshes / "subject-01.vtk"), tmp_path / "points.csv"
    )
    assert display_version() in editor.windowTitle()
    editor.close()
    window.close()
    app.processEvents()
