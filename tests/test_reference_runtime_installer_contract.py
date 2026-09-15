from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = (
    ROOT
    / "distribution"
    / "windows"
    / "reference-runtime-payload-contract-v0.1.json"
)
INSTALLER = ROOT / "distribution" / "windows" / "DiffeoForge.iss"
INSTALLER_HELPER = (
    ROOT / "distribution" / "windows" / "install-reference-runtime.ps1"
)


def test_reference_runtime_payload_contract_retains_identity_and_license_boundary() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["launcher"] == {
        "type": "wsl",
        "distribution": "DiffeoForge-Reference-4.3",
        "executable": "/opt/diffeoforge/reference/bin/deformetrica",
    }
    assert contract["engine"]["version"] == "4.3.0"
    assert contract["engine"]["commercial_use_permitted"] is False
    assert contract["archive"]["network_download_during_install"] is False
    assert contract["archive"]["overwrite_existing_distribution"] is False
    assert contract["public_distribution_authorized"] is False
    assert contract["release_authorized"] is False


def test_inno_installer_requires_hash_and_license_for_optional_runtime_payload() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "#ifdef ReferenceRuntimeArchive" in script
    assert "#error ReferenceRuntimeSha256 is required" in script
    assert "#error ReferenceRuntimeLicenseFile is required" in script
    assert "DEFORMETRICA-LICENSE.txt" in script
    assert "install-reference-runtime.ps1" in script
    assert "-ExpectedSha256" in script
    assert "runhidden waituntilterminated" in script


def test_runtime_installer_helper_never_overwrites_an_existing_distribution() -> None:
    script = INSTALLER_HELPER.read_text(encoding="utf-8")

    assert '$Distribution -cne "DiffeoForge-Reference-4.3"' in script
    assert "Get-FileHash" in script
    assert "--import $Distribution" in script
    assert "The existing managed runtime is damaged" in script
    assert "it was not overwritten" in script
    assert "--unregister $Distribution" in script
