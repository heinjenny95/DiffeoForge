from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop import installer_build_evidence as evidence_module
from diffeoforge.desktop.installer_build_evidence import (
    EVIDENCE_NAME,
    OBSERVATION_NAME,
    SIDECAR_NAME,
    InstallerBuildEvidenceError,
    create_installer_build_evidence,
    verify_installer_build_evidence,
    verify_installer_build_prerequisites,
)

ROOT = Path(__file__).parents[1]
OBSERVER_COMMIT = "a" * 40
BUNDLE_COMMIT = "b" * 40
OBSERVED_AT = "2026-07-18T16:00:00Z"
INSTALLER_SHA256 = "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    project = tmp_path / "observer source KÃ¤fer"
    windows = project / "distribution" / "windows"
    tools = project / "tools"
    windows.mkdir(parents=True)
    tools.mkdir()
    shutil.copyfile(
        ROOT / "distribution" / "windows" / evidence_module.CONTRACT_NAME,
        windows / evidence_module.CONTRACT_NAME,
    )
    shutil.copyfile(
        ROOT / "tools" / evidence_module.WRAPPER_NAME,
        tools / evidence_module.WRAPPER_NAME,
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "diffeoforge"\nversion = "0.0.0.dev0"\n',
        encoding="utf-8",
    )
    bundle = tmp_path / "frozen bundle"
    source_evidence = tmp_path / "six file evidence"
    plan_output = tmp_path / "plan output"
    toolchain = tmp_path / "portable toolchain"
    portable_directory = tmp_path / "portable evidence"
    evidence_output = tmp_path / "build evidence"
    for directory in (
        bundle,
        source_evidence,
        plan_output,
        toolchain,
        portable_directory,
        evidence_output,
    ):
        directory.mkdir()
    compiler = toolchain / "ISCC.exe"
    compiler.write_bytes(b"synthetic authenticated compiler")
    plan_path = plan_output / "installer-build-plan.json"
    plan_path.write_bytes(b'{"synthetic":"plan"}\n')
    plan_digest = _sha256(plan_path)
    (plan_output / "installer-build-plan.sha256").write_text(
        f"{plan_digest}  installer-build-plan.json\n", encoding="ascii"
    )
    portable_path = portable_directory / evidence_module.PORTABLE_EVIDENCE_NAME
    portable_path.write_bytes(b'{"synthetic":"portable"}\n')
    portable_digest = _sha256(portable_path)
    setup_name = "DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe"
    setup = plan_output / setup_name
    arguments = [
        "/Qp",
        "/DAppVersion=0.0.0.dev0",
        f"/DSourceCommit={BUNDLE_COMMIT}",
        f"/DBundleDir={bundle.resolve()}",
        f"/DEvidenceDir={source_evidence.resolve()}",
        f"/DLicenseFile={(project / 'LICENSE').resolve()}",
        f"/DOutputDir={plan_output.resolve()}",
        "/DOutputBaseFilename=DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup",
        str((project / "distribution" / "windows" / "DiffeoForge.iss").resolve()),
    ]
    plan = {
        "source": {
            "commit_sha": BUNDLE_COMMIT,
            "application_version": "0.0.0.dev0",
            "development_version": True,
            "release_candidate": False,
        },
        "toolchain": {"asset_sha256": INSTALLER_SHA256},
        "inputs": {
            "bundle": {
                "directory": str(bundle.resolve()),
                "inventory_sha256": "c" * 64,
            },
            "evidence": {
                "directory": str(source_evidence.resolve()),
                "freeze_evidence_sha256": "d" * 64,
                "dependency_evidence_sha256": "e" * 64,
                "sbom_sha256": "f" * 64,
            },
        },
        "output": {
            "directory": str(plan_output.resolve()),
            "setup_filename": setup_name,
            "setup_path": str(setup.resolve()),
        },
        "compiler": {
            "program": "ISCC.exe",
            "arguments": arguments,
            "shell": False,
            "execution_authorized": False,
        },
    }
    portable = {
        "installer": {"sha256": INSTALLER_SHA256},
        "portable_install": {"installation_directory": str(toolchain.resolve())},
        "compiler_probe": {
            "program": {"path": str(compiler.resolve())},
            "exit_code": 0,
        },
        "compiler_execution": {"diffeoforge_installer_built": False},
        "execution_authorized": False,
    }
    monkeypatch.setattr(
        evidence_module,
        "verify_desktop_installer_build_plan",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        evidence_module,
        "verify_desktop_installer_build_plan_after_build",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        evidence_module,
        "verify_inno_portable_toolchain_evidence",
        lambda *_args, **_kwargs: portable,
    )
    return {
        "project": project,
        "bundle": bundle,
        "source_evidence": source_evidence,
        "plan_output": plan_output,
        "toolchain": toolchain,
        "plan_path": plan_path,
        "plan_digest": plan_digest,
        "portable_path": portable_path,
        "portable_digest": portable_digest,
        "evidence_output": evidence_output,
        "setup": setup,
        "plan": plan,
        "portable": portable,
    }


def _arguments(sources: dict[str, object]) -> dict[str, object]:
    return {
        "expected_plan_sha256": sources["plan_digest"],
        "portable_evidence_path": sources["portable_path"],
        "expected_portable_evidence_sha256": sources["portable_digest"],
        "project_file": Path(sources["project"]) / "pyproject.toml",
        "evidence_output_directory": sources["evidence_output"],
        "observer_source_commit": OBSERVER_COMMIT,
    }


