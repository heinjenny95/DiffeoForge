from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop import sbom as sbom_module
from diffeoforge.desktop.dependency_metadata_evidence import (
    EVIDENCE_NAME as DEPENDENCY_EVIDENCE_NAME,
)
from diffeoforge.desktop.dependency_metadata_evidence import (
    SIDECAR_NAME as DEPENDENCY_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME as FREEZE_EVIDENCE_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    SIDECAR_NAME as FREEZE_SIDECAR_NAME,
)
from diffeoforge.desktop.freeze_evidence import (
    DesktopFreezeEvidenceError,
    create_desktop_freeze_evidence,
)
from diffeoforge.desktop.sbom import (
    BUILDER_VERSION,
    SBOM_NAME,
    SIDECAR_NAME,
    DesktopSbomError,
    create_desktop_cyclonedx_sbom,
    verify_desktop_cyclonedx_sbom,
)

FIXED_TIME = "2026-07-18T08:00:00+00:00"
SOURCE_COMMIT = "b" * 40
VERSIONS = {
    "diffeoforge": "0.0.0.dev0",
    "numpy": "2.5.1",
    "psutil": "7.2.2",
    "pyinstaller": "6.21.0",
    "pyside6-essentials": "6.11.1",
    "shiboken6": "6.11.1",
    "torch": "2.13.0+cpu",
}


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "DiffeoForge"
    internal = root / "_internal" / "diffeoforge" / "schema"
    internal.mkdir(parents=True)
    for name in (
        "DiffeoForge.exe",
        "DiffeoForgeWorker.exe",
        "DiffeoForgeReferenceWorker.exe",
        "DiffeoForgeReferencePreparationWorker.exe",
    ):
        (root / name).write_bytes(name.encode("ascii"))
    (internal / "schema.json").write_text('{"schema": true}\n', encoding="utf-8")
    create_desktop_freeze_evidence(
        root,
        source_commit=SOURCE_COMMIT,
        created_at=FIXED_TIME,
        package_versions=VERSIONS,
        python_version="3.12.10",
        platform_description="Windows-2025Server-test",
    )
    return root, _sha256((root / FREEZE_EVIDENCE_NAME).read_bytes())


def _package(name: str, version: str) -> dict:
    metadata_sha256 = _sha256(f"metadata:{name}:{version}".encode())
    license_sha256 = _sha256(f"license:{name}".encode())
    license_field = "Legacy license text requiring review" if name == "torch" else None
    observations = ["license_classifiers_present"]
    if license_field is not None:
        observations.extend(
            ["legacy_license_field_present", "license_and_expression_both_present"]
        )
    return {
        "name": name,
        "version": version,
        "metadata": {
            "metadata_version": "2.4",
            "name": name,
            "version": version,
            "bytes": 100 + len(name),
            "sha256": metadata_sha256,
            "license_expression": "MIT",
            "license_field": license_field,
            "license_classifiers": ["License :: OSI Approved :: MIT License"],
            "license_files_declared": ["LICENSE"],
            "requires_dist": ["example>=1"],
        },
        "license_files": [
            {
                "path": f"{name}-{version}.dist-info/licenses/LICENSE",
                "bytes": 50 + len(name),
                "sha256": license_sha256,
                "source": "declared",
            }
        ],
        "unresolved_declared_license_files": [],
        "observations": sorted(observations),
        "review_status": "unreviewed",
    }


