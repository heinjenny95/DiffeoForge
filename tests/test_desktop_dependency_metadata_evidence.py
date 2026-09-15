from __future__ import annotations

import hashlib
import json
from email import message_from_bytes
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop import dependency_metadata_evidence as dependency_evidence
from diffeoforge.desktop.dependency_metadata_evidence import (
    EVIDENCE_NAME,
    SIDECAR_NAME,
    DesktopDependencyMetadataEvidenceError,
    create_desktop_dependency_metadata_evidence,
    verify_desktop_dependency_metadata_evidence,
)
from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME,
    create_desktop_freeze_evidence,
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
    "torch": "2.13.0",
}


class _FakePackagePath:
    def __init__(self, relative: str, located: Path) -> None:
        self.relative = relative
        self.located = located

    def __str__(self) -> str:
        return self.relative

    def locate(self) -> Path:
        return self.located


class _FakeDistribution:
    def __init__(
        self,
        *,
        metadata_bytes: bytes,
        metadata_path: _FakePackagePath,
        license_path: _FakePackagePath | None,
        version: str,
    ) -> None:
        self.metadata = message_from_bytes(metadata_bytes)
        self.files = [metadata_path]
        if license_path is not None:
            self.files.append(license_path)
        self.version = version


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "DiffeoForge"
    internal = root / "_internal" / "diffeoforge" / "schema"
    internal.mkdir(parents=True)
    for name in (
        "DiffeoForge.exe",
        "DiffeoForgeWorker.exe",
        "DiffeoForgeReferenceWorker.exe",
        "DiffeoForgeReferencePreparationWorker.exe",
        "DiffeoForgeReferenceExecutionWorker.exe",
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
    return root


def _fake_distributions(tmp_path: Path) -> dict[str, _FakeDistribution]:
    distributions = {}
    for name, version in VERSIONS.items():
        normalized = name.replace("-", "_")
        dist_info = tmp_path / f"{normalized}-{version}.dist-info"
        license_directory = dist_info / "licenses"
        license_directory.mkdir(parents=True)
        metadata_bytes = (
            "Metadata-Version: 2.4\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
            "License-Expression: MIT\n"
            "License-File: LICENSE\n"
            "Classifier: License :: OSI Approved :: MIT License\n"
            "Requires-Dist: example>=1\n"
            "\n"
        ).encode()
        metadata_file = dist_info / "METADATA"
        metadata_file.write_bytes(metadata_bytes)
        license_file = license_directory / "LICENSE"
        license_file.write_text(f"license for {name}\n", encoding="utf-8")
        prefix = f"{normalized}-{version}.dist-info"
        distributions[name] = _FakeDistribution(
            metadata_bytes=metadata_bytes,
            metadata_path=_FakePackagePath(f"{prefix}/METADATA", metadata_file),
            license_path=_FakePackagePath(
                f"{prefix}/licenses/LICENSE", license_file
            ),
            version=version,
        )
        if name == "diffeoforge":
            editable = tmp_path / "__editable__.diffeoforge.pth"
            editable.write_text("editable test path\n", encoding="utf-8")
            distributions[name].files.append(
                _FakePackagePath("../../../__editable__.diffeoforge.pth", editable)
            )
        if name == "torch":
            vendored = tmp_path / "torch" / "_vendor" / "vendored.dist-info"
            vendored.mkdir(parents=True)
            vendored_metadata = vendored / "METADATA"
            vendored_metadata.write_text(
                "Metadata-Version: 2.4\nName: vendored\nVersion: 1\n",
                encoding="utf-8",
            )
            vendored_license = vendored / "LICENSE"
            vendored_license.write_text("vendored license\n", encoding="utf-8")
            distributions[name].files.extend(
                [
                    _FakePackagePath(
                        "torch/_vendor/vendored.dist-info/METADATA",
                        vendored_metadata,
                    ),
                    _FakePackagePath(
                        "torch/_vendor/vendored.dist-info/LICENSE",
                        vendored_license,
                    ),
                ]
            )
    return distributions


def _freeze_sha256(bundle: Path) -> str:
    return hashlib.sha256((bundle / MANIFEST_NAME).read_bytes()).hexdigest()


def _rewrite_evidence(path: Path, evidence: dict) -> None:
    payload = (
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    path.with_name(SIDECAR_NAME).write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {EVIDENCE_NAME}\n",
        encoding="ascii",
        newline="\n",
    )


def test_dependency_metadata_evidence_is_exact_bound_and_non_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    distributions = _fake_distributions(tmp_path / "metadata")
    monkeypatch.setattr(
        dependency_evidence.importlib.metadata,
        "distribution",
        lambda name: distributions[name],
    )
    output = tmp_path / "Evidence Käfer"
    output.mkdir()
    freeze_sha256 = _freeze_sha256(bundle)

    evidence_path = create_desktop_dependency_metadata_evidence(
        bundle,
        expected_freeze_evidence_sha256=freeze_sha256,
        output_directory=output,
    )
    evidence = verify_desktop_dependency_metadata_evidence(
        evidence_path,
        expected_freeze_evidence_sha256=freeze_sha256,
    )

    assert evidence_path == output / EVIDENCE_NAME
    assert evidence["schema_version"] == "0.2"
    assert evidence["source"]["freeze_evidence_schema_version"] == "0.4"
    assert evidence["status"].endswith("not_license_or_redistribution_approval")
    assert evidence["source"]["freeze_evidence_sha256"] == freeze_sha256
    assert evidence["package_count"] == len(VERSIONS)
    assert [package["name"] for package in evidence["packages"]] == sorted(
        name.replace("_", "-").lower() for name in VERSIONS
    )
    for package in evidence["packages"]:
        assert package["metadata"]["license_expression"] == "MIT"
        assert len(package["license_files"]) == 1
        assert package["license_files"][0]["source"] == "declared"
        assert package["unresolved_declared_license_files"] == []
        assert package["review_status"] == "unreviewed"
    assert evidence["review_boundary"] == {
        "license_compatibility": "not_reviewed",
        "redistribution": "not_reviewed",
        "sbom": "not_an_sbom",
    }
    sidecar = (output / SIDECAR_NAME).read_text(encoding="ascii").split()
    assert sidecar == [hashlib.sha256(evidence_path.read_bytes()).hexdigest(), EVIDENCE_NAME]

    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        create_desktop_dependency_metadata_evidence(
            bundle,
            expected_freeze_evidence_sha256=freeze_sha256,
            output_directory=output,
        )


def test_dependency_metadata_verifier_retains_v01_compatibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    distributions = _fake_distributions(tmp_path / "metadata")
    monkeypatch.setattr(
        dependency_evidence.importlib.metadata,
        "distribution",
        lambda name: distributions[name],
    )
    output = tmp_path / "evidence"
    output.mkdir()
    freeze_sha256 = _freeze_sha256(bundle)
    evidence_path = create_desktop_dependency_metadata_evidence(
        bundle,
        expected_freeze_evidence_sha256=freeze_sha256,
        output_directory=output,
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["schema_version"] = "0.1"
    evidence["source"]["freeze_evidence_schema_version"] = "0.3"
    _rewrite_evidence(evidence_path, evidence)

    verified = verify_desktop_dependency_metadata_evidence(
        evidence_path,
        expected_freeze_evidence_sha256=freeze_sha256,
    )

    assert verified["schema_version"] == "0.1"
    assert verified["source"]["freeze_evidence_schema_version"] == "0.3"


def test_dependency_metadata_evidence_rejects_wrong_source_version_and_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    distributions = _fake_distributions(tmp_path / "metadata")
    monkeypatch.setattr(
        dependency_evidence.importlib.metadata,
        "distribution",
        lambda name: distributions[name],
    )
    output = tmp_path / "evidence"
    output.mkdir()
    freeze_sha256 = _freeze_sha256(bundle)

    with pytest.raises(
        DesktopDependencyMetadataEvidenceError, match="externally expected"
    ):
        create_desktop_dependency_metadata_evidence(
            bundle,
            expected_freeze_evidence_sha256="0" * 64,
            output_directory=output,
        )

    distributions["torch"].version = "unexpected"
    with pytest.raises(DesktopDependencyMetadataEvidenceError, match="version differs"):
        create_desktop_dependency_metadata_evidence(
            bundle,
            expected_freeze_evidence_sha256=freeze_sha256,
            output_directory=output,
        )
    assert list(output.iterdir()) == []
    distributions["torch"].version = VERSIONS["torch"]

    evidence_path = create_desktop_dependency_metadata_evidence(
        bundle,
        expected_freeze_evidence_sha256=freeze_sha256,
        output_directory=output,
    )
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["packages"][0]["version"] = "tampered"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DesktopDependencyMetadataEvidenceError, match="sidecar"):
        verify_desktop_dependency_metadata_evidence(
            evidence_path,
            expected_freeze_evidence_sha256=freeze_sha256,
        )
    (output / SIDECAR_NAME).write_text(
        f"{hashlib.sha256(evidence_path.read_bytes()).hexdigest()}  {EVIDENCE_NAME}\n",
        encoding="ascii",
        newline="\n",
    )
    with pytest.raises(DesktopDependencyMetadataEvidenceError, match="canonical"):
        verify_desktop_dependency_metadata_evidence(
            evidence_path,
            expected_freeze_evidence_sha256=freeze_sha256,
        )
    canonical = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    evidence_path.write_bytes(canonical)
    (output / SIDECAR_NAME).write_text(
        f"{hashlib.sha256(canonical).hexdigest()}  {EVIDENCE_NAME}\n",
        encoding="ascii",
        newline="\n",
    )
    with pytest.raises(
        DesktopDependencyMetadataEvidenceError, match="package-set SHA-256"
    ):
        verify_desktop_dependency_metadata_evidence(
            evidence_path,
            expected_freeze_evidence_sha256=freeze_sha256,
        )


def test_dependency_metadata_evidence_must_stay_outside_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    distributions = _fake_distributions(tmp_path / "metadata")
    monkeypatch.setattr(
        dependency_evidence.importlib.metadata,
        "distribution",
        lambda name: distributions[name],
    )

    with pytest.raises(ConfigurationError, match="outside the frozen bundle"):
        create_desktop_dependency_metadata_evidence(
            bundle,
            expected_freeze_evidence_sha256=_freeze_sha256(bundle),
            output_directory=bundle,
        )
