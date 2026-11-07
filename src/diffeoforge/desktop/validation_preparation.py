"""Non-UI preparation of a frozen validation design; never starts an engine."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_validation_study import (
    create_reference_validation_study,
    load_reference_validation_study,
)
from diffeoforge.result_report import collect_run_report


def check_cancelled(cancelled: Event) -> None:
    if cancelled.is_set():
        raise InterruptedError("Preparation cancelled. No validation engine was started.")


def prepare_validation_from_result(
    run_directory: Path,
    preferred_config: Path | None,
    cancelled: Event,
    phase: Callable[[str], None],
) -> Path:
    phase("Verifying the source atlas and calibrated configuration…")
    check_cancelled(cancelled)
    report = collect_run_report(run_directory)
    expected_hash = str(report.manifest["source_config"]["sha256"])
    candidates = [
        preferred_config,
        Path(str(report.manifest["source_config"]["path"])),
        run_directory / "config" / "source-config.yaml",
    ]
    config_path = None
    for candidate in candidates:
        check_cancelled(cancelled)
        if candidate is None or not candidate.is_file():
            continue
        if sha256_file(candidate) != expected_hash:
            continue
        config = load_config(candidate)
        result = (
            config.get("project", {})
            .get("parameter_provenance", {})
            .get("recommendation", {})
            .get("calibration_result", {})
        )
        if result.get("status") == "completed":
            config_path = candidate.resolve()
            break
    if config_path is None:
        raise ValueError(
            "The hash-matching pilot-calibrated atlas configuration is missing. "
            "Restore it before opening Validation Lab."
        )
    validation_root = config_path.parent
    if config_path.is_relative_to(run_directory):
        validation_root = run_directory.parent.parent
    root = validation_root / "diffeoforge-validation-lab"
    phase("Verifying the frozen study, inputs and existing evidence…")
    check_cancelled(cancelled)
    if root.exists():
        # Integrity failures remain visible; never hide them by silently creating a new study.
        existing = load_reference_validation_study(root)
        if existing.plan.source_config_sha256 != expected_hash:
            root = validation_root / f"diffeoforge-validation-lab-{expected_hash[:10]}"
    check_cancelled(cancelled)
    if not root.exists():
        phase("Freezing the validation design and protected input copies…")
        create_reference_validation_study(config_path, root)
    # A cancelled atomic preparation may leave a valid reusable study, never a launched run.
    check_cancelled(cancelled)
    return root