def _package_set_sha256(packages: list[dict]) -> str:
    payload = json.dumps(
        packages,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(payload)


def _write_dependency_evidence(
    directory: Path,
    *,
    bundle: Path,
    freeze_sha256: str,
) -> tuple[Path, str]:
    directory.mkdir()
    freeze = json.loads((bundle / FREEZE_EVIDENCE_NAME).read_text(encoding="utf-8"))
    packages = [_package(name, version) for name, version in sorted(VERSIONS.items())]
    evidence = {
        "schema_version": "0.1",
        "status": (
            "distribution_metadata_inventory_not_license_or_redistribution_approval"
        ),
        "target": "windows-x86_64-cpu",
        "source": {
            "freeze_evidence_schema_version": "0.3",
            "freeze_evidence_sha256": freeze_sha256,
            "source_commit_sha": SOURCE_COMMIT,
            "bundle_inventory_sha256": freeze["bundle"]["inventory_sha256"],
        },
        "generator": {"diffeoforge": VERSIONS["diffeoforge"], "python": "3.12.10"},
        "package_count": len(packages),
        "package_set_sha256": _package_set_sha256(packages),
        "packages": packages,
        "review_boundary": {
            "license_compatibility": "not_reviewed",
            "redistribution": "not_reviewed",
            "sbom": "not_an_sbom",
        },
        "missing_release_gates": [
            "license_compatibility_review",
            "license_inventory",
            "redistribution_approval",
            "sbom",
        ],
        "scientific_boundary": "Synthetic installed-metadata evidence; no release claim.",
    }
    return _rewrite_dependency_evidence(directory, evidence)


def _rewrite_dependency_evidence(
    directory: Path,
    evidence: dict,
) -> tuple[Path, str]:
    payload = _json_bytes(evidence)
    digest = _sha256(payload)
    path = directory / DEPENDENCY_EVIDENCE_NAME
    path.write_bytes(payload)
    (directory / DEPENDENCY_SIDECAR_NAME).write_bytes(
        f"{digest}  {DEPENDENCY_EVIDENCE_NAME}\n".encode("ascii")
    )
    return path, digest


def _sources(tmp_path: Path) -> tuple[Path, str, Path, str]:
    bundle, freeze_sha256 = _bundle(tmp_path / "bundle")
    dependency_path, dependency_sha256 = _write_dependency_evidence(
        tmp_path / "dependency",
        bundle=bundle,
        freeze_sha256=freeze_sha256,
    )
    return bundle, freeze_sha256, dependency_path, dependency_sha256


def _create(
    bundle: Path,
    freeze_sha256: str,
    dependency_path: Path,
    dependency_sha256: str,
    output: Path,
) -> Path:
    output.mkdir()
    return create_desktop_cyclonedx_sbom(
        bundle,
        dependency_path,
        expected_freeze_evidence_sha256=freeze_sha256,
        expected_dependency_evidence_sha256=dependency_sha256,
        output_directory=output,
    )


def test_sbom_is_deterministic_schema_valid_bound_and_non_overwriting(
    tmp_path: Path,
) -> None:
    bundle, freeze_sha256, dependency_path, dependency_sha256 = _sources(tmp_path)
    first = _create(
        bundle,
        freeze_sha256,
        dependency_path,
        dependency_sha256,
        tmp_path / "first Käfer",
    )
    second = _create(
        bundle,
        freeze_sha256,
        dependency_path,
        dependency_sha256,
        tmp_path / "second",
    )

    assert first.read_bytes() == second.read_bytes()
    sbom_sha256 = _sha256(first.read_bytes())
    document = verify_desktop_cyclonedx_sbom(
        first,
        freeze_evidence_path=bundle / FREEZE_EVIDENCE_NAME,
        dependency_evidence_path=dependency_path,
        expected_freeze_evidence_sha256=freeze_sha256,
        expected_dependency_evidence_sha256=dependency_sha256,
        expected_sbom_sha256=sbom_sha256,
    )

    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.7"
    assert document["version"] == 1
    assert document["metadata"]["timestamp"] == FIXED_TIME
    assert document["metadata"]["lifecycles"] == [{"phase": "post-build"}]
    assert document["metadata"]["tools"]["components"][0]["version"] == BUILDER_VERSION
    assert document["serialNumber"] == (
        f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, dependency_sha256)}"
    )
    assert [component["purl"] for component in document["components"]] == sorted(
        component["purl"] for component in document["components"]
    )
    assert all(component["scope"] == "required" for component in document["components"])
    assert all("hashes" not in component for component in document["components"])
    assert all(
        component["licenses"] == [{"expression": "MIT"}]
        for component in document["components"]
    )
    assert "dependencies" not in document
    assert document["compositions"][0]["aggregate"] == "incomplete"
    torch = next(component for component in document["components"] if component["name"] == "torch")
    torch_properties = torch["properties"]
    assert any(
        prop["name"] == "diffeoforge:evidence:legacy-license-field"
        for prop in torch_properties
    )
    assert any(
        prop["name"] == "diffeoforge:evidence:license-file-record"
        and "sha256" in prop["value"]
        for prop in torch_properties
    )
    assert (first.parent / SIDECAR_NAME).read_bytes() == (
        f"{sbom_sha256}  {SBOM_NAME}\n".encode("ascii")
    )

    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=first.parent,
        )


