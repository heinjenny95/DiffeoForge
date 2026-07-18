from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = ROOT / "distribution" / "windows" / "sbom-contract-v0.1.json"
ADR = ROOT / "docs" / "decisions" / "0005-cyclonedx-post-build-sbom.md"


def test_sbom_contract_is_deterministic_current_and_nonapproving() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "0.1"
    assert contract["status"] == "accepted_design_not_an_sbom_or_release_artifact"
    assert contract["standard"] == {
        "name": "CycloneDX",
        "spec_version": "1.7",
        "format": "JSON",
        "media_type": "application/vnd.cyclonedx+json; version=1.7",
    }
    assert contract["builder_tool"] == {
        "distribution": "cyclonedx-python-lib",
        "version": "11.11.0",
        "scope": "builder_only_not_bundled_runtime",
        "schema_validator": "official_library_schema_v1_7",
    }
    assert contract["determinism"] == {
        "serial_number": "uuid5_url_namespace_from_dependency_evidence_sha256",
        "timestamp": "exact_freeze_evidence_created_at",
        "bom_version": 1,
        "component_order": "purl_ascending",
        "json_serialization": "utf8_sorted_keys_indent_2_single_trailing_lf",
        "output_overwrite": False,
    }
    assert contract["component_mapping"]["component_hashes"] == {
        "policy": "omit_until_distribution_archive_or_component_payload_hash_exists",
        "metadata_sha256_is_not_a_component_hash": True,
    }
    assert contract["license_mapping"]["compatibility_or_redistribution_conclusion"] is False
    assert contract["dependency_graph"] == {
        "v0_1_policy": "omit_unproven_edges",
        "composition_aggregate": "incomplete",
        "reason": (
            "requires_dist_contains_markers_extras_and_nonruntime_requirements_"
            "not_resolved_by_current_evidence"
        ),
    }
    assert contract["output"]["future_clean_runner_upload_file_count"] == 6
    assert {
        "license_compatibility_review",
        "license_inventory_human_review",
        "redistribution_approval",
    } <= set(contract["missing_release_gates_after_valid_sbom"])


def test_sbom_adr_preserves_evidence_and_release_boundaries() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert (
        "Status: Accepted; generator implemented and clean-runner observation complete"
        in text
    )
    assert "29638832620" in text
    assert "cyclonedx-python-lib==11.11.0" in text
    assert "CycloneDX composition will therefore be `incomplete`" in text
    assert "they are not\nCycloneDX component hashes" in text
    assert "They do not imply\ncompatibility or redistribution approval" in text
    assert "No SBOM file is uploaded merely because this ADR exists" in text.replace(
        "\n", " "
    )


def test_sbom_implementation_and_builder_pin_match_contract() -> None:
    module = ROOT / "src" / "diffeoforge" / "desktop" / "sbom.py"
    tool = ROOT / "tools" / "desktop_sbom.py"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert module.is_file()
    assert tool.is_file()
    assert 'BUILDER_VERSION = "11.11.0"' in module.read_text(encoding="utf-8")
    assert '"cyclonedx-python-lib==11.11.0"' in pyproject
    assert "future_clean_runner_upload_file_count" in CONTRACT.read_text(
        encoding="utf-8"
    )
