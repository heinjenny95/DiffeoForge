"""Shared strict JSON loading for review and approval evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from diffeoforge.config import ConfigurationError


def _unique_object(label: str):
    def convert(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConfigurationError(f"{label} contains duplicate JSON object key: {key}")
            result[key] = value
        return result

    return convert


def _reject_constant(label: str):
    def reject(value: str) -> None:
        raise ConfigurationError(f"{label} contains unsupported JSON constant: {value}")

    return reject


def load_strict_json_object(
    payload: bytes,
    path: Path,
    *,
    label: str,
) -> dict[str, Any]:
    """Load one strict UTF-8 JSON object with unique keys and finite numbers."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"{label} is not strict UTF-8: {path}") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object(label),
            parse_constant=_reject_constant(label),
        )
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            f"{label} is not one valid JSON document at line {error.lineno}, "
            f"column {error.colno}: {path}"
        ) from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} JSON root must be an object: {path}")
    return value
