from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from diffeoforge.desktop.freeze_evidence import (
    MANIFEST_NAME,
    MISSING_RELEASE_GATES,
    SCIENTIFIC_BOUNDARY,
    SIDECAR_NAME,
    STATUS,
    TARGET,
    DesktopFreezeEvidenceError,
    create_desktop_freeze_evidence,
    verify_desktop_freeze_evidence,
)

FIXED_TIME = "2026-07-17T18:00:00+00:00"
SOURCE_COMMIT = "a" * 40
VERSIONS = {
    "diffeoforge": "0.0.0.dev0",
    "numpy": "2.5.1",
    "psutil": "7.2.2",
    "pyinstaller": "6.21.0",
    "pyside6-essentials": "6.11.1",
    "shiboken6": "6.11.1",
    "torch": "2.13.0",
}


def _bundle(
    tmp_path: Path,
    *,
    include_reference_worker: bool = True,
    include_preparation_worker: bool = True,
    include_execution_worker: bool = True,
) -> Path:
    root = tmp_path / "DiffeoForge"
    internal = root / "_internal" / "diffeoforge" / "schema"
    internal.mkdir(parents=True)
    (root / "DiffeoForge.exe").write_bytes(b"desktop executable")
    (root / "DiffeoForgeWorker.exe").write_bytes(b"worker executable")
    if include_reference_worker:
        (root / "DiffeoForgeReferenceWorker.exe").write_bytes(
            b"reference worker executable"
        )
    if include_preparation_worker:
        (root / "DiffeoForgeReferencePreparationWorker.exe").write_bytes(
            b"reference preparation worker executable"
        )
    if include_execution_worker:
        (root / "DiffeoForgeReferenceExecutionWorker.exe").write_bytes(
            b"reference execution worker executable"
        )
    (internal / "schema.json").write_text('{"schema": true}\n', encoding="utf-8")
    return root


def _create(root: Path) -> Path:
    return create_desktop_freeze_evidence(
        root,
        source_commit=SOURCE_COMMIT,
        created_at=FIXED_TIME,
        package_versions=VERSIONS,
        python_version="3.12.13",
        platform_description="Windows-11-10.0.26100-SP0",
    )


def _rewrite_manifest(root: Path, manifest: dict) -> None:
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    (root / MANIFEST_NAME).write_bytes(payload)
    (root / SIDECAR_NAME).write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {MANIFEST_NAME}\n",
        encoding="ascii",
        newline="\n",
    )


def test_desktop_freeze_evidence_is_exact_non_overwriting_and_self_verifying(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)

    manifest_path = _create(root)
    manifest = verify_desktop_freeze_evidence(root)

    assert manifest_path == root / MANIFEST_NAME
    assert manifest["schema_version"] == "0.4"
    assert manifest["status"] == "engineering_evidence_not_a_release"
    assert manifest["target"] == "windows-x86_64-cpu"
    assert manifest["builder"] == {
        "name": "PyInstaller",
        "version": "6.21.0",
        "mode": "onedir",
        "python": "3.12.13",
        "platform": "Windows-11-10.0.26100-SP0",
    }
    assert manifest["entry_points"] == {
        "desktop": "DiffeoForge.exe",
        "reference_execution_worker": "DiffeoForgeReferenceExecutionWorker.exe",
        "reference_preparation_worker": "DiffeoForgeReferencePreparationWorker.exe",
        "reference_worker": "DiffeoForgeReferenceWorker.exe",
        "worker": "DiffeoForgeWorker.exe",
    }
    assert manifest["bundle"]["file_count"] == 6
    assert [record["path"] for record in manifest["bundle"]["files"]] == sorted(
        record["path"] for record in manifest["bundle"]["files"]
    )
    assert "clean_windows_vm" in manifest["missing_release_gates"]
    assert "not an installer" in manifest["scientific_boundary"]
    with pytest.raises(FileExistsError, match="will not be replaced"):
        _create(root)


def test_desktop_freeze_verifier_rejects_tampered_missing_and_extra_files(
    tmp_path: Path,
) -> None:
    tampered = _bundle(tmp_path / "tampered")
    _create(tampered)
    (tampered / "DiffeoForgeWorker.exe").write_bytes(b"changed")
    with pytest.raises(DesktopFreezeEvidenceError, match="size differs"):
        verify_desktop_freeze_evidence(tampered)

    missing = _bundle(tmp_path / "missing")
    _create(missing)
    (missing / "_internal" / "diffeoforge" / "schema" / "schema.json").unlink()
    with pytest.raises(DesktopFreezeEvidenceError, match="inventory differs"):
        verify_desktop_freeze_evidence(missing)

    extra = _bundle(tmp_path / "extra")
    _create(extra)
    (extra / "unexpected.bin").write_bytes(b"not inventoried")
    with pytest.raises(DesktopFreezeEvidenceError, match="inventory differs"):
        verify_desktop_freeze_evidence(extra)


