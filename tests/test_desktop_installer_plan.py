from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop.dependency_metadata_evidence import (
    EVIDENCE_NAME as DEPENDENCY_EVIDENCE_NAME,
)
from diffeoforge.desktop.dependency_metadata_evidence import (
    SIDECAR_NAME as DEPENDENCY_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME as FREEZE_EVIDENCE_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    SIDECAR_NAME as FREEZE_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import create_desktop_freeze_evidence
from diffeoforge.desktop.installer_plan import (
    PLAN_NAME,
    SIDECAR_NAME,
    DesktopInstallerPlanError,
    create_desktop_installer_build_plan,
    verify_desktop_installer_build_plan,
)
from diffeoforge.desktop.sbom import create_desktop_cyclonedx_sbom

ROOT = Path(__file__).parents[1]
FIXED_TIME = "2026-07-18T08:00:00+00:00"
SOURCE_COMMIT = "c" * 40
DEVELOPMENT_VERSION = "0.0.0.dev0"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _versions(application_version: str) -> dict[str, str]:
    return {
        "diffeoforge": application_version,
        "numpy": "2.5.1",
        "psutil": "7.2.2",
        "pyinstaller": "6.21.0",
        "pyside6-essentials": "6.11.1",
        "shiboken6": "6.11.1",
        "torch": "2.13.0+cpu",
    }


def _project(tmp_path: Path, *, version: str = DEVELOPMENT_VERSION) -> Path:
    project = tmp_path / "source Käfer"
    windows = project / "distribution" / "windows"
    windows.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "distribution" / "windows" / "DiffeoForge.iss",
        windows / "DiffeoForge.iss",
    )
    shutil.copyfile(
        ROOT / "distribution" / "windows" / "installer-contract-v0.1.json",
        windows / "installer-contract-v0.1.json",
    )
    shutil.copyfile(ROOT / "LICENSE", project / "LICENSE")
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "diffeoforge"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return project


def _bundle(
    tmp_path: Path,
    *,
    application_version: str = DEVELOPMENT_VERSION,
) -> tuple[Path, str]:
    bundle = tmp_path / "bundle Käfer" / "DiffeoForge"
    internal = bundle / "_internal" / "diffeoforge" / "schema"
    internal.mkdir(parents=True)
    for name in (
        "DiffeoForge.exe",
        "DiffeoForgeWorker.exe",
        "DiffeoForgeReferenceWorker.exe",
        "DiffeoForgeReferencePreparationWorker.exe",
    ):
        (bundle / name).write_bytes(name.encode("ascii"))
    (internal / "schema.json").write_text('{"schema": true}\n', encoding="utf-8")
    create_desktop_freeze_evidence(
        bundle,
        source_commit=SOURCE_COMMIT,
        created_at=FIXED_TIME,
        package_versions=_versions(application_version),
        python_version="3.12.10",
        platform_description="Windows-2025Server-test",
    )
    return bundle, _sha256((bundle / FREEZE_EVIDENCE_NAME).read_bytes())


def _package(name: str, version: str) -> dict:
    return {
        "name": name,
        "version": version,
        "metadata": {
            "metadata_version": "2.4",
            "name": name,
            "version": version,
            "bytes": 100 + len(name),
            "sha256": _sha256(f"metadata:{name}:{version}".encode()),
            "license_expression": "MIT",
            "license_field": None,
            "license_classifiers": ["License :: OSI Approved :: MIT License"],
            "license_files_declared": ["LICENSE"],
            "requires_dist": ["example>=1"],
        },
        "license_files": [
            {
                "path": f"{name}-{version}.dist-info/licenses/LICENSE",
                "bytes": 50 + len(name),
                "sha256": _sha256(f"license:{name}".encode()),
                "source": "declared",
            }
        ],
        "unresolved_declared_license_files": [],
        "observations": ["license_classifiers_present"],
        "review_status": "unreviewed",
    }


