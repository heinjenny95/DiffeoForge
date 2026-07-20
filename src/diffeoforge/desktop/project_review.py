"""Qt-independent parameter and workload review for desktop projects."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.report import (
    collect_preflight,
    default_preflight_report_path,
    write_preflight_report,
)


@dataclass(frozen=True)
class ReviewItem:
    """One effective value and the reason it matters to a researcher."""

    label: str
    value: str
    explanation: str


@dataclass(frozen=True)
class ProjectReviewResult:
    """Display-ready evidence collected through shared validated core services."""

    engine: DesktopEngine
    project_name: str
    config_path: Path
    config_sha256: str
    report_path: Path
    report_label: str
    subject_count: int
    parameters: tuple[ReviewItem, ...]
    workload: tuple[ReviewItem, ...]
    warnings: tuple[str, ...]
    scientific_boundary: str


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return f"{value:.6g}"


def _bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.3g} {unit}"


def _setting(value: Any, *, none: str = "automatic maximum") -> str:
    if value is None:
        return none
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return " → ".join(str(item) for item in value)
    return str(value)


def _reference_review(config_path: Path, config_sha256: str) -> ProjectReviewResult:
    preflight = collect_preflight(config_path)
    config = preflight.config
    model = config["model"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    runtime = config["runtime"]
    diagonal = preflight.template.bounding_box_diagonal
    ratios = preflight.parameter_ratios
    report_path = default_preflight_report_path(config_path)
    write_preflight_report(preflight, report_path, overwrite=report_path.exists())

    parameters = (
        ReviewItem(
            "Coordinate unit",
            str(config["input"]["units"]),
            "Determines the physical interpretation of all lengths and distances.",
        ),
        ReviewItem(
            "Attachment",
            (
                f"{model['attachment']['type']} · width "
                f"{_number(model['attachment']['kernel_width'])}"
            ),
            "Compares template and subject surfaces; the width controls the spatial scale.",
        ),
        ReviewItem(
            "Deformation kernel",
            _number(deformation["kernel_width"]),
            "Controls the spatial smoothness of the diffeomorphic deformation.",
        ),
        ReviewItem(
            "Control-point spacing",
            _number(deformation["initial_control_point_spacing"]),
            "Controls the density of the initial deformation parameters.",
        ),
        ReviewItem(
            "Time discretization",
            f"{deformation['timepoints']} time points · RK2 {_setting(deformation['use_rk2'])}",
            "Defines the numerical discretization of the deformation trajectory.",
        ),
        ReviewItem(
            "Noise standard deviation",
            _number(model["noise_std"]),
            "Weights the data-attachment term in the atlas model.",
        ),
        ReviewItem(
            "Optimization",
            (
                f"max. {optimization['max_iterations']} iterations · step "
                f"{_number(optimization['initial_step_size'])}"
            ),
            "Starter values for gradient ascent; convergence and biological "
            "plausibility must be reviewed.",
        ),
        ReviewItem(
            "Reproducibility",
            (
                f"Seed {runtime['random_seed']} · {runtime['threads']} Threads · "
                f"{runtime['precision']}"
            ),
            "Explicit engine-execution settings for the external reference route.",
        ),
    )
    subject_points = [subject.points for subject in preflight.subjects]
    subject_faces = [subject.cells for subject in preflight.subjects]
    workload = (
        ReviewItem(
            "Dataset",
            f"{len(preflight.subjects)} subjects + 1 template",
            "Fully parsed and validated VTK surfaces.",
        ),
        ReviewItem(
            "Template scale",
            _number(diagonal),
            "Template bounding-box diagonal; reference scale for generated starter values.",
        ),
        ReviewItem(
            "Attachment / template scale",
            f"{ratios['Attachment kernel width / template diagonal']:.3%}",
            "Dimensionless ratio from the effective preflight.",
        ),
        ReviewItem(
            "Deformation / template scale",
            f"{ratios['Deformation kernel width / template diagonal']:.3%}",
            "Dimensionless ratio from the effective preflight.",
        ),
        ReviewItem(
            "Mesh resolution",
            (
                f"{min(subject_points):,}–{max(subject_points):,} points · "
                f"{min(subject_faces):,}–{max(subject_faces):,} faces"
            ).replace(",", " "),
            "Observed subject-mesh range, not a quality assessment of the shape "
            "representation.",
        ),
        ReviewItem(
            "Source data",
            _bytes(preflight.total_input_bytes),
            "File size of the reviewed meshes; not a RAM or computation-time forecast.",
        ),
        ReviewItem(
            "Compute cost",
            "not modeled",
            "Execution occurs in the external Deformetrica 4.3 environment; "
            "a pilot measurement is required.",
        ),
    )
    warnings = (
        "Geometry-scaled starter values are exploratory and are not scientifically "
        "validated presets.",
        *preflight.notices,
        "DiffeoForge did not start Deformetrica and does not forecast peak RAM or "
        "computation time here.",
    )
    return ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name=str(config["project"]["name"]),
        config_path=config_path,
        config_sha256=config_sha256,
        report_path=report_path,
        report_label="Preflight-Report",
        subject_count=len(preflight.subjects),
        parameters=parameters,
        workload=workload,
        warnings=warnings,
        scientific_boundary=(
            "This view confirms the schema, paths, mesh geometry, and effective parameters. "
            "It confirms neither parameter suitability nor biological validity and does not "
            "execute the external Deformetrica engine."
        ),
    )


def _modern_review(config_path: Path, config_sha256: str) -> ProjectReviewResult:
    try:
        from diffeoforge.modern_workflow import load_modern_workflow_config
        from diffeoforge.modern_workload import (
            REPORT_HTML_NAME,
            SCIENTIFIC_BOUNDARY,
            collect_modern_workload,
            default_modern_workload_path,
            write_modern_workload_report,
        )
    except ImportError as error:
        raise RuntimeError(
            "Modern engine dependencies are missing; install diffeoforge[modern-engine]."
        ) from error

    config = load_modern_workflow_config(config_path)
    report = collect_modern_workload(config_path)
    report_directory = default_modern_workload_path(config_path)
    write_modern_workload_report(
        report,
        report_directory,
        overwrite=report_directory.exists(),
    )
    report_path = report_directory / REPORT_HTML_NAME
    model = config["model"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    analysis = config["analysis"]
    runtime = config["runtime"]
    procrustes = config["preprocessing"]["procrustes"]
    pairwise = report["engine"]["pairwise_evaluation"]
    pairwise_value = "dense · complete pair matrices"
    if pairwise["mode"] == "blockwise":
        pairwise_value = (
            f"blockwise · tiles {pairwise['query_tile_size']} × {pairwise['source_tile_size']}"
        )
    noise_std = math.sqrt(model["noise_variance"])
    parameters = (
        ReviewItem(
            "Coordinate unit",
            str(config["input"]["units"]),
            "Determines the physical interpretation of all lengths and distances.",
        ),
        ReviewItem(
            "Attachment",
            (
                f"{model['attachment']['type']} · width "
                f"{_number(model['attachment']['kernel_width'])}"
            ),
            "Compares template and subject surfaces at the configured spatial scale.",
        ),
        ReviewItem(
            "Deformation kernel",
            _number(deformation["kernel_width"]),
            "Controls the spatial smoothness of the diffeomorphic deformation.",
        ),
        ReviewItem(
            "Control points",
            f"{config['initialization']['control_points']['count']} · farthest template vertices",
            "Count and deterministic initialization of the deformation parameters.",
        ),
        ReviewItem(
            "Time integration",
            (
                f"{deformation['timepoints']} time points · "
                f"{deformation['shooting_integrator']} / {deformation['flow_integrator']}"
            ),
            "Explicit discretization for shooting and template flow.",
        ),
        ReviewItem(
            "Noise variance",
            f"{_number(model['noise_variance'])} · standard deviation {_number(noise_std)}",
            "Weights the data-attachment term; the standard deviation is derived exactly "
            "from the variance.",
        ),
        ReviewItem(
            "Optimization blocks",
            f"{_setting(optimization['block_order'])} · max. {optimization['max_cycles']} cycles",
            "Deterministic update order and a hard cycle cap; reaching the cap is not convergence.",
        ),
        ReviewItem(
            "Convergence rule",
            f"every block gradient ≤ {_number(optimization['gradient_tolerance'])}",
            "Converged is recorded only when all parameter blocks satisfy the declared "
            "gradient tolerance in the same completed cycle.",
        ),
        ReviewItem(
            "PCA output",
            (
                f"components {_setting(analysis['pca_components'])} · "
                f"deformations {_setting(analysis['deformation_components'])}"
            ),
            "Limits later PCA and extreme-shape artifacts, not atlas optimization itself.",
        ),
        ReviewItem(
            "Landmark-Procrustes",
            _setting(procrustes["enabled"]),
            "Optional homologous-landmark alignment before atlas computation.",
        ),
        ReviewItem(
            "Execution",
            f"CPU · float64 · {runtime['threads']} Threads · Seed {runtime['random_seed']}",
            "Effective, reproducible execution contract for the experimental Modern engine.",
        ),
        ReviewItem(
            "Pairwise evaluation",
            pairwise_value,
            "The same execution strategy used by the atlas and accounted for by the "
            "workload report.",
        ),
    )
    operation = report["operation_model"]
    forward = operation["one_objective_forward"]
    logical = operation["largest_logical_pair"]
    tile = operation["largest_execution_tile"]
    payload = report["payload_model"]
    optimizer = report["optimizer_bound"]
    output = report["output_bound"]
    host = report["host_observations"]
    template_faces = int(report["input"]["template"]["triangles"])
    subject_face_counts = tuple(
        int(subject["triangles"]) for subject in report["input"]["subjects"]
    )
    maximum_faces = max((template_faces, *subject_face_counts))
    workload = (
        ReviewItem(
            "Dataset",
            f"{report['input']['subject_count']} subjects + 1 template",
            "Fully inventoried meshes; hashes and dimensions are in the HTML/JSON report.",
        ),
        ReviewItem(
            "Mesh faces",
            (
                f"template {_number(template_faces)} · subjects "
                f"{_number(min(subject_face_counts))}–{_number(max(subject_face_counts))}"
            ),
            "Observed input resolution, recorded before compute; DiffeoForge does not "
            "silently decimate or remesh these files.",
        ),
        ReviewItem(
            "One objective forward pass",
            (
                f"{_number(forward['gaussian_calls'])} Gaussian calls · "
                f"{_number(forward['gaussian_pair_elements'])} pair elements"
            ),
            "Exact formula for the currently configured engine and mesh inventory.",
        ),
        ReviewItem(
            "Largest logical pair",
            (
                f"{logical['rows']} × {logical['columns']} · "
                f"{_bytes(logical['float64_xyz_difference_tensor_bytes'])} "
                "XYZ differences"
            ),
            "Logical all-pairs dimensions; blockwise evaluation does not necessarily "
            "allocate this all at once.",
        ),
        ReviewItem(
            "Largest execution tile",
            (
                f"{tile['tile_rows']} × {tile['tile_columns']} · "
                f"{_bytes(tile['float64_xyz_difference_tensor_bytes'])}"
            ),
            "Exact upper bound for one configured XYZ-difference tile, not total peak RAM.",
        ),
        ReviewItem(
            "Known payload arithmetic",
            _bytes(payload["known_payload_arithmetic_subtotal_bytes"]),
            "Explicitly accounted tensor payloads; Autograd, allocator, BLAS, and the "
            "operating system are intentionally excluded.",
        ),
        ReviewItem(
            "Objective/gradient upper bound",
            _number(optimizer["objective_gradient_evaluation_upper_bound"]),
            "Configuration-derived upper bound including line search, not an observed "
            "iteration count.",
        ),
        ReviewItem(
            "Gaussian pair-element upper bound",
            _number(optimizer["gaussian_pair_elements_upper_bound"]),
            "Exact multiplication of the forward model and optimizer upper bound.",
        ),
        ReviewItem(
            "Maximum bundle meshes",
            _number(output["maximum_bundle_vtk_meshes"]),
            "Upper bound for later atlas, reconstruction, and PCA VTK artifacts.",
        ),
        ReviewItem(
            "Observed computer",
            (
                f"{host.get('logical_cpus') or 'unknown'} logical CPUs · "
                f"{_bytes(host.get('physical_memory_bytes'))} physical RAM"
            ),
            "Host observation at planning time; not a promise that these resources are free.",
        ),
        ReviewItem(
            "Peak RAM and computation time",
            "unknown · pilot measurement required",
            "DiffeoForge does not invent forecasts from incomplete memory and time models.",
        ),
    )
    high_detail_warning: tuple[str, ...] = ()
    if maximum_faces >= 5_000:
        if pairwise["mode"] == "dense":
            high_detail_warning = (
                "High-face-count input is configured with dense pairwise evaluation. "
                "Review the exact logical-pair evidence and benchmark an explicit blockwise "
                "plan before a production run.",
            )
        else:
            high_detail_warning = (
                "High-face-count input uses explicit blockwise tiles. The reported tile "
                "bound is not a total-RAM or computation-time guarantee; a representative "
                "benchmark is still required before production.",
            )
    warnings = (
        "Geometry-scaled starter values are exploratory and are not scientifically "
        "validated presets.",
        *high_detail_warning,
        *(str(warning) for warning in report["warnings"]),
    )
    return ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name=str(config["project"]["name"]),
        config_path=config_path,
        config_sha256=config_sha256,
        report_path=report_path,
        report_label="Modern-Workload-Report",
        subject_count=report["input"]["subject_count"],
        parameters=parameters,
        workload=workload,
        warnings=warnings,
        scientific_boundary=(
            "This view shows exact all-pairs operation counts and known tensor payloads for "
            "the configured CPU/float64 plan. It is not a peak-RAM forecast, computation-"
            "time prediction, benchmark measurement, or guarantee for 300 subjects. Autograd, "
            "memory management, BLAS threads, and operating-system load can change real "
            f"resource use. Original report contract: {SCIENTIFIC_BOUNDARY}"
        ),
    )


def review_project(
    config_path: Path | str,
    engine: DesktopEngine | str,
) -> ProjectReviewResult:
    """Review one generated project without executing either atlas engine."""

    source = Path(config_path).expanduser().resolve()
    selected = DesktopEngine(engine)
    hash_before = sha256_file(source)
    if selected is DesktopEngine.MODERN_CPU:
        result = _modern_review(source, hash_before)
    else:
        result = _reference_review(source, hash_before)
    if sha256_file(source) != hash_before:
        raise RuntimeError("Project configuration changed while it was being reviewed")
    return result
