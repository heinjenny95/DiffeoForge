from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reference_prelaunch import (
    DesktopReferenceLaunchRequest,
    DesktopReferencePrelaunchError,
    build_reference_launch_request,
    validate_reference_launch_request,
)
from diffeoforge.desktop.reference_readiness import DesktopReferenceReadiness
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.diagnostics import DoctorCheck, DoctorReport

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, *, container: bool = True) -> Path:
    source = "minimal-atlas-container.yaml" if container else "minimal-atlas.yaml"
    path = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / source, path)
    return path


def _review(path: Path, *, engine: DesktopEngine = DesktopEngine.DEFORMETRICA_REFERENCE):
    return ProjectReviewResult(
        engine=engine,
        project_name="reference",
        config_path=path,
        config_sha256=sha256_file(path),
        report_path=path.with_suffix(".html"),
        report_label="Preflight-Report",
        subject_count=8,
        parameters=(),
        workload=(),
        warnings=(),
        scientific_boundary="test boundary",
    )


def _readiness(
    path: Path,
    *,
    digest: str | None = None,
    engine: str = "docker",
    image: str = "diffeoforge-deformetrica:4.3.0-cpu",
    status: str = "ready",
) -> DesktopReferenceReadiness:
    report = DoctorReport(
        status=status,
        workspace=str(path.parent),
        engine=engine,
        image=image,
        checks=(DoctorCheck("reference_image", "Reference image", "pass", "present"),),
    )
    return DesktopReferenceReadiness(
        config_path=path,
        config_sha256=sha256_file(path) if digest is None else digest,
        workspace=path.parent,
        engine=engine,
        image=image,
        report=report,
    )


def test_reference_prelaunch_binds_round_trip_without_mutation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    review = _review(config)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    request = build_reference_launch_request(
        review,
        _readiness(config),
        request_id="reference-test-001",
        run_id="pilot-001",
    )
    round_trip = DesktopReferenceLaunchRequest.from_dict(request.as_dict())

    assert round_trip == request
    assert request.destination == (tmp_path / "runs" / "pilot-001").resolve()
    assert request.launcher_engine == "docker"
    assert request.launcher_image == "diffeoforge-deformetrica:4.3.0-cpu"
    assert request.expected_config_sha256 == review.config_sha256
    assert not request.destination.exists()
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"digest": "0" * 64}, "different configuration bytes"),
        ({"engine": "podman"}, "different container launcher settings"),
        ({"image": "other:image"}, "different container launcher settings"),
        ({"status": "blocked"}, "readiness is blocked"),
    ],
)
def test_reference_prelaunch_rejects_mismatched_or_blocked_readiness(
    tmp_path: Path,
    kwargs: dict[str, str],
    message: str,
) -> None:
    config = _config(tmp_path)

    with pytest.raises(DesktopReferencePrelaunchError, match=message):
        build_reference_launch_request(
            _review(config),
            _readiness(config, **kwargs),
            request_id="reference-test",
            run_id="pilot-001",
        )


def test_reference_prelaunch_rejects_different_config_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    other = tmp_path / "other.yaml"
    shutil.copyfile(config, other)

    with pytest.raises(DesktopReferencePrelaunchError, match="different reviewed"):
        build_reference_launch_request(
            _review(config),
            _readiness(other.resolve()),
            request_id="reference-test",
            run_id="pilot-001",
        )


def test_reference_prelaunch_rejects_different_workspace(tmp_path: Path) -> None:
    config = _config(tmp_path)
    readiness = _readiness(config)
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    mismatched = DesktopReferenceReadiness(
        config_path=readiness.config_path,
        config_sha256=readiness.config_sha256,
        workspace=other_workspace,
        engine=readiness.engine,
        image=readiness.image,
        report=DoctorReport(
            status="ready",
            workspace=str(other_workspace),
            engine=readiness.engine,
            image=readiness.image,
            checks=readiness.report.checks,
        ),
    )

    with pytest.raises(DesktopReferencePrelaunchError, match="different project workspace"):
        build_reference_launch_request(
            _review(config),
            mismatched,
            request_id="reference-test",
            run_id="pilot-001",
        )


