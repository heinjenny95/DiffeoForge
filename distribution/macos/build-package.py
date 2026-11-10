"""Build, relocate and qualify the v197 Mac test package on a native Mac runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from diffeoforge import __version__
from diffeoforge.config import load_config
from diffeoforge.desktop.reference_execution_controller import ReferenceExecutionController
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.runs import execute_run, prepare_resume_run, prepare_run

BASELINE = "6efc9725691416ea75e44df0bb07e6255611c5b8"
MACHO_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


def inventory(root):
    return {p.relative_to(root).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def reference_request(path, destination, native, identifier):
    return DesktopReferenceLaunchRequest(
        request_id=identifier, config_path=path.resolve(), destination=destination.resolve(),
        run_id=identifier, expected_config_sha256=digest(path), launcher_type="native",
        launcher_executable=str(native), launcher_engine=None, launcher_image=None,
    )


def reference_check(repository, root, native, worker):
    """Production frozen worker, normal export, checkpoint successor and cancellation."""
    meshes = root / "Example Käfer/meshes"
    shutil.copytree(repository / "examples/synthetic/meshes", meshes)
    base = load_config(repository / "examples/minimal-atlas.yaml")
    base["input"].update(directory=str(meshes), template=str(meshes / "template.vtk"))
    base["output"]["directory"] = str(root / "runs")
    base["runtime"].update(threads=1, launcher={"type": "native", "executable": str(native)})
    results = {}
    for name, kernel, cap in (("worker-keops", "keops", 100), ("varifold", "keops", 100),
                              ("checkpoint", "keops", 2)):
        config = json.loads(json.dumps(base))
        config["runtime"]["kernel_backend"] = kernel
        config["optimization"].update(max_iterations=cap, save_every_n_iterations=1)
        if name == "varifold":
            config["model"]["attachment"]["type"] = "varifold"
        path = root / f"{name}.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        destination = root / "runs" / name
        if name == "worker-keops":
            request = reference_request(path, destination, native, name)
            request.verify_launch_inputs()
            result = ReferenceExecutionController(request, worker_command=(str(worker),)).run()
            assert result.completed and result.exit_code == 0, (result.outcome, result.stderr)
            results["production_worker"] = dict(outcome=result.outcome, exit_code=result.exit_code)
        else:
            prepared = prepare_run(path, run_id=name)
            assert execute_run(prepared) == 0
        saved = json.loads((destination / "result.json").read_text())
        assert saved["status"] == "completed" and saved["return_code"] == 0
        results[name] = {"status": saved["status"], "return_code": saved["return_code"]}
    parent = root / "runs/checkpoint"
    before = inventory(parent)
    continued = prepare_resume_run(parent, run_id="checkpoint-plus300", additional_iterations=300)
    assert execute_run(continued) == 0
    successor = json.loads((continued / "manifest.json").read_text())
    assert successor["effective_config"]["optimization"]["max_iterations"] == 302
    assert inventory(parent) == before
    results["checkpoint_continuation"] = {"cap": 302, "source_unchanged": True}
    # A queued safe cancellation must stop without creating a scientific run.
    path = root / "worker-keops.yaml"
    request = reference_request(path, root / "runs/cancelled", native, "cancelled")
    controller = ReferenceExecutionController(request, worker_command=(str(worker),))
    assert controller.request_cancel()
    cancelled = controller.run()
    assert cancelled.outcome == "stopped_before_prepare" and not request.destination.exists()
    results["safe_cancellation"] = cancelled.outcome
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("native_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert platform.system() == "Darwin" and __version__ == "0.0.0.dev197"
    repository = Path(__file__).resolve().parents[2]
    run(["git", "diff", "--exit-code", BASELINE, "--", "src", "pyproject.toml"],
        cwd=repository)
    build_commit = run(["git", "rev-parse", "HEAD"], cwd=repository,
                       capture_output=True, text=True).stdout.strip()
    native_root = args.native_root.resolve()
    proof = json.loads((native_root / "mac-reference-probe.json").read_text())
    assert proof["status"] == "passed" and not proof["private_inputs_used"]
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", MPLBACKEND="Agg", OMP_NUM_THREADS="1")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", root / "dist",
         "--workpath", root / "work", repository / "distribution/macos/DiffeoForge.spec"], env=env)
    app = root / "dist/DiffeoForge.app"
    contents = app / "Contents"
    native_prefix = contents / "Resources/ReferenceRuntime"
    shutil.copytree(native_root / "python", native_prefix, symlinks=True)
    # A relocated check must not silently use its original interpreter/libraries
    # or already-compiled kernels from the native setup phase.
    (native_root / "python").rename(native_root / "python-build-prefix-retained")
    fresh_home = root / "Qualification Home"
    fresh_home.mkdir()
    os.environ["HOME"] = str(fresh_home)
    os.environ["MPLCONFIGDIR"] = str(fresh_home / "matplotlib")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(HOME=str(fresh_home), MPLCONFIGDIR=str(fresh_home / "matplotlib"),
               PYTHONDONTWRITEBYTECODE="1")
    native = native_prefix / "bin/deformetrica"
    executable = contents / "MacOS/DiffeoForge"
    worker = contents / "MacOS/DiffeoForgeReferenceExecutionWorker"
    assert native.is_file() and worker.is_file()
    # Ad-hoc signing is explicit; no Developer ID or notarization is claimed.
    signed = []
    for path in sorted(native_prefix.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic in MACHO_MAGICS:
                run(["codesign", "--force", "--sign", "-", path], capture_output=True)
                signed.append(str(path.relative_to(app)))
    run(["codesign", "--force", "--deep", "--sign", "-", app], capture_output=True)
    run(["codesign", "--verify", "--deep", "--strict", app], capture_output=True)
    reported_version = run([executable, "--version"], env=env, capture_output=True,
                           text=True).stdout.split()[-1]
    assert reported_version == __version__
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == "0.0.197" and info["CFBundleVersion"] == "197"
    run([executable, "--smoke"], env=env)
    run([executable, "--smoke-media"], env=env)
    before = inventory(app)
    checks = reference_check(repository, root / "qualification", native, worker)
    assert inventory(app) == before, "Using the app modified signed application files"
    # Construct a normal Cocoa window too; offscreen-only success is insufficient.
    cocoa = dict(env)
    cocoa.pop("QT_QPA_PLATFORM", None)
    run([executable, "--smoke"], env=cocoa)
    run(["codesign", "--verify", "--deep", "--strict", app], capture_output=True)
    staging = root / "DMG"
    staging.mkdir()
    shutil.move(str(app), staging / app.name)
    app = staging / app.name
    (staging / "Applications").symlink_to("/Applications")
    shutil.copyfile(repository / "distribution/macos/README-macOS.txt", staging / "README.txt")
    shutil.copytree(repository / "examples/synthetic", staging / "Example/synthetic")
    example = load_config(repository / "examples/minimal-atlas.yaml")
    example["runtime"]["launcher"]["executable"] = (
        "/Applications/DiffeoForge.app/Contents/Resources/ReferenceRuntime/bin/deformetrica"
    )
    example["runtime"]["threads"] = 1
    (staging / "Example/atlas.yaml").write_text(yaml.safe_dump(example, sort_keys=False))
    architecture = "AppleSilicon" if platform.machine() == "arm64" else "Intel"
    output = root / "delivery"
    output.mkdir()
    package = output / f"DiffeoForge-v197-macOS-{architecture}.dmg"
    run(["hdiutil", "create", "-volname", f"DiffeoForge v197 {architecture}", "-srcfolder",
         staging, "-ov", "-format", "UDZO", package], capture_output=True)
    run(["hdiutil", "verify", package], capture_output=True)
    # Mount, copy out of the image into a second path and run the actual copied app.
    attached = run(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", package],
                   capture_output=True)
    mounted = plistlib.loads(attached.stdout)
    mount = next(Path(row["mount-point"]) for row in mounted["system-entities"]
                 if row.get("mount-point"))
    installed = root / "Clean Install Käfer/DiffeoForge.app"
    installed.parent.mkdir()
    try:
        run(["ditto", mount / "DiffeoForge.app", installed])
    finally:
        run(["hdiutil", "detach", mount], capture_output=True)
    run([installed / "Contents/MacOS/DiffeoForge", "--smoke"], env=cocoa)
    run([installed / "Contents/Resources/ReferenceRuntime/bin/deformetrica", "--help"],
        capture_output=True, env=env)
    assert inventory(installed) == inventory(app)
    run(["codesign", "--verify", "--deep", "--strict", installed], capture_output=True)
    package_hash = digest(package)
    (output / (package.name + ".sha256")).write_text(f"{package_hash}  {package.name}\n")
    evidence = dict(status="macos_test_package_verified", version=__version__,
                    application_feature_baseline=BASELINE,
                    build_commit=build_commit,
                    host_architecture=platform.machine(), reference_architecture="x86_64",
                    native_reference_probe=proof, checks=checks, cocoa_smoke=True,
                    relocated_installed_copy_verified=True, application_inventory_unchanged=True,
                    native_macho_files_signed=len(signed), signature="ad-hoc", notarized=False,
                    colleague_interactive_acceptance=False, gpu_or_modern_engine_claim=False,
                    package={"name": package.name, "bytes": package.stat().st_size,
                             "sha256": package_hash}, application_files=inventory(app))
    (output / "verification.json").write_text(json.dumps(evidence, indent=2))
    shutil.copyfile(repository / "distribution/macos/README-macOS.txt", output / "README.txt")
    print(json.dumps({key: value for key, value in evidence.items()
                      if key != "application_files"}), flush=True)


if __name__ == "__main__":
    main()
