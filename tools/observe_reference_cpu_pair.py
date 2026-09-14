"""Bounded, public-only AUTO/COMPATIBLE full-atlas diagnostic; no product defaults."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from probe_reference_cpu import checked_meshes

from diffeoforge.backends import build_command
from diffeoforge.reference import compare_reference_run, load_reference_manifest
from diffeoforge.runs import parse_convergence, prepare_run, verify_prepared_run

PROTOCOL = "public-reference-cpu-full-pair-v1"
IMAGE = "diffeoforge-deformetrica:4.3.0-cpu"
ORDER = (("AUTO", 1), ("COMPATIBLE", 1), ("COMPATIBLE", 2), ("AUTO", 2))
PUBLIC_CONFIG = "examples/minimal-atlas-container.yaml"
PUBLIC_REFERENCE = "reference/synthetic-v1/reference-manifest.json"
FIXED_FILES = {
    PUBLIC_CONFIG: "56eca7c12b9ecb67c147cc3ce60528ae78fec6456e6c5aa3d97beb7348c179f6",
    PUBLIC_REFERENCE: "92a42df282cbf9564e8995bd8380735e9f2063a48686530c3b2ab8350ab3511a",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    if path.exists() or path.with_suffix(".sha256").exists():
        raise FileExistsError("Evidence report or checksum already exists")
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    with path.with_suffix(".sha256").open("x", encoding="ascii", newline="\n") as stream:
        stream.write(hashlib.sha256(payload).hexdigest() + "\n")


def checked_reference(repo):
    checked_meshes(repo)
    for name, expected in FIXED_FILES.items():
        if sha(repo / name) != expected:
            raise ValueError("Only the frozen public configuration/reference is accepted")
    root = repo / "reference/synthetic-v1"
    manifest = load_reference_manifest(root)
    for item in manifest["artifacts"]:
        if sha(root / item["fixture_path"]) != item["sha256"]:
            raise ValueError("Frozen reference artifact changed")
    return manifest


def paired_command(command, mode, name):
    if mode not in {"AUTO", "COMPATIBLE"}:
        raise ValueError("Unsupported diagnostic mode")
    if command.argv[:2] != ("docker", "run") or IMAGE not in command.argv:
        raise ValueError("Only the frozen Docker launcher is accepted")
    if not name.startswith("df-cpu-pair-") or not name.replace("-", "").isalnum():
        raise ValueError("Invalid task-scoped container name")
    # Keep every generated command argument and isolation flag. Only the explicit
    # per-container diagnostic mode and a unique cleanup name are added.
    return [*command.argv[:2], "--name", name, "--env", f"MKL_CBWR={mode}", *command.argv[2:]]


def run_container(argv, log, name):
    with log.open("xb") as stream:
        try:
            result = subprocess.run(
                argv, stdout=stream, stderr=subprocess.STDOUT, timeout=720, check=False
            )
        except BaseException:
            # A killed Docker client can leave its container running. Remove only
            # this uniquely named container created for the current diagnostic.
            subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False
            )
            raise
    if result.returncode:
        raise RuntimeError(f"Diagnostic container returned {result.returncode}; see {log.name}")


def summarize(records):
    if [(r["mode"], r["repeat"]) for r in records] != list(ORDER):
        raise ValueError("All four predeclared observations are required in order")
    if any(r["engine_sha256"] != records[0]["engine_sha256"] for r in records):
        raise ValueError("Generated model/data/optimization XML differs between runs")
    repeated = {}
    for mode in ("AUTO", "COMPATIBLE"):
        first, second = [r for r in records if r["mode"] == mode]
        repeated[mode] = first["artifact_sha256"] == second["artifact_sha256"]
    return {
        "diagnostic_complete": True,
        "mode_repeatability": repeated,
        "compatible_reference_pass": all(
            r["comparison"]["status"] == "passed" for r in records if r["mode"] == "COMPATIBLE"
        ),
        "auto_reference_pass": all(
            r["comparison"]["status"] == "passed" for r in records if r["mode"] == "AUTO"
        ),
    }


def observe(repo, output):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("This diagnostic requires native Linux x86_64 Docker execution")
    if output.exists():
        raise FileExistsError("Diagnostic evidence is never overwritten")
    reference = checked_reference(repo)
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], text=True))[0]
    forbidden = {"MKL_CBWR", "MKL_DEBUG_CPU_TYPE", "MKL_ENABLE_INSTRUCTIONS", "MKL_NUM_THREADS"}
    if any(entry.split("=", 1)[0] in forbidden for entry in image["Config"].get("Env", [])):
        raise ValueError("Unexpected numerical override in frozen image")
    cpu = Path("/proc/cpuinfo").read_text()
    model = next(
        line.split(":", 1)[1].strip() for line in cpu.splitlines() if line.startswith("model name")
    )
    vendor = next(
        line.split(":", 1)[1].strip() for line in cpu.splitlines() if line.startswith("vendor_id")
    )
    output.mkdir(parents=True, exist_ok=False)
    evidence = output / "evidence"
    evidence.mkdir()
    records = []
    report = {
        "protocol": PROTOCOL,
        "cpu_model": model,
        "cpu_vendor": vendor,
        "platform": platform.platform(),
        "image_id": image["Id"],
        "source_commit": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip(),
        "worker_sha256": sha(Path(__file__)),
        "fixed_files": FIXED_FILES,
        "runtime": {"precision": "float32", "threads": 4, "processes": 1},
        "records": records,
        "diagnostic_complete": False,
        "limits": "Public fixture only; not production defaults or universal CPU qualification.",
    }
    try:
        for mode, repeat in ORDER:
            label = f"{mode.lower()}-r{repeat}"
            run = prepare_run(
                repo / "examples/minimal-atlas-container.yaml",
                output_directory=output / "runs",
                run_id=label,
            )
            manifest = verify_prepared_run(run)
            command = build_command(manifest["effective_config"], run)
            name = "df-cpu-pair-" + uuid4().hex
            argv = paired_command(command, mode, name)
            log = run / "logs/deformetrica.log"
            started = time.monotonic()
            run_container(argv, log, name)
            elapsed = time.monotonic() - started
            # This is a diagnostic execution, not a normal app run/result. Verify
            # protected prepared inputs again; do not forge app lifecycle events.
            for protected in manifest["protected_artifacts"]:
                if sha(run / protected["path"]) != protected["sha256"]:
                    raise ValueError("Prepared input changed during diagnostic execution")
            parse_convergence(log, run / "logs/convergence.csv")
            comparison = compare_reference_run(run, repo / "reference/synthetic-v1")
            retained = evidence / label
            retained.mkdir()
            filenames = [a["run_path"] for a in reference["artifacts"]]
            filenames += [
                "logs/deformetrica.log",
                "engine/model.xml",
                "engine/data_set.xml",
                "engine/optimization_parameters.xml",
            ]
            for filename in filenames:
                destination = retained / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / filename, destination)
            records.append(
                {
                    "mode": mode,
                    "repeat": repeat,
                    "label": label,
                    "elapsed_seconds": elapsed,
                    "argv": argv,
                    "comparison": comparison,
                    "artifact_sha256": {
                        a["id"]: sha(run / a["run_path"]) for a in reference["artifacts"]
                    },
                    "engine_sha256": {
                        f: sha(run / f) for f in filenames if f.startswith("engine/")
                    },
                }
            )
            print(f"{model}: {label}: {comparison['passed_count']}/10", flush=True)
        for mode in ("AUTO", "COMPATIBLE"):
            name = "df-cpu-pair-" + uuid4().hex
            argv = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--name",
                name,
                "--tmpfs=/tmp:rw,exec,nosuid,size=1g",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,source={repo},target=/source,readonly",
                "--mount",
                f"type=bind,source={evidence},target=/evidence",
                "--env",
                "OMP_NUM_THREADS=4",
                "--env",
                f"MKL_CBWR={mode}",
                "--entrypoint",
                "python",
                IMAGE,
                "/source/tools/probe_reference_cpu.py",
                "--repository",
                "/source",
                "--output",
                f"/evidence/probe-{mode}.json",
            ]
            run_container(argv, output / f"probe-{mode}.log", name)
            probe = json.loads((evidence / f"probe-{mode}.json").read_text())
            if (
                probe["cpu_model"] != model
                or probe["torch"] != "1.6.0+cpu"
                or probe["threads"] != 4
                or probe["environment"]["MKL_CBWR"] != mode
            ):
                raise ValueError("Container probe identity/version/thread/mode mismatch")
        report.update(summarize(records))
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["evidence_sha256"] = {
            path.relative_to(evidence).as_posix(): sha(path)
            for path in sorted(evidence.rglob("*"))
            if path.is_file()
        }
        write_json(evidence / "report.json", report)
    return report


def verify(repo, directory):
    reference = checked_reference(repo)
    payload = (directory / "report.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != (directory / "report.sha256").read_text().strip():
        raise ValueError("Report checksum mismatch")
    report = json.loads(payload)
    if report["protocol"] != PROTOCOL or report["fixed_files"] != FIXED_FILES:
        raise ValueError("Unknown protocol or changed reference")
    expected = set(report["evidence_sha256"])
    actual = {
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.name not in {"report.json", "report.sha256"}
    }
    if actual != expected:
        raise ValueError("Missing or unexpected retained evidence")
    for filename, digest in report["evidence_sha256"].items():
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory.resolve()) or sha(path) != digest:
            raise ValueError("Evidence checksum or path mismatch")
    for record, (mode, repeat) in zip(report["records"], ORDER, strict=True):
        if (record["mode"], record["repeat"], record["label"]) != (
            mode,
            repeat,
            f"{mode.lower()}-r{repeat}",
        ):
            raise ValueError("Unexpected condition")
        retained = directory / record["label"]
        if compare_reference_run(retained, repo / "reference/synthetic-v1") != record["comparison"]:
            raise ValueError("Comparison does not rederive from retained bytes")
        if {a["id"]: sha(retained / a["run_path"]) for a in reference["artifacts"]} != (
            record["artifact_sha256"]
        ):
            raise ValueError("Artifact receipt differs")
        if {f: sha(retained / f) for f in record["engine_sha256"]} != record["engine_sha256"]:
            raise ValueError("Engine XML receipt differs")
    derived = summarize(report["records"])
    if any(report.get(k) != v for k, v in derived.items()):
        raise ValueError("Summary does not rederive")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("observe", "verify"))
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    repo, directory = args.repository.resolve(), args.directory.resolve()
    result = observe(repo, directory) if args.command == "observe" else verify(repo, directory)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "cpu_model",
                    "cpu_vendor",
                    "diagnostic_complete",
                    "compatible_reference_pass",
                    "auto_reference_pass",
                    "mode_repeatability",
                )
            },
            indent=2,
        )
    )
    if not result["compatible_reference_pass"] or not all(result["mode_repeatability"].values()):
        raise SystemExit(4)


if __name__ == "__main__":
    main()
