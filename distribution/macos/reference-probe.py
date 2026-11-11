"""Isolated native macOS reference-runtime qualification using public meshes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from diffeoforge import __version__

PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20241002/"
    "cpython-3.8.20%2B20241002-x86_64-apple-darwin-install_only_stripped.tar.gz"
)
PYTHON_SHA256 = "375b6eead6c852cabbf3ccfd43dc4f6dd4c36381bf74c9a7910acb839fd5c57f"


def make_portable_launchers(prefix):
    binary = prefix / "bin"
    shell_prefix = '#!/bin/sh\nset -eu\nDF_BIN=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
    launcher = shell_prefix + '''
export PATH="$DF_BIN:$PATH"
export CC="$DF_BIN/df-cc" CXX="$DF_BIN/df-cxx"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 USE_CUDA=0 CUDA_VISIBLE_DEVICES=-1
unset QT_PLUGIN_PATH QML2_IMPORT_PATH DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
exec "$DF_BIN/python3.8" -B -c 'from deformetrica.__main__ import main; main()' "$@"
'''
    (binary / "deformetrica").write_text(launcher)
    (binary / "cmake").write_text(shell_prefix + '''
exec "$DF_BIN/python3.8" -B -c 'from cmake import cmake; cmake()' "$@"
''')
    for name, compiler in (("df-cc", "clang"), ("df-cxx", "clang++")):
        (binary / name).write_text(
            '#!/bin/sh\nexec /usr/bin/' + compiler + ' -arch x86_64 "$@"\n'
        )
    for name in ("deformetrica", "cmake", "df-cc", "df-cxx"):
        (binary / name).chmod(0o755)


def avoid_clang_version_header_collision(prefix):
    """Rename package metadata that shadows libc++'s <version> header."""
    package = prefix / "lib/python3.8/site-packages/pykeops"
    source = package / "__init__.py"
    version = package / "version"
    original = source.read_text()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    token = "'version'), encoding='utf-8'"
    assert original.count(token) == 1 and version.read_text().strip() == "1.4.1"
    mathematical = {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (package / "keops").rglob("*") if p.is_file()}
    version.rename(package / "package-version.txt")
    patched = original.replace(token, "'package-version.txt'), encoding='utf-8'")
    assert patched.count("set_bin_folder()") == 1
    # Compiled native modules may retain loader paths to this runtime. Do not
    # reuse another installation's cache after a user moves or copies the app.
    cache_prefix = f"diffeoforge-mac-{__version__}-"
    patched = patched.replace(
        "set_bin_folder()",
        "import hashlib\nset_bin_folder(os.path.join(os.path.expanduser('~'), '.cache', "
        f"{cache_prefix!r} + hashlib.sha256(os.path.realpath(__file__).encode())"
        ".hexdigest()[:16]))",
    )
    source.write_text(patched)
    assert mathematical == {
        str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (package / "keops").rglob("*") if p.is_file()
    }
    return dict(before_sha256=before, after_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                metadata_rename="version -> package-version.txt",
                cache_isolation=f"installation-path-bound macOS {__version__} cache",
                mathematical_files=len(mathematical), mathematical_bytes_unchanged=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert platform.system() == "Darwin", "This probe runs on native macOS only"
    root = args.output.resolve()
    root.mkdir(exist_ok=False, parents=True)
    repository = Path(__file__).resolve().parents[2]
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    if os.environ.get("GITHUB_SHA", source_commit) != source_commit:
        raise RuntimeError("The checked-out source does not match GITHUB_SHA")
    archive = root / "python.tar.gz"
    urllib.request.urlretrieve(PYTHON_URL, archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == PYTHON_SHA256
    with tarfile.open(archive) as stream:
        stream.extractall(root, filter="data")
    prefix = root / "python"
    python = prefix / "bin/python3.8"
    architecture = platform.machine()
    if architecture == "arm64":
        subprocess.run(
            ["/usr/sbin/softwareupdate", "--install-rosetta", "--agree-to-license"],
            check=True,
        )
    command = ["/usr/bin/arch", "-x86_64", str(python)]
    env = dict(os.environ, MPLBACKEND="Agg", OMP_NUM_THREADS="1", USE_CUDA="0",
               CUDA_VISIBLE_DEVICES="-1", PYTHONNOUSERSITE="1")
    subprocess.run(command + ["-B", "-m", "pip", "install", "pip==25.0.1",
                              "setuptools==75.3.2", "wheel==0.45.1", "numpy==1.24.4",
                              "cmake==3.28.3"], check=True, env=env)
    subprocess.run(command + ["-B", "-m", "pip", "install", "--no-deps",
                              "--report", str(root / "native-install.json"), "-r",
                              str(repository / "distribution/macos/reference-requirements.txt")],
                   check=True, env=env)
    subprocess.run(command + ["-B", "-m", "pip", "check"], check=True, env=env)
    compatibility = avoid_clang_version_header_collision(prefix)
    make_portable_launchers(prefix)
    # The selected pinned CMake and target-architecture compiler also apply to
    # adapter-launched native children, not just pip installation subprocesses.
    os.environ["PATH"] = str(prefix / "bin") + os.pathsep + os.environ["PATH"]
    code = (
        "import json,platform,torch,deformetrica,pykeops; "
        "print(json.dumps(dict(machine=platform.machine(),python=platform.python_version(),"
        "torch=torch.__version__,deformetrica=deformetrica.__version__,"
        "pykeops=pykeops.__version__,cuda=torch.cuda.is_available())))"
    )
    result = subprocess.run(command + ["-B", "-c", code], check=True, env=env,
                            text=True, capture_output=True)
    (root / "native-imports.txt").write_text(result.stdout + result.stderr)
    assert '"machine": "x86_64"' in result.stdout
    assert '"cuda": false' in result.stdout
    # The prefix's console script is used only here, before relocation.
    meshes = root / "Example Käfer/meshes"
    shutil.copytree(repository / "examples/synthetic/meshes", meshes)
    import yaml

    from diffeoforge.config import load_config
    from diffeoforge.runs import execute_run, prepare_run

    config = load_config(repository / "examples/minimal-atlas.yaml")
    config["input"]["directory"] = str(meshes)
    config["input"]["template"] = str(meshes / "template.vtk")
    config["output"]["directory"] = str(root / "runs")
    config["runtime"]["threads"] = 1
    config["runtime"]["launcher"]["executable"] = str(prefix / "bin/deformetrica")
    config["optimization"]["max_iterations"] = 2
    config["optimization"]["save_every_n_iterations"] = 1
    outcomes = {}
    for kernel in ("torch", "keops"):
        config["runtime"]["kernel_backend"] = kernel
        path = root / f"native-{kernel}.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        prepared = prepare_run(path, run_id=f"mac-{kernel}")
        return_code = execute_run(prepared)
        result = json.loads((prepared / "result.json").read_text())
        outcomes[kernel] = dict(status=result["status"], return_code=return_code)
        assert return_code == 0 and result["status"] == "completed", outcomes
    proof = dict(status="passed", host_architecture=architecture,
                 native_architecture="x86_64", source_commit=source_commit,
                 python_archive_sha256=PYTHON_SHA256, public_native_runs=outcomes,
                 clang_metadata_compatibility=compatibility,
                 private_inputs_used=False, windows_owner_state_accessed=False)
    (root / "mac-reference-probe.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