def test_desktop_freeze_creation_requires_windows_entry_points_and_clean_provenance(
    tmp_path: Path,
) -> None:
    missing_worker = _bundle(tmp_path / "missing-worker")
    (missing_worker / "DiffeoForgeWorker.exe").unlink()
    with pytest.raises(DesktopFreezeEvidenceError, match="entry point"):
        _create(missing_worker)

    missing_reference_worker = _bundle(tmp_path / "missing-reference-worker")
    (missing_reference_worker / "DiffeoForgeReferenceWorker.exe").unlink()
    with pytest.raises(DesktopFreezeEvidenceError, match="entry point"):
        _create(missing_reference_worker)

    missing_preparation_worker = _bundle(tmp_path / "missing-preparation-worker")
    (missing_preparation_worker / "DiffeoForgeReferencePreparationWorker.exe").unlink()
    with pytest.raises(DesktopFreezeEvidenceError, match="entry point"):
        _create(missing_preparation_worker)

    missing_execution_worker = _bundle(tmp_path / "missing-execution-worker")
    (missing_execution_worker / "DiffeoForgeReferenceExecutionWorker.exe").unlink()
    with pytest.raises(DesktopFreezeEvidenceError, match="entry point"):
        _create(missing_execution_worker)

    non_windows = _bundle(tmp_path / "non-windows")
    with pytest.raises(DesktopFreezeEvidenceError, match="Windows host"):
        create_desktop_freeze_evidence(
            non_windows,
            source_commit=SOURCE_COMMIT,
            created_at=FIXED_TIME,
            package_versions=VERSIONS,
            python_version="3.12.13",
            platform_description="Linux-6.8-x86_64",
        )

    invalid_commit = _bundle(tmp_path / "invalid-commit")
    with pytest.raises(ValueError, match="Git SHA"):
        create_desktop_freeze_evidence(
            invalid_commit,
            source_commit="dirty",
            created_at=FIXED_TIME,
            package_versions=VERSIONS,
            python_version="3.12.13",
            platform_description="Windows-11-test",
        )


def test_desktop_freeze_verifier_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    _create(root)
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["bundle"]["files"][0]["path"] = "../outside.exe"
    _rewrite_manifest(root, manifest)

    with pytest.raises(DesktopFreezeEvidenceError, match="schema violation|Unsafe"):
        verify_desktop_freeze_evidence(root)


def test_desktop_freeze_verifier_rejects_unknown_schema_version(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    _create(root)
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["schema_version"] = "0.5"
    _rewrite_manifest(root, manifest)

    with pytest.raises(DesktopFreezeEvidenceError, match="Unsupported.*0.5"):
        verify_desktop_freeze_evidence(root)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(status="release"), "schema violation"),
        (lambda value: value.update(target="linux-x86_64-cpu"), "schema violation"),
        (
            lambda value: value["entry_points"].update(worker="other.exe"),
            "schema violation",
        ),
        (
            lambda value: value["entry_points"].update(
                reference_worker="other-reference.exe"
            ),
            "schema violation",
        ),
        (
            lambda value: value["entry_points"].update(
                reference_preparation_worker="other-preparation.exe"
            ),
            "schema violation",
        ),
        (
            lambda value: value["entry_points"].update(
                reference_execution_worker="other-execution.exe"
            ),
            "schema violation",
        ),
    ],
)
def test_desktop_freeze_verifier_rejects_wrong_status_and_entry_points(
    tmp_path: Path,
    mutation,
    match: str,
) -> None:
    root = _bundle(tmp_path)
    _create(root)
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    mutation(manifest)
    _rewrite_manifest(root, manifest)

    with pytest.raises(DesktopFreezeEvidenceError, match=match):
        verify_desktop_freeze_evidence(root)


