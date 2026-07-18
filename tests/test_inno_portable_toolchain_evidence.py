from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop import inno_portable_toolchain_evidence as evidence_module
from diffeoforge.desktop.inno_portable_toolchain_evidence import (
    EVIDENCE_NAME,
    SIDECAR_NAME,
    InnoPortableToolchainEvidenceError,
    create_inno_portable_toolchain_evidence,
    verify_inno_portable_toolchain_evidence,
    verify_inno_portable_toolchain_prerequisites,
)

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "a" * 40
OBSERVED_AT = "2026-07-18T15:00:00Z"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_project(tmp_path: Path, installer: Path, components: dict[str, bytes]) -> Path:
    project = tmp_path / "source beetle"
    windows = project / "distribution" / "windows"
    tools = project / "tools"
    windows.mkdir(parents=True)
    tools.mkdir()
    contract = json.loads(
        (
            ROOT
            / "distribution"
            / "windows"
            / "inno-portable-toolchain-evidence-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )
    contract["installer"] = {
        "name": installer.name,
        "bytes": installer.stat().st_size,
        "sha256": _sha256(installer),
    }
    contract["portable_install"]["expected_file_count"] = len(components)
    contract["portable_install"]["expected_directory_count"] = 0
    contract["portable_install"]["expected_total_bytes"] = sum(
        len(payload) for payload in components.values()
    )
    contract["critical_components"]["files"] = {
        name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in components.items()
    }
    _write_json(windows / evidence_module.CONTRACT_NAME, contract)
    shutil.copyfile(
        ROOT / "distribution" / "windows" / evidence_module.PROBE_SCRIPT_NAME,
        windows / evidence_module.PROBE_SCRIPT_NAME,
    )
    shutil.copyfile(
        ROOT / "tools" / evidence_module.WRAPPER_NAME,
        tools / evidence_module.WRAPPER_NAME,
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "diffeoforge"\nversion = "0.0.0.dev0"\n',
        encoding="utf-8",
    )
    return project


def _prerequisite_documents(installer: Path) -> tuple[dict, dict]:
    installer_record = {"path": str(installer.resolve()), "sha256": _sha256(installer)}
    return (
        {
            "asset": installer_record,
            "source": {"commit_sha": "b" * 40},
            "execution_authorized": False,
        },
        {
            "installer": installer_record,
            "source": {"commit_sha": "c" * 40},
            "issigtool_execution": {"exit_code": 0},
            "installer_execution_authorized": False,
            "execution_authorized": False,
        },
    )


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path | str]:
    installer_directory = tmp_path / "installer input"
    installer_directory.mkdir()
    installer = installer_directory / evidence_module.INSTALLER_NAME
    installer.write_bytes(b"authenticated-test-installer")
    components = {
        "ISCC.exe": b"synthetic-iscc",
        "ISCmplr.dll": b"synthetic-compiler-library",
        "ISPP.dll": b"synthetic-preprocessor-library",
        "ISSigTool.exe": b"synthetic-installed-signature-tool",
    }
    monkeypatch.setattr(evidence_module, "INSTALLER_BYTES", installer.stat().st_size)
    monkeypatch.setattr(evidence_module, "INSTALLER_SHA256", _sha256(installer))
    monkeypatch.setattr(evidence_module, "EXPECTED_FILE_COUNT", len(components))
    monkeypatch.setattr(evidence_module, "EXPECTED_DIRECTORY_COUNT", 0)
    monkeypatch.setattr(
        evidence_module,
        "EXPECTED_TOTAL_BYTES",
        sum(len(payload) for payload in components.values()),
    )
    monkeypatch.setattr(
        evidence_module,
        "CRITICAL_COMPONENTS",
        {
            name: (len(payload), hashlib.sha256(payload).hexdigest())
            for name, payload in components.items()
        },
    )
    project = _copy_project(tmp_path, installer, components)
    toolchain = tmp_path / "portable toolchain"
    probe_output = tmp_path / "probe output"
    output = tmp_path / "evidence output"
    for directory in (toolchain, probe_output, output):
        directory.mkdir()
    for name, payload in components.items():
        (toolchain / name).write_bytes(payload)
    toolchain_evidence_directory = tmp_path / "prior toolchain evidence"
    signature_evidence_directory = tmp_path / "prior signature evidence"
    toolchain_evidence_directory.mkdir()
    signature_evidence_directory.mkdir()
    toolchain_evidence = toolchain_evidence_directory / "inno-toolchain-evidence.json"
    signature_evidence = signature_evidence_directory / "inno-signature-evidence.json"
    toolchain_evidence.write_bytes(b'{"synthetic":"toolchain"}\n')
    signature_evidence.write_bytes(b'{"synthetic":"signature"}\n')
    toolchain_document, signature_document = _prerequisite_documents(installer)
    monkeypatch.setattr(
        evidence_module,
        "verify_inno_toolchain_evidence",
        lambda *_args, **_kwargs: toolchain_document,
    )
    monkeypatch.setattr(
        evidence_module,
        "verify_inno_signature_evidence",
        lambda *_args, **_kwargs: signature_document,
    )
    return {
        "installer": installer,
        "toolchain_evidence": toolchain_evidence,
        "toolchain_evidence_sha256": _sha256(toolchain_evidence),
        "signature_evidence": signature_evidence,
        "signature_evidence_sha256": _sha256(signature_evidence),
        "project": project,
        "toolchain": toolchain,
        "probe_output": probe_output,
        "output": output,
    }


def _arguments(sources: dict[str, Path | str]) -> dict:
    return {
        "toolchain_evidence_path": sources["toolchain_evidence"],
        "expected_toolchain_evidence_sha256": sources["toolchain_evidence_sha256"],
        "signature_evidence_path": sources["signature_evidence"],
        "expected_signature_evidence_sha256": sources["signature_evidence_sha256"],
        "project_file": Path(sources["project"]) / "pyproject.toml",
        "toolchain_directory": sources["toolchain"],
        "probe_output_directory": sources["probe_output"],
        "evidence_output_directory": sources["output"],
        "source_commit": SOURCE_COMMIT,
    }


def _write_raw_observations(sources: dict[str, Path | str]) -> None:
    project = Path(sources["project"])
    installer = Path(sources["installer"]).resolve()
    toolchain = Path(sources["toolchain"]).resolve()
    probe_output = Path(sources["probe_output"]).resolve()
    output = Path(sources["output"]).resolve()
    probe_script = (project / "distribution" / "windows" / evidence_module.PROBE_SCRIPT_NAME)
    log = output / evidence_module.INSTALL_LOG_NAME
    log.write_text(
        "Installation process succeeded.\nNeed to restart Windows? No\n/PORTABLE=1\n",
        encoding="utf-8",
    )
    inventory = evidence_module._inventory(toolchain)
    install_command = [
        "/PORTABLE=1",
        "/CURRENTUSER",
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/NOICONS",
        "/LANG=english",
        f'/DIR="{toolchain}"',
        f'/LOG="{log}"',
    ]
    _write_json(
        output / evidence_module.INSTALL_OBSERVATION_NAME,
        {
            "schema_version": "0.1",
            "observed_at": OBSERVED_AT,
            "installer_path": str(installer),
            "installer_bytes": installer.stat().st_size,
            "installer_sha256": _sha256(installer),
            "command": install_command,
            "exit_code": 0,
            "installation_directory": str(toolchain),
            "log_path": str(log),
            "installed_inventory": inventory,
            "installed_file_count": len(inventory),
            "installed_directory_count": 0,
            "installed_total_bytes": sum(int(item["bytes"]) for item in inventory),
            "uninstaller_file_count": 0,
            "portable_mode": True,
            "current_user": True,
            "restart": False,
            "system_install_claim": False,
        },
    )
    components = []
    for name in sorted(evidence_module.CRITICAL_COMPONENTS):
        component = toolchain / name
        components.append(
            {
                "name": name,
                "path": str(component),
                "bytes": component.stat().st_size,
                "sha256": _sha256(component),
                "status": "Valid",
                "signer_subject": evidence_module.SIGNER_SUBJECT,
                "signer_issuer": "CN=Synthetic Test Issuer",
                "signer_thumbprint": "A" * 40,
                "timestamp_subject": "CN=Synthetic Test Timestamp",
                "timestamp_thumbprint": "B" * 40,
            }
        )
    _write_json(
        output / evidence_module.AUTHENTICODE_OBSERVATION_NAME,
        {"schema_version": "0.1", "observed_at": OBSERVED_AT, "components": components},
    )
    compiled = probe_output / evidence_module.PROBE_OUTPUT_NAME
    compiled.write_bytes(b"synthetic-payload-free-compiler-probe")
    iscc = toolchain / "ISCC.exe"
    _write_json(
        output / evidence_module.PROBE_OBSERVATION_NAME,
        {
            "schema_version": "0.1",
            "observed_at": OBSERVED_AT,
            "program_path": str(iscc),
            "program_bytes": iscc.stat().st_size,
            "program_sha256": _sha256(iscc),
            "script_path": str(probe_script.resolve()),
            "script_bytes": probe_script.stat().st_size,
            "script_sha256": _sha256(probe_script),
            "command": [
                "/Qp",
                "/O+",
                f"/O{probe_output}",
                "/FDiffeoForge-Compiler-Probe",
                str(probe_script.resolve()),
            ],
            "exit_code": 0,
            "output_lines": ["Successful compile (synthetic observation)"],
            "output_path": str(compiled),
            "output_bytes": compiled.stat().st_size,
            "output_sha256": _sha256(compiled),
            "payload_free": True,
            "distribution_authorized": False,
        },
    )


def _create(sources: dict[str, Path | str]) -> tuple[Path, str]:
    _write_raw_observations(sources)
    path = create_inno_portable_toolchain_evidence(
        sources["installer"], **_arguments(sources)
    )
    return path, _sha256(path)


def test_preflight_and_canonical_offline_reconstruction(
    sources: dict[str, Path | str],
) -> None:
    for path in (sources["toolchain"], sources["probe_output"]):
        for entry in Path(path).iterdir():
            entry.unlink()
    preflight = verify_inno_portable_toolchain_prerequisites(
        sources["installer"], **_arguments(sources)
    )
    assert preflight["status"] == "portable_inno_toolchain_prerequisites_satisfied"
    assert preflight["diffeoforge_installer_build_authorized"] is False


def test_create_and_verify_reconstructs_every_retained_binding(
    sources: dict[str, Path | str],
) -> None:
    path, digest = _create(sources)
    evidence = verify_inno_portable_toolchain_evidence(
        path, expected_evidence_sha256=digest
    )
    assert evidence["portable_install"]["installed_file_count"] == 4
    assert evidence["compiler_probe"]["exit_code"] == 0
    assert evidence["compiler_execution"]["diffeoforge_installer_built"] is False
    assert evidence["execution_authorized"] is False
    assert path.read_bytes() == _json_bytes(evidence)
    assert path.with_name(SIDECAR_NAME).read_text(encoding="ascii") == (
        f"{digest}  {EVIDENCE_NAME}\n"
    )


def test_raw_inventory_order_is_normalized_before_exact_comparison(
    sources: dict[str, Path | str],
) -> None:
    _write_raw_observations(sources)
    raw_path = Path(sources["output"]) / evidence_module.INSTALL_OBSERVATION_NAME
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["installed_inventory"].reverse()
    _write_json(raw_path, raw)

    path = create_inno_portable_toolchain_evidence(
        sources["installer"], **_arguments(sources)
    )
    digest = _sha256(path)
    assert verify_inno_portable_toolchain_evidence(
        path, expected_evidence_sha256=digest
    )["portable_install"]["installed_file_count"] == 4


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        ("toolchain", b"tampered-component"),
        ("probe", b"tampered-probe"),
        ("raw", b'{"tampered":true}\n'),
    ],
)
def test_offline_verifier_rejects_tampered_retained_inputs(
    sources: dict[str, Path | str], target: str, replacement: bytes
) -> None:
    path, digest = _create(sources)
    if target == "toolchain":
        changed = Path(sources["toolchain"]) / "ISCC.exe"
    elif target == "probe":
        changed = Path(sources["probe_output"]) / evidence_module.PROBE_OUTPUT_NAME
    else:
        changed = Path(sources["output"]) / evidence_module.PROBE_OBSERVATION_NAME
    changed.write_bytes(replacement)
    with pytest.raises(InnoPortableToolchainEvidenceError):
        verify_inno_portable_toolchain_evidence(path, expected_evidence_sha256=digest)


