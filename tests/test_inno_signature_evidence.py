from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop import inno_signature_evidence as evidence_module
from diffeoforge.desktop.inno_signature_evidence import (
    API_VERIFIER_NAME,
    EVIDENCE_NAME,
    EXECUTION_NAME,
    KEY_CONTENT_NAME,
    SIDECAR_NAME,
    SIGNATURE_ATTESTATION_NAME,
    SIGNATURE_VERIFIER_NAME,
    TAG_OBSERVATION_NAME,
    TOOL_ATTESTATION_NAME,
    TOOL_AUTHENTICODE_NAME,
    TOOL_VERIFIER_NAME,
    InnoSignatureEvidenceError,
    create_inno_signature_evidence,
    verify_inno_signature_evidence,
    verify_inno_signature_prerequisites,
)

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "e" * 40
OBSERVED_AT = "2026-07-18T13:00:00Z"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_bytes(_json_bytes(value))


def _project(tmp_path: Path, records: dict[str, tuple[int, str]]) -> Path:
    project = tmp_path / "source Käfer"
    windows = project / "distribution" / "windows"
    tools = project / "tools"
    windows.mkdir(parents=True)
    tools.mkdir()
    contract = json.loads(
        (
            ROOT / "distribution" / "windows" / "inno-signature-evidence-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )
    for key, section in (
        ("installer", "installer"),
        ("signature", "signature"),
        ("tool", "signature_tool"),
        ("key", "public_key"),
    ):
        contract[section]["bytes"], contract[section]["sha256"] = records[key]
    _write_json(windows / evidence_module.CONTRACT_NAME, contract)
    shutil.copyfile(
        ROOT / "tools" / evidence_module.WRAPPER_NAME,
        tools / evidence_module.WRAPPER_NAME,
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "diffeoforge"\nversion = "0.0.0.dev0"\n',
        encoding="utf-8",
    )
    return project


def _statement(
    *,
    release_tag: str,
    release_database_id: int,
    release_tag_object_sha1: str,
    release_purl: str,
    subject_name: str,
    subject_sha256: str,
) -> dict:
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"uri": release_purl, "digest": {"sha1": release_tag_object_sha1}},
            {"name": subject_name, "digest": {"sha256": subject_sha256}},
        ],
        "predicateType": evidence_module.PREDICATE_TYPE,
        "predicate": {
            "databaseId": str(release_database_id),
            "ownerId": "1092483",
            "packageId": str(evidence_module.REPOSITORY_ID),
            "purl": release_purl,
            "repository": evidence_module.REPOSITORY,
            "repositoryId": str(evidence_module.REPOSITORY_ID),
            "tag": release_tag,
        },
    }


