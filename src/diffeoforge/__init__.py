"""Public package metadata for DiffeoForge."""

import re

__version__ = "0.0.0.dev90"


def display_version(version: str = __version__) -> str:
    """Human build label; keep historical dev0 and release versions unchanged."""
    match = re.fullmatch(r"0\.0\.0\.dev([1-9][0-9]*)", version)
    return f"v{match[1]} (Private Alpha)" if match else version
