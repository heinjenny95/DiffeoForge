from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from diffeoforge.desktop import installer_installation_evidence as evidence

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _context(tmp_path: Path) -> dict[str, object]:
    bundle = tmp_path / "bundle"
    _write(bundle / "DiffeoForge.exe", b"desktop")
    _write(bundle / "_internal" / "runtime.bin", b"runtime")
    evidence_dir = tmp_path / "six"
    for name in evidence.EVIDENCE_COPY_NAMES:
        _write(evidence_dir / name, name.encode())
    license_file = _write(tmp_path / "LICENSE", b"license")
    setup = _write(tmp_path / "setup.exe", b"setup")
    build = _write(tmp_path / "installer-build-evidence.json", b"{}\n")
    return {
        "document": {
            "observer_source": {"commit_sha": "a" * 40},
            "distribution_authorized": False,
        },
        "path": build,
        "expected_sha256": hashlib.sha256(build.read_bytes()).hexdigest(),
        "setup": setup,
        "bundle": bundle,
        "evidence_directory": evidence_dir,
        "license": license_file,
    }


def _installed_tree(tmp_path: Path, context: dict[str, object]) -> Path:
    root = tmp_path / "installed"
    for source in context["bundle"].rglob("*"):
        if source.is_file():
            relative = source.relative_to(context["bundle"])
            _write(root / relative, source.read_bytes())
    for name in evidence.EVIDENCE_COPY_NAMES:
        _write(root / "evidence" / name, (context["evidence_directory"] / name).read_bytes())
    _write(root / "LICENSE.txt", context["license"].read_bytes())
    _write(root / "unins000.exe", b"uninstaller")
    _write(root / "unins000.dat", b"uninstaller-data")
    return root


def test_contract_schema_wrapper_and_package_boundaries() -> None:
    contract_path = (
        ROOT
        / "distribution"
        / "windows"
        / "installer-installation-evidence-contract-v0.1.json"
    )
    evidence._validate_contract(contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["runner_boundary"]["normal_developer_account_execution"] is False
    assert contract["output"]["setup_upload"] is False
    assert contract["output"]["exact_files"] == sorted(evidence.COMPLETE_NAMES)

    wrapper = (ROOT / "tools" / evidence.WRAPPER_NAME).read_text(encoding="utf-8")
    assert '$env:GITHUB_ACTIONS -ne "true"' in wrapper
    assert '"/CURRENTUSER"' in wrapper
    assert '"--smoke"' in wrapper
    assert "Get-NetTCPConnection" in wrapper
    assert "Get-NetUDPEndpoint" in wrapper
    assert "verify-retained" in wrapper
    assert "setup upload" not in wrapper.lower()


def test_pr_gated_manual_workflow_is_pinned_ephemeral_and_evidence_only() -> None:
    path = (
        ROOT
        / ".github"
        / "workflows"
        / "windows-installer-installation-evidence.yml"
    )
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)

    assert workflow["on"]["workflow_dispatch"] == ""
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert (
        ".github/workflows/windows-installer-installation-evidence.yml"
        in workflow["on"]["pull_request"]["paths"]
    )
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["isolated-installer-lifecycle"]
    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] == "90"
    assert job["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert [step.get("uses") for step in job["steps"] if "uses" in step] == [
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    ]
    assert "tools/prepare_installer_observation_inputs.ps1" in text
    assert "tools/observe_inno_toolchain.ps1" in text
    assert "tools/observe_inno_signature.ps1" in text
    assert "tools/observe_inno_portable_toolchain.ps1" in text
    assert "tools/observe_installer_build.ps1" in text
    assert "tools/observe_installer_installation.ps1" in text
    assert "User Project Käfer" in text
    assert "Installed DiffeoForge Käfer" in text
    assert "no setup executable" in text
    upload = next(
        step
        for step in job["steps"]
        if step["name"] == "Upload exact lifecycle evidence only"
    )
    assert upload["with"]["path"] == "${{ env.INSTALLATION_EVIDENCE_UPLOAD }}"
    assert "Setup.exe" not in upload["with"]["path"]


def test_input_preparation_reuses_complete_frozen_smoke_and_six_file_evidence() -> None:
    helper = (ROOT / "tools" / "prepare_installer_observation_inputs.ps1").read_text(
        encoding="utf-8"
    )

    assert "git -C $repository status --porcelain=v1 --untracked-files=all" in helper
    assert "distribution\\windows\\build-evidence.ps1" in helper
    assert "PreparationApprovalSha256" in helper
    assert "desktop_bundle_evidence.py verify" in helper
    assert "desktop_dependency_metadata_evidence.py create" in helper
    assert "desktop_dependency_metadata_evidence.py verify" in helper
    assert "desktop_sbom.py create" in helper
    assert "desktop_sbom.py verify" in helper
    assert '"freeze-evidence.json"' in helper
    assert '"freeze-dependency-metadata.json"' in helper
    assert '"freeze-sbom.cdx.json"' in helper
    assert "exactly six files" in helper