def test_sbom_rejects_wrong_hashes_source_bindings_and_inside_bundle(
    tmp_path: Path,
) -> None:
    bundle, freeze_sha256, dependency_path, dependency_sha256 = _sources(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(DesktopSbomError, match="Dependency evidence differs"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256="0" * 64,
            output_directory=output,
        )
    with pytest.raises(ConfigurationError, match="outside the frozen bundle"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=bundle,
        )

    evidence = json.loads(dependency_path.read_text(encoding="utf-8"))
    evidence["source"]["source_commit_sha"] = "c" * 40
    dependency_path, changed_sha256 = _rewrite_dependency_evidence(
        dependency_path.parent,
        evidence,
    )
    with pytest.raises(DesktopSbomError, match="source commit binding"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=changed_sha256,
            output_directory=output,
        )


def test_sbom_rejects_invalid_license_expression_and_builder_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, freeze_sha256, dependency_path, _ = _sources(tmp_path)
    evidence = json.loads(dependency_path.read_text(encoding="utf-8"))
    evidence["packages"][0]["metadata"]["license_expression"] = "MIT AND ("
    evidence["package_set_sha256"] = _package_set_sha256(evidence["packages"])
    dependency_path, dependency_sha256 = _rewrite_dependency_evidence(
        dependency_path.parent,
        evidence,
    )
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(DesktopSbomError, match="invalid SPDX License-Expression"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=output,
        )

    original_version = sbom_module.importlib.metadata.version
    monkeypatch.setattr(
        sbom_module.importlib.metadata,
        "version",
        lambda name: "0.0" if name == "cyclonedx-python-lib" else original_version(name),
    )
    with pytest.raises(DesktopSbomError, match="builder version differs"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=output,
        )


def test_sbom_verifier_rejects_rehashed_tampering_and_bad_freeze_aggregate(
    tmp_path: Path,
) -> None:
    bundle, freeze_sha256, dependency_path, dependency_sha256 = _sources(tmp_path)
    sbom_path = _create(
        bundle,
        freeze_sha256,
        dependency_path,
        dependency_sha256,
        tmp_path / "output",
    )
    document = json.loads(sbom_path.read_text(encoding="utf-8"))
    document["metadata"]["component"]["version"] = "tampered"
    payload = _json_bytes(document)
    sbom_path.write_bytes(payload)
    (sbom_path.parent / SIDECAR_NAME).write_bytes(
        f"{_sha256(payload)}  {SBOM_NAME}\n".encode("ascii")
    )
    with pytest.raises(DesktopSbomError, match="deterministic source-evidence mapping"):
        verify_desktop_cyclonedx_sbom(
            sbom_path,
            freeze_evidence_path=bundle / FREEZE_EVIDENCE_NAME,
            dependency_evidence_path=dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
        )

    freeze_path = bundle / FREEZE_EVIDENCE_NAME
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["bundle"]["total_bytes"] += 1
    freeze_payload = _json_bytes(freeze)
    changed_freeze_sha256 = _sha256(freeze_payload)
    freeze_path.write_bytes(freeze_payload)
    (bundle / FREEZE_SIDECAR_NAME).write_bytes(
        f"{changed_freeze_sha256}  {FREEZE_EVIDENCE_NAME}\n".encode("ascii")
    )
    with pytest.raises(DesktopFreezeEvidenceError, match="total byte count differs"):
        verify_desktop_cyclonedx_sbom(
            sbom_path,
            freeze_evidence_path=freeze_path,
            dependency_evidence_path=dependency_path,
            expected_freeze_evidence_sha256=changed_freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
        )


def test_sbom_rejects_symbolic_bundle_and_output_paths(tmp_path: Path) -> None:
    bundle, freeze_sha256, dependency_path, dependency_sha256 = _sources(tmp_path)
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    bundle_link = tmp_path / "bundle-link"
    output_link = tmp_path / "output-link"
    try:
        bundle_link.symlink_to(bundle, target_is_directory=True)
        output_link.symlink_to(real_output, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic-link creation is unavailable on this runner: {error}")

    with pytest.raises(DesktopSbomError, match="bundle root must not be symbolic"):
        create_desktop_cyclonedx_sbom(
            bundle_link,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=real_output,
        )
    with pytest.raises(ConfigurationError, match="existing real directory"):
        create_desktop_cyclonedx_sbom(
            bundle,
            dependency_path,
            expected_freeze_evidence_sha256=freeze_sha256,
            expected_dependency_evidence_sha256=dependency_sha256,
            output_directory=output_link,
        )


def test_standalone_cli_verifies_downloaded_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, freeze_sha256, dependency_path, dependency_sha256 = _sources(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "_diffeoforge_desktop_sbom_tool",
        Path(__file__).resolve().parents[1] / "tools" / "desktop_sbom.py",
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)

    output_directory = tmp_path / "output"
    output_directory.mkdir()
    create_result = tool.main(
        [
            "create",
            str(bundle),
            str(dependency_path),
            "--expect-freeze-evidence-sha256",
            freeze_sha256,
            "--expect-dependency-evidence-sha256",
            dependency_sha256,
            "--output-directory",
            str(output_directory),
        ]
    )
    sbom_path = output_directory / SBOM_NAME
    verify_result = tool.main(
        [
            "verify",
            str(sbom_path),
            str(bundle / FREEZE_EVIDENCE_NAME),
            str(dependency_path),
            "--expect-freeze-evidence-sha256",
            freeze_sha256,
            "--expect-dependency-evidence-sha256",
            dependency_sha256,
            "--expect-sbom-sha256",
            _sha256(sbom_path.read_bytes()),
        ]
    )
    output = capsys.readouterr()

    assert create_result == 0
    assert verify_result == 0
    assert "Created deterministic CycloneDX 1.7 SBOM:" in output.out
    assert '"bom_format": "CycloneDX"' in output.out
    assert '"composition": "incomplete"' in output.out
    assert output.err == ""
