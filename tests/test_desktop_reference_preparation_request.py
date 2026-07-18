from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
    DesktopReferencePreparationRequestError,
    build_reference_preparation_request,
)
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Preparation Worker Request Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _approval(root: Path) -> tuple[Path, dict, str]:
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id="worker-approved-001")
    request = create_reference_preparation_approval(
        config,
        run_id="worker-approved-001",
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    path = write_reference_preparation_approval(request, root / "review" / "approval.json")
    return path, request, hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_build_request_is_deterministic_round_trippable_and_read_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval_path, approval, approval_hash = _approval(root)
    before = _files(root)

    first = build_reference_preparation_request(
        approval_path,
        root / "atlas.yaml",
        expected_approval_sha256=approval_hash.upper(),
        request_id="prepare-worker-001",
    )
    second = build_reference_preparation_request(
        approval_path,
        root / "atlas.yaml",
        expected_approval_sha256=f" {approval_hash} ",
        request_id="prepare-worker-001",
    )
    parsed = DesktopReferencePreparationRequest.from_dict(
        json.loads(json.dumps(first.as_dict()))
    )

    assert first == second == parsed
    assert _files(root) == before
    assert not (root / "runs").exists()
    assert first.expected_approval_sha256 == approval_hash
    assert first.expected_config_sha256 == approval["plan"]["source_config"]["sha256"]
    assert first.approved_plan_fingerprint == approval["approval"][
        "approved_plan_fingerprint"
    ]
    assert first.destination == Path(approval["plan"]["run"]["destination"])
    assert first.as_dict()["engine_execution_authorized"] is False


def test_build_request_rejects_wrong_external_hash_without_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval_path, _, _ = _approval(root)

    with pytest.raises(
        DesktopReferencePreparationRequestError,
        match="independently recorded",
    ):
        build_reference_preparation_request(
            approval_path,
            root / "atlas.yaml",
            expected_approval_sha256="0" * 64,
            request_id="wrong-hash",
        )

    assert not (root / "runs").exists()


def test_build_request_wraps_invalid_approval_as_request_error(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval_path = root / "review" / "approval.json"
    approval_path.parent.mkdir()
    approval_path.write_text('{"approval":', encoding="utf-8")
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()

    with pytest.raises(
        DesktopReferencePreparationRequestError,
        match="cannot be bound",
    ):
        build_reference_preparation_request(
            approval_path,
            root / "atlas.yaml",
            expected_approval_sha256=approval_hash,
            request_id="invalid-approval",
        )

    assert not (root / "runs").exists()


def test_verify_rejects_changed_mesh_config_or_approval(tmp_path: Path) -> None:
    root = _project(tmp_path)
    approval_path, approval, approval_hash = _approval(root)
    request = build_reference_preparation_request(
        approval_path,
        root / "atlas.yaml",
        expected_approval_sha256=approval_hash,
        request_id="changed-inputs",
    )
    destination = Path(approval["plan"]["run"]["destination"])

    subject = root / "synthetic" / "meshes" / "subject-01.vtk"
    original_subject = subject.read_bytes()
    subject.write_bytes(original_subject + b"\n")
    with pytest.raises(DesktopReferencePreparationRequestError, match="no longer matches"):
        request.verify_inputs()
    subject.write_bytes(original_subject)

    config = root / "atlas.yaml"
    original_config = config.read_bytes()
    config.write_bytes(original_config + b"\n")
    with pytest.raises(DesktopReferencePreparationRequestError, match="configuration changed"):
        request.verify_inputs()
    config.write_bytes(original_config)

    approval_path.write_bytes(approval_path.read_bytes() + b" ")
    with pytest.raises(DesktopReferencePreparationRequestError, match="Approval request changed"):
        request.verify_inputs()

    assert not destination.exists()


def test_request_schema_rejects_execution_authorization_or_relative_paths(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    approval_path, _, approval_hash = _approval(root)
    request = build_reference_preparation_request(
        approval_path,
        root / "atlas.yaml",
        expected_approval_sha256=approval_hash,
        request_id="schema-boundary",
    )

    changed = request.as_dict()
    changed["engine_execution_authorized"] = True
    with pytest.raises(DesktopReferencePreparationRequestError, match="schema"):
        DesktopReferencePreparationRequest.from_dict(changed)

    changed = request.as_dict()
    changed["approval_path"] = "relative/approval.json"
    with pytest.raises(DesktopReferencePreparationRequestError, match="absolute"):
        DesktopReferencePreparationRequest.from_dict(changed)
