"""Switch a completed joint atlas to morphospace stopping at its accepted checkpoint."""

import hashlib
import json
import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_stop import (
    MORPHOSPACE_STABILITY,
    MORPHOSPACE_STABILITY_UNLIMITED,
    OPTIMIZER_CONVERGENCE,
    atlas_stop_available,
    stop_policy,
)
from diffeoforge.reference_morphospace_native import LIVE_PREFIX, manifest_subject_labels

COMPLETED_STAGE_REASONS = (
    "native_tolerance",
    "iteration_limit",
    "morphospace_stable",
    "line_search_exhausted",
    "optimizer_callback",
)
ORIGIN_PATH = Path("config/atlas-continuation-origin.json")
_DEFERRED_CAP_LOG = (
    "final mesh export deferred: native stop maximum_iterations; checkpoint retained"
)


@dataclass(frozen=True)
class QualityContinuation:
    mode: str
    checkpoint_iteration: int
    additional_iterations: int | None
    source_reason: str
    source_mode: str
    source_maximum_iterations: int | None
    source_tolerance: float
    checkpoint_sha256: str
    source_log_sha256: str

    def __post_init__(self):
        if (
            self.mode not in (MORPHOSPACE_STABILITY, MORPHOSPACE_STABILITY_UNLIMITED)
            or type(self.checkpoint_iteration) is not int
            or self.checkpoint_iteration < 1
            or (self.additional_iterations is not None) != (self.mode == MORPHOSPACE_STABILITY)
            or (
                self.additional_iterations is not None
                and (type(self.additional_iterations) is not int or self.additional_iterations < 1)
            )
            or self.source_reason not in COMPLETED_STAGE_REASONS
            or self.source_mode
            not in (OPTIMIZER_CONVERGENCE, MORPHOSPACE_STABILITY, "iteration_target")
            or (
                self.source_maximum_iterations is not None
                and (
                    type(self.source_maximum_iterations) is not int
                    or self.source_maximum_iterations < self.checkpoint_iteration
                )
            )
            or (
                self.source_maximum_iterations is None and self.source_mode != MORPHOSPACE_STABILITY
            )
            or type(self.source_tolerance) not in (int, float)
            or not isfinite(self.source_tolerance)
            or self.source_tolerance <= 0
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in (self.checkpoint_sha256, self.source_log_sha256)
            )
        ):
            raise ConfigurationError("Invalid morphospace continuation settings.")

    @property
    def maximum_iterations(self):
        if self.additional_iterations is None:
            return None
        return self.checkpoint_iteration + self.additional_iterations

    @property
    def policy(self):
        return stop_policy(
            MORPHOSPACE_STABILITY, unlimited_iterations=self.maximum_iterations is None
        )


def read_continuation_origin(run, manifest):
    """Read the protected configuration change that still governs this atlas segment."""
    from diffeoforge.reference_convergence_context import validate_context
    from diffeoforge.strict_json import load_strict_json_object

    record = next(
        (
            item
            for item in manifest["protected_artifacts"]
            if item["path"] == ORIGIN_PATH.as_posix()
        ),
        None,
    )
    if record is None:
        return None
    path = run / ORIGIN_PATH
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ConfigurationError("The protected atlas continuation origin changed.")
    origin = load_strict_json_object(content, path, label="Atlas continuation origin")
    config = manifest["effective_config"]
    tolerance = config["optimization"]["convergence_tolerance"]
    if (
        origin.get("version") != 1
        or origin.get("policy") != config["project"].get("atlas_stop")
        or origin.get("convergence_tolerance") != tolerance
    ):
        raise ConfigurationError(
            "The effective atlas settings differ from their continuation origin."
        )
    if origin.get("objective_reference") is not None:
        validate_context(origin["objective_reference"], tolerance)
    return origin


def continuation_origin_reference(source, manifest, *, provenance, verified_stability=None):
    """Keep an observed objective origin available across changes of stopping rule."""
    from diffeoforge.reference_morphospace_stopping import optimizer_reference_from_history

    origin = read_continuation_origin(source, manifest)
    if origin and origin.get("objective_reference") is not None:
        return origin["objective_reference"]
    if provenance and provenance.get("convergence_reference") is not None:
        return provenance["convergence_reference"]
    rows = verified_stability and verified_stability["observations"]
    if rows and rows[0]["checkpoint"] is not None:
        return optimizer_reference_from_history(verified_stability, manifest["effective_config"])
    return None


