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

import yaml

from diffeoforge.config import load_config
from diffeoforge.desktop.reference_execution_controller import ReferenceExecutionController
from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata


def run(arguments, **kwargs):
    return subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def live_cancellation(checker, repository, root, native, worker):
    """Cancel a real public-data native calculation after progress is observed."""
    root.mkdir()
    mesh = read_vtk_polydata(repository / "examples/synthetic/meshes/template.vtk")
    vertices, triangles = list(mesh.vertices), list(mesh.triangles)
    # Subdivide only the public template so one dense evaluation lasts long
    # enough to distinguish in-flight cancellation from a completed-run race.
    for _ in range(3):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert platform.system() == "Darwin"
    candidate, output = args.candidate.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    proof = json.loads((candidate / "verification.json").read_text())
    assert proof["status"] == "macos_test_package_verified"
    assert proof["version"] == "0.0.0.dev193"
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
    spec = importlib.util.spec_from_file_location(
        "mac_package_qualification", Path(__file__).with_name("build-package.py")
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    assert checker.inventory(installed) == proof["application_files"]
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
    run([binary, "--version"], capture_output=True, env=env)
    run([binary, "--smoke"], env=env)
    run([binary, "--smoke-media"], env=env)
    native = installed / "Contents/Resources/ReferenceRuntime/bin/deformetrica"
    worker = installed / "Contents/MacOS/DiffeoForgeReferenceExecutionWorker"
    results = checker.reference_check(Path(__file__).resolve().parents[2],
                                      output / "public-workflows", native, worker)
    results["in_flight_cancellation"] = live_cancellation(
        checker, Path(__file__).resolve().parents[2], output / "cancellation-check", native, worker
    )
    assert checker.inventory(installed) == proof["application_files"]
    run(["codesign", "--verify", "--deep", "--strict", installed], capture_output=True)
    final = dict(status="downloaded_package_independently_verified", version=proof["version"],
                 host_architecture=platform.machine(), macos_version=platform.mac_ver()[0],
                 source_package=proof["package"],
                 original_build_prefix_available=False, original_keops_cache_used=False,
                 cocoa_startup=True, media_export=True, production_worker_and_native_checks=results,
                 installed_bytes_unchanged=True, signing="ad-hoc", notarized=False,
                 interactive_colleague_acceptance=False, private_data_used=False)
    (output / "independent-verification.json").write_text(json.dumps(final, indent=2))
    print(json.dumps(final), flush=True)


if __name__ == "__main__":
    main()
