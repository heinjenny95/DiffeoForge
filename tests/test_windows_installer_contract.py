from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = ROOT / "distribution" / "windows" / "installer-contract-v0.1.json"
ADR = ROOT / "docs" / "decisions" / "0006-reproducible-windows-installer-contract.md"
GUIDE = ROOT / "docs" / "WINDOWS_INSTALLER_CONTRACT.md"


def test_installer_contract_pins_authentic_current_x64_toolchain() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "0.1"
    assert contract["status"] == "accepted_design_not_an_installer_or_release_artifact"
    assert contract["target"] == "windows-x86_64-cpu"
    assert contract["toolchain"] == {
        "name": "Inno Setup",
        "version": "7.0.2",
        "edition": "x64",
        "release_repository": "jrsoftware/issrc",
        "release_tag": "is-7_0_2",
        "release_database_id": 352_994_135,
        "release_tag_object_sha1": "d2509df69f828a7148294e29b2ca252c3250210c",
        "release_commit_sha1": "c25dc6479cdc3be28e682a025fcf60765bba3de0",
        "release_immutable": True,
        "asset": "innosetup-7.0.2-x64.exe",
        "asset_id": 475_225_237,
        "asset_bytes": 17_020_192,
        "asset_sha256": (
            "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1"
        ),
        "asset_url": (
            "https://github.com/jrsoftware/issrc/releases/download/"
            "is-7_0_2/innosetup-7.0.2-x64.exe"
        ),
        "authenticity_checks_before_execution": [
            "github_release_attestation",
            "exact_sha256",
            "valid_authenticode_publisher_pyrsys_b_v",
        ],
        "release_attestation_command": (
            "gh release verify-asset is-7_0_2 <asset> "
            "--repo jrsoftware/issrc --format json"
        ),
        "compiler": "ISCC.exe",
        "compiler_mode": "console_noninteractive",
        "unpinned_latest_or_package_manager_resolution": False,
    }


def test_installer_contract_preserves_input_install_and_uninstall_boundaries() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["required_inputs"]["downloaded_evidence"] == {
        "exact_regular_non_reparse_file_count": 6,
        "external_freeze_evidence_sha256": True,
        "external_dependency_evidence_sha256": True,
        "external_sbom_sha256": True,
        "deterministic_sbom_reconstruction_required": True,
    }
    assert contract["architecture"] == {
        "setup_architecture": "x64",
        "architectures_allowed": "x64compatible",
        "architectures_install_in_64_bit_mode": "x64compatible",
        "arm64_behavior": "x64_emulation_only_not_native_arm64_claim",
    }
    assert contract["operating_system"] == {
        "inno_min_version": "10.0.17763",
        "minimum_name": "Windows 10 version 1809",
        "basis": "Qt_6_11_supported_windows_platform_floor",
        "windows_11_in_scope": True,
        "minimum_install_gate_is_not_a_tested_support_claim": True,
    }
    scope = contract["installation_scope"]
    assert scope["default"] == "current_user_non_admin"
    assert scope["privileges_required"] == "lowest"
    assert scope["privileges_required_overrides_allowed"] == ["dialog", "commandline"]
    assert scope["automatic_post_install_launch"] is False
    assert scope["telemetry_update_or_download_action"] is False

    content = contract["installed_content_boundary"]
    assert content["verified_bundle_tree"] == "complete_and_unchanged"
    assert len(content["evidence_copies"]) == 6
    assert content["project_or_mesh_data_inside_application_directory"] is False
    assert content["network_fetched_payload"] is False

    uninstall = contract["uninstall_boundary"]
    assert uninstall["remove_application_files_shortcuts_and_uninstall_registration_only"]
    assert uninstall["recursive_user_project_deletion"] is False
    assert uninstall["uninstall_run_commands"] is False


def test_installer_contract_does_not_overstate_determinism_or_release_status() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    build = contract["build_and_output"]

    assert build["overwrite_existing_output"] is False
    assert build["bit_for_bit_rebuild_determinism_claim"] is False
    assert len(contract["future_installer_evidence_bindings"]) == 9
    assert {
        "installer_implementation",
        "human_license_inventory",
        "redistribution_approval",
        "authenticode_signature",
        "clean_windows_vm",
        "cpu_numerical_release_validation",
        "scientific_validation",
    } <= set(contract["missing_release_gates_after_contract_acceptance"])


def test_installer_adr_and_guide_match_machine_contract_and_nonclaims() -> None:
    adr = ADR.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")

    for text in (adr, guide):
        assert "Inno Setup 7.0.2" in text
        assert "5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1" in text
        assert "Pyrsys B.V." in text
        assert "x64compatible" in text
        assert "10.0.17763" in text
        assert "byte" in text.lower()

    assert "no installer implemented or distributed" in adr
    assert "one verified private engineering build" in guide
    assert "no installer has been executed, signed, distributed, or released" in " ".join(
        guide.split()
    )
    assert "redistribution approval" in adr
    assert "No executable will be uploaded or described as usable" in guide
