"""Independent Mac runner: install the downloaded image without build caches."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import plistlib
import subprocess
import time
from pathlib import Path
from threading import Timer

import yaml

from diffeoforge import __version__
from diffeoforge.config import load_config
from diffeoforge.desktop.reference_execution_controller import ReferenceExecutionController
from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata
from diffeoforge.reference_atlas_stop import MORPHOSPACE_STABILITY, stop_policy
from diffeoforge.reference_final_export_recovery import checkpoint_iteration
from diffeoforge.reference_morphospace_stopping import read_morphospace_stability
from diffeoforge.result_report import collect_run_report
from diffeoforge.runs import EXECUTION_CHECKPOINT_PATH


def run(arguments, **kwargs):
    return subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def live_cancellation(checker, repository, root, native, worker):
    """Cancel a real public-data native calculation after progress is observed."""
    root.mkdir()
    mesh = read_vtk_polydata(repository / "examples/synthetic/meshes/template.vtk")
    vertices, triangles = list(mesh.vertices), list(mesh.triangles)
    # Two refinements give 5,120 faces: long enough to observe live progress,
    # while bounding the dense Torch self-attachment below the runner's RAM.
    # A third refinement would quadruple faces and multiply dense memory by 16.
    for _ in range(2):
        edges, refined = {}, []

        def midpoint(a, b, edge_map=edges):
            key = tuple(sorted((a, b)))
            if key not in edge_map:
                edge_map[key] = len(vertices)
                vertices.append(tuple((vertices[a][i] + vertices[b][i]) / 2 for i in range(3)))
            return edge_map[key]

        for a, b, c in triangles:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            refined.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        triangles = refined
    template = write_vtk_polydata(root / "public-subdivided-template.vtk", vertices, triangles)
    config = load_config(repository / "examples/minimal-atlas.yaml")
    config["input"].update(directory=str(repository / "examples/synthetic/meshes"),
                           template=str(template))
    config["output"]["directory"] = str(root / "runs")
    config["runtime"].update(threads=1, kernel_backend="torch",
                             launcher={"type": "native", "executable": str(native)})
    path = root / "cancel.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    request = checker.reference_request(path, root / "runs/live-cancel", native, "live-cancel")
    controller = ReferenceExecutionController(request, worker_command=(str(worker),))
    sent = []

    def observe(event):
        if event.kind == "progress" and not sent:
            assert controller.request_cancel()
            sent.append(time.monotonic())

    result = controller.run(event_callback=observe)
    assert sent and result.interrupted, (result.outcome, result.stderr)
    seconds = time.monotonic() - sent[0]
    assert seconds < 20, f"Native cancellation took {seconds:.2f}s"
    return dict(outcome=result.outcome, seconds_after_request=seconds,
                public_template_vertices=len(vertices), cancelled_after_progress=True)


def verified_open_ended_checkpoint(destination, policy, capped_fixture_limit):
    """Verify retained files and check the saved iteration without loading a pickle."""
    report = collect_run_report(destination)
    failed_checks = [check.label for check in report.checks if check.status != "pass"]
    assert not failed_checks, failed_checks
    assert report.result["status"] == "interrupted"
    assert report.max_iterations is None
    assert report.manifest["effective_config"]["optimization"]["max_iterations"] == (
        capped_fixture_limit
    )
    stability = read_morphospace_stability(destination, verified_run_report=report)
    assert stability is not None and stability["policy"] == policy and stability["observations"]
    terminal = stability["terminal"]
    assert terminal is None or terminal["reason"] == "cancelled", terminal
    saved_iteration = checkpoint_iteration(destination / EXECUTION_CHECKPOINT_PATH)
    assert saved_iteration > capped_fixture_limit, (
        "The verified checkpoint did not advance beyond the fixture's declared limit"
    )
    return saved_iteration


def open_ended_cancellation(checker, repository, root, native, worker):
    """Observe and cancel the installed uncapped worker beyond a real fixture limit."""
    root.mkdir()
    public_meshes = repository / "examples/synthetic/meshes"
    config = load_config(repository / "examples/minimal-atlas.yaml")
    policy = stop_policy(MORPHOSPACE_STABILITY, unlimited_iterations=True)
    config["project"]["atlas_stop"] = policy
    config["input"].update(directory=str(public_meshes),
                           template=str(public_meshes / "template.vtk"))
    config["output"]["directory"] = str(root / "runs")
    config["runtime"].update(threads=1, kernel_backend="torch",
                             launcher={"type": "native", "executable": str(native)})
    # Saving every step leaves an accepted state beyond this limit before the
    # cancellation request, even when a platform stops with SIGTERM.
    limit = 1
    config["optimization"].update(
        max_iterations=limit, save_every_n_iterations=1, print_every_n_iterations=1,
    )
    path = root / "open-ended.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    destination = root / "runs/open-ended"
    request = checker.reference_request(path, destination, native, "open-ended")
    controller = ReferenceExecutionController(request, worker_command=(str(worker),))
    observed_iteration = None
    sent_at = None

    def observe(event):
        nonlocal observed_iteration, sent_at
        if event.kind != "progress":
            return
        assert event.payload["maximum_iterations"] is None
        assert event.payload["eta_to_iteration_cap_seconds"] is None
        iteration = event.payload["iteration"]
        if iteration > limit + 1 and sent_at is None:
            assert controller.request_cancel()
            observed_iteration, sent_at = iteration, time.monotonic()

    # The test must bound its own wall time even though the reviewed optimizer
    # is open-ended. A deadline cancellation does not count as observed proof.
    deadline = Timer(180, controller.request_cancel)
    deadline.start()
    try:
        result = controller.run(event_callback=observe)
    finally:
        deadline.cancel()
    assert sent_at is not None and result.interrupted, (result.outcome, result.stderr)
    elapsed = time.monotonic() - sent_at
    assert elapsed < 20, f"Open-ended native cancellation took {elapsed:.2f}s"
    saved_iteration = verified_open_ended_checkpoint(destination, policy, limit)
    return dict(outcome=result.outcome, seconds_after_request=elapsed,
                declared_fixture_iterations=limit, reported_iteration_limit=None,
                observed_iteration=observed_iteration,
                verified_checkpoint_iteration=saved_iteration)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert platform.system() == "Darwin"
    repository = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "mac_package_qualification", Path(__file__).with_name("build-package.py")
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    build_commit = checker.checked_source_commit(repository)
    candidate, output = args.candidate.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    proof = json.loads((candidate / "verification.json").read_text())
    assert proof["status"] == "macos_test_package_verified"
    assert proof["version"] == __version__
    assert proof["build_commit"] == build_commit
    assert proof["application_feature_baseline"] == build_commit
    assert proof["native_reference_probe"]["source_commit"] == build_commit
    assert proof["host_architecture"] == platform.machine()
    package = candidate / proof["package"]["name"]
    assert package.is_file() and package.stat().st_size == proof["package"]["bytes"]
    assert hashlib.sha256(package.read_bytes()).hexdigest() == proof["package"]["sha256"]
    run(["hdiutil", "verify", package], capture_output=True)
    attached = run(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", package],
                   capture_output=True)
    mounted = plistlib.loads(attached.stdout)
    mount = next(Path(row["mount-point"]) for row in mounted["system-entities"]
                 if row.get("mount-point"))
    installed = output / "Applications Käfer/DiffeoForge.app"
    installed.parent.mkdir()
    try:
        run(["ditto", mount / "DiffeoForge.app", installed])
    finally:
        run(["hdiutil", "detach", mount], capture_output=True)
    assert checker.inventory(installed) == proof["application_files"]
    icon = checker.verify_app_icon(repository, installed)
    assert icon == proof["application_icon"]
    if platform.machine() == "arm64":
        run(["/usr/sbin/softwareupdate", "--install-rosetta", "--agree-to-license"])
    isolated_home = output / "Fresh User Home"
    isolated_home.mkdir()
    # No original native prefix exists on this runner; the fresh HOME also
    # excludes precompiled KeOps kernels and previous GUI/native preferences.
    os.environ["HOME"] = str(isolated_home)
    os.environ["MPLCONFIGDIR"] = str(isolated_home / "matplotlib")
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    binary = installed / "Contents/MacOS/DiffeoForge"
    run(["codesign", "--verify", "--deep", "--strict", installed], capture_output=True)
    version = run([binary, "--version"], capture_output=True, text=True, env=env).stdout.split()[-1]
    assert version == proof["version"]
    run([binary, "--smoke"], env=env)
    run([binary, "--smoke-media"], env=env)
    native = installed / "Contents/Resources/ReferenceRuntime/bin/deformetrica"
    worker = installed / "Contents/MacOS/DiffeoForgeReferenceExecutionWorker"
    results = checker.reference_check(repository, output / "public-workflows", native, worker)
    results["in_flight_cancellation"] = live_cancellation(
        checker, repository, output / "cancellation-check", native, worker
    )
    results["open_ended_cancellation"] = open_ended_cancellation(
        checker, repository, output / "open-ended-check", native, worker
    )
    assert checker.inventory(installed) == proof["application_files"]
    run(["codesign", "--verify", "--deep", "--strict", installed], capture_output=True)
    final = dict(status="downloaded_package_independently_verified", version=proof["version"],
                 application_feature_baseline=build_commit, build_commit=build_commit,
                 host_architecture=platform.machine(), macos_version=platform.mac_ver()[0],
                 source_package=proof["package"],
                 original_build_prefix_available=False, original_keops_cache_used=False,
                 cocoa_startup=True, media_export=True, production_worker_and_native_checks=results,
                 application_icon=icon,
                 installed_bytes_unchanged=True, signing="ad-hoc", notarized=False,
                 interactive_colleague_acceptance=False, private_data_used=False)
    (output / "independent-verification.json").write_text(json.dumps(final, indent=2))
    print(json.dumps(final), flush=True)


if __name__ == "__main__":
    main()
