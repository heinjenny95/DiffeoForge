from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_private_alpha_contract_is_same_owner_nonrelease_and_exact() -> None:
    contract = json.loads(
        (
            ROOT
            / "distribution"
            / "windows"
            / "private-alpha-handoff-contract-v0.1.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["schema_version"] == "0.1"
    assert contract["target"] == "windows-x86_64-cpu"
    assert contract["scope"] == {
        "same_owner": True,
        "same_machine": True,
        "output_under_current_user_profile": True,
        "output_outside_source_repository": True,
        "setup_execution": False,
        "public_upload": False,
    }
    assert contract["required_prerequisites"]["setup_authenticode_status"] == (
        "NotSigned"
    )
    assert contract["security_observation"]["malware_clearance_claim"] is False
    assert contract["output"]["exact_files"] == sorted(
        [
            "DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe",
            "LICENSE.txt",
            "PRIVATE-ALPHA-README.txt",
            "private-alpha-manifest.json",
            "private-alpha-manifest.sha256",
            "windows-security-observation.json",
        ]
    )


def test_private_alpha_wrapper_is_fail_closed_and_never_executes_setup() -> None:
    wrapper = (ROOT / "tools" / "package_private_alpha.ps1").read_text(
        encoding="utf-8"
    )

    assert 'ValidateSet("Create", "Verify")' in wrapper
    assert "installer_build_evidence.py verify" in wrapper
    assert "Get-AuthenticodeSignature" in wrapper
    assert "Start-MpScan -ScanType CustomScan" in wrapper
    assert "Get-MpThreatDetection" in wrapper
    assert "Get-CimInstance -Namespace root/SecurityCenter2" in wrapper
    assert 'if ($env:GITHUB_ACTIONS -eq "true")' in wrapper
    assert "requires a clean Git worktree" in wrapper
    assert "outside the source repository" in wrapper
    assert "already exists and will not be overwritten" in wrapper
    assert "[IO.Directory]::Move" in wrapper
    assert "setup_execution_performed = $false" in wrapper
    assert "public_upload_authorized = $false" in wrapper
    assert "release_authorized = $false" in wrapper
    assert "Start-Process" not in wrapper
    assert "& $setup" not in wrapper


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows PowerShell verifier")
def test_private_alpha_retained_verifier_accepts_exact_and_rejects_mutation(
    tmp_path: Path,
) -> None:
    setup_name = "DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe"
    root = tmp_path / "Private Alpha"
    root.mkdir()

    def write(name: str, payload: bytes) -> Path:
        path = root / name
        path.write_bytes(payload)
        return path

    def record(path: Path) -> dict[str, object]:
        return {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    setup = write(setup_name, b"setup")
    license_file = write("LICENSE.txt", b"license")
    readme = write("PRIVATE-ALPHA-README.txt", b"readme")
    setup_record = record(setup)
    security_value = {
        "schema_version": "0.1",
        "setup": {
            **setup_record,
            "authenticode_status": "NotSigned",
        },
        "microsoft_defender": {
            "scan_status": "not_performed_microsoft_defender_disabled"
        },
        "malware_clearance_claim": False,
    }
    security = write(
        "windows-security-observation.json",
        (json.dumps(security_value, indent=2) + "\n").encode(),
    )
    manifest_value = {
        "schema_version": "0.1",
        "status": (
            "same_owner_local_private_alpha_handoff_not_signed_distributable_or_released"
        ),
        "target": "windows-x86_64-cpu",
        "installer_build": {"setup_source": setup_record},
        "files": {
            "setup": setup_record,
            "readme": record(readme),
            "license": record(license_file),
            "security_observation": record(security),
        },
        "setup_authenticode_status": "NotSigned",
        "setup_execution_performed": False,
        "public_upload_authorized": False,
        "public_distribution_authorized": False,
        "release_authorized": False,
    }
    manifest = write(
        "private-alpha-manifest.json",
        (json.dumps(manifest_value, indent=2) + "\n").encode(),
    )
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    write(
        "private-alpha-manifest.sha256",
        f"{manifest_sha256}  private-alpha-manifest.json\n".encode(),
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "tools" / "package_private_alpha.ps1"),
        "-Mode",
        "Verify",
        "-OutputDirectory",
        str(root),
        "-ExpectedManifestSha256",
        manifest_sha256,
    ]

    accepted = subprocess.run(command, check=False, capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr
    assert "Verified private-alpha handoff" in accepted.stdout

    setup.write_bytes(b"changed")
    rejected = subprocess.run(command, check=False, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "Setup content record differs" in rejected.stderr
