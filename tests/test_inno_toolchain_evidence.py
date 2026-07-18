from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop import inno_toolchain_evidence as evidence_module
from diffeoforge.desktop.inno_toolchain_evidence import (
    ATTESTATION_NAME,
    AUTHENTICODE_NAME,
    EVIDENCE_NAME,
    SIDECAR_NAME,
    VERIFIER_NAME,
    InnoToolchainEvidenceError,
    create_inno_toolchain_evidence,
    verify_inno_toolchain_evidence,
)

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "d" * 40
OBSERVED_AT = "2026-07-18T12:00:00Z"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_bytes(_json_bytes(value))


def _project(tmp_path: Path, *, asset_bytes: int, asset_sha256: str) -> Path:
    project = tmp_path / "source Käfer"
    windows = project / "distribution" / "windows"
    tools = project / "tools"
    windows.mkdir(parents=True)
    tools.mkdir()
    contract = json.loads(
        (
            ROOT / "distribution" / "windows" / "inno-toolchain-evidence-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )
    contract["asset"]["bytes"] = asset_bytes
    contract["asset"]["sha256"] = asset_sha256
    _write_json(windows / "inno-toolchain-evidence-contract-v0.1.json", contract)
    shutil.copyfile(
        ROOT / "tools" / "observe_inno_toolchain.ps1",
        tools / "observe_inno_toolchain.ps1",
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "diffeoforge"\nversion = "0.0.0.dev0"\n',
        encoding="utf-8",
    )
    return project


def _statement(*, asset_sha256: str) -> dict:
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "uri": evidence_module.RELEASE_PURL,
                "digest": {"sha1": evidence_module.RELEASE_TAG_OBJECT_SHA1},
            },
            {
                "name": evidence_module.ASSET_NAME,
                "digest": {"sha256": asset_sha256},
            },
        ],
        "predicateType": evidence_module.PREDICATE_TYPE,
        "predicate": {
            "databaseId": str(evidence_module.RELEASE_DATABASE_ID),
            "ownerId": "1092483",
            "packageId": str(evidence_module.REPOSITORY_ID),
            "purl": evidence_module.RELEASE_PURL,
            "repository": evidence_module.REPOSITORY,
            "repositoryId": str(evidence_module.REPOSITORY_ID),
            "tag": evidence_module.RELEASE_TAG,
        },
    }


def _attestation(*, asset_sha256: str) -> dict:
    statement = _statement(asset_sha256=asset_sha256)
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
            "mediaType": "application/vnd.dev.sigstore.verificationresult+json;version=0.1",
            "signature": {
                "certificate": {
                    "certificateIssuer": "synthetic",
                    "subjectAlternativeName": evidence_module.ATTESTER_SAN,
                }
            },
            "verifiedTimestamps": [
                {
                    "type": "TimestampAuthority",
                    "uri": evidence_module.TIMESTAMP_AUTHORITY,
                    "timestamp": "2026-07-13T07:43:34Z",
                }
            ],
            "verifiedIdentity": {},
            "statement": statement,
        },
    }


def _authenticode(asset: Path, *, asset_sha256: str) -> dict:
    return {
        "schema_version": "0.1",
        "observed_at": OBSERVED_AT,
        "asset_path": str(asset.resolve()),
        "asset_sha256": asset_sha256,
        "status": "Valid",
        "status_message": "Signature verified.",
        "signer_subject": evidence_module.SIGNER_SUBJECT,
        "signer_issuer": "CN=Sectigo Public Code Signing CA R36",
        "signer_thumbprint": "A" * 40,
        "signer_not_before": "2025-03-10T00:00:00Z",
        "signer_not_after": "2028-03-09T23:59:59Z",
        "timestamp_subject": "CN=Sectigo Public Time Stamping Signer R37",
        "timestamp_thumbprint": "B" * 40,
    }


def _verifier(program: Path, asset: Path) -> dict:
    return {
        "schema_version": "0.1",
        "observed_at": OBSERVED_AT,
        "program_path": str(program.resolve()),
        "program_bytes": program.stat().st_size,
        "program_sha256": _sha256(program.read_bytes()),
        "version_output": "gh version 2.96.0 (2026-07-02)\nhttps://example.invalid",
        "command": [
            "release",
            "verify-asset",
            str(asset.resolve()),
            "--repo",
            evidence_module.REPOSITORY,
            "--format",
            "json",
        ],
        "exit_code": 0,
    }


