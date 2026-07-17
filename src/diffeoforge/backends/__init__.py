"""Numerical backend adapters."""

from diffeoforge.backends.deformetrica_reference import (
    BACKEND_CONTRACT_VERSION,
    BACKEND_ID,
    ENGINE_CONSTANTS,
    CommandSpec,
    build_command,
    ensure_launcher_available,
    generate_engine_files,
    generate_resume_optimization_file,
    render_engine_file_bytes,
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
    "generate_resume_optimization_file",
    "render_engine_file_bytes",
    "validate_reference_config",
]
