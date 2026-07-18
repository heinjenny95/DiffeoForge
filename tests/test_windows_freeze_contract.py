from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
WINDOWS = ROOT / "distribution" / "windows"


def test_windows_evidence_builder_is_explicitly_pinned_and_onedir() -> None:
    requirements = (WINDOWS / "freeze-requirements.txt").read_text(encoding="utf-8")
    spec = (WINDOWS / "DiffeoForge.spec").read_text(encoding="utf-8")

    meaningful_requirements = [
        line for line in requirements.splitlines() if line and not line.startswith("#")
    ]
    assert meaningful_requirements == ["PyInstaller==6.21.0"]
    assert 'name="DiffeoForge"' in spec
    assert 'name="DiffeoForgeWorker"' in spec
    assert 'name="DiffeoForgeReferenceWorker"' in spec
    assert 'name="DiffeoForgeReferencePreparationWorker"' in spec
    assert "console=False" in spec
    assert "console=True" in spec
    assert "bundle = COLLECT(" in spec
    assert "onefile" not in spec.lower()


def test_windows_freeze_has_separate_desktop_and_pipe_worker_entry_points() -> None:
    desktop = (WINDOWS / "diffeoforge_desktop.py").read_text(encoding="utf-8")
    worker = (WINDOWS / "diffeoforge_worker.py").read_text(encoding="utf-8")
    reference_worker = (WINDOWS / "diffeoforge_reference_worker.py").read_text(
        encoding="utf-8"
    )
    preparation_worker = (
        WINDOWS / "diffeoforge_reference_preparation_worker.py"
    ).read_text(encoding="utf-8")
    build = (WINDOWS / "build-evidence.ps1").read_text(encoding="utf-8")

    assert "diffeoforge.desktop.app import main" in desktop
    assert "diffeoforge.desktop.worker import _process_main" in worker
    assert "diffeoforge.desktop.reference_worker_harness import main" in reference_worker
    assert (
        "diffeoforge.desktop.reference_preparation_worker_harness import ("
        in preparation_worker
    )
    assert "main," in preparation_worker
    assert "git status --porcelain=v1 --untracked-files=all" in build
    assert "DiffeoForgeWorker.exe" in build
    assert "DiffeoForgeReferenceWorker.exe" in build
    assert "DiffeoForgeReferencePreparationWorker.exe" in build
    assert "smoke_frozen_reference_worker.py" in build
    assert "audit_frozen_reference_parent_death.py" in build
    assert "audit_frozen_reference_preparation_parent_death.py" in build
    assert "smoke_frozen_reference_preparation_worker.py" in build
    assert "PreparationApprovalSha256" in build
    assert "reference-plan-approval-verify" in build
    assert "Preparation approval does not match" in build
    assert "hard-parent-death audit failed" in build
    assert build.index("audit_frozen_reference_preparation_parent_death.py") < (
        build.index("smoke_frozen_reference_preparation_worker.py")
    )
    assert "desktop_bundle_evidence.py create" in build
    assert "desktop_bundle_evidence.py verify" in build