def _complete_build(sources: dict[str, object]) -> None:
    setup = Path(sources["setup"])
    setup.write_bytes(b"synthetic unsigned engineering installer")
    setup_sha256 = _sha256(setup)
    setup.with_name(f"{setup.name}.sha256").write_bytes(
        f"{setup_sha256}  {setup.name}\n".encode("ascii")
    )
    compiler = Path(sources["toolchain"]) / "ISCC.exe"
    _write_json(
        Path(sources["evidence_output"]) / OBSERVATION_NAME,
        {
            "schema_version": "0.1",
            "observed_at": OBSERVED_AT,
            "observer_source_commit": OBSERVER_COMMIT,
            "program_path": str(compiler.resolve()),
            "program_bytes": compiler.stat().st_size,
            "program_sha256": _sha256(compiler),
            "plan_path": str(Path(sources["plan_path"]).resolve()),
            "plan_sha256": sources["plan_digest"],
            "command": sources["plan"]["compiler"]["arguments"],
            "exit_code": 0,
            "output_lines": ["Successful compile (synthetic observation)"],
            "setup_path": str(setup.resolve()),
            "setup_bytes": setup.stat().st_size,
            "setup_sha256": setup_sha256,
            "setup_authenticode_status": "NotSigned",
            "setup_execution": False,
            "distribution_authorized": False,
        },
    )


def _create(sources: dict[str, object]) -> tuple[Path, str]:
    _complete_build(sources)
    path = create_installer_build_evidence(sources["plan_path"], **_arguments(sources))
    return path, _sha256(path)


def test_preflight_is_bounded_to_nonrelease_plan(sources: dict[str, object]) -> None:
    result = verify_installer_build_prerequisites(
        sources["plan_path"], **_arguments(sources)
    )
    assert result["status"] == "engineering_installer_build_prerequisites_satisfied"
    assert result["release_candidate"] is False
    assert result["setup_execution_authorized"] is False
    assert result["distribution_authorized"] is False


def test_create_and_offline_verify_every_retained_binding(
    sources: dict[str, object],
) -> None:
    path, digest = _create(sources)
    evidence = verify_installer_build_evidence(
        path, expected_evidence_sha256=digest
    )
    assert evidence["plan"]["release_candidate"] is False
    assert evidence["compiler_execution"]["exit_code"] == 0
    assert evidence["compiler_execution"]["setup_authenticode_status"] == "NotSigned"
    assert evidence["setup_execution_authorized"] is False
    assert evidence["distribution_authorized"] is False
    assert evidence["release_authorized"] is False
    assert path.read_bytes() == _json_bytes(evidence)
    assert path.with_name(SIDECAR_NAME).read_text(encoding="ascii") == (
        f"{digest}  {EVIDENCE_NAME}\n"
    )


@pytest.mark.parametrize("target", ["setup", "raw", "portable", "plan"])
def test_offline_verifier_rejects_tampered_retained_inputs(
    sources: dict[str, object], target: str
) -> None:
    path, digest = _create(sources)
    changed = {
        "setup": Path(sources["setup"]),
        "raw": Path(sources["evidence_output"]) / OBSERVATION_NAME,
        "portable": Path(sources["portable_path"]),
        "plan": Path(sources["plan_path"]),
    }[target]
    changed.write_bytes(b"tampered")
    with pytest.raises(InstallerBuildEvidenceError):
        verify_installer_build_evidence(path, expected_evidence_sha256=digest)


def test_verifier_requires_external_digest_and_exact_evidence_boundary(
    sources: dict[str, object],
) -> None:
    path, digest = _create(sources)
    with pytest.raises(InstallerBuildEvidenceError, match="externally expected"):
        verify_installer_build_evidence(
            path, expected_evidence_sha256="0" * 64
        )
    (Path(sources["evidence_output"]) / "unexpected.txt").write_text(
        "extra", encoding="utf-8"
    )
    with pytest.raises(InstallerBuildEvidenceError, match="exact file boundary"):
        verify_installer_build_evidence(path, expected_evidence_sha256=digest)


def test_preflight_rejects_release_candidate_and_nonempty_output(
    sources: dict[str, object],
) -> None:
    sources["plan"]["source"]["release_candidate"] = True
    with pytest.raises(InstallerBuildEvidenceError, match="bounded engineering build"):
        verify_installer_build_prerequisites(
            sources["plan_path"], **_arguments(sources)
        )
    sources["plan"]["source"]["release_candidate"] = False
    (Path(sources["evidence_output"]) / "existing.txt").write_text(
        "occupied", encoding="utf-8"
    )
    with pytest.raises(InstallerBuildEvidenceError, match="exact file boundary"):
        verify_installer_build_prerequisites(
            sources["plan_path"], **_arguments(sources)
        )


def test_wrapper_preflights_before_iscc_and_never_executes_setup() -> None:
    wrapper = (ROOT / "tools" / evidence_module.WRAPPER_NAME).read_text(encoding="utf-8")
    preflight = wrapper.index("installer_build_evidence.py preflight")
    compiler = wrapper.index("& $compiler.FullName")
    create = wrapper.index("installer_build_evidence.py create")
    assert preflight < compiler < create
    assert "& $setup" not in wrapper
    assert "Setup executed: false" in wrapper
    assert "Distribution or release authorized: false" in wrapper


def test_cli_verify_reports_all_non_authorizations(
    sources: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    path, digest = _create(sources)
    script = ROOT / "tools" / "installer_build_evidence.py"
    spec = importlib.util.spec_from_file_location("installer_build_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["verify", str(path), "--expect-evidence-sha256", digest]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["setup_execution_authorized"] is False
    assert report["distribution_authorized"] is False
    assert report["release_authorized"] is False
