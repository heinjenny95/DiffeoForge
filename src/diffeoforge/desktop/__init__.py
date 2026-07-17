"""Optional desktop application backed by the shared DiffeoForge core."""

from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    ProjectSetupResult,
    create_project,
)

__all__ = [
    "DesktopEngine",
    "ProjectSetupRequest",
    "ProjectSetupResult",
    "create_project",
]
