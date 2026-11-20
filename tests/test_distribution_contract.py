from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = ROOT / "distribution" / "desktop-contract-v0.1.json"


def test_desktop_contract_freezes_safe_first_distribution_boundary() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "0.1"
    assert contract["status"] == "architecture_only_not_a_release_artifact"
    assert contract["application"] == {
        "name": "DiffeoForge Desktop",
        "ui_toolkit": "PySide6",
        "bundle_builder": "PyInstaller",
        "bundle_mode": "onedir",
        "installer_builder": "Inno Setup",
        "requires_preinstalled_python": False,
        "default_network_access": False,
    }
    variants = {variant["id"]: variant for variant in contract["variants"]}
    assert variants["windows-cpu"]["bundled"] is True
    assert variants["windows-cpu"]["release_order"] == 1
    assert variants["windows-nvidia"]["release_order"] > 1
    assert variants["deformetrica-reference"]["bundled"] is False
    assert "engine execution unauthorized" in contract["process_boundaries"][
        "reference_preparation_worker"
    ]
    assert "supervised external Deformetrica execution" in contract[
        "process_boundaries"
    ]["reference_execution_worker"]
    assert contract["data_ownership"]["uninstall_preserves_projects"] is True


def test_desktop_contract_requires_security_science_and_clean_machine_evidence() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = contract["required_release_evidence"]

    assert len(evidence) == len(set(evidence))
    assert {
        "clean_windows_vm_without_python",
        "offline_install_start_doctor_cc0_smoke_uninstall",
        "authenticode_signature_verification",
        "software_bill_of_materials",
        "third_party_license_inventory",
        "cpu_numerical_validation",
        "crash_interruption_recovery",
        "no_network_default_verification",
    } <= set(evidence)
    assert "production-ready for 300 specimens" in contract[
        "forbidden_claims_before_gates_pass"
    ]


def test_distribution_contract_is_included_in_source_distribution_configuration() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"/distribution"' in pyproject
