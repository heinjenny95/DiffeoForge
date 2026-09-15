"""Hash-bound, non-mutating prelaunch contract for the reference supervisor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema

from diffeoforge.config import ConfigurationError, resolve_output_directory
from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.reference_production_readiness import (
    assess_reference_resume_production_readiness,
)
from diffeoforge.desktop.reference_readiness import (
    DesktopReferenceReadiness,
    DesktopReferenceReadinessError,
    parse_reference_config_bytes,
)
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.reference_runtime import launcher_identity
from diffeoforge.runs import inspect_resume_source

REFERENCE_LAUNCH_REQUEST_VERSION = "0.2"


class DesktopReferencePrelaunchError(RuntimeError):
    """Raised when a future reference launch cannot remain exactly bound."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-reference-launch-request-v0.2.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_reference_launch_request(value: Mapping[str, Any]) -> None:
    """Validate one serialized reference-launch request."""

    try:
        jsonschema.Draft202012Validator(_schema()).validate(dict(value))
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        raise DesktopReferencePrelaunchError(
            f"Reference launch request schema validation failed at {location}: "
            f"{error.message}"
        ) from error


def _bound_config(
    config_path: Path,
    expected_sha256: str,
) -> Mapping[str, Any]:
    try:
        content = config_path.read_bytes()
    except OSError as error:
        raise DesktopReferencePrelaunchError(
            f"Reference configuration is no longer readable: {error}"
        ) from error
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise DesktopReferencePrelaunchError(
            "Reference configuration changed after the prelaunch request was bound"
        )
    try:
        config = parse_reference_config_bytes(content)
    except (
        ConfigurationError,
        DesktopReferenceReadinessError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DesktopReferencePrelaunchError(
            f"Bound reference configuration is invalid: {error}"
        ) from error
    try:
        hash_after = sha256_file(config_path)
    except OSError as error:
        raise DesktopReferencePrelaunchError(
            f"Reference configuration became unreadable during verification: {error}"
        ) from error
    if hash_after != expected_sha256:
        raise DesktopReferencePrelaunchError(
            "Reference configuration changed while the prelaunch request was verified"
        )
    return config


def _configured_launcher(config: Mapping[str, Any]) -> dict[str, str]:
    try:
        return launcher_identity(config["runtime"]["launcher"])
    except (KeyError, TypeError, ValueError) as error:
        raise DesktopReferencePrelaunchError(
            f"Configured reference launcher is invalid: {error}"
        ) from error


@dataclass(frozen=True)
class DesktopReferenceLaunchRequest:
    """Exact future supervisor input; construction and verification are read-only."""

    request_id: str
    config_path: Path
    destination: Path
    run_id: str
    expected_config_sha256: str
    launcher_engine: str | None
    launcher_image: str | None
    launcher_type: str = "container"
    launcher_distribution: str | None = None
    launcher_executable: str | None = None
    resume_source: Path | None = None

    @property
    def engine(self) -> str:
        return "deformetrica_reference"

    def as_dict(self) -> dict[str, Any]:
        launcher = self.launcher
        return {
            "reference_launch_request_version": REFERENCE_LAUNCH_REQUEST_VERSION,
            "request_id": self.request_id,
            "engine": self.engine,
            "config_path": str(self.config_path),
            "expected_config_sha256": self.expected_config_sha256,
            "run_id": self.run_id,
            "destination": str(self.destination),
            "resume_source": (
                None if self.resume_source is None else str(self.resume_source)
            ),
            "launcher": launcher,
        }

    @property
    def launcher(self) -> dict[str, str]:
        if self.launcher_type == "wsl":
            if self.launcher_distribution is None or self.launcher_executable is None:
                raise DesktopReferencePrelaunchError(
                    "WSL launch request is missing its distribution or executable"
                )
            return {
                "type": "wsl",
                "distribution": self.launcher_distribution,
                "executable": self.launcher_executable,
            }
        if self.launcher_type == "native":
            if self.launcher_executable is None:
                raise DesktopReferencePrelaunchError(
                    "Native launch request is missing its executable"
                )
            return {"type": "native", "executable": self.launcher_executable}
        if self.launcher_engine is None or self.launcher_image is None:
            raise DesktopReferencePrelaunchError(
                "Container launch request is missing its engine or image"
            )
        return {
            "type": "container",
            "engine": self.launcher_engine,
            "image": self.launcher_image,
        }

    def __post_init__(self) -> None:
        if (
            not self.config_path.is_absolute()
            or not self.destination.is_absolute()
            or (self.resume_source is not None and not self.resume_source.is_absolute())
        ):
            raise DesktopReferencePrelaunchError(
                "Reference launch request paths must be absolute"
            )
        validate_reference_launch_request(self.as_dict())
        if self.destination.name != self.run_id:
            raise DesktopReferencePrelaunchError(
                "Reference launch destination name must equal the normalized run_id"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DesktopReferenceLaunchRequest:
        validate_reference_launch_request(value)
        launcher = value["launcher"]
        config_path = Path(value["config_path"]).expanduser()
        destination = Path(value["destination"]).expanduser()
        if not config_path.is_absolute() or not destination.is_absolute():
            raise DesktopReferencePrelaunchError(
                "Reference launch request paths must be absolute"
            )
        launcher_type = str(launcher["type"])
        return cls(
            request_id=str(value["request_id"]),
            config_path=config_path.resolve(),
            destination=destination.resolve(),
            run_id=str(value["run_id"]),
            expected_config_sha256=str(value["expected_config_sha256"]),
            launcher_engine=(
                str(launcher["engine"]) if launcher_type == "container" else None
            ),
            launcher_image=(
                str(launcher["image"]) if launcher_type == "container" else None
            ),
            launcher_type=launcher_type,
            launcher_distribution=(
                str(launcher["distribution"]) if launcher_type == "wsl" else None
            ),
            launcher_executable=(
                str(launcher["executable"])
                if launcher_type in {"wsl", "native"}
                else None
            ),
            resume_source=(
                None
                if value["resume_source"] is None
                else Path(value["resume_source"]).expanduser().resolve()
            ),
        )

    def verify_launch_inputs(self) -> None:
        """Recheck exact bytes, launcher, destination resolution, and nonexistence."""

        config = _bound_config(self.config_path, self.expected_config_sha256)
        if _configured_launcher(config) != self.launcher:
            raise DesktopReferencePrelaunchError(
                "Configured reference launcher changed after the prelaunch request was bound"
            )
        if self.resume_source is not None:
            try:
                evidence = inspect_resume_source(self.resume_source)
            except (OSError, ConfigurationError, TypeError, ValueError) as error:
                raise DesktopReferencePrelaunchError(
                    f"Reference resume source is not eligible: {error}"
                ) from error
            source_config = evidence.source_run / "config" / "source-config.yaml"
            if source_config.resolve() != self.config_path:
                raise DesktopReferencePrelaunchError(
                    "Reference resume request is bound to a different protected source "
                    "configuration"
                )
            manifest_config = evidence.manifest["source_config"]
            if manifest_config["sha256"] != self.expected_config_sha256:
                raise DesktopReferencePrelaunchError(
                    "Reference resume configuration hash differs from the source manifest"
                )
            if _configured_launcher(evidence.manifest["effective_config"]) != self.launcher:
                raise DesktopReferencePrelaunchError(
                    "Reference resume launcher differs from the protected effective runtime"
                )
            production_readiness = assess_reference_resume_production_readiness(evidence)
            if production_readiness.production_scale and not production_readiness.ready:
                raise DesktopReferencePrelaunchError(
                    "Reference production-scale resume is not safe: "
                    + " ".join(production_readiness.blockers)
                )
            output_root = evidence.source_run.parent
        else:
            try:
                output_root = resolve_output_directory(config, self.config_path)
            except (OSError, ConfigurationError, TypeError, ValueError) as error:
                raise DesktopReferencePrelaunchError(
                    f"Reference output directory cannot be resolved: {error}"
                ) from error
        expected_destination = (output_root / self.run_id).resolve()
        if expected_destination != self.destination:
            raise DesktopReferencePrelaunchError(
                "Configured reference output resolves to a different launch destination"
            )
        if self.destination.exists():
            raise DesktopReferencePrelaunchError(
                f"Reference launch destination already exists: {self.destination}"
            )


def build_reference_launch_request(
    review: ProjectReviewResult,
    readiness: DesktopReferenceReadiness,
    *,
    request_id: str,
    run_id: str,
) -> DesktopReferenceLaunchRequest:
    """Bind matching reviewed bytes and ready observation without preparing a run."""

    if not isinstance(review, ProjectReviewResult):
        raise TypeError("review must be a ProjectReviewResult")
    if not isinstance(readiness, DesktopReferenceReadiness):
        raise TypeError("readiness must be a DesktopReferenceReadiness")
    if review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE:
        raise DesktopReferencePrelaunchError(
            "Reference prelaunch requires a Deformetrica reference review"
        )
    if readiness.config_path.resolve() != review.config_path.resolve():
        raise DesktopReferencePrelaunchError(
            "Reference readiness targets a different reviewed configuration"
        )
    if readiness.config_sha256 != review.config_sha256:
        raise DesktopReferencePrelaunchError(
            "Reference readiness is bound to different configuration bytes"
        )
    if not readiness.ready:
        raise DesktopReferencePrelaunchError(
            "Reference environment readiness is blocked; no prelaunch request was created"
        )

    config_path = review.config_path.resolve()
    if readiness.workspace.resolve() != config_path.parent:
        raise DesktopReferencePrelaunchError(
            "Reference readiness targets a different project workspace"
        )
    config = _bound_config(config_path, review.config_sha256)
    configured_launcher = _configured_launcher(config)
    if configured_launcher != readiness.launcher:
        qualifier = "container " if configured_launcher["type"] == "container" else ""
        raise DesktopReferencePrelaunchError(
            f"Reference readiness targets different {qualifier}launcher settings"
        )
    try:
        output_root = resolve_output_directory(config, config_path)
    except (OSError, ConfigurationError, TypeError, ValueError) as error:
        raise DesktopReferencePrelaunchError(
            f"Reference output directory cannot be resolved: {error}"
        ) from error
    request = DesktopReferenceLaunchRequest(
        request_id=request_id,
        config_path=config_path,
        destination=(output_root / run_id).resolve(),
        run_id=run_id,
        expected_config_sha256=review.config_sha256,
        launcher_engine=configured_launcher.get("engine"),
        launcher_image=configured_launcher.get("image"),
        launcher_type=configured_launcher["type"],
        launcher_distribution=configured_launcher.get("distribution"),
        launcher_executable=configured_launcher.get("executable"),
    )
    request.verify_launch_inputs()
    return request


def build_reference_resume_launch_request(
    source_run_directory: Path | str,
    *,
    request_id: str,
    run_id: str,
) -> DesktopReferenceLaunchRequest:
    """Bind one verified interrupted run to a new immutable desktop successor."""

    try:
        evidence = inspect_resume_source(source_run_directory)
        source_config = evidence.source_run / "config" / "source-config.yaml"
        source_config_record = next(
            artifact
            for artifact in evidence.manifest["protected_artifacts"]
            if artifact["path"] == "config/source-config.yaml"
        )
        configured_launcher = _configured_launcher(evidence.manifest["effective_config"])
    except (KeyError, OSError, StopIteration, ConfigurationError, TypeError, ValueError) as error:
        raise DesktopReferencePrelaunchError(
            f"Reference resume source could not be bound: {error}"
        ) from error
    request = DesktopReferenceLaunchRequest(
        request_id=request_id,
        config_path=source_config.resolve(),
        destination=(evidence.source_run.parent / run_id).resolve(),
        run_id=run_id,
        expected_config_sha256=str(source_config_record["sha256"]),
        launcher_engine=configured_launcher.get("engine"),
        launcher_image=configured_launcher.get("image"),
        launcher_type=configured_launcher["type"],
        launcher_distribution=configured_launcher.get("distribution"),
        launcher_executable=configured_launcher.get("executable"),
        resume_source=evidence.source_run,
    )
    request.verify_launch_inputs()
    return request