def _sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    asset_payload = b"synthetic Inno Setup asset for offline unit tests\n"
    asset_sha256 = _sha256(asset_payload)
    monkeypatch.setattr(evidence_module, "ASSET_BYTES", len(asset_payload))
    monkeypatch.setattr(evidence_module, "ASSET_SHA256", asset_sha256)
    project = _project(
        tmp_path,
        asset_bytes=len(asset_payload),
        asset_sha256=asset_sha256,
    )
    asset_directory = tmp_path / "asset input"
    asset_directory.mkdir()
    asset = asset_directory / evidence_module.ASSET_NAME
    asset.write_bytes(asset_payload)
    program_directory = tmp_path / "verifier input"
    program_directory.mkdir()
    program = program_directory / "gh.exe"
    program.write_bytes(b"synthetic GitHub CLI verifier\n")
    output = tmp_path / "observation Käfer"
    output.mkdir()
    _write_json(output / ATTESTATION_NAME, _attestation(asset_sha256=asset_sha256))
    _write_json(
        output / AUTHENTICODE_NAME,
        _authenticode(asset, asset_sha256=asset_sha256),
    )
    _write_json(output / VERIFIER_NAME, _verifier(program, asset))
    return {
        "project": project,
        "asset": asset,
        "asset_sha256": asset_sha256,
        "program": program,
        "output": output,
    }


def _create(sources: dict[str, object]) -> Path:
    return create_inno_toolchain_evidence(
        sources["asset"],
        project_file=Path(sources["project"]) / "pyproject.toml",
        output_directory=sources["output"],
        source_commit=SOURCE_COMMIT,
    )


def test_evidence_is_canonical_deterministic_bound_and_nonexecuting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = _create(sources)
    payload = path.read_bytes()
    digest = _sha256(payload)
    evidence = verify_inno_toolchain_evidence(
        path,
        expected_evidence_sha256=digest,
    )

    assert evidence["source"]["commit_sha"] == SOURCE_COMMIT
    assert evidence["asset"]["sha256"] == sources["asset_sha256"]
    assert evidence["release_attestation"]["release_tag"] == "is-7_0_2"
    assert evidence["release_attestation"]["release_tag_object_sha1"] == (
        "d2509df69f828a7148294e29b2ca252c3250210c"
    )
    assert evidence["authenticode"]["status"] == "Valid"
    assert evidence["authenticode"]["signer_subject"] == (
        "CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL"
    )
    assert evidence["verifier"]["version"] == "2.96.0"
    assert evidence["verifier"]["command"][1] == "verify-asset"
    assert evidence["execution_authorized"] is False
    assert (Path(sources["output"]) / SIDECAR_NAME).read_bytes() == (
        f"{digest}  {EVIDENCE_NAME}\n".encode("ascii")
    )

    path.unlink()
    (Path(sources["output"]) / SIDECAR_NAME).unlink()
    recreated = _create(sources)
    assert recreated.read_bytes() == payload

    with pytest.raises(InnoToolchainEvidenceError, match="exact file boundary"):
        _create(sources)


def test_evidence_rejects_wrong_external_hash_and_changed_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = _create(sources)
    digest = _sha256(path.read_bytes())
    with pytest.raises(InnoToolchainEvidenceError, match="externally expected"):
        verify_inno_toolchain_evidence(
            path,
            expected_evidence_sha256="0" * 64,
        )
    Path(sources["asset"]).write_bytes(b"changed")
    with pytest.raises(InnoToolchainEvidenceError, match="size or SHA-256"):
        verify_inno_toolchain_evidence(
            path,
            expected_evidence_sha256=digest,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("asset_digest", "asset digest differs"),
        ("tag_digest", "tag identity differs"),
        ("predicate", "predicate differs"),
        ("certificate", "identity differs"),
        ("payload", "DSSE payload differs"),
    ],
)
def test_evidence_rejects_wrong_release_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = Path(sources["output"]) / ATTESTATION_NAME
    value = json.loads(path.read_text(encoding="utf-8"))
    statement = value["verificationResult"]["statement"]
    if mutation == "asset_digest":
        statement["subject"][1]["digest"]["sha256"] = "0" * 64
    elif mutation == "tag_digest":
        statement["subject"][0]["digest"]["sha1"] = "0" * 40
    elif mutation == "predicate":
        statement["predicate"]["repository"] = "other/repository"
    elif mutation == "certificate":
        value["verificationResult"]["signature"]["certificate"]["subjectAlternativeName"] = (
            "https://example.invalid"
        )
    else:
        decoded = _statement(asset_sha256=sources["asset_sha256"])
        decoded["predicate"]["tag"] = "different"
        value["attestation"]["bundle"]["dsseEnvelope"]["payload"] = base64.b64encode(
            json.dumps(decoded).encode("utf-8")
        ).decode("ascii")
    if mutation != "payload":
        value["attestation"]["bundle"]["dsseEnvelope"]["payload"] = base64.b64encode(
            json.dumps(statement, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
    _write_json(path, value)
    with pytest.raises(InnoToolchainEvidenceError, match=message):
        _create(sources)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "NotSigned", "identity differs"),
        ("signer_subject", "CN=Wrong Publisher", "identity differs"),
        ("signer_thumbprint", "bad", "thumbprint"),
        ("signer_not_after", "2026-01-01T00:00:00Z", "outside signer"),
    ],
)
def test_evidence_rejects_wrong_authenticode_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    message: str,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = Path(sources["output"]) / AUTHENTICODE_NAME
    observation = json.loads(path.read_text(encoding="utf-8"))
    observation[field] = value
    _write_json(path, observation)
    with pytest.raises(InnoToolchainEvidenceError, match=message):
        _create(sources)