def _attestation(**kwargs: object) -> dict:
    statement = _statement(**kwargs)
    payload = base64.b64encode(
        json.dumps(statement, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return {
        "attestation": {
            "bundle": {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "verificationMaterial": {},
                "dsseEnvelope": {
                    "payload": payload,
                    "payloadType": "application/vnd.in-toto+json",
                    "signatures": [{"sig": "synthetic-not-cryptographic"}],
                },
            }
        },
        "verificationResult": {
            "signature": {"certificate": {"subjectAlternativeName": evidence_module.ATTESTER_SAN}},
            "verifiedTimestamps": [
                {
                    "type": "TimestampAuthority",
                    "uri": evidence_module.TIMESTAMP_AUTHORITY,
                    "timestamp": "2026-07-13T07:43:34Z",
                }
            ],
            "statement": statement,
        },
    }


def _authenticode(tool: Path, tool_sha256: str) -> dict:
    return {
        "schema_version": "0.1",
        "observed_at": OBSERVED_AT,
        "asset_path": str(tool.resolve()),
        "asset_sha256": tool_sha256,
        "status": "Valid",
        "status_message": "Signature verified.",
        "signer_subject": evidence_module.SIGNER_SUBJECT,
        "signer_issuer": "CN=Sectigo Public Code Signing CA R36",
        "signer_thumbprint": "A" * 40,
        "signer_not_before": "2025-03-10T00:00:00Z",
        "signer_not_after": "2028-03-09T23:59:59Z",
        "timestamp_subject": "CN=Sectigo Public Time Stamping Signer R36",
        "timestamp_thumbprint": "B" * 40,
    }


def _release_verifier(program: Path, subject: Path, release_tag: str) -> dict:
    return {
        "schema_version": "0.1",
        "observed_at": OBSERVED_AT,
        "program_path": str(program.resolve()),
        "program_bytes": program.stat().st_size,
        "program_sha256": _sha256(program.read_bytes()),
        "version_output": "gh version 2.96.0 (2026-07-02)",
        "command": [
            "release",
            "verify-asset",
            release_tag,
            str(subject.resolve()),
            "--repo",
            evidence_module.REPOSITORY,
            "--format",
            "json",
        ],
        "exit_code": 0,
    }


def _signed_tag() -> dict:
    return {
        "sha": evidence_module.INSTALLER_RELEASE_TAG_OBJECT_SHA1,
        "tag": evidence_module.INSTALLER_RELEASE_TAG,
        "object": {
            "sha": evidence_module.INSTALLER_RELEASE_COMMIT_SHA1,
            "type": "commit",
        },
        "verification": {
            "verified": True,
            "reason": "valid",
            "signature": "-----BEGIN PGP SIGNATURE-----\nsynthetic\n",
            "payload": (
                f"object {evidence_module.INSTALLER_RELEASE_COMMIT_SHA1}\n"
                f"type commit\ntag {evidence_module.INSTALLER_RELEASE_TAG}\n"
            ),
            "verified_at": "2026-07-11T10:57:51Z",
        },
    }


def _key_content(key_payload: bytes) -> dict:
    commit = evidence_module.INSTALLER_RELEASE_COMMIT_SHA1
    encoded = base64.b64encode(key_payload).decode("ascii")
    return {
        "name": evidence_module.KEY_NAME,
        "path": evidence_module.KEY_NAME,
        "sha": evidence_module.KEY_GIT_BLOB_SHA1,
        "size": len(key_payload),
        "download_url": (
            "https://raw.githubusercontent.com/jrsoftware/issrc/"
            f"{commit}/{evidence_module.KEY_NAME}"
        ),
        "type": "file",
        "content": "\n".join(encoded[index : index + 12] for index in range(0, len(encoded), 12)),
        "encoding": "base64",
    }


def _sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path | str]:
    payloads = {
        "installer": b"synthetic installer\n",
        "signature": b"synthetic detached signature\n",
        "key": b"synthetic public key\n",
        "tool": b"synthetic signature verifier\n",
    }
    records = {name: (len(value), _sha256(value)) for name, value in payloads.items()}
    for name in ("INSTALLER", "SIGNATURE", "KEY", "TOOL"):
        key = name.lower()
        monkeypatch.setattr(evidence_module, f"{name}_BYTES", records[key][0])
        monkeypatch.setattr(evidence_module, f"{name}_SHA256", records[key][1])
    project = _project(tmp_path, records)

    installer_dir = tmp_path / "installer input"
    installer_dir.mkdir()
    installer = installer_dir / evidence_module.INSTALLER_NAME
    signature = installer_dir / evidence_module.SIGNATURE_NAME
    installer.write_bytes(payloads["installer"])
    signature.write_bytes(payloads["signature"])
    key_dir = tmp_path / "key input"
    key_dir.mkdir()
    key_path = key_dir / evidence_module.KEY_NAME
    key_path.write_bytes(payloads["key"])
    tool_dir = tmp_path / "tool input"
    tool_dir.mkdir()
    tool = tool_dir / evidence_module.TOOL_NAME
    tool.write_bytes(payloads["tool"])
    program_dir = tmp_path / "github input"
    program_dir.mkdir()
    program = program_dir / "gh.exe"
    program.write_bytes(b"synthetic GitHub CLI\n")
    output = tmp_path / "observation Käfer"
    output.mkdir()

    _write_json(
        output / TOOL_ATTESTATION_NAME,
        _attestation(
            release_tag=evidence_module.TOOL_RELEASE_TAG,
            release_database_id=evidence_module.TOOL_RELEASE_DATABASE_ID,
            release_tag_object_sha1=evidence_module.TOOL_RELEASE_TAG_OBJECT_SHA1,
            release_purl=evidence_module.TOOL_RELEASE_PURL,
            subject_name=evidence_module.TOOL_NAME,
            subject_sha256=records["tool"][1],
        ),
    )
    _write_json(
        output / SIGNATURE_ATTESTATION_NAME,
        _attestation(
            release_tag=evidence_module.INSTALLER_RELEASE_TAG,
            release_database_id=evidence_module.INSTALLER_RELEASE_DATABASE_ID,
            release_tag_object_sha1=evidence_module.INSTALLER_RELEASE_TAG_OBJECT_SHA1,
            release_purl=evidence_module.INSTALLER_RELEASE_PURL,
            subject_name=evidence_module.SIGNATURE_NAME,
            subject_sha256=records["signature"][1],
        ),
    )
    _write_json(output / TOOL_AUTHENTICODE_NAME, _authenticode(tool, records["tool"][1]))
    _write_json(
        output / TOOL_VERIFIER_NAME,
        _release_verifier(program, tool, evidence_module.TOOL_RELEASE_TAG),
    )
    _write_json(
        output / SIGNATURE_VERIFIER_NAME,
        _release_verifier(program, signature, evidence_module.INSTALLER_RELEASE_TAG),
    )
    _write_json(output / TAG_OBSERVATION_NAME, _signed_tag())
    _write_json(output / KEY_CONTENT_NAME, _key_content(payloads["key"]))
    api_verifier = {
        "schema_version": "0.1",
        "observed_at": OBSERVED_AT,
        "program_path": str(program.resolve()),
        "program_bytes": program.stat().st_size,
        "program_sha256": _sha256(program.read_bytes()),
        "version_output": "gh version 2.96.0 (2026-07-02)",
        "commands": [
            {
                "arguments": ["api", evidence_module.TAG_API_ENDPOINT],
                "exit_code": 0,
                "output_file": TAG_OBSERVATION_NAME,
                "output_sha256": _sha256((output / TAG_OBSERVATION_NAME).read_bytes()),
            },
            {
                "arguments": ["api", evidence_module.KEY_API_ENDPOINT],
                "exit_code": 0,
                "output_file": KEY_CONTENT_NAME,
                "output_sha256": _sha256((output / KEY_CONTENT_NAME).read_bytes()),
            },
        ],
    }
    _write_json(output / API_VERIFIER_NAME, api_verifier)
    return {
        "project": project,
        "installer": installer,
        "signature": signature,
        "key": key_path,
        "tool": tool,
        "program": program,
        "output": output,
        **{f"{name}_sha256": value[1] for name, value in records.items()},
    }


def _arguments(sources: dict[str, Path | str]) -> dict[str, Path | str]:
    return {
        "signature_path": sources["signature"],
        "public_key_path": sources["key"],
        "signature_tool_path": sources["tool"],
        "project_file": Path(sources["project"]) / "pyproject.toml",
        "output_directory": sources["output"],
        "source_commit": SOURCE_COMMIT,
    }


def _add_execution(sources: dict[str, Path | str]) -> None:
    hashes = {
        "installer_sha256": sources["installer_sha256"],
        "signature_sha256": sources["signature_sha256"],
        "public_key_sha256": sources["key_sha256"],
        "signature_tool_sha256": sources["tool_sha256"],
    }
    installer = Path(sources["installer"]).resolve()
    key = Path(sources["key"]).resolve()
    tool = Path(sources["tool"]).resolve()
    _write_json(
        Path(sources["output"]) / EXECUTION_NAME,
        {
            "schema_version": "0.1",
            "observed_at": OBSERVED_AT,
            "program_path": str(tool),
            "program_bytes": tool.stat().st_size,
            "program_sha256": sources["tool_sha256"],
            "signature_path": str(Path(sources["signature"]).resolve()),
            "command": [f"--key-file={key}", "verify", str(installer)],
            "exit_code": 0,
            "output_lines": [f"{installer}: OK"],
            "inputs_before": hashes,
            "inputs_after": hashes,
            "signature_tool_execution_scope": "verify_exact_installer_signature_only",
            "installer_execution": False,
        },
    )


def test_preflight_then_canonical_evidence_is_deterministic_and_nonexecuting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    preflight = verify_inno_signature_prerequisites(sources["installer"], **_arguments(sources))
    assert preflight["status"] == "issigtool_verifier_prerequisites_satisfied"
    assert preflight["signature_tool_execution_scope"] == ("verify_exact_installer_signature_only")
    assert preflight["installer_execution_authorized"] is False

    _add_execution(sources)
    path = create_inno_signature_evidence(sources["installer"], **_arguments(sources))
    payload = path.read_bytes()
    digest = _sha256(payload)
    evidence = verify_inno_signature_evidence(path, expected_evidence_sha256=digest)
    assert evidence["issigtool_execution"]["exit_code"] == 0
    assert evidence["issigtool_execution"]["installer_execution"] is False
    assert evidence["installer_execution_authorized"] is False
    assert evidence["execution_authorized"] is False
    assert (Path(sources["output"]) / SIDECAR_NAME).read_bytes() == (
        f"{digest}  {EVIDENCE_NAME}\n".encode("ascii")
    )

    path.unlink()
    (Path(sources["output"]) / SIDECAR_NAME).unlink()
    recreated = create_inno_signature_evidence(sources["installer"], **_arguments(sources))
    assert recreated.read_bytes() == payload


@pytest.mark.parametrize(
    ("file_name", "mutate", "message"),
    [
        (
            TOOL_ATTESTATION_NAME,
            lambda value: value["verificationResult"]["statement"]["predicate"].__setitem__(
                "tag", "other"
            ),
            "predicate differs",
        ),
        (
            TOOL_AUTHENTICODE_NAME,
            lambda value: value.__setitem__("signer_subject", "CN=Wrong"),
            "Authenticode identity differs",
        ),
        (
            SIGNATURE_VERIFIER_NAME,
            lambda value: value["command"].__setitem__(2, "latest"),
            "release verifier observation differs",
        ),
        (
            TAG_OBSERVATION_NAME,
            lambda value: value["verification"].__setitem__("verified", False),
            "tag identity or verification differs",
        ),
    ],
)
def test_preflight_rejects_identity_command_and_tag_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
    mutate: object,
    message: str,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = Path(sources["output"]) / file_name
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    if file_name == TOOL_ATTESTATION_NAME:
        statement = value["verificationResult"]["statement"]
        value["attestation"]["bundle"]["dsseEnvelope"]["payload"] = base64.b64encode(
            json.dumps(statement, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
    _write_json(path, value)
    with pytest.raises(InnoSignatureEvidenceError, match=message):
        verify_inno_signature_prerequisites(sources["installer"], **_arguments(sources))


def test_preflight_rejects_key_content_and_api_output_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    key_observation = Path(sources["output"]) / KEY_CONTENT_NAME
    value = json.loads(key_observation.read_text(encoding="utf-8"))
    value["content"] = base64.b64encode(b"different key").decode("ascii")
    _write_json(key_observation, value)
    with pytest.raises(InnoSignatureEvidenceError, match="public-key content identity differs"):
        verify_inno_signature_prerequisites(sources["installer"], **_arguments(sources))

    sources = _sources(tmp_path / "api", monkeypatch)
    api_path = Path(sources["output"]) / API_VERIFIER_NAME
    api = json.loads(api_path.read_text(encoding="utf-8"))
    api["commands"][0]["output_sha256"] = "0" * 64
    _write_json(api_path, api)
    with pytest.raises(InnoSignatureEvidenceError, match="API verifier observation differs"):
        verify_inno_signature_prerequisites(sources["installer"], **_arguments(sources))


def test_evidence_rejects_execution_drift_external_hash_and_changed_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    _add_execution(sources)
    execution_path = Path(sources["output"]) / EXECUTION_NAME
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["output_lines"] = ["forged: OK"]
    _write_json(execution_path, execution)
    with pytest.raises(InnoSignatureEvidenceError, match="verification observation differs"):
        create_inno_signature_evidence(sources["installer"], **_arguments(sources))

    sources = _sources(tmp_path / "complete", monkeypatch)
    _add_execution(sources)
    path = create_inno_signature_evidence(sources["installer"], **_arguments(sources))
    digest = _sha256(path.read_bytes())
    with pytest.raises(InnoSignatureEvidenceError, match="externally expected"):
        verify_inno_signature_evidence(path, expected_evidence_sha256="0" * 64)
    Path(sources["signature"]).write_bytes(b"changed")
    with pytest.raises(InnoSignatureEvidenceError, match="signature size or SHA-256 differs"):
        verify_inno_signature_evidence(path, expected_evidence_sha256=digest)


def test_wrapper_preflights_before_scoped_tool_and_never_executes_installer() -> None:
    wrapper = (ROOT / "tools" / evidence_module.WRAPPER_NAME).read_text(encoding="utf-8")

    preflight = wrapper.index("tools\\inno_signature_evidence.py preflight")
    execution = wrapper.index("& $resolvedTool.FullName @executionArguments")
    create = wrapper.index("tools\\inno_signature_evidence.py create")
    assert preflight < execution < create
    assert "Get-AuthenticodeSignature -LiteralPath $resolvedTool.FullName" in wrapper
    assert '"is-6_7_3"' in wrapper
    assert '"is-7_0_2"' in wrapper
    assert "CreateNew" in wrapper
    assert "git -C $repository status --porcelain=v1 --untracked-files=all" in wrapper
    assert "& $resolvedInstaller" not in wrapper
    assert "Start-Process" not in wrapper
    assert "Inno Setup installer execution authorized: false" in wrapper


def test_machine_contract_records_exact_trust_chain_and_nonclaims() -> None:
    contract = json.loads(
        (
            ROOT / "distribution" / "windows" / "inno-signature-evidence-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )
    assert contract["signature_tool"]["release_tag"] == "is-6_7_3"
    assert contract["signature_tool"]["release_asset_id"] == 430_321_504
    assert contract["signature"]["release_tag"] == "is-7_0_2"
    assert contract["signature"]["release_asset_id"] == 475_225_360
    assert contract["public_key"]["release_commit_sha1"] == (
        "c25dc6479cdc3be28e682a025fcf60765bba3de0"
    )
    assert contract["execution"]["preflight_before_signature_tool_execution"] is True
    assert contract["execution"]["installer_execution"] is False
    assert contract["execution"]["execution_authorized"] is False


def test_tool_cli_preflight_create_and_offline_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = importlib.util.spec_from_file_location(
        "inno_signature_evidence_tool",
        ROOT / "tools" / "inno_signature_evidence.py",
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    sources = _sources(tmp_path, monkeypatch)
    common = [
        str(sources["installer"]),
        "--signature",
        str(sources["signature"]),
        "--public-key",
        str(sources["key"]),
        "--signature-tool",
        str(sources["tool"]),
        "--project-file",
        str(Path(sources["project"]) / "pyproject.toml"),
        "--output-directory",
        str(sources["output"]),
        "--source-commit",
        SOURCE_COMMIT,
    ]
    assert tool.main(["preflight", *common]) == 0
    _add_execution(sources)
    assert tool.main(["create", *common]) == 0
    path = Path(sources["output"]) / EVIDENCE_NAME
    digest = _sha256(path.read_bytes())
    assert tool.main(["verify", str(path), "--expect-evidence-sha256", digest]) == 0
    output = capsys.readouterr().out
    assert '"installer_execution_authorized": false' in output
    assert "Created Inno signature evidence" in output
