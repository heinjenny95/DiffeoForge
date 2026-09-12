"""Read-only discovery and verification of an external Modern CUDA runtime."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs

MODERN_CUDA_PYTHON_ENV = "DIFFEOFORGE_MODERN_CUDA_PYTHON"
_PROBE_TIMEOUT_SECONDS = 90
_PROBE = """
import json
import pathlib
import torch
import diffeoforge
import diffeoforge.desktop.worker as worker
import diffeoforge.modern_workflow as workflow

available = bool(torch.cuda.is_available())
payload = {
    "torch_version": str(torch.__version__),
    "cuda_available": available,
    "cuda_version": None if torch.version.cuda is None else str(torch.version.cuda),
    "device_name": torch.cuda.get_device_name(0) if available else None,
    "device_capability": list(torch.cuda.get_device_capability(0)) if available else None,
    "diffeoforge_path": str(pathlib.Path(diffeoforge.__file__).resolve()),
    "worker_path": str(pathlib.Path(worker.__file__).resolve()),
    "engine_implementation_version": workflow.ENGINE_IMPLEMENTATION_VERSION,
}
print(json.dumps(payload, sort_keys=True))
""".strip()


class ModernCudaRuntimeError(RuntimeError):
    """Raised when no exact external CUDA worker can be bound safely."""


@dataclass(frozen=True)
class ModernCudaRuntime:
    """Fresh read-only evidence for one external CUDA-capable Python runtime."""

    python_path: Path
    python_sha256: str
    torch_version: str
    cuda_version: str
    device_name: str
    device_capability: tuple[int, int]
    diffeoforge_path: Path
    diffeoforge_sha256: str
    worker_path: Path
    worker_sha256: str
    engine_implementation_version: str

    @property
    def worker_command(self) -> tuple[str, ...]:
        return (
            str(self.python_path),
            "-I",
            "-m",
            "diffeoforge.desktop.worker",
        )

    @property
    def summary(self) -> str:
        return (
            f"{self.device_name} · PyTorch {self.torch_version} · CUDA "
            f"{self.cuda_version} · Engine {self.engine_implementation_version}"
        )


def _candidate_python_paths() -> tuple[Path, ...]:
    candidates: list[Path] = []
    configured = os.environ.get(MODERN_CUDA_PYTHON_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    runtime_root = Path.home() / "Documents" / "DiffeoForge-Runtimes"
    if runtime_root.is_dir():
        candidates.extend(
            sorted(
                runtime_root.glob("*/Scripts/python.exe"),
                key=lambda path: str(path).casefold(),
            )
        )
        candidates.extend(
            sorted(
                runtime_root.glob("*/bin/python"),
                key=lambda path: str(path).casefold(),
            )
        )
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return tuple(unique)


def probe_modern_cuda_runtime(python_path: Path | str) -> ModernCudaRuntime:
    """Probe one interpreter without mutating its environment or running an atlas."""

    from diffeoforge.modern_workflow import ENGINE_IMPLEMENTATION_VERSION

    source = Path(python_path).expanduser().resolve()
    if not source.is_file():
        raise ModernCudaRuntimeError(f"CUDA Python executable does not exist: {source}")
    try:
        completed = subprocess.run(
            (str(source), "-I", "-c", _PROBE),
            cwd=source.parent.parent,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
            **hidden_windows_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ModernCudaRuntimeError(
            f"Could not probe CUDA runtime {source}: {error}"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no detail"
        raise ModernCudaRuntimeError(
            f"CUDA runtime probe failed for {source}: {detail}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ModernCudaRuntimeError(
            "CUDA runtime probe did not emit exactly one JSON record"
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise ModernCudaRuntimeError("CUDA runtime probe emitted invalid JSON") from error
    if not isinstance(payload, dict) or payload.get("cuda_available") is not True:
        raise ModernCudaRuntimeError(
            f"PyTorch runtime cannot access CUDA: {source}"
        )
    engine_version = str(payload.get("engine_implementation_version", ""))
    if engine_version != ENGINE_IMPLEMENTATION_VERSION:
        raise ModernCudaRuntimeError(
            "CUDA runtime carries a different Modern engine implementation: "
            f"expected {ENGINE_IMPLEMENTATION_VERSION}, observed {engine_version or 'missing'}"
        )
    capability = payload.get("device_capability")
    if (
        not isinstance(capability, list)
        or len(capability) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in capability)
    ):
        raise ModernCudaRuntimeError("CUDA runtime reported an invalid device capability")
    text_fields = {
        name: str(payload.get(name, "")).strip()
        for name in (
            "torch_version",
            "cuda_version",
            "device_name",
            "diffeoforge_path",
            "worker_path",
        )
    }
    if any(not value for value in text_fields.values()):
        raise ModernCudaRuntimeError("CUDA runtime probe omitted required identity fields")
    diffeoforge_path = Path(text_fields["diffeoforge_path"]).resolve()
    worker_path = Path(text_fields["worker_path"]).resolve()
    if not diffeoforge_path.is_file() or not worker_path.is_file():
        raise ModernCudaRuntimeError(
            "CUDA runtime reported absent DiffeoForge or worker source files"
        )
    return ModernCudaRuntime(
        python_path=source,
        python_sha256=sha256_file(source),
        torch_version=text_fields["torch_version"],
        cuda_version=text_fields["cuda_version"],
        device_name=text_fields["device_name"],
        device_capability=(int(capability[0]), int(capability[1])),
        diffeoforge_path=diffeoforge_path,
        diffeoforge_sha256=sha256_file(diffeoforge_path),
        worker_path=worker_path,
        worker_sha256=sha256_file(worker_path),
        engine_implementation_version=engine_version,
    )


def discover_modern_cuda_runtime() -> ModernCudaRuntime:
    """Return the first deterministic passing runtime or one actionable failure."""

    candidates = _candidate_python_paths()
    if not candidates:
        raise ModernCudaRuntimeError(
            "No external CUDA runtime was found. Set "
            f"{MODERN_CUDA_PYTHON_ENV} to its Python executable or install it below "
            f"{Path.home() / 'Documents' / 'DiffeoForge-Runtimes'}."
        )
    failures: list[str] = []
    for candidate in candidates:
        try:
            return probe_modern_cuda_runtime(candidate)
        except ModernCudaRuntimeError as error:
            failures.append(str(error))
    raise ModernCudaRuntimeError(
        "No discovered Modern CUDA runtime passed verification: " + " | ".join(failures)
    )


def verify_modern_cuda_runtime_binding(runtime: ModernCudaRuntime) -> None:
    """Fail if the reviewed external interpreter changed before worker launch."""

    if not isinstance(runtime, ModernCudaRuntime):
        raise TypeError("runtime must be ModernCudaRuntime")
    if not runtime.python_path.is_file():
        raise ModernCudaRuntimeError(
            f"Reviewed CUDA Python executable is absent: {runtime.python_path}"
        )
    if sha256_file(runtime.python_path) != runtime.python_sha256:
        raise ModernCudaRuntimeError(
            "Reviewed CUDA Python executable changed before worker launch"
        )
    for label, path, expected_hash in (
        ("DiffeoForge package", runtime.diffeoforge_path, runtime.diffeoforge_sha256),
        ("desktop worker", runtime.worker_path, runtime.worker_sha256),
    ):
        if not path.is_file():
            raise ModernCudaRuntimeError(
                f"Reviewed CUDA {label} source is absent: {path}"
            )
        if sha256_file(path) != expected_hash:
            raise ModernCudaRuntimeError(
                f"Reviewed CUDA {label} source changed before worker launch"
            )