def completed_atlas_checkpoint(source, manifest, checkpoint, digest, *, verified_stability=None):
    """Resolve the exact accepted iteration and supported reason for the joint stop."""
    from diffeoforge.reference_final_export_recovery import checkpoint_iteration
    from diffeoforge.reference_morphospace_stopping import read_morphospace_stability
    from diffeoforge.runs import ITERATION_RE, completed_gradient_ascent_history

    config = manifest["effective_config"]
    policy = config["project"].get("atlas_stop")
    labels = manifest_subject_labels(manifest)
    schedule = config["output"].get("checkpoint_mode", "native_full_outputs")
    successor = {
        **config,
        "output": {**config["output"], "checkpoint_mode": "compact_final_export"},
    }
    if (
        schedule
        not in {"native_full_outputs", "compact_convergence_export", "compact_final_export"}
        or not atlas_stop_available(successor)
        or len(set(labels)) != len(labels)
        or len(labels) < 2
    ):
        raise ConfigurationError("Choose a completed full-cohort atlas with a native checkpoint.")

    log = source / "logs/deformetrica.log"
    log_digest = sha256_file(log)
    maximum, text, stop = completed_gradient_ascent_history(source)
    iteration = checkpoint_iteration(checkpoint)
    if policy is not None:
        report = verified_stability or read_morphospace_stability(source)
        terminal = report and report["terminal"]
        if (
            not terminal
            or terminal["export"] != "complete"
            or terminal["reason"] not in COMPLETED_STAGE_REASONS
            or terminal["iteration"] != iteration
            or terminal["checkpoint_sha256"] != digest
        ):
            raise ConfigurationError(
                "A verified terminal joint checkpoint and final export are required."
            )
        reason = terminal["reason"]
        if reason in ("line_search_exhausted", "optimizer_callback"):
            # The native callback has no dedicated stop message. Its accepted state is
            # logged by the atlas adapter and sealed with the reason after final export.
            line = next((line for line in reversed(text.splitlines()) if LIVE_PREFIX in line), "")
            try:
                row = json.loads(line.partition(LIVE_PREFIX)[2])
            except ValueError:
                row = None
            markers = list(ITERATION_RE.finditer(text))
            last_print = int(markers[-1].group(1)) if markers else -1
            print_interval = config["optimization"]["print_every_n_iterations"]
            failed_search = stop.signal == "line_search_exhausted"
            if (
                not report["observations"]
                or row != report["observations"][-1]
                or not row.get("checkpoint")
                or row["iteration"] != iteration
                or not max(0, iteration - print_interval + 1) <= last_print <= iteration
                or failed_search != (reason == "line_search_exhausted")
                or stop.signal in ("tolerance_threshold", "pilot_review_request")
            ):
                raise ConfigurationError(
                    "The stop log does not verify the final accepted atlas state."
                )
    else:
        # Earlier atlases recorded the native stop and checkpoint but no joint stability report.
        markers = list(ITERATION_RE.finditer(text))
        last = text[markers[-1].end() :].casefold() if markers else ""
        previous = int(markers[-1].group(1)) if markers else -1
        print_interval = config["optimization"]["print_every_n_iterations"]
        next_print = (previous // print_interval + 1) * print_interval
        if (
            stop.signal == "tolerance_threshold"
            and markers
            and "tolerance threshold met. stopping the optimization process." in last
            and "number of line search loops exceeded" not in last
            and ">> stop: pilot review request" not in last
            and previous < iteration <= min(maximum, next_print)
        ):
            if (
                schedule != "compact_final_export"
                and iteration < min(maximum, next_print)
                and iteration % config["optimization"]["save_every_n_iterations"] == 0
                and "diffeoforge final mesh export completed" not in last
            ):
                raise ConfigurationError(
                    "The last periodic checkpoint cannot be distinguished "
                    "from the terminal native tolerance state."
                )
            reason = "native_tolerance"
        elif iteration == maximum and (
            stop.signal == "maximum_iterations"
            or (
                stop.signal == "unknown"
                and schedule == "compact_convergence_export"
                and _DEFERRED_CAP_LOG in last
            )
        ):
            reason = "iteration_limit"
        else:
            raise ConfigurationError(
                "The saved log and checkpoint must confirm a tolerance or iteration-limit stop."
            )
    if (
        (reason == "iteration_limit" and iteration != maximum)
        or sha256_file(log) != log_digest
        or sha256_file(checkpoint) != digest
    ):
        raise ConfigurationError(
            "The terminal optimizer evidence differs from the saved checkpoint."
        )
    return iteration, reason, log_digest


def quality_continuation_plan(
    source, manifest, checkpoint, digest, mode, *, quality_iterations=300, verified_stability=None
):
    iteration, reason, log_digest = completed_atlas_checkpoint(
        source,
        manifest,
        checkpoint,
        digest,
        verified_stability=verified_stability,
    )
    from diffeoforge.reference_atlas_stop import atlas_iteration_limit

    config = manifest["effective_config"]
    budget = None if mode == MORPHOSPACE_STABILITY_UNLIMITED else quality_iterations
    return QualityContinuation(
        mode,
        iteration,
        budget,
        reason,
        config["project"].get("atlas_stop", {}).get("mode", OPTIMIZER_CONVERGENCE),
        atlas_iteration_limit(config),
        config["optimization"]["convergence_tolerance"],
        digest,
        log_digest,
    )