def test_desktop_freeze_evidence_cli_verifies_existing_bundle(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "Evidence Käfer")
    _create(root)

    completed = subprocess.run(
        [sys.executable, "tools/desktop_bundle_evidence.py", "verify", str(root)],
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["source_commit"] == SOURCE_COMMIT
    assert summary["file_count"] == 6


def test_desktop_freeze_verifier_retains_legacy_v01_compatibility(
    tmp_path: Path,
) -> None:
    root = _bundle(
        tmp_path / "legacy",
        include_reference_worker=False,
        include_preparation_worker=False,
        include_execution_worker=False,
    )
    records = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if not path.is_file():
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    inventory_payload = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    manifest = {
        "schema_version": "0.1",
        "status": STATUS,
        "created_at": FIXED_TIME,
        "target": TARGET,
        "source": {"commit_sha": SOURCE_COMMIT, "dirty_worktree_allowed": False},
        "builder": {
            "name": "PyInstaller",
            "version": VERSIONS["pyinstaller"],
            "mode": "onedir",
            "python": "3.12.13",
            "platform": "Windows-11-10.0.26100-SP0",
        },
        "runtime_packages": VERSIONS,
        "entry_points": {
            "desktop": "DiffeoForge.exe",
            "worker": "DiffeoForgeWorker.exe",
        },
        "bundle": {
            "directory_name": root.name,
            "file_count": len(records),
            "total_bytes": sum(record["bytes"] for record in records),
            "inventory_sha256": hashlib.sha256(
                inventory_payload.encode("utf-8")
            ).hexdigest(),
            "files": records,
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _rewrite_manifest(root, manifest)

    verified = verify_desktop_freeze_evidence(root)

    assert verified["schema_version"] == "0.1"
    assert verified["entry_points"] == {
        "desktop": "DiffeoForge.exe",
        "worker": "DiffeoForgeWorker.exe",
    }


def test_desktop_freeze_verifier_retains_v02_three_entry_point_compatibility(
    tmp_path: Path,
) -> None:
    root = _bundle(
        tmp_path / "legacy-v02",
        include_preparation_worker=False,
        include_execution_worker=False,
    )
    records = []
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if not path.is_file():
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    inventory_payload = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    manifest = {
        "schema_version": "0.2",
        "status": STATUS,
        "created_at": FIXED_TIME,
        "target": TARGET,
        "source": {"commit_sha": SOURCE_COMMIT, "dirty_worktree_allowed": False},
        "builder": {
            "name": "PyInstaller",
            "version": VERSIONS["pyinstaller"],
            "mode": "onedir",
            "python": "3.12.13",
            "platform": "Windows-11-10.0.26100-SP0",
        },
        "runtime_packages": VERSIONS,
        "entry_points": {
            "desktop": "DiffeoForge.exe",
            "reference_worker": "DiffeoForgeReferenceWorker.exe",
            "worker": "DiffeoForgeWorker.exe",
        },
        "bundle": {
            "directory_name": root.name,
            "file_count": len(records),
            "total_bytes": sum(record["bytes"] for record in records),
            "inventory_sha256": hashlib.sha256(
                inventory_payload.encode("utf-8")
            ).hexdigest(),
            "files": records,
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _rewrite_manifest(root, manifest)

    verified = verify_desktop_freeze_evidence(root)

    assert verified["schema_version"] == "0.2"
    assert verified["entry_points"] == {
        "desktop": "DiffeoForge.exe",
        "reference_worker": "DiffeoForgeReferenceWorker.exe",
        "worker": "DiffeoForgeWorker.exe",
    }


def test_desktop_freeze_verifier_retains_v03_four_entry_point_compatibility(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path / "legacy-v03", include_execution_worker=False)
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix())
        if path.is_file()
    ]
    inventory_payload = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    manifest = {
        "schema_version": "0.3",
        "status": STATUS,
        "created_at": FIXED_TIME,
        "target": TARGET,
        "source": {"commit_sha": SOURCE_COMMIT, "dirty_worktree_allowed": False},
        "builder": {
            "name": "PyInstaller",
            "version": VERSIONS["pyinstaller"],
            "mode": "onedir",
            "python": "3.12.13",
            "platform": "Windows-11-10.0.26100-SP0",
        },
        "runtime_packages": VERSIONS,
        "entry_points": {
            "desktop": "DiffeoForge.exe",
            "reference_preparation_worker": (
                "DiffeoForgeReferencePreparationWorker.exe"
            ),
            "reference_worker": "DiffeoForgeReferenceWorker.exe",
            "worker": "DiffeoForgeWorker.exe",
        },
        "bundle": {
            "directory_name": root.name,
            "file_count": len(records),
            "total_bytes": sum(record["bytes"] for record in records),
            "inventory_sha256": hashlib.sha256(
                inventory_payload.encode("utf-8")
            ).hexdigest(),
            "files": records,
        },
        "missing_release_gates": list(MISSING_RELEASE_GATES),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _rewrite_manifest(root, manifest)

    verified = verify_desktop_freeze_evidence(root)

    assert verified["schema_version"] == "0.3"
    assert "reference_execution_worker" not in verified["entry_points"]
