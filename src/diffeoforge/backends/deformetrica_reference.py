"""Frozen Deformetrica 4.3 reference-backend adapter."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
from pathlib import Path, PureWindowsPath
from typing import Any

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_runtime import probe_wsl_launcher
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs

BACKEND_ID = "deformetrica_reference"
BACKEND_CONTRACT_VERSION = "0.1"
CONTAINER_WORKING_DIRECTORY = "/work"
ENGINE_CONSTANTS = {
    "line_search_shrink": 0.5,
    "line_search_expand": 1.5,
    "state_file": "output/deformetrica-state.p",
}


@dataclass(frozen=True)
class CommandSpec:
    """A fully resolved backend command and its controlled environment."""

    argv: tuple[str, ...]
    working_directory: str
    environment: Mapping[str, str]

    def as_manifest(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "environment": dict(self.environment),
        }


def validate_reference_config(config: Mapping[str, Any]) -> None:
    """Reject unsupported reference-backend modes before run preparation."""

    runtime = config["runtime"]
    if runtime["backend"] != BACKEND_ID:
        raise ConfigurationError(f"Unsupported backend: {runtime['backend']}")
    if runtime["device"] != "cpu":
        raise ConfigurationError(
            "The Deformetrica 4.3 reference backend is CPU-only until GPU equivalence "
            "has been validated."
        )
    if config["output"]["retain_flow_meshes"] is not True:
        raise ConfigurationError(
            "Reference runs must retain flow meshes in contract 0.1 so evidence is not deleted."
        )


def _indent_xml(element: ET.Element, level: int = 0) -> None:
    indentation = "\n" + level * "    "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indentation + "    "
        for child in element:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indentation
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def _add_text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = str(value)
    return child


def _render_xml(root: ET.Element) -> bytes:
    _indent_xml(root)
    buffer = BytesIO()
    stream = TextIOWrapper(buffer, encoding="utf-8", newline=None)
    ET.ElementTree(root).write(stream, encoding="unicode", xml_declaration=True)
    stream.flush()
    payload = buffer.getvalue()
    stream.detach()
    return payload


def _model_xml(
    config: Mapping[str, Any],
    staged_template: Path,
) -> bytes:
    model = config["model"]
    runtime = config["runtime"]

    root = ET.Element("model")
    _add_text(root, "model-type", "DeterministicAtlas")
    _add_text(root, "dimension", model["dimension"])
    _add_text(root, "dtype", runtime["precision"])
    _add_text(root, "random-seed", runtime["random_seed"])
    _add_text(
        root,
        "initial-cp-spacing",
        model["deformation"]["initial_control_point_spacing"],
    )
    template = ET.SubElement(root, "template")
    obj = ET.SubElement(template, "object", {"id": model["object_id"]})
    _add_text(obj, "deformable-object-type", "SurfaceMesh")
    _add_text(obj, "attachment-type", model["attachment"]["type"])
    _add_text(obj, "noise-std", model["noise_std"])
    _add_text(obj, "kernel-type", runtime["kernel_backend"])
    _add_text(obj, "kernel-device", "cpu")
    _add_text(obj, "kernel-width", model["attachment"]["kernel_width"])
    _add_text(obj, "filename", staged_template.as_posix())

    deformation = ET.SubElement(root, "deformation-parameters")
    _add_text(deformation, "kernel-width", model["deformation"]["kernel_width"])
    _add_text(deformation, "kernel-type", runtime["kernel_backend"])
    _add_text(deformation, "kernel-device", "cpu")
    _add_text(deformation, "number-of-timepoints", model["deformation"]["timepoints"])
    return _render_xml(root)


def _dataset_xml(
    config: Mapping[str, Any],
    staged_subjects: Sequence[Path],
) -> bytes:
    root = ET.Element("data_set")
    for subject_path in staged_subjects:
        subject = ET.SubElement(root, "subject", {"id": subject_path.name})
        visit = ET.SubElement(subject, "visit", {"id": "experiment"})
        filename = ET.SubElement(
            visit,
            "filename",
            {"object_id": config["model"]["object_id"]},
        )
        filename.text = subject_path.as_posix()
    return _render_xml(root)


def _optimization_xml(
    config: Mapping[str, Any],
    *,
    state_file: str | None = None,
) -> bytes:
    optimization = config["optimization"]
    method = {
        "gradient_ascent": "GradientAscent",
        "lbfgs": "ScipyLBFGS",
    }[optimization["method"]]

    root = ET.Element("optimization-parameters")
    _add_text(root, "optimization-method-type", method)
    _add_text(root, "optimized-log-likelihood", "complete")
    _add_text(root, "number-of-processes", config["runtime"]["processes"])
    _add_text(root, "gpu-mode", "none")
    _add_text(root, "initial-step-size", optimization["initial_step_size"])
    _add_text(root, "max-iterations", optimization["max_iterations"])
    _add_text(root, "convergence-tolerance", optimization["convergence_tolerance"])
    _add_text(root, "downsampling-factor", optimization["downsampling_factor"])
    _add_text(
        root,
        "max-line-search-iterations",
        optimization["max_line_search_iterations"],
    )
    _add_text(root, "save-every-n-iters", optimization["save_every_n_iterations"])
    _add_text(root, "print-every-n-iters", optimization["print_every_n_iterations"])
    _add_text(
        root,
        "scale-initial-step-size",
        "On" if optimization["scale_initial_step_size"] else "Off",
    )
    _add_text(
        root,
        "use-sobolev-gradient",
        "On" if optimization["use_sobolev_gradient"] else "Off",
    )
    _add_text(
        root,
        "sobolev-kernel-width-ratio",
        optimization["sobolev_kernel_width_ratio"],
    )
    _add_text(
        root,
        "use-rk2",
        "On" if config["model"]["deformation"]["use_rk2"] else "Off",
    )
    _add_text(root, "freeze-template", "On" if optimization["freeze_template"] else "Off")
    _add_text(
        root,
        "freeze-control-points",
        "On" if optimization["freeze_control_points"] else "Off",
    )
    if state_file is not None:
        _add_text(root, "state-file", state_file)
    return _render_xml(root)


def render_engine_file_bytes(
    config: Mapping[str, Any],
    staged_template: Path,
    staged_subjects: Sequence[Path],
) -> dict[str, bytes]:
    """Render the exact three Deformetrica XML inputs without writing files."""

    validate_reference_config(config)
    return {
        "model.xml": _model_xml(config, staged_template),
        "data_set.xml": _dataset_xml(config, staged_subjects),
        "optimization_parameters.xml": _optimization_xml(config),
    }


def generate_engine_files(
    config: Mapping[str, Any],
    engine_directory: Path,
    staged_template: Path,
    staged_subjects: Sequence[Path],
) -> tuple[Path, Path, Path]:
    """Generate the three explicit XML inputs used by Deformetrica 4.3."""

    validate_reference_config(config)
    rendered = render_engine_file_bytes(config, staged_template, staged_subjects)
    model_path = engine_directory / "model.xml"
    dataset_path = engine_directory / "data_set.xml"
    optimization_path = engine_directory / "optimization_parameters.xml"
    model_path.write_bytes(rendered["model.xml"])
    dataset_path.write_bytes(rendered["data_set.xml"])
    optimization_path.write_bytes(rendered["optimization_parameters.xml"])
    return model_path, dataset_path, optimization_path


def generate_resume_optimization_file(
    config: Mapping[str, Any],
    path: Path,
) -> Path:
    """Generate optimization XML that resumes from the run-local state file."""

    validate_reference_config(config)
    path.write_bytes(
        _optimization_xml(
            config,
            state_file="../output/deformetrica-state.p",
        )
    )
    return path


def _command_run_directory(path: Path, *, follow_symlinks: bool) -> Path:
    return path.resolve() if follow_symlinks else path.absolute()


def _windows_to_wsl(path: Path, *, follow_symlinks: bool = True) -> str:
    raw = str(_command_run_directory(path, follow_symlinks=follow_symlinks))
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if not match:
        raise ConfigurationError(f"Cannot translate path to WSL: {path}")
    remainder = PureWindowsPath(raw).parts[1:]
    return "/mnt/{}/{}".format(match.group(1).lower(), "/".join(remainder))


def build_command(
    config: Mapping[str, Any],
    run_directory: Path,
    *,
    follow_run_directory_symlinks: bool = True,
) -> CommandSpec:
    """Resolve the exact native or WSL command for a prepared run."""

    validate_reference_config(config)
    runtime = config["runtime"]
    launcher = runtime["launcher"]
    environment = {
        "OMP_NUM_THREADS": str(runtime["threads"]),
        "USE_CUDA": "0",
        "CUDA_VISIBLE_DEVICES": "-1",
    }
    arguments = (
        "estimate",
        "engine/model.xml",
        "engine/data_set.xml",
        "-p",
        "engine/optimization_parameters.xml",
        "--output=output",
        "-v",
        runtime["verbosity"],
    )
    command_run_directory = _command_run_directory(
        run_directory,
        follow_symlinks=follow_run_directory_symlinks,
    )

    if launcher["type"] == "native":
        executable = launcher["executable"]
        return CommandSpec(
            argv=(executable, *arguments),
            working_directory=str(command_run_directory),
            environment=environment,
        )

    if launcher["type"] == "wsl":
        if os.name != "nt":
            raise ConfigurationError("The WSL launcher is only available from Windows.")
        if shutil.which("wsl.exe") is None:
            raise ConfigurationError("wsl.exe is not available on PATH.")
        wsl_directory = _windows_to_wsl(
            run_directory,
            follow_symlinks=follow_run_directory_symlinks,
        )
        env_arguments = tuple(f"{key}={value}" for key, value in environment.items())
        return CommandSpec(
            argv=(
                "wsl.exe",
                "-d",
                launcher["distribution"],
                "--cd",
                wsl_directory,
                "--",
                "env",
                *env_arguments,
                launcher["executable"],
                *arguments,
            ),
            working_directory=str(command_run_directory),
            environment=environment,
        )

    if launcher["type"] == "container":
        engine = launcher["engine"]
        image = launcher["image"]
        mount = (
            f"type=bind,source={command_run_directory},"
            f"target={CONTAINER_WORKING_DIRECTORY}"
        )
        container_environment = tuple(
            argument
            for key, value in environment.items()
            for argument in ("--env", f"{key}={value}")
        )
        user_arguments = (
            ()
            if os.name == "nt"
            else ("--user", f"{os.getuid()}:{os.getgid()}")
        )
        return CommandSpec(
            argv=(
                engine,
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--tmpfs=/tmp:rw,exec,nosuid,size=1g",
                "--mount",
                mount,
                "--workdir",
                CONTAINER_WORKING_DIRECTORY,
                *user_arguments,
                *container_environment,
                image,
                *arguments,
            ),
            working_directory=str(command_run_directory),
            environment=environment,
        )

    raise ConfigurationError(f"Unsupported launcher type: {launcher['type']}")


def ensure_launcher_available(config: Mapping[str, Any]) -> None:
    """Fail before computation when the configured launcher cannot be invoked."""

    launcher = config["runtime"]["launcher"]
    if launcher["type"] == "native":
        executable = launcher["executable"]
        if Path(executable).is_absolute() and not Path(executable).is_file():
            raise ConfigurationError(f"Deformetrica executable does not exist: {executable}")
        if not Path(executable).is_absolute() and shutil.which(executable) is None:
            raise ConfigurationError(f"Deformetrica executable is not on PATH: {executable}")
        return

    if launcher["type"] == "wsl":
        probe = probe_wsl_launcher(launcher)
        if not probe.ready:
            guidance = f" {probe.guidance}" if probe.guidance else ""
            raise ConfigurationError(
                f"Deformetrica WSL runtime is unavailable: {probe.summary}.{guidance}"
            )
        return

    if launcher["type"] == "container":
        engine = launcher["engine"]
        if shutil.which(engine) is None:
            raise ConfigurationError(
                f"Container engine is not available on PATH: {engine}"
            )
        try:
            completed = subprocess.run(
                [engine, "image", "inspect", launcher["image"]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                **hidden_windows_process_kwargs(),
            )
        except subprocess.TimeoutExpired as error:
            raise ConfigurationError(
                f"Timed out while inspecting container image: {launcher['image']}"
            ) from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ConfigurationError(
                f"Container image is not available locally: {launcher['image']}. "
                f"Build or pull it before execution. {detail}"
            )
        return

    raise ConfigurationError(f"Unsupported launcher type: {launcher['type']}")