def test_evidence_rejects_wrong_verifier_binding_and_extra_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    verifier_path = Path(sources["output"]) / VERIFIER_NAME
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["command"][1] = "attestation"
    _write_json(verifier_path, verifier)
    with pytest.raises(InnoToolchainEvidenceError, match="verifier observation differs"):
        _create(sources)

    sources = _sources(tmp_path / "extra", monkeypatch)
    Path(sources["output"]).joinpath("unexpected.txt").write_text(
        "unexpected",
        encoding="utf-8",
    )
    with pytest.raises(InnoToolchainEvidenceError, match="exact file boundary"):
        _create(sources)


def test_evidence_rejects_changed_verifier_program(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path, monkeypatch)
    path = _create(sources)
    digest = _sha256(path.read_bytes())
    Path(sources["program"]).write_bytes(b"changed verifier")
    with pytest.raises(InnoToolchainEvidenceError, match="verifier file binding"):
        verify_inno_toolchain_evidence(
            path,
            expected_evidence_sha256=digest,
        )


def test_observation_wrapper_never_executes_downloaded_asset() -> None:
    wrapper = (ROOT / "tools" / "observe_inno_toolchain.ps1").read_text(encoding="utf-8")

    assert '"release",' in wrapper
    assert '"verify-asset",' in wrapper
    assert '"jrsoftware/issrc",' in wrapper
    assert "Get-AuthenticodeSignature" in wrapper
    assert "Get-FileHash" in wrapper
    assert "CreateNew" in wrapper
    assert "git -C $repository rev-parse HEAD" in wrapper
    assert "git -C $repository status --porcelain=v1 --untracked-files=all" in wrapper
    assert "Start-Process" not in wrapper
    assert "ISCC.exe" not in wrapper
    assert "gh attestation verify" not in wrapper
    assert "& $resolvedAsset" not in wrapper
    assert "Downloaded asset execution authorized: false" in wrapper


def test_machine_contract_records_release_specific_verifier_and_nonclaims() -> None:
    contract = json.loads(
        (
            ROOT / "distribution" / "windows" / "inno-toolchain-evidence-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["asset"]["release_tag_object_sha1"] == (
        "d2509df69f828a7148294e29b2ca252c3250210c"
    )
    assert contract["asset"]["release_asset_id"] == 475_225_237
    assert contract["release_attestation"]["command"][1] == "verify-asset"
    assert contract["release_attestation"]["generic_gh_attestation_verify_is_not_equivalent"]
    assert contract["observation"]["downloaded_asset_execution"] is False
    assert contract["observation"]["compiler_execution"] is False
    assert contract["observation"]["execution_authorized"] is False


def test_tool_cli_create_and_offline_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = importlib.util.spec_from_file_location(
        "inno_toolchain_evidence_tool",
        ROOT / "tools" / "inno_toolchain_evidence.py",
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    sources = _sources(tmp_path, monkeypatch)

    assert (
        tool.main(
            [
                "create",
                str(sources["asset"]),
                "--project-file",
                str(Path(sources["project"]) / "pyproject.toml"),
                "--output-directory",
                str(sources["output"]),
                "--source-commit",
                SOURCE_COMMIT,
            ]
        )
        == 0
    )
    evidence_path = Path(sources["output"]) / EVIDENCE_NAME
    digest = _sha256(evidence_path.read_bytes())
    assert (
        tool.main(
            [
                "verify",
                str(evidence_path),
                "--expect-evidence-sha256",
                digest,
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Created non-executing Inno toolchain evidence" in output
    assert '"execution_authorized": false' in output
