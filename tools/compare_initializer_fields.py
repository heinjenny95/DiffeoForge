"""Read-only equality gate for separately executed fixed-basis initializers.

This compares supplied execution evidence; it does not launch a computation,
establish anatomical suitability, or qualify a downstream joint atlas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

PROTOCOL = "fixed-basis-initializer-equality-v1"
ARRAYS = ("template", "controls", "momenta")


def _digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _packet(path):
    path = Path(path).resolve()
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol") != PROTOCOL:
        raise ValueError("Unsupported initializer evidence protocol")
    if not isinstance(record.get("settings"), dict) or not record["settings"]:
        raise ValueError("Missing effective initializer settings")
    settings = record["settings"]
    tolerance = settings.get("convergence_tolerance")
    if (
        settings.get("freeze_template") is not True
        or settings.get("freeze_control_points") is not True
        or settings.get("precision") not in ("float32", "float64")
        or type(settings.get("timepoints")) is not int
        or settings["timepoints"] < 2
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or tolerance <= 0
    ):
        raise ValueError("Missing fixed-basis precision, integration, or stopping contract")
    basis = record.get("basis_identity", {})
    if not all(_digest(basis.get(key)) for key in ("template_sha256", "controls_sha256")):
        raise ValueError("Missing original template connectivity and control basis identities")
    identities = record.get("subjects", [])
    if not identities or any(
        not isinstance(row.get("id"), str) or not row["id"] or not _digest(row.get("sha256"))
        for row in identities
    ):
        raise ValueError("Missing ordered subject identities")
    if len({row["id"] for row in identities}) != len(identities):
        raise ValueError("Duplicate subject identity")
    pilots = record.get("pilot_indices")
    if (
        not isinstance(pilots, list)
        or any(type(index) is not int or not 0 <= index < len(identities) for index in pilots)
        or len(pilots) != len(set(pilots))
    ):
        raise ValueError("Invalid retained pilot rows")
    arrays = {}
    for name in ARRAYS:
        item = record["arrays"][name]
        relative = Path(item["path"])
        target = (path.parent / relative).resolve()
        if relative.is_absolute() or path.parent not in target.parents:
            raise ValueError("Evidence array must stay within its packet directory")
        if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Evidence array checksum mismatch: " + name)
        values = np.load(target, allow_pickle=False)
        if values.dtype.kind != "f" or not np.isfinite(values).all():
            raise ValueError("Initializer arrays require finite floating point values")
        arrays[name] = values
    template, controls, momenta = [arrays[name] for name in ARRAYS]
    if (
        template.ndim != 2
        or controls.ndim != 2
        or momenta.ndim != 3
        or not len(template)
        or not len(controls)
        or template.shape[1] not in (2, 3)
        or controls.shape[1] != template.shape[1]
        or momenta.shape != (len(identities), len(controls), template.shape[1])
    ):
        raise ValueError("Initializer array shape differs from its ordered cohort and basis")
    completed = record.get("completed", [])
    indices = [row.get("index") for row in completed]
    expected = set(range(len(identities))) - set(pilots)
    if (
        any(type(index) is not int for index in indices)
        or len(indices) != len(set(indices))
        or set(indices) != expected
    ):
        raise ValueError("Every nonpilot subject requires exactly one completion receipt")
    maximum = record["settings"].get("max_iterations")
    if type(maximum) is not int or maximum < 1:
        raise ValueError("Missing recorded native iteration allowance")
    for row in completed:
        iterations = row.get("iterations")
        if (
            type(iterations) is not int
            or not 0 <= iterations <= maximum
            or row.get("stop") not in ("native_tolerance", "iteration_limit")
            or (row["stop"] == "iteration_limit" and iterations != maximum)
        ):
            raise ValueError("Invalid native completion or iteration-cap evidence")
    seconds = record.get("wall_seconds")
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (float, int))
        or not math.isfinite(seconds)
        or seconds <= 0
    ):
        raise ValueError("Require a finite measured wall time")
    return record, arrays


def compare(reference_path, candidate_path):
    reference, left = _packet(reference_path)
    candidate, right = _packet(candidate_path)
    checks = {
        "original_basis_identities_identical": reference["basis_identity"]
        == candidate["basis_identity"],
        "ordered_subjects_identical": reference["subjects"] == candidate["subjects"],
        "recorded_settings_identical": reference["settings"] == candidate["settings"],
        "retained_pilot_indices_identical": reference["pilot_indices"]
        == candidate["pilot_indices"],
        "native_stops_and_iterations_identical": sorted(
            reference["completed"], key=lambda row: row["index"]
        )
        == sorted(candidate["completed"], key=lambda row: row["index"]),
    }
    for name in ARRAYS:
        checks[name + "_identical"] = (
            left[name].dtype == right[name].dtype
            and left[name].shape == right[name].shape
            and left[name].tobytes(order="C") == right[name].tobytes(order="C")
        )
    passed = all(checks.values())
    return {
        "protocol": PROTOCOL,
        "passed": passed,
        "checks": checks,
        "subjects": len(reference["subjects"]),
        "controls": len(left["controls"]),
        "retained_pilots": len(reference["pilot_indices"]),
        "capped_subjects": sum(row["stop"] == "iteration_limit" for row in reference["completed"]),
        "reference_wall_seconds": reference["wall_seconds"],
        "candidate_wall_seconds": candidate["wall_seconds"],
        "observed_wall_time_ratio": reference["wall_seconds"] / candidate["wall_seconds"]
        if passed
        else None,
        "scope": (
            "Equality of the supplied initializer evidence; no anatomical or joint-atlas approval"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(args.reference, args.candidate)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
