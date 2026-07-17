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
from diffeoforge.desktop.reference_readiness import (
    DesktopReferenceReadiness,
    DesktopReferenceReadinessError,
    parse_reference_config_bytes,
)
from diffeoforge.desktop.worker_protocol import sha256_file

REFERENCE_LAUNCH_REQUEST_VERSION = "0.1"


class DesktopReferencePrelaunchError(RuntimeError):
    """Raised when a future reference launch cannot remain exactly bound."""


def _schema() -> dict[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "desktop-reference-launch-request-v0.1.json"
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


def _container_launcher(config: Mapping[str, Any]) -> tuple[str, str]:
    launcher = config["runtime"]["launcher"]
    if launcher["type"] != "container":
        raise DesktopReferencePrelaunchError(
            "Desktop reference prelaunch currently supports the container launcher only"
        )
    return str(launcher["engine"]), str(launcher["image"])


@dataclass(frozen=True)
class DesktopReferenceLaunchRequest:
    """Exact future supervisor input; construction and verification are read-only."""

    request_id: str
    config_path: Path
    destination: Path
    run_id: str
    expected_config_sha256: str
    launcher_engine: str
    launcher_image: str

    @property
    def engine(self) -> str:
        return "deformetrica_reference"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_launch_request_version": REFERENCE_LAUNCH_REQUEST_VERSION,
            "request_id": self.request_id,
            "engine": self.engine,
            "config_path": str(self.config_path),
            "expected_config_sha256": self.expected_config_sha256,
            "run_id": self.run_id,
            "destination": str(self.destination),
            "launcher": {
                "type": "container",
                "engine": self.launcher_engine,
                "image": self.launcher_image,
            },
        }

    def __post_init__(self) -> None:
        if not self.config_path.is_absolute() or not self.destination.is_absolute():
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
        return cls(
            request_id=str(value["request_id"]),
            config_path=config_path.resolve(),
            destination=destination.resolve(),
            run_id=str(value["run_id"]),
            expected_config_sha256=str(value["expected_config_sha256"]),
            launcher_engine=str(launcher["engine"]),
            launcher_image=str(launcher["image"]),
        )

    def verify_launch_inputs(self) -> None:
        """Recheck exact bytes, launcher, destination resolution, and nonexistence."""

        config = _bound_config(self.config_path, self.expected_config_sha256)
        engine, image = _container_launcher(config)
        if engine != self.launcher_engine or image != self.launcher_image:
            raise DesktopReferencePrelaunchError(
                "Configured reference launcher changed after the prelaunch request was bound"
            )
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
    engine, image = _container_launcher(config)
    if engine != readiness.engine or image != readiness.image:
        raise DesktopReferencePrelaunchError(
            "Reference readiness targets different container launcher settings"
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
        launcher_engine=engine,
        launcher_image=image,
    )
    request.verify_launch_inputs()
    return request
