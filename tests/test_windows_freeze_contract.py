from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WINDOWS = ROOT / "distribution" / "windows"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-freeze-evidence.yml"


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


def test_windows_freeze_excludes_and_audits_builder_only_sbom_modules() -> None:
    spec = (WINDOWS / "DiffeoForge.spec").read_text(encoding="utf-8")

    expected_prefixes = (
        "boolean",
        "cyclonedx",
        "defusedxml",
        "diffeoforge.desktop.inno_signature_evidence",
        "diffeoforge.desktop.inno_toolchain_evidence",
        "diffeoforge.desktop.installer_plan",
        "diffeoforge.desktop.sbom",
        "license_expression",
        "packageurl",
        "py_serializable",
        "sortedcontainers",
    )
    for prefix in expected_prefixes:
        assert f'    "{prefix}",' in spec

    assert "if not is_builder_only_module(module_name)" in spec
    assert "*builder_only_module_prefixes" in spec
    assert "for module_name, *_ in analysis.pure" in spec
    assert "contains builder-only modules" in spec
    assert spec.count("assert_builder_only_modules_absent(") == 5
    compile(spec, str(WINDOWS / "DiffeoForge.spec"), "exec")


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


def test_windows_freeze_workflow_is_manual_pinned_and_evidence_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)

    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["freeze-evidence"]
    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] == "60"
    assert job["env"] == {"PYTHONUTF8": "1", "QT_QPA_PLATFORM": "offscreen"}

    steps = job["steps"]
    assert [step.get("uses") for step in steps if "uses" in step] == [
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    ]
    install = next(step["run"] for step in steps if step["name"].startswith("Install"))
    assert (
        'python -m pip install -e ".[dev,desktop,modern-engine,sbom-builder]"'
        in install
    )
    assert "distribution/windows/freeze-requirements.txt" in install
    assert "PyInstaller.__version__ == '6.21.0'" in install
    assert "torch.version.cuda is None" in install

    build = next(step["run"] for step in steps if step["name"].startswith("Build"))
    assert '$env:RUNNER_TEMP "DiffeoForge Freeze K\u00e4fer"' in build
    assert "clean-runner-preparation" in build
    assert "PreparationApprovalSha256 = $approvalSha256" in build
    assert "SmokeConfig = $modernConfig" in build
    assert "SmokeDestination = $modernDestination" in build
    assert "distribution/windows/build-evidence.ps1" in build
    assert "tools/desktop_bundle_evidence.py verify" in build
    assert build.count("Copy-Item -LiteralPath (Join-Path $bundle") == 2
    assert '"freeze-evidence.json"' in build
    assert '"freeze-evidence.sha256"' in build
    assert "tools/desktop_dependency_metadata_evidence.py create" in build
    assert "tools/desktop_dependency_metadata_evidence.py verify" in build
    assert '"freeze-dependency-metadata.json"' in build
    assert '"freeze-dependency-metadata.sha256"' in build
    assert "--expect-freeze-evidence-sha256 $observed" in build
    assert "tools/desktop_sbom.py create" in build
    assert "tools/desktop_sbom.py verify" in build
    assert '"freeze-sbom.cdx.json"' in build
    assert '"freeze-sbom.cdx.sha256"' in build
    assert "--expect-dependency-evidence-sha256 $dependencyObserved" in build
    assert "--expect-sbom-sha256 $sbomObserved" in build
    assert "uploadedEntries.Count -ne 6" in build
    assert "uploadedFiles.Count -ne 6" in build
    assert "unsafeUploadEntries.Count -ne 0" in build
    assert "[IO.FileAttributes]::ReparsePoint" in build
    assert "Compare-Object $expectedUploadNames $observedUploadNames" in build
    assert "exactly the six approved files" in build
    assert "Copied freeze evidence does not match its SHA-256 sidecar" in build
    assert "Independent CycloneDX SBOM verification failed" in build
    assert '"- SBOM composition: $($sbom.compositions[0].aggregate)"' in build
    assert "License/redistribution review: not reviewed" in build
    assert "three evidence files and three sidecars only" in build

    upload = next(step for step in steps if step["name"] == "Upload exact evidence only")
    assert upload["with"] == {
        "name": "windows-freeze-evidence-${{ github.sha }}",
        "path": "${{ env.FREEZE_EVIDENCE_UPLOAD }}",
        "if-no-files-found": "error",
        "retention-days": "14",
        "compression-level": "0",
    }
    assert "windows-freeze-dist" not in upload["with"]["path"]
