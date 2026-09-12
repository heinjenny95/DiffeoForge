"""Transparent, scale-aware starter profiles for the Deformetrica route."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceParameterProfile:
    """One explicitly named, non-validated starter profile."""

    key: str
    label: str
    attachment_ratio: float
    deformation_ratio: float
    control_point_spacing_ratio: float
    noise_ratio: float
    max_iterations: int
    initial_step_size: float = 0.01
    convergence_tolerance: float = 0.0001


REFERENCE_PARAMETER_PROFILES: Mapping[str, ReferenceParameterProfile] = {
    "recommended": ReferenceParameterProfile(
        "recommended", "Recommended starting values", 0.10, 0.15, 0.15, 0.025, 100
    ),
    "pilot": ReferenceParameterProfile(
        "pilot", "Fast pilot", 0.10, 0.15, 0.15, 0.025, 20
    ),
    "high_detail": ReferenceParameterProfile(
        "high_detail", "High detail", 0.05, 0.10, 0.10, 0.0125, 200
    ),
}


def reference_parameter_profile(key: str) -> ReferenceParameterProfile:
    """Return a supported profile without silently accepting unknown names."""

    try:
        return REFERENCE_PARAMETER_PROFILES[key]
    except KeyError as error:
        raise ValueError(f"Unsupported Deformetrica parameter profile: {key!r}") from error