def test_reference_prelaunch_rejects_changed_reviewed_bytes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    review = _review(config)
    readiness = _readiness(config)
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(DesktopReferencePrelaunchError, match="changed after"):
        build_reference_launch_request(
            review,
            readiness,
            request_id="reference-test",
            run_id="pilot-001",
        )


def test_reference_prelaunch_wraps_invalid_bound_configuration(tmp_path: Path) -> None:
    config = (tmp_path / "atlas.yaml").resolve()
    config.write_text("not: [valid\n", encoding="utf-8")
    digest = sha256_file(config)
    request = DesktopReferenceLaunchRequest(
        request_id="reference-test",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=digest,
        launcher_engine="docker",
        launcher_image="reference:image",
    )

    with pytest.raises(DesktopReferencePrelaunchError, match="Bound reference configuration"):
        request.verify_launch_inputs()


def test_reference_prelaunch_discards_concurrent_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    review = _review(config)
    readiness = _readiness(config)

    def changing_hash(path: Path) -> str:
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return sha256_file(path)

    monkeypatch.setattr(
        "diffeoforge.desktop.reference_prelaunch.sha256_file",
        changing_hash,
    )

    with pytest.raises(DesktopReferencePrelaunchError, match="changed while"):
        build_reference_launch_request(
            review,
            readiness,
            request_id="reference-test",
            run_id="pilot-001",
        )


def test_reference_prelaunch_request_rechecks_launcher_output_and_destination(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    base = build_reference_launch_request(
        _review(config),
        _readiness(config),
        request_id="reference-test",
        run_id="pilot-001",
    )

    wrong_launcher = DesktopReferenceLaunchRequest(
        **{**base.__dict__, "launcher_image": "different:image"}
    )
    with pytest.raises(DesktopReferencePrelaunchError, match="launcher changed"):
        wrong_launcher.verify_launch_inputs()

    wrong_destination = DesktopReferenceLaunchRequest(
        **{
            **base.__dict__,
            "destination": (tmp_path / "elsewhere" / base.run_id).resolve(),
        }
    )
    with pytest.raises(DesktopReferencePrelaunchError, match="different launch destination"):
        wrong_destination.verify_launch_inputs()

    base.destination.mkdir(parents=True)
    with pytest.raises(DesktopReferencePrelaunchError, match="already exists"):
        base.verify_launch_inputs()


def test_reference_prelaunch_rejects_nonreference_and_noncontainer_routes(
    tmp_path: Path,
) -> None:
    container = _config(tmp_path)
    with pytest.raises(DesktopReferencePrelaunchError, match="reference review"):
        build_reference_launch_request(
            _review(container, engine=DesktopEngine.MODERN_CPU),
            _readiness(container),
            request_id="reference-test",
            run_id="pilot-001",
        )

    native_root = tmp_path / "native"
    native_root.mkdir()
    native = _config(native_root, container=False)
    with pytest.raises(DesktopReferencePrelaunchError, match="container launcher only"):
        build_reference_launch_request(
            _review(native),
            _readiness(native),
            request_id="reference-test",
            run_id="pilot-001",
        )


@pytest.mark.parametrize("field", ["request_id", "run_id"])
def test_reference_prelaunch_schema_rejects_malformed_ids(tmp_path: Path, field: str) -> None:
    config = _config(tmp_path)
    request = build_reference_launch_request(
        _review(config),
        _readiness(config),
        request_id="reference-test",
        run_id="pilot-001",
    ).as_dict()
    request[field] = "not allowed / value"

    with pytest.raises(DesktopReferencePrelaunchError, match=field):
        validate_reference_launch_request(request)
