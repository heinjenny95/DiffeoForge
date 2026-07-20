"""Bind read-only reference-environment diagnostics to one reviewed config."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from diffeoforge.backends.deformetrica_reference import validate_reference_config
from diffeoforge.config import ConfigurationError, validate_schema
from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.diagnostics import DoctorReport, run_doctor, run_reference_doctor
from diffeoforge.reference_runtime import launcher_identity


class DesktopReferenceReadinessError(RuntimeError):
    """Raised when reference readiness cannot remain bound to reviewed bytes."""


@dataclass(frozen=True)
class DesktopReferenceReadiness:
    """Exact reviewed launcher settings plus their observational doctor report."""

    config_path: Path
    config_sha256: str
    workspace: Path
    engine: str
    image: str
    report: DoctorReport
    launcher_type: str = "container"
    launcher_distribution: str | None = None
    launcher_executable: str | None = None

    def __post_init__(self) -> None:
        if Path(self.report.workspace).resolve() != self.workspace.resolve():
            raise ValueError("Reference doctor report targets a different workspace")
        if self.report.launcher is not None:
            if launcher_identity(self.report.launcher) != self.launcher:
                raise ValueError("Reference doctor report targets different launcher settings")
        elif self.report.engine != self.engine or self.report.image != self.image:
            raise ValueError("Reference doctor report targets different launcher settings")

    @property
    def launcher(self) -> dict[str, str]:
        """Return the exact schema launcher identity."""

        if self.launcher_type == "wsl":
            if self.launcher_distribution is None or self.launcher_executable is None:
                raise ValueError("WSL readiness is missing its distribution or executable")
            return {
                "type": "wsl",
                "distribution": self.launcher_distribution,
                "executable": self.launcher_executable,
            }
        if self.launcher_type == "native":
            if self.launcher_executable is None:
                raise ValueError("Native readiness is missing its executable")
            return {"type": "native", "executable": self.launcher_executable}
        return {"type": "container", "engine": self.engine, "image": self.image}

    @property
    def ready(self) -> bool:
        """Return the existing doctor's conservative environment decision."""

        return self.report.ready


def _reviewed_config_bytes(review: ProjectReviewResult) -> bytes:
    try:
        content = review.config_path.read_bytes()
    except OSError as error:
        raise DesktopReferenceReadinessError(
            f"Reviewed configuration is no longer readable: {error}"
        ) from error
    if hashlib.sha256(content).hexdigest() != review.config_sha256:
        raise DesktopReferenceReadinessError(
            "Project configuration changed after parameter review; review it again "
            "before checking the reference environment"
        )
    return content


def parse_reference_config_bytes(content: bytes) -> Mapping[str, Any]:
    """Parse and validate one exact in-memory reference configuration."""

    try:
        text = content.decode("utf-8")
        loaded = yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError) as error:
        raise DesktopReferenceReadinessError(
            f"Reviewed configuration is not readable YAML: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise DesktopReferenceReadinessError(
            "Reviewed configuration root must be a YAML mapping"
        )
    try:
        validate_schema(loaded)
        validate_reference_config(loaded)
    except ConfigurationError as error:
        raise DesktopReferenceReadinessError(
            f"Reviewed reference configuration is invalid: {error}"
        ) from error
    return loaded


def check_reference_environment(
    review: ProjectReviewResult,
) -> DesktopReferenceReadiness:
    """Inspect the exact reviewed reference runtime without modifying it."""

    if not isinstance(review, ProjectReviewResult):
        raise TypeError("review must be a ProjectReviewResult")
    if review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE:
        raise DesktopReferenceReadinessError(
            "Reference environment diagnostics require a Deformetrica reference review"
        )

    content = _reviewed_config_bytes(review)
    config = parse_reference_config_bytes(content)
    launcher = config["runtime"]["launcher"]
    workspace = review.config_path.resolve().parent
    identity = launcher_identity(launcher)
    launcher_type = identity["type"]
    if launcher_type == "container":
        engine = identity["engine"]
        image = identity["image"]
        report = run_doctor(workspace, engine=engine, image=image)
        distribution = None
        executable = None
    else:
        report = run_reference_doctor(workspace, launcher=identity)
        engine = launcher_type
        distribution = identity.get("distribution")
        executable = identity["executable"]
        image = (
            f"{distribution}:{executable}"
            if distribution is not None
            else executable
        )
    try:
        hash_after = sha256_file(review.config_path)
    except OSError as error:
        raise DesktopReferenceReadinessError(
            f"Reviewed configuration became unreadable during diagnostics: {error}"
        ) from error
    if hash_after != review.config_sha256:
        raise DesktopReferenceReadinessError(
            "Project configuration changed while the reference environment was checked; "
            "discarding the diagnostic result"
        )

    return DesktopReferenceReadiness(
        config_path=review.config_path.resolve(),
        config_sha256=review.config_sha256,
        workspace=workspace,
        engine=engine,
        image=image,
        report=report,
        launcher_type=launcher_type,
        launcher_distribution=distribution,
        launcher_executable=executable,
    )