def _dependency_evidence(
    evidence: Path,
    *,
    bundle: Path,
    freeze_sha256: str,
    application_version: str = DEVELOPMENT_VERSION,
) -> str:
    packages = [
        _package(name, version) for name, version in sorted(_versions(application_version).items())
    ]
    freeze = json.loads((bundle / FREEZE_EVIDENCE_NAME).read_text(encoding="utf-8"))
    package_set = json.dumps(
        packages,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    document = {
        "schema_version": "0.1",
        "status": ("distribution_metadata_inventory_not_license_or_redistribution_approval"),
        "target": "windows-x86_64-cpu",
        "source": {
            "freeze_evidence_schema_version": "0.3",
            "freeze_evidence_sha256": freeze_sha256,
            "source_commit_sha": SOURCE_COMMIT,
            "bundle_inventory_sha256": freeze["bundle"]["inventory_sha256"],
        },
        "generator": {
            "diffeoforge": application_version,
            "python": "3.12.10",
        },
        "package_count": len(packages),
        "package_set_sha256": _sha256(package_set),
        "packages": packages,
        "review_boundary": {
            "license_compatibility": "not_reviewed",
            "redistribution": "not_reviewed",
            "sbom": "not_an_sbom",
        },
        "missing_release_gates": [
            "license_compatibility_review",
            "license_inventory",
            "redistribution_approval",
            "sbom",
        ],
        "scientific_boundary": "Synthetic dependency evidence; no release claim.",
    }
    payload = _json_bytes(document)
    digest = _sha256(payload)
    (evidence / DEPENDENCY_EVIDENCE_NAME).write_bytes(payload)
    (evidence / DEPENDENCY_SIDECAR_NAME).write_bytes(
        f"{digest}  {DEPENDENCY_EVIDENCE_NAME}\n".encode("ascii")
    )
    return digest


def _sources(
    tmp_path: Path,
    *,
    version: str = DEVELOPMENT_VERSION,
) -> tuple[Path, Path, Path, str, str, str]:
    project = _project(tmp_path, version=version)
    bundle, freeze_sha256 = _bundle(tmp_path, application_version=version)
    evidence = tmp_path / "evidence Käfer"
    evidence.mkdir()
    dependency_sha256 = _dependency_evidence(
        evidence,
        bundle=bundle,
        freeze_sha256=freeze_sha256,
        application_version=version,
    )
    for name in (FREEZE_EVIDENCE_NAME, FREEZE_SIDECAR_NAME):
        shutil.copyfile(bundle / name, evidence / name)
    sbom_path = create_desktop_cyclonedx_sbom(
        bundle,
        evidence / DEPENDENCY_EVIDENCE_NAME,
        expected_freeze_evidence_sha256=freeze_sha256,
        expected_dependency_evidence_sha256=dependency_sha256,
        output_directory=evidence,
    )
    return (
        project,
        bundle,
        evidence,
        freeze_sha256,
        dependency_sha256,
        _sha256(sbom_path.read_bytes()),
    )


def _create(
    sources: tuple[Path, Path, Path, str, str, str],
    output: Path,
    *,
    release_candidate: bool = False,
) -> Path:
    project, bundle, evidence, freeze_sha256, dependency_sha256, sbom_sha256 = sources
    output.mkdir()
    return create_desktop_installer_build_plan(
        bundle,
        evidence,
        project_file=project / "pyproject.toml",
        output_directory=output,
        expected_freeze_evidence_sha256=freeze_sha256,
        expected_dependency_evidence_sha256=dependency_sha256,
        expected_sbom_sha256=sbom_sha256,
        release_candidate=release_candidate,
    )


def test_plan_is_canonical_reconstructable_deterministic_and_non_executing(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    output = tmp_path / "installer plan Käfer"
    plan_path = _create(sources, output)
    payload = plan_path.read_bytes()
    digest = _sha256(payload)
    plan = verify_desktop_installer_build_plan(
        plan_path,
        expected_plan_sha256=digest,
    )

    assert plan["status"] == "installer_build_plan_not_an_installer_or_release_artifact"
    assert plan["source"] == {
        "commit_sha": SOURCE_COMMIT,
        "application_version": DEVELOPMENT_VERSION,
        "development_version": True,
        "release_candidate": False,
    }
    assert plan["toolchain"]["asset_sha256"] == (
        "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
    )
    assert plan["toolchain"]["execution_authorized"] is False
    assert plan["compiler"]["program"] == "ISCC.exe"
    assert plan["compiler"]["shell"] is False
    assert plan["compiler"]["execution_authorized"] is False
    assert plan["compiler"]["arguments"] == [
        "/Qp",
        f"/DAppVersion={DEVELOPMENT_VERSION}",
        f"/DSourceCommit={SOURCE_COMMIT}",
        f"/DBundleDir={sources[1].resolve()}",
        f"/DEvidenceDir={sources[2].resolve()}",
        f"/DLicenseFile={(sources[0] / 'LICENSE').resolve()}",
        f"/DOutputDir={output.resolve()}",
        "/DOutputBaseFilename=DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup",
        str((sources[0] / "distribution" / "windows" / "DiffeoForge.iss").resolve()),
    ]
    assert plan["output"]["overwrite"] is False
    assert not Path(plan["output"]["setup_path"]).exists()
    assert (output / SIDECAR_NAME).read_bytes() == (f"{digest}  {PLAN_NAME}\n".encode("ascii"))

    (output / PLAN_NAME).unlink()
    (output / SIDECAR_NAME).unlink()
    recreated = create_desktop_installer_build_plan(
        sources[1],
        sources[2],
        project_file=sources[0] / "pyproject.toml",
        output_directory=output,
        expected_freeze_evidence_sha256=sources[3],
        expected_dependency_evidence_sha256=sources[4],
        expected_sbom_sha256=sources[5],
    )
    assert recreated.read_bytes() == payload

    with pytest.raises(DesktopInstallerPlanError, match="expected plan boundary"):
        create_desktop_installer_build_plan(
            sources[1],
            sources[2],
            project_file=sources[0] / "pyproject.toml",
            output_directory=output,
            expected_freeze_evidence_sha256=sources[3],
            expected_dependency_evidence_sha256=sources[4],
            expected_sbom_sha256=sources[5],
        )


def test_plan_rejects_development_release_candidate_and_wrong_runtime_version(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    with pytest.raises(DesktopInstallerPlanError, match="development or local"):
        _create(sources, tmp_path / "release", release_candidate=True)

    sources[0].joinpath("pyproject.toml").write_text(
        '[project]\nname = "diffeoforge"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    with pytest.raises(DesktopInstallerPlanError, match="fully verified frozen runtime"):
        _create(sources, tmp_path / "wrong version")


def test_plan_rejects_extra_evidence_nested_output_and_existing_setup(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    sources[2].joinpath("extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(DesktopInstallerPlanError, match="exactly the six"):
        _create(sources, tmp_path / "extra evidence output")
    sources[2].joinpath("extra.txt").unlink()

    nested_output = sources[0] / "installer output"
    nested_output.mkdir()
    with pytest.raises(DesktopInstallerPlanError, match="outside repository"):
        create_desktop_installer_build_plan(
            sources[1],
            sources[2],
            project_file=sources[0] / "pyproject.toml",
            output_directory=nested_output,
            expected_freeze_evidence_sha256=sources[3],
            expected_dependency_evidence_sha256=sources[4],
            expected_sbom_sha256=sources[5],
        )

    existing = tmp_path / "existing setup"
    existing.mkdir()
    existing.joinpath("DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe").write_bytes(
        b"not an installer"
    )
    with pytest.raises(DesktopInstallerPlanError, match="expected plan boundary"):
        create_desktop_installer_build_plan(
            sources[1],
            sources[2],
            project_file=sources[0] / "pyproject.toml",
            output_directory=existing,
            expected_freeze_evidence_sha256=sources[3],
            expected_dependency_evidence_sha256=sources[4],
            expected_sbom_sha256=sources[5],
        )


def test_verification_rejects_input_change_and_requires_external_plan_hash(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    plan_path = _create(sources, tmp_path / "plan")
    digest = _sha256(plan_path.read_bytes())

    with pytest.raises(DesktopInstallerPlanError, match="externally expected"):
        verify_desktop_installer_build_plan(
            plan_path,
            expected_plan_sha256="0" * 64,
        )

    script = sources[0] / "distribution" / "windows" / "DiffeoForge.iss"
    script.write_text(script.read_text(encoding="utf-8") + "; changed\n", encoding="utf-8")
    with pytest.raises(DesktopInstallerPlanError, match="reconstructed exact inputs"):
        verify_desktop_installer_build_plan(
            plan_path,
            expected_plan_sha256=digest,
        )


def test_inno_script_is_offline_and_has_no_execution_or_project_deletion() -> None:
    script = (ROOT / "distribution" / "windows" / "DiffeoForge.iss").read_text(encoding="utf-8")

    for directive in (
        "AppId=DiffeoForge.WindowsCPU.x86_64",
        "SetupArchitecture=x64",
        "ArchitecturesAllowed=x64compatible",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        "MinVersion=10.0.17763",
        "PrivilegesRequired=lowest",
        "PrivilegesRequiredOverridesAllowed=dialog commandline",
        "SetupLogging=yes",
        "UninstallLogging=yes",
    ):
        assert directive in script
    for define in (
        "AppVersion",
        "SourceCommit",
        "BundleDir",
        "EvidenceDir",
        "LicenseFile",
        "OutputDir",
        "OutputBaseFilename",
    ):
        assert f"#ifndef {define}" in script
        assert f"#error {define} compiler define is required" in script
    assert "[Run]" not in script
    assert "[UninstallRun]" not in script
    assert "download" not in script.lower()
    assert "http" not in script[script.index("[Files]") :]
    assert all(term not in script.lower() for term in ("mesh", "landmark", "atlas", "pca"))
    assert script.count('Source: "{#EvidenceDir}\\') == 6
    assert "Flags: unchecked" in script


def test_installer_plan_cli_create_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    spec = importlib.util.spec_from_file_location(
        "desktop_installer_plan_tool",
        ROOT / "tools" / "desktop_installer_plan.py",
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    sources = _sources(tmp_path)
    output = tmp_path / "CLI output"
    output.mkdir()

    assert (
        tool.main(
            [
                "create",
                str(sources[1]),
                str(sources[2]),
                "--project-file",
                str(sources[0] / "pyproject.toml"),
                "--output-directory",
                str(output),
                "--expect-freeze-evidence-sha256",
                sources[3],
                "--expect-dependency-evidence-sha256",
                sources[4],
                "--expect-sbom-sha256",
                sources[5],
            ]
        )
        == 0
    )
    digest = _sha256((output / PLAN_NAME).read_bytes())
    assert (
        tool.main(
            [
                "verify",
                str(output / PLAN_NAME),
                "--expect-plan-sha256",
                digest,
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    assert "Created non-executing installer build plan" in captured
    assert '"execution_authorized": false' in captured
