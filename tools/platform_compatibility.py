"""Bounded public-fixture CPU observations, not platform/release qualification.

Run against an installed wheel. Only compact numerical observations are suitable
for CI upload; full work directories stay on their temporary runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "public-platform-cpu-v1"
EXPECTED_PLATFORMS = frozenset({"Linux-x86_64", "Windows-AMD64", "Darwin-arm64"})
EXPECTED_FIXTURES = frozenset({"template.vtk", *(f"subject-{n:02}.vtk" for n in range(1, 6))})
RTOL = 1e-8
ATOL = 1e-10
BOUNDARY = (
    "Small public synthetic CPU compatibility checks only; not native installer, "
    "Deformetrica, GPU/MPS, biological, performance or production qualification."
)
STATE_SHAPES = {
    "template": (162, 3),
    "control_points": (9, 3),
    "momenta": (45, 3),
    "reconstructions": (5, 162, 3),
    "objective": (3,),
    "residuals": (5,),
}


def _check_source(source_commit: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if head != source_commit or dirty:
        raise ValueError("Observation requires the exact clean source commit")


def _package_hash() -> str:
    import diffeoforge

    root = Path(diffeoforge.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.suffix in {".py", ".json"}):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _write(path: Path, value: object) -> None:
    text = _json(value)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    with path.with_suffix(".sha256").open("x", encoding="ascii", newline="\n") as handle:
        handle.write(hashlib.sha256(text.encode()).hexdigest() + "\n")


def _read(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > 2_000_000:
        raise ValueError("Oversized observation")
    if hashlib.sha256(data).hexdigest() != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Observation SHA-256 differs")
    return json.loads(data)


def _numbers(value: object) -> None:
    if isinstance(value, list):
        if not value:
            raise ValueError("Empty numerical evidence")
        for child in value:
            _numbers(child)
    elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Non-finite or nonnumerical evidence")


def compare_states(first: dict, second: dict, *, rtol: float = RTOL, atol: float = ATOL) -> dict:
    import numpy as np

    if not first or set(first) != set(second):
        raise ValueError("Numerical state fields differ or are empty")
    errors = {}
    for key in sorted(first):
        _numbers(first[key])
        _numbers(second[key])
        left = np.asarray(first[key], dtype=np.float64)
        right = np.asarray(second[key], dtype=np.float64)
        if left.shape != right.shape:
            raise ValueError(f"Numerical shape differs: {key}")
        # Symmetric relative scale: neither operating system is ground truth.
        delta = np.abs(left - right)
        permitted = atol + rtol * np.maximum(np.abs(left), np.abs(right))
        if not np.all(delta <= permitted):
            raise ValueError(f"Numerical tolerance exceeded: {key}; max abs {delta.max()}")
        errors[key] = float(delta.max())
    return errors


def compare_observations(observations: list[dict]) -> dict:
    import numpy as np

    if len(observations) != len(EXPECTED_PLATFORMS):
        raise ValueError("Exactly three platform observations are required")
    by_platform = {item["platform"]: item for item in observations}
    if set(by_platform) != EXPECTED_PLATFORMS:
        raise ValueError("Missing, duplicate or unexpected platform")
    reference = by_platform["Linux-x86_64"]
    for item in observations:
        for key in (
            "protocol",
            "source_commit",
            "fixture_hashes",
            "engine",
            "versions",
            "boundary",
            "package_sha256",
        ):
            if item[key] != reference[key]:
                raise ValueError(f"Observation provenance differs: {key}")
        if item["protocol"] != PROTOCOL or item["boundary"] != BOUNDARY:
            raise ValueError("Unexpected observation protocol/boundary")
        if not re.fullmatch(r"[0-9a-f]{40}", item["source_commit"]):
            raise ValueError("Invalid source commit")
        if set(item["fixture_hashes"]) != EXPECTED_FIXTURES or any(
            not re.fullmatch(r"[0-9a-f]{64}", value) for value in item["fixture_hashes"].values()
        ):
            raise ValueError("Invalid public fixture provenance")
        if not re.fullmatch(r"[0-9a-f]{64}", item["package_sha256"]):
            raise ValueError("Invalid installed package hash")
        if set(item["checks"]) != {
            "worker_completed",
            "worker_cancelled",
            "result_reopened",
            "continuation_verified",
            "same_platform_resume",
            "dense_blockwise",
            "fixture_unchanged",
        } or any(value is not True for value in item["checks"].values()):
            raise ValueError("A required local check is absent or failed")
        if set(item["states"]) != {"dense", "blockwise", "continued"}:
            raise ValueError("Required numerical scenarios differ")
        for state in item["states"].values():
            if set(state) != set(STATE_SHAPES):
                raise ValueError("Required numerical fields differ")
            for key, shape in STATE_SHAPES.items():
                _numbers(state[key])
                if np.asarray(state[key]).shape != shape:
                    raise ValueError(f"Public fixture state shape differs: {key}")
    comparisons = {}
    # Compare all three pairs, not only two pairs against an arbitrary baseline.
    names = sorted(by_platform)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            comparisons[f"{first} vs {second}"] = {
                scenario: compare_states(
                    by_platform[first]["states"][scenario],
                    by_platform[second]["states"][scenario],
                )
                for scenario in ("dense", "blockwise", "continued")
            }
    return {
        "protocol": PROTOCOL,
        "status": "pass",
        "source_commit": reference["source_commit"],
        "rtol": RTOL,
        "atol": ATOL,
        "comparisons_max_abs": comparisons,
        "boundary": BOUNDARY,
    }


def _snapshot(run: Path) -> tuple[dict, dict]:
    from diffeoforge.desktop.result_review import review_modern_result
    from diffeoforge.mesh import read_vtk_polydata
    from diffeoforge.modern_bundle import verify_modern_atlas_bundle
    from diffeoforge.modern_workflow import verify_modern_workflow

    workflow = verify_modern_workflow(run)
    root = run / workflow["result_bundle"]["path"]
    bundle = verify_modern_atlas_bundle(root)
    review = review_modern_result(run)
    if review.run_directory != run.resolve():
        raise ValueError("Result reopen targeted another run")

    def vectors(relative: str) -> list:
        with (root / relative).open(encoding="utf-8", newline="") as handle:
            return [[float(row[key]) for key in ("x", "y", "z")] for row in csv.DictReader(handle)]

    optimizer = bundle["optimizer"]
    state = {
        "template": read_vtk_polydata(root / bundle["template"]["path"]).vertices,
        "control_points": vectors(bundle["parameters"]["control_points_path"]),
        "momenta": vectors(bundle["parameters"]["momenta_path"]),
        "reconstructions": [
            read_vtk_polydata(root / subject["reconstruction_path"]).vertices
            for subject in bundle["subjects"]
        ],
        "objective": [
            optimizer[f"final_{key}"] for key in ("objective", "attachment", "regularity")
        ],
        "residuals": [subject["residual"] for subject in bundle["subjects"]],
    }
    # Canonical JSON lists, not platform-specific ndarray serialization.
    state = json.loads(_json(state))
    return state, bundle


def observe(output: Path, source_commit: str) -> Path:
    import yaml

    from diffeoforge.desktop.worker_controller import DesktopWorkerController
    from diffeoforge.desktop.worker_protocol import build_worker_request
    from diffeoforge.mesh import sha256_file
    from diffeoforge.modern_continuation import (
        CONFIG_NAME,
        create_modern_continuation,
        verify_modern_continuation_run,
    )
    from diffeoforge.modern_workflow import initialize_modern_workflow, run_modern_workflow

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("An exact source commit is required")
    _check_source(source_commit)
    # Never accept a user's biological mesh directory as this test's input.
    fixture = ROOT / "examples" / "synthetic" / "meshes"
    hashes = {p.name: sha256_file(p) for p in sorted(fixture.glob("*.vtk"))}
    if set(hashes) != EXPECTED_FIXTURES:
        raise ValueError("Expected the six checked-in CC0 synthetic surfaces")
    output = output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    work = output / "Synthetic project with spaces Ä"
    work.mkdir()
    meshes = work / "meshes"
    shutil.copytree(fixture, meshes)

    def config(name: str, cycles: int, mode: str = "dense") -> Path:
        path = initialize_modern_workflow(
            meshes,
            units="unitless",
            config_path=work / f"{name}.yaml",
            template=meshes / "template.vtk",
            subject_pattern="subject-*.vtk",
            attachment_kernel_width=0.45,
            deformation_kernel_width=0.6,
            noise_variance=0.01,
            max_cycles=cycles,
            threads=1,
            pairwise_mode=mode,
            query_tile_size=64 if mode == "blockwise" else None,
            source_tile_size=64 if mode == "blockwise" else None,
        )
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        value["model"]["deformation"]["timepoints"] = 5
        value["optimization"]["direction_update"] = "lbfgs"
        value["optimization"]["gradient_tolerance"] = 0.0
        value["optimization"]["checkpoint_interval_cycles"] = 1
        value["analysis"]["deformation_components"] = 1
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")
        return path

    full_config = config("dense", 2)
    request = build_worker_request(
        full_config, request_id="platform-complete", destination=work / "full"
    )
    controller = DesktopWorkerController(request, cwd=work)
    result = controller.run()
    if not result.completed or result.exit_code != 0:
        raise ValueError("Synthetic worker did not complete")
    dense, bundle = _snapshot(request.destination)
    print("Verified public synthetic worker run and result reopen", flush=True)

    parent = run_modern_workflow(config("parent", 1), destination=work / "parent")
    plan = create_modern_continuation(parent, work / "continuation", max_cycles=1, threads=1)
    successor = run_modern_workflow(plan / CONFIG_NAME, destination=work / "continued")
    continuation = verify_modern_continuation_run(plan, successor)
    if continuation["initial_objective_matches"] is not True:
        raise ValueError("Continuation initial state differs")
    continued, _ = _snapshot(successor)
    compare_states(dense, continued, rtol=1e-12, atol=1e-12)

    block_run = run_modern_workflow(
        config("blockwise", 2, "blockwise"), destination=work / "blockwise"
    )
    blockwise, _ = _snapshot(block_run)
    compare_states(dense, blockwise)
    print("Verified continuation and dense/blockwise numerical agreement", flush=True)

    cancelled_request = build_worker_request(
        config("cancel", 10),
        request_id="platform-cancel",
        destination=work / "cancelled",
    )
    cancelled_controller = DesktopWorkerController(cancelled_request, cwd=work)

    def cancel_after_start(event) -> None:
        if event.kind == "started" and not cancelled_controller.request_cancel():
            raise ValueError("Worker cancellation was not accepted")

    cancelled = cancelled_controller.run(event_callback=cancel_after_start)
    if not cancelled.cancelled or cancelled_request.destination.exists():
        raise ValueError("Cancellation published a result or did not terminate")
    if tuple(work.glob(".cancelled.tmp-*")):
        raise ValueError("Cooperative cancellation left private run state")
    if hashes != {p.name: sha256_file(p) for p in sorted(fixture.glob("*.vtk"))}:
        raise ValueError("Public source fixture was modified")

    observation = {
        "protocol": PROTOCOL,
        "source_commit": source_commit,
        "platform": f"{platform.system()}-{platform.machine()}",
        "fixture_hashes": hashes,
        "engine": bundle["engine"]["implementation_version"],
        "package_sha256": _package_hash(),
        "versions": {
            name: importlib.metadata.version(name).split("+")[0] for name in ("torch", "numpy")
        },
        "python": platform.python_version(),
        "boundary": BOUNDARY,
        "checks": dict.fromkeys(
            (
                "worker_completed",
                "worker_cancelled",
                "result_reopened",
                "continuation_verified",
                "same_platform_resume",
                "dense_blockwise",
                "fixture_unchanged",
            ),
            True,
        ),
        "states": {"dense": dense, "continued": continued, "blockwise": blockwise},
    }
    path = output / "observation.json"
    _write(path, observation)
    print(f"Verified observation: {path}", flush=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--output", required=True, type=Path)
    observe_parser.add_argument("--source-commit", required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--input", required=True, type=Path)
    compare_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "observe":
        observe(args.output, args.source_commit)
    else:
        observations = [_read(p) for p in sorted(args.input.glob("*/observation.json"))]
        comparison = compare_observations(observations)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _write(args.output, comparison)
        print("All three platform pairs passed the predeclared synthetic CPU tolerances")
    return 0


if __name__ == "__main__":
    sys.exit(main())
