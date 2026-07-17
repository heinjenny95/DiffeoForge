"""Bind a desktop worker launch to the exact reviewed configuration bytes."""

from __future__ import annotations

from dataclasses import dataclass

from diffeoforge.desktop.project_review import ProjectReviewResult
from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerRequest,
    build_worker_request,
    sha256_file,
)
from diffeoforge.private_runs import PrivateRunDiscovery, discover_private_runs


class DesktopReviewedRunError(RuntimeError):
    """Raised when a GUI launch no longer matches its completed review."""


@dataclass(frozen=True)
class DesktopReviewedRunReadiness:
    """Exact reviewed request plus observational destination safety state."""

    request: DesktopWorkerRequest
    discovery: PrivateRunDiscovery

    def __post_init__(self) -> None:
        if self.request.destination.resolve() != self.discovery.destination.resolve():
            raise ValueError("Reviewed request and private-run discovery target different paths")

    @property
    def ready_for_worker(self) -> bool:
        return self.discovery.ready_for_new_run


def build_reviewed_worker_request(
    review: ProjectReviewResult,
    *,
    request_id: str,
) -> DesktopWorkerRequest:
    """Create one Modern request only when the reviewed config bytes are unchanged."""

    if not isinstance(review, ProjectReviewResult):
        raise TypeError("review must be a ProjectReviewResult")
    if review.engine is not DesktopEngine.MODERN_CPU:
        raise DesktopReviewedRunError(
            "Desktop worker launch is currently available only for Modern CPU projects"
        )
    try:
        observed_hash = sha256_file(review.config_path)
    except OSError as error:
        raise DesktopReviewedRunError(
            f"Reviewed configuration is no longer readable: {error}"
        ) from error
    if observed_hash != review.config_sha256:
        raise DesktopReviewedRunError(
            "Project configuration changed after parameter review; review it again before launch"
        )
    try:
        request = build_worker_request(review.config_path, request_id=request_id)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise DesktopReviewedRunError(f"Reviewed Modern run cannot be launched: {error}") from error
    if request.expected_config_sha256 != review.config_sha256:
        raise DesktopReviewedRunError(
            "Project configuration changed while the reviewed launch was being prepared"
        )
    return request


def check_reviewed_run_readiness(
    review: ProjectReviewResult,
    *,
    request_id: str,
) -> DesktopReviewedRunReadiness:
    """Bind reviewed bytes and inspect their exact destination without mutation."""

    request = build_reviewed_worker_request(review, request_id=request_id)
    discovery = discover_private_runs(request.destination)
    return DesktopReviewedRunReadiness(request=request, discovery=discovery)
