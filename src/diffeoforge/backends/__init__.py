"""Numerical backend adapters."""

from diffeoforge.backends.deformetrica_reference import (
    BACKEND_CONTRACT_VERSION,
    BACKEND_ID,
    ENGINE_CONSTANTS,
    CommandSpec,
    build_command,
    ensure_launcher_available,
    generate_engine_files,
    validate_reference_config,
)

__all__ = [
    "BACKEND_CONTRACT_VERSION",
    "BACKEND_ID",
    "ENGINE_CONSTANTS",
    "CommandSpec",
    "build_command",
    "ensure_launcher_available",
    "generate_engine_files",
    "validate_reference_config",
]