def test_installed_snapshot_exact_matches_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    root = _installed_tree(tmp_path, context)
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)
    output = tmp_path / "output" / evidence.INVENTORY_NAME
    output.parent.mkdir()

    document = evidence.create_installed_file_inventory(
        root,
        context["path"],
        expected_build_evidence_sha256=context["expected_sha256"],
        output_file=output,
    )

    assert document["source_bundle_copy_verified"] is True
    assert document["evidence_copies_verified"] is True
    assert document["license_copy_verified"] is True
    assert document["uninstaller_files"] == ["unins000.dat", "unins000.exe"]
    assert output.read_bytes() == evidence._json_bytes(document)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda root: (root / "DiffeoForge.exe").write_bytes(b"changed"), "differs"),
        (lambda root: _write(root / "surprise.txt", b"extra"), "unexpected"),
        (lambda root: (root / "unins000.dat").unlink(), "pair"),
    ],
)
def test_installed_snapshot_rejects_changed_or_extra_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    match: str,
) -> None:
    context = _context(tmp_path)
    root = _installed_tree(tmp_path, context)
    mutation(root)
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)
    output = tmp_path / "output" / evidence.INVENTORY_NAME
    output.parent.mkdir()

    with pytest.raises(evidence.InstallerInstallationEvidenceError, match=match):
        evidence.create_installed_file_inventory(
            root,
            context["path"],
            expected_build_evidence_sha256=context["expected_sha256"],
            output_file=output,
        )


def _raw_lifecycle(
    directory: Path, context: dict[str, object]
) -> tuple[Path, Path, Path, Path]:
    install_log = _write(directory / evidence.INSTALL_LOG_NAME, b"install log")
    uninstall_log = _write(directory / evidence.UNINSTALL_LOG_NAME, b"uninstall log")
    installed_root = directory.parent / "installed"
    desktop_source = context["bundle"] / "DiffeoForge.exe"
    desktop_record = {
        "path": "DiffeoForge.exe",
        "bytes": desktop_source.stat().st_size,
        "sha256": hashlib.sha256(desktop_source.read_bytes()).hexdigest(),
    }
    uninstaller_payload = b"uninstaller"
    uninstaller_record = {
        "path": "unins000.exe",
        "bytes": len(uninstaller_payload),
        "sha256": hashlib.sha256(uninstaller_payload).hexdigest(),
    }
    inventory_records = [desktop_record, uninstaller_record]
    inventory = {
        "schema_version": "0.1",
        "status": "installed_tree_observed_before_launch",
        "install_root": str(installed_root),
        "source_bundle": {"directory": str(context["bundle"]), "file_count": 1},
        "records": inventory_records,
        "file_count": len(inventory_records),
        "total_bytes": sum(record["bytes"] for record in inventory_records),
        "inventory_sha256": evidence._inventory_sha256(inventory_records),
        "source_bundle_copy_verified": True,
        "evidence_copies_verified": True,
        "license_copy_verified": True,
        "uninstaller_files": ["unins000.exe"],
    }
    (directory / evidence.INVENTORY_NAME).write_bytes(evidence._json_bytes(inventory))
    runner = {
        "github_actions": True,
        "ephemeral": True,
        "os": "Windows",
        "architecture": "X64",
        "runner_name": "GitHub Actions 1",
    }
    sentinel = {
        "path": str(directory.parent / "project" / "sentinel.bin"),
        "bytes": 8,
        "sha256": "c" * 64,
    }
    install = {
        "schema_version": "0.1",
        "phase": "install",
        "observed_at": "2026-07-18T12:00:00Z",
        "runner": runner,
        "setup": _record(context["setup"]),
        "exit_code": 0,
        "install_root": str(installed_root),
        "log": _record(install_log),
        "shortcut_path": str(directory.parent / "DiffeoForge.lnk"),
        "shortcut_verified": True,
        "registration_path": "HKCU:\\Software\\DiffeoForge",
        "registration_verified": True,
        "sentinel_before": sentinel,
        "sentinel_after": sentinel,
    }
    smoke = {
        "schema_version": "0.1",
        "phase": "smoke",
        "observed_at": "2026-07-18T12:01:00Z",
        "runner": runner,
        "program": {
            "path": str(installed_root / "DiffeoForge.exe"),
            "bytes": desktop_record["bytes"],
            "sha256": desktop_record["sha256"],
        },
        "exit_code": 0,
        "arguments": ["--smoke"],
        "network_scope": "desktop_process_only_not_host_wide_isolation",
        "network_connection_count": 0,
        "network_observations": [],
        "sentinel_after": sentinel,
    }
    uninstall = {
        "schema_version": "0.1",
        "phase": "uninstall",
        "observed_at": "2026-07-18T12:02:00Z",
        "runner": runner,
        "program": {
            "path": str(installed_root / "unins000.exe"),
            "bytes": uninstaller_record["bytes"],
            "sha256": uninstaller_record["sha256"],
        },
        "exit_code": 0,
        "log": _record(uninstall_log),
        "install_root": str(installed_root),
        "install_root_absent": True,
        "shortcut_path": str(directory.parent / "DiffeoForge.lnk"),
        "shortcut_absent": True,
        "registration_path": "HKCU:\\Software\\DiffeoForge",
        "registration_absent": True,
        "sentinel_after": sentinel,
    }
    for name, value in (
        (evidence.INSTALL_OBSERVATION_NAME, install),
        (evidence.SMOKE_OBSERVATION_NAME, smoke),
        (evidence.UNINSTALL_OBSERVATION_NAME, uninstall),
    ):
        (directory / name).write_bytes(evidence._json_bytes(value))
    return install_log, uninstall_log, context["path"], context["setup"]


