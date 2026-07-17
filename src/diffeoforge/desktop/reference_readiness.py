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
from diffeoforge.diagnostics import DoctorReport, run_doctor


class DesktopReferenceReadinessError(RuntimeError):
    """Raised when reference readiness cannot remain bound to reviewed bytes."""


@dataclass(frozen=True)
class DesktopReferenceReadiness:
    """Exact reviewed container settings plus their observational doctor report."""

    config_path: Path
    config_sha256: str
    workspace: Path
    engine: str
    image: str
    report: DoctorReport

    def __post_init__(self) -> None:
        if Path(self.report.workspace).resolve() != self.workspace.resolve():
            raise ValueError("Reference doctor report targets a different workspace")
        if self.report.engine != self.engine or self.report.image != self.image:
            raise ValueError("Reference doctor report targets different launcher settings")

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
    """Inspect the exact reviewed container environment without modifying it."""

    if not isinstance(review, ProjectReviewResult):
        raise TypeError("review must be a ProjectReviewResult")
    if review.engine is not DesktopEngine.DEFORMETRICA_REFERENCE:
        raise DesktopReferenceReadinessError(
            "Reference environment diagnostics require a Deformetrica reference review"
        )

    content = _reviewed_config_bytes(review)
    config = parse_reference_config_bytes(content)
    launcher = config["runtime"]["launcher"]
    if launcher["type"] != "container":
        raise DesktopReferenceReadinessError(
            "Desktop reference diagnostics currently support the configured container "
            "launcher only"
        )

    workspace = review.config_path.resolve().parent
    engine = str(launcher["engine"])
    image = str(launcher["image"])
    report = run_doctor(workspace, engine=engine, image=image)
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
    )