def test_verifier_requires_external_digest_and_exact_output_boundary(
    sources: dict[str, Path | str],
) -> None:
    path, digest = _create(sources)
    with pytest.raises(InnoPortableToolchainEvidenceError):
        verify_inno_portable_toolchain_evidence(
            path, expected_evidence_sha256="0" * 64
        )
    (Path(sources["output"]) / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(InnoPortableToolchainEvidenceError):
        verify_inno_portable_toolchain_evidence(path, expected_evidence_sha256=digest)


def test_preflight_rejects_nonempty_or_overlapping_directories(
    sources: dict[str, Path | str],
) -> None:
    (Path(sources["output"]) / "existing.txt").write_text("occupied", encoding="utf-8")
    with pytest.raises(InnoPortableToolchainEvidenceError, match="three empty"):
        verify_inno_portable_toolchain_prerequisites(
            sources["installer"], **_arguments(sources)
        )
    arguments = _arguments(sources)
    arguments["evidence_output_directory"] = sources["probe_output"]
    with pytest.raises(InnoPortableToolchainEvidenceError, match="distinct"):
        verify_inno_portable_toolchain_prerequisites(sources["installer"], **arguments)


def test_prerequisite_failure_forbids_preflight(
    sources: dict[str, Path | str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        evidence_module,
        "verify_inno_signature_evidence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid signature")),
    )
    for path in (sources["toolchain"],):
        for entry in Path(path).iterdir():
            entry.unlink()
    with pytest.raises(InnoPortableToolchainEvidenceError, match="verification failed"):
        verify_inno_portable_toolchain_prerequisites(
            sources["installer"], **_arguments(sources)
        )


def test_wrapper_preflights_before_starting_installer_and_compiler() -> None:
    wrapper = (ROOT / "tools" / evidence_module.WRAPPER_NAME).read_text(encoding="utf-8")
    preflight = wrapper.index("inno_portable_toolchain_evidence.py preflight")
    installer = wrapper.index("$process = Start-Process")
    compiler = wrapper.index("& $iscc.FullName")
    create = wrapper.index("inno_portable_toolchain_evidence.py create")
    assert preflight < installer < compiler < create
    assert '-WindowStyle Hidden' in wrapper
    assert '"/PORTABLE=1"' in wrapper
    assert "[pscustomobject][ordered]@{" in wrapper
    assert "DiffeoForge installer built: false" in wrapper


def test_cli_verify_reports_bounded_non_authorization(
    sources: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    path, digest = _create(sources)
    script = ROOT / "tools" / "inno_portable_toolchain_evidence.py"
    spec = importlib.util.spec_from_file_location("portable_inno_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["verify", str(path), "--expect-evidence-sha256", digest]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["compiler_probe_exit_code"] == 0
    assert report["diffeoforge_installer_built"] is False
    assert report["execution_authorized"] is False