def test_create_and_verify_lifecycle_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    directory = tmp_path / "observation"
    directory.mkdir()
    _raw_lifecycle(directory, context)
    source = tmp_path / "source"
    project = _write(source / "pyproject.toml", b"[project]\nname='diffeoforge'\n")
    contract = _write(source / "distribution" / "windows" / evidence.CONTRACT_NAME, b"contract")
    wrapper = _write(source / "tools" / evidence.WRAPPER_NAME, b"wrapper")
    monkeypatch.setattr(
        evidence,
        "_source_inputs",
        lambda _path: (project, source, contract, wrapper),
    )
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)

    document = evidence.create_installer_installation_evidence(
        directory,
        context["path"],
        expected_build_evidence_sha256=context["expected_sha256"],
        project_file=project,
        source_commit="a" * 40,
    )
    evidence_path = directory / evidence.EVIDENCE_NAME
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    verified = evidence.verify_installer_installation_evidence(
        evidence_path, expected_evidence_sha256=digest
    )

    assert verified == document
    assert verified["runner"]["ephemeral"] is True
    assert verified["installed_smoke"]["process_network_connection_count"] == 0
    assert verified["release_authorized"] is False

    retained = evidence.verify_retained_installer_installation_evidence(
        evidence_path, expected_evidence_sha256=digest
    )
    assert retained == document


def test_retained_artifact_verifier_rejects_changed_phase_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    directory = tmp_path / "observation"
    directory.mkdir()
    _raw_lifecycle(directory, context)
    source = tmp_path / "source"
    project = _write(source / "pyproject.toml", b"[project]\nname='diffeoforge'\n")
    contract = _write(
        source / "distribution" / "windows" / evidence.CONTRACT_NAME, b"contract"
    )
    wrapper = _write(source / "tools" / evidence.WRAPPER_NAME, b"wrapper")
    monkeypatch.setattr(
        evidence,
        "_source_inputs",
        lambda _path: (project, source, contract, wrapper),
    )
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)
    evidence.create_installer_installation_evidence(
        directory,
        context["path"],
        expected_build_evidence_sha256=context["expected_sha256"],
        project_file=project,
        source_commit="a" * 40,
    )
    evidence_path = directory / evidence.EVIDENCE_NAME
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    with (directory / evidence.INSTALL_LOG_NAME).open("ab") as handle:
        handle.write(b"changed")

    with pytest.raises(
        evidence.InstallerInstallationEvidenceError, match="install log"
    ):
        evidence.verify_retained_installer_installation_evidence(
            evidence_path, expected_evidence_sha256=digest
        )


def test_lifecycle_evidence_rejects_changed_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    directory = tmp_path / "observation"
    directory.mkdir()
    _raw_lifecycle(directory, context)
    smoke_path = directory / evidence.SMOKE_OBSERVATION_NAME
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    smoke["sentinel_after"]["sha256"] = "d" * 64
    smoke_path.write_bytes(evidence._json_bytes(smoke))
    source = tmp_path / "source"
    project = _write(source / "pyproject.toml", b"project")
    contract = _write(source / "distribution" / "windows" / evidence.CONTRACT_NAME, b"contract")
    wrapper = _write(source / "tools" / evidence.WRAPPER_NAME, b"wrapper")
    monkeypatch.setattr(
        evidence,
        "_source_inputs",
        lambda _path: (project, source, contract, wrapper),
    )
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)

    with pytest.raises(
        evidence.InstallerInstallationEvidenceError, match="sentinel changed"
    ):
        evidence.create_installer_installation_evidence(
            directory,
            context["path"],
            expected_build_evidence_sha256=context["expected_sha256"],
            project_file=project,
            source_commit="a" * 40,
        )


def test_schema_rejects_release_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    directory = tmp_path / "observation"
    directory.mkdir()
    _raw_lifecycle(directory, context)
    source = tmp_path / "source"
    project = _write(source / "pyproject.toml", b"project")
    contract = _write(source / "distribution" / "windows" / evidence.CONTRACT_NAME, b"contract")
    wrapper = _write(source / "tools" / evidence.WRAPPER_NAME, b"wrapper")
    monkeypatch.setattr(
        evidence,
        "_source_inputs",
        lambda _path: (project, source, contract, wrapper),
    )
    monkeypatch.setattr(evidence, "_build_context", lambda *_args, **_kwargs: context)
    document = evidence.create_installer_installation_evidence(
        directory,
        context["path"],
        expected_build_evidence_sha256=context["expected_sha256"],
        project_file=project,
        source_commit="a" * 40,
    )
    document["release_authorized"] = True

    with pytest.raises(evidence.InstallerInstallationEvidenceError, match="schema"):
        evidence._validate_schema(document)
