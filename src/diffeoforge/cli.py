"""Command-line entry point for the pre-alpha workflow scaffold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError, load_config
from diffeoforge.diagnostics import DEFAULT_CONTAINER_IMAGE, run_doctor
from diffeoforge.initialization import (
    SUPPORTED_UNITS,
    detect_template,
    initialize_project,
)
from diffeoforge.reference import compare_reference_run
from diffeoforge.reference_approved_preparation import prepare_approved_reference_run
from diffeoforge.reference_calibration import (
    build_reference_calibration_plan,
    read_pilot_subject_declarations,
)
from diffeoforge.reference_calibration_report import export_reference_calibration_plan
from diffeoforge.reference_calibration_study import (
    ReferenceCalibrationStudyRunner,
    create_reference_calibration_search_extension_study,
    create_reference_calibration_study,
    load_reference_calibration_study,
    record_reference_calibration_stage_review,
)
from diffeoforge.reference_holdout_study import (
    ReferenceHoldoutStudyRunner,
    create_reference_holdout_study,
    load_reference_holdout_study,
)
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    serialize_reference_preparation_approval_verification,
    verify_saved_reference_preparation_approval,
    write_reference_preparation_approval,
    write_reference_preparation_approval_verification,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    write_reference_preparation_plan_report,
)
from diffeoforge.reference_preparation_reconciliation import (
    reconcile_reference_preparation,
    serialize_reference_preparation_reconciliation,
    write_reference_preparation_reconciliation,
)
from diffeoforge.reference_preparation_reconciliation_verification import (
    serialize_reference_preparation_reconciliation_verification,
    verify_saved_reference_preparation_reconciliation,
    write_reference_preparation_reconciliation_verification,
)
from diffeoforge.reference_preparation_verification import (
    serialize_reference_preparation_plan_verification,
    verify_saved_reference_preparation_plan,
    write_reference_preparation_plan_verification,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters
from diffeoforge.reference_validation_study import (
    ReferenceValidationStudyRunner,
    create_reference_validation_study,
    load_reference_validation_study,
)
from diffeoforge.reference_validation_synthetic import (
    evaluate_synthetic_correspondence_error,
    write_synthetic_validation_benchmark,
)
from diffeoforge.report import (
    collect_preflight,
    default_preflight_report_path,
    write_preflight_report,
)
from diffeoforge.result_report import collect_run_report, write_result_report
from diffeoforge.runs import (
    execute_run,
    prepare_resume_run,
    prepare_run,
    recover_run,
    run_status,
)
from diffeoforge.scientific_report import (
    ScientificReportError,
    collect_scientific_atlas_report,
    verify_scientific_atlas_report,
    write_scientific_atlas_report,
)
from diffeoforge.surface_io import is_supported_surface_path

_AUTO_REPORT = Path("__diffeoforge_auto_report__")


def _write_stdout_bytes(payload: bytes) -> None:
    """Write exact machine-readable bytes when stdout exposes a binary buffer."""

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload.decode("utf-8"))
        return
    buffer.write(payload)
    buffer.flush()


def _show_modern_progress(event) -> None:
    stage = f"{event.completed_stages}/{event.total_stages} stages"
    if event.optimizer is None:
        print(
            f"Progress [{stage}] {event.phase} {event.status}: {event.message}",
            flush=True,
        )
        return
    optimizer = event.optimizer
    decision = f"{optimizer.completed_decisions}/{optimizer.maximum_decisions} decisions"
    block = "initial" if optimizer.block is None else optimizer.block
    print(
        f"Progress [{stage}; optimizer {decision}] cycle "
        f"{optimizer.cycle}/{optimizer.max_cycles} {block} {optimizer.status}; "
        f"objective={optimizer.objective:.12g}; "
        f"line-search={optimizer.line_search_evaluations}",
        flush=True,
    )


def _remote_client_from_args(args):
    from diffeoforge.remote_atlas_transport import RemoteAtlasClient, load_remote_token

    return RemoteAtlasClient(
        args.server,
        load_remote_token(args.token_file),
        ca_file=args.ca_file,
    )


def _tile_shape_argument(value: str) -> tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError("tile shape must use QUERYxSOURCE, for example 64x128")
    try:
        query_tile_size, source_tile_size = (int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "tile shape must contain integer query and source sizes"
        ) from error
    if not 1 <= query_tile_size <= 999_999 or not 1 <= source_tile_size <= 999_999:
        raise argparse.ArgumentTypeError("tile dimensions must be between 1 and 999999")
    return query_tile_size, source_tile_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffeoforge",
        description="Reproducible diffeomorphic atlas workflows for 3D surface meshes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check whether the host and frozen reference backend are ready.",
    )
    doctor_parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Project directory whose write access and free space should be checked.",
    )
    doctor_parser.add_argument("--engine", default="docker", choices=("docker",))
    doctor_parser.add_argument("--image", default=DEFAULT_CONTAINER_IMAGE)
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the machine-readable doctor result.",
    )

    init_parser = subparsers.add_parser(
        "init",
        help="Inspect a mesh directory and create a transparent starter configuration.",
    )
    init_parser.add_argument(
        "mesh_directory",
        type=Path,
        help="Directory containing subject VTK files.",
    )
    init_parser.add_argument(
        "--template",
        type=Path,
        help="Initial template mesh. Auto-detected only when named template.vtk.",
    )
    init_parser.add_argument(
        "--units",
        choices=SUPPORTED_UNITS,
        help="Coordinate unit shared by every mesh; prompted when omitted interactively.",
    )
    init_parser.add_argument("--project-name", help="Human-readable atlas name.")
    init_parser.add_argument(
        "--subject-pattern",
        default="*.vtk",
        help="Glob selecting subjects inside the mesh directory (default: *.vtk).",
    )
    init_parser.add_argument(
        "--config",
        type=Path,
        default=Path("atlas.yaml"),
        help="Configuration to create (default: ./atlas.yaml).",
    )
    init_parser.add_argument(
        "--runs-directory",
        type=Path,
        help="Run root written to the configuration (default: ./runs).",
    )
    init_parser.add_argument(
        "--attachment-kernel-width",
        type=float,
        help="Explicit value; otherwise 0.10 times the template diagonal.",
    )
    init_parser.add_argument(
        "--deformation-kernel-width",
        type=float,
        help="Explicit value; otherwise 0.15 times the template diagonal.",
    )
    init_parser.add_argument(
        "--control-point-spacing",
        type=float,
        help="Explicit value; otherwise 0.15 times the template diagonal.",
    )
    init_parser.add_argument(
        "--noise-std",
        type=float,
        help="Explicit value; otherwise 0.025 times the template diagonal.",
    )
    init_parser.add_argument("--threads", type=int, help="CPU threads (default: at most 4).")
    init_parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help=(
            "Reference execution mode: CPU only or Deformetrica KeOps CUDA kernels (default: cpu)."
        ),
    )
    init_parser.add_argument(
        "--random-seed",
        type=int,
        default=20260715,
        help="Non-negative reproducibility seed (default: 20260715).",
    )
    init_parser.add_argument(
        "--image",
        default=DEFAULT_CONTAINER_IMAGE,
        help=f"Local reference image (default: {DEFAULT_CONTAINER_IMAGE}).",
    )
    init_parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not create the default HTML preflight report.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing generated configuration and report.",
    )

    modern_init_parser = subparsers.add_parser(
        "modern-init",
        help="Create an explicit starter configuration for the modern float64 path.",
    )
    modern_init_parser.add_argument("mesh_directory", type=Path)
    modern_init_parser.add_argument("--template", type=Path)
    modern_init_parser.add_argument("--units", choices=SUPPORTED_UNITS)
    modern_init_parser.add_argument("--project-name")
    modern_init_parser.add_argument("--subject-pattern", default="*.vtk")
    modern_init_parser.add_argument("--config", type=Path, default=Path("modern-atlas.yaml"))
    modern_init_parser.add_argument("--output-directory", type=Path)
    modern_init_parser.add_argument(
        "--landmarks",
        type=Path,
        help="Optional labelled landmark CSV; enables recorded Procrustes alignment.",
    )
    modern_init_parser.add_argument("--control-points", type=int, default=9)
    modern_init_parser.add_argument("--attachment-kernel-width", type=float)
    modern_init_parser.add_argument("--deformation-kernel-width", type=float)
    modern_init_parser.add_argument("--noise-variance", type=float)
    modern_init_parser.add_argument("--max-cycles", type=int, default=3)
    modern_init_parser.add_argument("--threads", type=int)
    modern_init_parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Exact execution device; CUDA never falls back to CPU (default: cpu).",
    )
    modern_init_parser.add_argument("--random-seed", type=int, default=20260715)
    modern_init_parser.add_argument(
        "--pairwise-mode",
        choices=("dense", "blockwise"),
        default="dense",
        help="Exact pairwise execution mode (default: dense correctness oracle).",
    )
    modern_init_parser.add_argument(
        "--query-tile-size",
        type=int,
        help="Required positive query-row tile size for --pairwise-mode blockwise.",
    )
    modern_init_parser.add_argument(
        "--source-tile-size",
        type=int,
        help="Required positive source-row tile size for --pairwise-mode blockwise.",
    )
    modern_init_parser.add_argument(
        "--template-gradient",
        choices=("euclidean", "sobolev"),
        default="euclidean",
        help=(
            "Template optimizer gradient; Sobolev uses the Deformetrica-compatible "
            "Gaussian convolution (default: euclidean)."
        ),
    )
    modern_init_parser.add_argument(
        "--sobolev-kernel-width-ratio",
        type=float,
        default=1.0,
        help=(
            "Sobolev smoothing width divided by deformation-kernel width "
            "(default: 1.0)."
        ),
    )
    modern_init_parser.add_argument("--force", action="store_true")

    modern_reference_design_parser = subparsers.add_parser(
        "modern-reference-qualification-init",
        help=(
            "Freeze a fixed-template, fixed-control-point Modern Engine comparison "
            "against a completed Deformetrica run without computing it."
        ),
    )
    modern_reference_design_parser.add_argument("reference_run", type=Path)
    modern_reference_design_parser.add_argument("--output", type=Path, required=True)
    modern_reference_design_parser.add_argument("--subjects", type=int, default=5)
    modern_reference_design_parser.add_argument("--cycles", type=int, default=3)
    modern_reference_design_parser.add_argument("--threads", type=int, default=4)
    modern_reference_design_parser.add_argument(
        "--scope",
        choices=("fixed_reference", "full_atlas"),
        default="fixed_reference",
        help=(
            "Qualification scope: isolate momenta against a fixed reference or estimate "
            "momenta, template, and control points together (default: fixed_reference)."
        ),
    )
    modern_reference_design_parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Exact Modern Engine execution device; CUDA never falls back to CPU.",
    )
    modern_reference_design_parser.add_argument(
        "--tile-size",
        type=int,
        default=64,
        help="Explicit equal query/source rows for exact blockwise recompute (default: 64).",
    )
    modern_reference_design_parser.add_argument(
        "--optimizer-direction",
        choices=("steepest", "lbfgs"),
        default="steepest",
        help="Declared momenta direction update (default: steepest).",
    )
    modern_reference_design_parser.add_argument(
        "--lbfgs-history-size",
        type=int,
        default=10,
        help="Retained L-BFGS curvature pairs when --optimizer-direction lbfgs.",
    )
    modern_reference_design_parser.add_argument(
        "--lbfgs-initial-step-size",
        type=float,
        default=1.0,
        help="Armijo starting step for curvature-scaled L-BFGS directions.",
    )
    modern_reference_design_parser.add_argument(
        "--line-search-condition",
        choices=("armijo", "strong_wolfe"),
        default="armijo",
        help="Declared acceptance rule for optimizer trial steps (default: armijo).",
    )
    modern_reference_design_parser.add_argument(
        "--strong-wolfe-curvature-constant",
        type=float,
        default=0.9,
        help="Strong-Wolfe directional-derivative contraction c2 (default: 0.9).",
    )
    modern_reference_design_parser.add_argument(
        "--strong-wolfe-maximum-step-size",
        type=float,
        default=10.0,
        help="Maximum bracket-expansion step for strong-Wolfe search (default: 10).",
    )
    modern_reference_design_parser.add_argument(
        "--subject-batch-size",
        type=int,
        help=(
            "Optional number of subjects retained per objective/gradient batch; "
            "smaller values trade extra forward work for bounded autograd memory."
        ),
    )
    modern_reference_design_parser.add_argument(
        "--template-gradient",
        choices=("euclidean", "sobolev"),
        default="euclidean",
        help=(
            "Template optimizer gradient for full-atlas scope; Sobolev uses the "
            "Deformetrica-compatible Gaussian convolution (default: euclidean)."
        ),
    )
    modern_reference_design_parser.add_argument(
        "--sobolev-kernel-width-ratio",
        type=float,
        default=1.0,
        help=(
            "Sobolev smoothing width divided by deformation-kernel width "
            "(default: 1.0)."
        ),
    )

    modern_reference_continue_parser = subparsers.add_parser(
        "modern-reference-qualification-continue",
        help=(
            "Freeze a successor qualification that starts from one verified, "
            "non-converged Modern result."
        ),
    )
    modern_reference_continue_parser.add_argument("design_directory", type=Path)
    modern_reference_continue_parser.add_argument("modern_run", type=Path)
    modern_reference_continue_parser.add_argument("--output", type=Path, required=True)
    modern_reference_continue_parser.add_argument("--cycles", type=int, default=10)
    modern_reference_continue_parser.add_argument("--threads", type=int)

    modern_reference_verify_parser = subparsers.add_parser(
        "modern-reference-qualification-verify",
        help="Verify a frozen no-results-yet Modern/Deformetrica comparison design.",
    )
    modern_reference_verify_parser.add_argument("design_directory", type=Path)

    modern_reference_assess_parser = subparsers.add_parser(
        "modern-reference-qualification-assess",
        help="Assess a verified Modern run against its frozen Deformetrica reference design.",
    )
    modern_reference_assess_parser.add_argument("design_directory", type=Path)
    modern_reference_assess_parser.add_argument("modern_run", type=Path)
    modern_reference_assess_parser.add_argument("--output", type=Path, required=True)
    modern_reference_assess_parser.add_argument(
        "--metric-workers",
        type=int,
        default=4,
        help="Parallel surface-distance workers, from 1 to 8 (default: 4).",
    )

    modern_reference_assessment_verify_parser = subparsers.add_parser(
        "modern-reference-qualification-assessment-verify",
        help="Recompute and strictly verify a fixed-reference qualification assessment.",
    )
    modern_reference_assessment_verify_parser.add_argument(
        "assessment_directory",
        type=Path,
    )
    modern_reference_assessment_verify_parser.add_argument(
        "--metric-workers",
        type=int,
        default=4,
        help="Parallel surface-distance workers, from 1 to 8 (default: 4).",
    )

    modern_continuation_parser = subparsers.add_parser(
        "modern-continuation-init",
        help=(
            "Freeze a hash-bound successor from one verified, non-converged "
            "Modern workflow without running it."
        ),
    )
    modern_continuation_parser.add_argument("parent_run", type=Path)
    modern_continuation_parser.add_argument("--output", type=Path, required=True)
    modern_continuation_parser.add_argument("--cycles", type=int, default=10)
    modern_continuation_parser.add_argument("--threads", type=int)

    modern_continuation_verify_parser = subparsers.add_parser(
        "modern-continuation-verify",
        help="Verify a frozen no-results-yet Modern continuation plan.",
    )
    modern_continuation_verify_parser.add_argument("plan_directory", type=Path)

    modern_continuation_run_parser = subparsers.add_parser(
        "modern-continuation-verify-run",
        help="Verify that a completed Modern successor exactly matches its frozen plan.",
    )
    modern_continuation_run_parser.add_argument("plan_directory", type=Path)
    modern_continuation_run_parser.add_argument("successor_run", type=Path)

    modern_recovery_parser = subparsers.add_parser(
        "modern-checkpoint-recovery-init",
        help=(
            "Freeze a hash-bound successor from the latest complete-cycle checkpoint "
            "in one abandoned private Modern run."
        ),
    )
    modern_recovery_parser.add_argument("private_directory", type=Path)
    modern_recovery_parser.add_argument("--output", type=Path, required=True)
    modern_recovery_parser.add_argument(
        "--cycles",
        type=int,
        help="Override the default remaining cycle count; zero publishes the recovered state.",
    )
    modern_recovery_parser.add_argument("--threads", type=int)

    modern_recovery_verify_parser = subparsers.add_parser(
        "modern-checkpoint-recovery-verify",
        help="Verify a frozen no-results-yet Modern checkpoint recovery plan.",
    )
    modern_recovery_verify_parser.add_argument("plan_directory", type=Path)

    modern_recovery_run_parser = subparsers.add_parser(
        "modern-checkpoint-recovery-verify-run",
        help="Verify that a completed Modern recovery exactly matches its frozen checkpoint.",
    )
    modern_recovery_run_parser.add_argument("plan_directory", type=Path)
    modern_recovery_run_parser.add_argument("successor_run", type=Path)

    modern_run_parser = subparsers.add_parser(
        "modern-run",
        help="Execute one immutable experimental modern atlas/PCA workflow.",
    )
    modern_run_parser.add_argument("config", type=Path)
    modern_run_parser.add_argument(
        "--output",
        type=Path,
        help="Override the exact previously nonexistent run destination.",
    )

    modern_remote_package_parser = subparsers.add_parser(
        "modern-remote-package",
        help=(
            "Create a portable hash-bound Modern atlas request without uploading "
            "or starting computation."
        ),
    )
    modern_remote_package_parser.add_argument("config", type=Path)
    modern_remote_package_parser.add_argument("--output", type=Path, required=True)

    modern_remote_package_verify_parser = subparsers.add_parser(
        "modern-remote-package-verify",
        help="Verify one portable Modern atlas request without network or compute.",
    )
    modern_remote_package_verify_parser.add_argument("job_directory", type=Path)

    modern_remote_run_parser = subparsers.add_parser(
        "modern-remote-run",
        help="Execute one verified portable Modern request on this server/host.",
    )
    modern_remote_run_parser.add_argument("job_directory", type=Path)
    modern_remote_run_parser.add_argument("--output", type=Path, required=True)

    modern_remote_result_verify_parser = subparsers.add_parser(
        "modern-remote-result-verify",
        help="Bind and verify a downloaded Modern result against its exact request.",
    )
    modern_remote_result_verify_parser.add_argument("job_directory", type=Path)
    modern_remote_result_verify_parser.add_argument("result_directory", type=Path)

    modern_remote_token_parser = subparsers.add_parser(
        "modern-remote-token-init",
        help="Create a private high-entropy bearer-token file without printing its secret.",
    )
    modern_remote_token_parser.add_argument("output", type=Path)

    modern_remote_server_parser = subparsers.add_parser(
        "modern-remote-server",
        help="Serve an authenticated persistent Modern atlas queue.",
    )
    modern_remote_server_parser.add_argument("--root", type=Path, required=True)
    modern_remote_server_parser.add_argument("--token-file", type=Path, required=True)
    modern_remote_server_parser.add_argument("--host", default="127.0.0.1")
    modern_remote_server_parser.add_argument("--port", type=int, default=8787)
    modern_remote_server_parser.add_argument("--tls-certificate", type=Path)
    modern_remote_server_parser.add_argument("--tls-private-key", type=Path)
    modern_remote_server_parser.add_argument("--workers", type=int, default=1)
    modern_remote_server_parser.add_argument(
        "--max-active-jobs",
        type=int,
        default=100,
    )
    modern_remote_server_parser.add_argument(
        "--max-upload-bytes",
        type=int,
        default=8 * 1024**3,
    )

    def add_remote_client_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--server", required=True)
        command_parser.add_argument("--token-file", type=Path, required=True)
        command_parser.add_argument("--ca-file", type=Path)

    modern_remote_submit_parser = subparsers.add_parser(
        "modern-remote-submit",
        help="Explicitly upload one verified portable request to an authenticated server.",
    )
    modern_remote_submit_parser.add_argument("job_directory", type=Path)
    modern_remote_submit_parser.add_argument(
        "--submission-id",
        help="Reuse a previously printed 32-character submission ID after an uncertain upload.",
    )
    add_remote_client_arguments(modern_remote_submit_parser)

    modern_remote_status_parser = subparsers.add_parser(
        "modern-remote-status",
        help="Read one authenticated remote job status and optional progress events.",
    )
    modern_remote_status_parser.add_argument("job_id")
    modern_remote_status_parser.add_argument("--events", action="store_true")
    modern_remote_status_parser.add_argument("--after", type=int, default=-1)
    modern_remote_status_parser.add_argument("--limit", type=int, default=100)
    add_remote_client_arguments(modern_remote_status_parser)

    modern_remote_wait_parser = subparsers.add_parser(
        "modern-remote-wait",
        help="Stream new progress until one authenticated remote job is terminal.",
    )
    modern_remote_wait_parser.add_argument("job_id")
    modern_remote_wait_parser.add_argument("--poll-seconds", type=float, default=2.0)
    modern_remote_wait_parser.add_argument("--download", type=Path)
    modern_remote_wait_parser.add_argument("--job-directory", type=Path)
    add_remote_client_arguments(modern_remote_wait_parser)

    modern_remote_cancel_parser = subparsers.add_parser(
        "modern-remote-cancel",
        help="Request cooperative cancellation of one queued or running remote job.",
    )
    modern_remote_cancel_parser.add_argument("job_id")
    add_remote_client_arguments(modern_remote_cancel_parser)

    modern_remote_download_parser = subparsers.add_parser(
        "modern-remote-download",
        help="Download and request-bind a completed remote Modern result.",
    )
    modern_remote_download_parser.add_argument("job_id")
    modern_remote_download_parser.add_argument("job_directory", type=Path)
    modern_remote_download_parser.add_argument("--output", type=Path, required=True)
    add_remote_client_arguments(modern_remote_download_parser)

    modern_remote_delete_parser = subparsers.add_parser(
        "modern-remote-delete",
        help="Explicitly delete one terminal remote job and its server-side data.",
    )
    modern_remote_delete_parser.add_argument("job_id")
    add_remote_client_arguments(modern_remote_delete_parser)

    modern_private_status_parser = subparsers.add_parser(
        "modern-private-status",
        help="Inspect private unpublished state for one exact destination without mutation.",
    )
    modern_private_status_parser.add_argument(
        "destination",
        type=Path,
        help="Exact prospective Modern workflow destination to inspect.",
    )
    modern_private_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the versioned machine-readable discovery report.",
    )

    modern_plan_parser = subparsers.add_parser(
        "modern-plan",
        help=(
            "Inspect configured-engine workload and conservative payload equivalents "
            "without computing."
        ),
    )
    modern_plan_parser.add_argument("config", type=Path)
    modern_plan_parser.add_argument(
        "--output",
        type=Path,
        help="Report directory (default: CONFIG_NAME.workload).",
    )
    modern_plan_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only a recognized generated workload-report directory.",
    )

    modern_benchmark_parser = subparsers.add_parser(
        "modern-benchmark",
        help="Measure configured objective/gradient repeats without extrapolation.",
    )
    modern_benchmark_parser.add_argument("config", type=Path)
    modern_benchmark_parser.add_argument(
        "--subjects",
        type=int,
        required=True,
        help="Explicit deterministic subject-prefix size to benchmark.",
    )
    modern_benchmark_parser.add_argument("--repeats", type=int, default=3)
    modern_benchmark_parser.add_argument("--warmups", type=int, default=1)
    modern_benchmark_parser.add_argument(
        "--tile-autograd-strategy",
        choices=("standard", "recompute"),
        default="standard",
        help="Benchmark-only override; recompute requires configured blockwise execution.",
    )
    modern_benchmark_parser.add_argument(
        "--query-tile-size",
        type=int,
        help=(
            "Benchmark-only query tile rows; requires --source-tile-size and configured "
            "blockwise execution."
        ),
    )
    modern_benchmark_parser.add_argument(
        "--source-tile-size",
        type=int,
        help=(
            "Benchmark-only source tile rows; requires --query-tile-size and configured "
            "blockwise execution."
        ),
    )
    modern_benchmark_parser.add_argument(
        "--output",
        type=Path,
        help="Report directory (default: CONFIG_NAME.benchmark).",
    )
    modern_benchmark_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only a recognized generated benchmark-report directory.",
    )

    modern_optimizer_benchmark_parser = subparsers.add_parser(
        "modern-optimizer-benchmark",
        help="Measure declared multi-cycle optimizer runs in fresh isolated processes.",
    )
    modern_optimizer_benchmark_parser.add_argument("config", type=Path)
    modern_optimizer_benchmark_parser.add_argument(
        "--subjects",
        type=int,
        required=True,
        help="Explicit deterministic subject-prefix size to benchmark.",
    )
    modern_optimizer_benchmark_parser.add_argument(
        "--cycles",
        type=int,
        required=True,
        help="Explicit benchmark cycle cap; the source configuration is not modified.",
    )
    modern_optimizer_benchmark_parser.add_argument("--repeats", type=int, default=3)
    modern_optimizer_benchmark_parser.add_argument(
        "--warmups",
        type=int,
        default=0,
        help="Full optimizer warm-up runs inside each fresh process (default: 0).",
    )
    modern_optimizer_benchmark_parser.add_argument(
        "--output",
        type=Path,
        help="Report directory (default: CONFIG_NAME.optimizer-benchmark).",
    )
    modern_optimizer_benchmark_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only a recognized generated optimizer-benchmark directory.",
    )
    modern_optimizer_benchmark_verify_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-verify",
        help="Strictly verify a published multi-cycle optimizer benchmark.",
    )
    modern_optimizer_benchmark_verify_parser.add_argument("report_directory", type=Path)

    modern_optimizer_design_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-design",
        help="Freeze a full-factorial subject/cycle optimizer design without running it.",
    )
    modern_optimizer_design_parser.add_argument("config", type=Path)
    modern_optimizer_design_parser.add_argument(
        "--subjects",
        type=int,
        nargs="+",
        required=True,
        help="One or more unique deterministic subject-prefix sizes.",
    )
    modern_optimizer_design_parser.add_argument(
        "--cycles",
        type=int,
        nargs="+",
        required=True,
        help="One or more unique benchmark-only optimizer cycle caps.",
    )
    modern_optimizer_design_parser.add_argument("--repeats", type=int, default=3)
    modern_optimizer_design_parser.add_argument("--warmups", type=int, default=0)
    modern_optimizer_design_parser.add_argument(
        "--order-seed",
        type=int,
        default=20260722,
        help="Seed for the versioned deterministic condition order.",
    )
    modern_optimizer_design_parser.add_argument(
        "--output",
        type=Path,
        help="New immutable design directory (default: CONFIG_NAME.optimizer-study).",
    )

    modern_optimizer_design_verify_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-design-verify",
        help="Strictly verify an immutable optimizer scaling design without running it.",
    )
    modern_optimizer_design_verify_parser.add_argument("design_directory", type=Path)

    modern_optimizer_study_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-study",
        help="Execute or resume one frozen subject/cycle optimizer design.",
    )
    modern_optimizer_study_parser.add_argument("design_directory", type=Path)
    modern_optimizer_study_parser.add_argument("config", type=Path)
    modern_optimizer_study_parser.add_argument(
        "--output",
        type=Path,
        help="Study run directory (default: DESIGN_DIRECTORY.run).",
    )

    modern_optimizer_study_status_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-study-status",
        help="Strictly inspect partial or complete optimizer evidence without changing it.",
    )
    modern_optimizer_study_status_parser.add_argument("run_directory", type=Path)
    modern_optimizer_study_status_parser.add_argument("--json", action="store_true")

    modern_optimizer_study_verify_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-study-verify",
        help="Verify a completed optimizer study and every separate raw report.",
    )
    modern_optimizer_study_verify_parser.add_argument("run_directory", type=Path)

    modern_optimizer_compare_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-study-compare",
        help="Strictly compare two compatible completed optimizer studies.",
    )
    modern_optimizer_compare_parser.add_argument("baseline_run", type=Path)
    modern_optimizer_compare_parser.add_argument("candidate_run", type=Path)
    modern_optimizer_compare_parser.add_argument("--output", type=Path, required=True)

    modern_optimizer_comparison_verify_parser = subparsers.add_parser(
        "modern-optimizer-benchmark-study-comparison-verify",
        help="Recompute and strictly verify an optimizer-study comparison.",
    )
    modern_optimizer_comparison_verify_parser.add_argument(
        "comparison_directory",
        type=Path,
    )

    modern_benchmark_design_parser = subparsers.add_parser(
        "modern-benchmark-design",
        help="Freeze a paired blockwise standard/recompute design before measuring.",
    )
    modern_benchmark_design_parser.add_argument("config", type=Path)
    modern_benchmark_design_parser.add_argument(
        "--subjects",
        type=int,
        nargs="+",
        required=True,
        help="One or more unique deterministic subject-prefix sizes.",
    )
    modern_benchmark_design_parser.add_argument("--repeats", type=int, default=5)
    modern_benchmark_design_parser.add_argument("--warmups", type=int, default=1)
    modern_benchmark_design_parser.add_argument(
        "--order-seed",
        type=int,
        default=20260716,
        help="Seed for the versioned deterministic paired condition order.",
    )
    modern_benchmark_design_parser.add_argument(
        "--output",
        type=Path,
        help="New immutable design directory (default: CONFIG_NAME.benchmark-study).",
    )

    modern_benchmark_design_verify_parser = subparsers.add_parser(
        "modern-benchmark-design-verify",
        help="Strictly verify one immutable paired benchmark design.",
    )
    modern_benchmark_design_verify_parser.add_argument("design_directory", type=Path)

    modern_benchmark_matrix_design_parser = subparsers.add_parser(
        "modern-benchmark-matrix-design",
        help="Freeze a full-factorial multi-tile design without running it.",
    )
    modern_benchmark_matrix_design_parser.add_argument("config", type=Path)
    modern_benchmark_matrix_design_parser.add_argument(
        "--subjects",
        type=int,
        nargs="+",
        required=True,
        help="One or more unique deterministic subject-prefix sizes.",
    )
    modern_benchmark_matrix_design_parser.add_argument(
        "--tile-shape",
        type=_tile_shape_argument,
        action="append",
        required=True,
        metavar="QUERYxSOURCE",
        help="Ordered tile pair; repeat for each unique full-factorial level.",
    )
    modern_benchmark_matrix_design_parser.add_argument("--repeats", type=int, default=5)
    modern_benchmark_matrix_design_parser.add_argument("--warmups", type=int, default=1)
    modern_benchmark_matrix_design_parser.add_argument(
        "--order-seed",
        type=int,
        default=20260717,
        help="Seed for the versioned deterministic cell and within-cell order.",
    )
    modern_benchmark_matrix_design_parser.add_argument(
        "--output",
        type=Path,
        help="New immutable design directory (default: CONFIG_NAME.benchmark-matrix).",
    )

    modern_benchmark_matrix_design_verify_parser = subparsers.add_parser(
        "modern-benchmark-matrix-design-verify",
        help="Strictly verify an immutable multi-tile design without running it.",
    )
    modern_benchmark_matrix_design_verify_parser.add_argument("design_directory", type=Path)

    modern_benchmark_matrix_study_parser = subparsers.add_parser(
        "modern-benchmark-matrix-study",
        help="Execute or resume one frozen multi-tile matrix without comparing it.",
    )
    modern_benchmark_matrix_study_parser.add_argument("design_directory", type=Path)
    modern_benchmark_matrix_study_parser.add_argument("config", type=Path)
    modern_benchmark_matrix_study_parser.add_argument(
        "--output",
        type=Path,
        help="Matrix study run directory (default: DESIGN_DIRECTORY.run).",
    )

    modern_benchmark_matrix_study_status_parser = subparsers.add_parser(
        "modern-benchmark-matrix-study-status",
        help="Strictly inspect partial or complete matrix evidence without changing it.",
    )
    modern_benchmark_matrix_study_status_parser.add_argument("run_directory", type=Path)
    modern_benchmark_matrix_study_status_parser.add_argument("--json", action="store_true")

    modern_benchmark_matrix_study_verify_parser = subparsers.add_parser(
        "modern-benchmark-matrix-study-verify",
        help="Verify a completed matrix study and every separate raw v0.4 report.",
    )
    modern_benchmark_matrix_study_verify_parser.add_argument("run_directory", type=Path)

    modern_benchmark_study_parser = subparsers.add_parser(
        "modern-benchmark-study",
        help="Execute or resume one frozen design without comparing conditions.",
    )
    modern_benchmark_study_parser.add_argument("design_directory", type=Path)
    modern_benchmark_study_parser.add_argument("config", type=Path)
    modern_benchmark_study_parser.add_argument(
        "--output",
        type=Path,
        help="Study run directory (default: DESIGN_DIRECTORY.run).",
    )

    modern_benchmark_study_status_parser = subparsers.add_parser(
        "modern-benchmark-study-status",
        help="Strictly inspect partial or complete study evidence without changing it.",
    )
    modern_benchmark_study_status_parser.add_argument("run_directory", type=Path)
    modern_benchmark_study_status_parser.add_argument("--json", action="store_true")

    modern_benchmark_study_verify_parser = subparsers.add_parser(
        "modern-benchmark-study-verify",
        help="Verify a completed frozen study and every separate raw report.",
    )
    modern_benchmark_study_verify_parser.add_argument("run_directory", type=Path)

    modern_verify_parser = subparsers.add_parser(
        "modern-verify",
        help="Verify an immutable modern workflow run and its nested atlas/PCA bundle.",
    )
    modern_verify_parser.add_argument("run_directory", type=Path)

    reference_pca_parser = subparsers.add_parser(
        "reference-pca",
        help="Create a verified linear PCA snapshot from completed Deformetrica momenta.",
    )
    reference_pca_parser.add_argument(
        "run_directory",
        type=Path,
        help="Completed immutable Deformetrica run directory.",
    )
    reference_pca_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "New result-analysis bundle directory "
            "(default: RUN/analysis/reference-result-analysis-v0.2)."
        ),
    )
    reference_pca_parser.add_argument(
        "--components",
        type=int,
        help="Retain an explicit number of components (default: all available).",
    )

    reference_pca_verify_parser = subparsers.add_parser(
        "reference-pca-verify",
        help="Verify and recompute one Deformetrica momenta PCA snapshot.",
    )
    reference_pca_verify_parser.add_argument("bundle_directory", type=Path)
    reference_pca_verify_parser.add_argument(
        "--source-run",
        type=Path,
        help="Also require an exact hash binding to this current Deformetrica run.",
    )

    reference_pca_deformation_design_parser = subparsers.add_parser(
        "reference-pca-deformation-design",
        help=(
            "Freeze exact mean/±PC momenta and a no-execution Deformetrica "
            "Shooting design."
        ),
    )
    reference_pca_deformation_design_parser.add_argument(
        "run_directory",
        type=Path,
        help="Completed immutable Deformetrica run directory.",
    )
    reference_pca_deformation_design_parser.add_argument(
        "--pca-bundle",
        type=Path,
        help="Verified reference PCA bundle (default: the run's v0.2 bundle).",
    )
    reference_pca_deformation_design_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New prospective Shooting design directory.",
    )
    reference_pca_deformation_design_parser.add_argument(
        "--components",
        type=int,
        default=3,
        help="Number of retained PCs to visualize (default: 3).",
    )
    reference_pca_deformation_design_parser.add_argument(
        "--standard-deviations",
        type=float,
        default=2.0,
        help="Endpoint distance from the mean along each PC (default: 2.0).",
    )

    reference_pca_deformation_verify_parser = subparsers.add_parser(
        "reference-pca-deformation-design-verify",
        help="Recompute and verify a prospective reference PCA Shooting design.",
    )
    reference_pca_deformation_verify_parser.add_argument(
        "design_directory",
        type=Path,
    )
    reference_pca_deformation_verify_parser.add_argument(
        "--source-run",
        type=Path,
        help="Override and verify against this exact current source run.",
    )

    reference_pca_deformation_run_parser = subparsers.add_parser(
        "reference-pca-deformation-run",
        help="Execute one verified reference PCA Shooting design exactly once.",
    )
    reference_pca_deformation_run_parser.add_argument(
        "design_directory",
        type=Path,
    )
    reference_pca_deformation_run_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "New immutable Shooting result directory (default: the source run's "
            "analysis/reference-pca-deformations-v0.1-result)."
        ),
    )
    reference_pca_deformation_run_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=7_200,
        help="Hard process timeout in seconds (default: 7200).",
    )

    reference_pca_deformation_result_verify_parser = subparsers.add_parser(
        "reference-pca-deformation-verify",
        help="Verify a completed Deformetrica PCA Shooting result.",
    )
    reference_pca_deformation_result_verify_parser.add_argument(
        "result_directory",
        type=Path,
    )
    reference_pca_deformation_result_verify_parser.add_argument(
        "--source-run",
        type=Path,
        help="Also bind verification to this exact current Deformetrica run.",
    )

    reference_pca_stability_parser = subparsers.add_parser(
        "reference-pca-stability",
        help="Create immutable sign/rotation-invariant evidence for two PCA bundles.",
    )
    reference_pca_stability_parser.add_argument("reference_bundle", type=Path)
    reference_pca_stability_parser.add_argument("comparison_bundle", type=Path)
    reference_pca_stability_parser.add_argument("--output", required=True, type=Path)
    reference_pca_stability_parser.add_argument(
        "--variance-target",
        type=float,
        default=0.90,
        help="Cumulative variance target per PCA (default: 0.90).",
    )
    reference_pca_stability_parser.add_argument(
        "--components",
        type=int,
        help="Use one explicit component count instead of target-selected counts.",
    )

    reference_pca_stability_verify_parser = subparsers.add_parser(
        "reference-pca-stability-verify",
        help="Reverify both source PCA bundles and recompute one stability artifact.",
    )
    reference_pca_stability_verify_parser.add_argument(
        "artifact_directory",
        type=Path,
    )

    modern_pca_stability_parser = subparsers.add_parser(
        "modern-pca-stability",
        help="Create immutable sign/rotation-invariant evidence for two Modern bundles.",
    )
    modern_pca_stability_parser.add_argument("reference_bundle", type=Path)
    modern_pca_stability_parser.add_argument("comparison_bundle", type=Path)
    modern_pca_stability_parser.add_argument("--output", required=True, type=Path)
    modern_pca_stability_parser.add_argument(
        "--variance-target",
        type=float,
        default=0.90,
        help="Cumulative variance target per PCA (default: 0.90).",
    )
    modern_pca_stability_parser.add_argument(
        "--components",
        type=int,
        help="Use one explicit component count instead of target-selected counts.",
    )

    modern_pca_stability_verify_parser = subparsers.add_parser(
        "modern-pca-stability-verify",
        help="Reverify both Modern bundles and recompute one stability artifact.",
    )
    modern_pca_stability_verify_parser.add_argument(
        "artifact_directory",
        type=Path,
    )

    reference_calibration_parser = subparsers.add_parser(
        "reference-calibration-plan",
        help=(
            "Analyze an already GPA-aligned cohort and export a transparent, "
            "non-executing Deformetrica pilot-calibration plan."
        ),
    )
    reference_calibration_parser.add_argument(
        "mesh_directory",
        type=Path,
        help="Folder containing the aligned template and subject meshes.",
    )
    reference_calibration_parser.add_argument(
        "--template",
        type=Path,
        help=(
            "Template mesh (default: the single supported file named template "
            "inside the mesh folder)."
        ),
    )
    reference_calibration_parser.add_argument(
        "--subject-pattern",
        default="*",
        help="Glob selecting subjects before supported-format filtering (default: *).",
    )
    reference_calibration_parser.add_argument(
        "--units",
        required=True,
        choices=SUPPORTED_UNITS,
        help="Coordinate unit of the aligned mesh coordinates.",
    )
    reference_calibration_parser.add_argument(
        "--surface-detail",
        required=True,
        choices=("fine", "balanced", "coarse"),
        help="Researcher-declared surface-detail intent.",
    )
    reference_calibration_parser.add_argument(
        "--deformation-scale",
        required=True,
        choices=("local", "balanced", "global"),
        help="Researcher-declared biological deformation scale.",
    )
    reference_calibration_parser.add_argument(
        "--expected-shape-disparity",
        choices=("low", "moderate", "high", "extreme"),
        default="moderate",
        help=(
            "Expected amplitude of real between-specimen differences, independently "
            "of local/global deformation reach (default: moderate)."
        ),
    )
    reference_calibration_parser.add_argument(
        "--smallest-relevant-feature",
        type=float,
        help=("Optional researcher-measured smallest feature to preserve, expressed in --units."),
    )
    reference_calibration_parser.add_argument(
        "--pilot-subjects",
        type=int,
        default=8,
        help="Requested deterministic pilot-cohort size (default: 8; minimum: 2).",
    )
    reference_calibration_parser.add_argument(
        "--pilot-declarations",
        type=Path,
        help=(
            "Optional CSV with exact filename,stratum,is_extreme columns. Every "
            "declared extreme and at least one member of each stratum must fit in "
            "--pilot-subjects."
        ),
    )
    reference_calibration_parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Calibration-report output folder.",
    )
    reference_calibration_parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing DiffeoForge calibration-plan export.",
    )

    calibration_study_init = subparsers.add_parser(
        "reference-calibration-study-init",
        help=(
            "Create a hash-bound staged pilot study from a project containing a "
            "transparent calibration plan."
        ),
    )
    calibration_study_init.add_argument(
        "config",
        type=Path,
        help="Reviewed Deformetrica atlas.yaml containing the calibration plan.",
    )
    calibration_study_init.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New calibration-study directory; it is never overwritten.",
    )
    calibration_study_init.add_argument(
        "--pilot-max-iterations",
        type=int,
        default=150,
        help="Iteration cap applied to every pilot candidate (default: 150).",
    )

    calibration_study_extend = subparsers.add_parser(
        "reference-calibration-study-extend",
        help=(
            "Create a hash-bound successor for an unbounded calibration winner; "
            "only new outward logarithmic neighbors remain pending."
        ),
    )
    calibration_study_extend.add_argument(
        "source_study_directory",
        type=Path,
        help="Completed source stage whose assessment reports search range not bounded.",
    )
    calibration_study_extend.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New successor-study directory; it is never overwritten.",
    )
    calibration_study_extend.add_argument(
        "--limit",
        action="append",
        required=True,
        metavar="PARAMETER=LOW:HIGH",
        help=(
            "Explicit positive feasibility interval for each reported boundary "
            "parameter; repeat once per parameter."
        ),
    )
    calibration_study_extend.add_argument(
        "--outward-steps",
        type=int,
        choices=(1, 2),
        default=2,
        help="Number of outward logarithmic neighbors per boundary (default: 2).",
    )

    calibration_study_run = subparsers.add_parser(
        "reference-calibration-study-run",
        help=(
            "Run calibration candidates, optionally completing all four stages with "
            "a transparent provisional recommendation."
        ),
    )
    calibration_study_run.add_argument("study_directory", type=Path)
    calibration_study_run.add_argument(
        "--complete",
        action="store_true",
        help=(
            "Run all remaining stages, record transparent provisional automatic "
            "selections, and create the final recommendation report."
        ),
    )

    calibration_study_status = subparsers.add_parser(
        "reference-calibration-study-status",
        help="Verify and show the current state of a calibration study.",
    )
    calibration_study_status.add_argument("study_directory", type=Path)
    calibration_study_status.add_argument("--json", action="store_true")

    calibration_study_review = subparsers.add_parser(
        "reference-calibration-study-review",
        help=(
            "Select one eligible candidate, optionally record visual QC, and prepare "
            "the next stage."
        ),
    )
    calibration_study_review.add_argument("study_directory", type=Path)
    calibration_study_review.add_argument(
        "--approve",
        action="append",
        default=[],
        metavar="CANDIDATE_ID",
        help=("Candidate whose atlas and reconstructions passed optional visual QC; repeatable."),
    )
    calibration_study_review.add_argument(
        "--reject",
        action="append",
        default=[],
        metavar="CANDIDATE_ID",
        help=("Candidate whose atlas and reconstructions failed optional visual QC; repeatable."),
    )
    calibration_study_review.add_argument(
        "--select",
        required=True,
        metavar="CANDIDATE_ID",
        help="Explicit researcher selection from the automatically valid candidates.",
    )

    validation_study_init = subparsers.add_parser(
        "reference-validation-study-init",
        help=(
            "Create a frozen post-pilot finalist validation and resampling study "
            "without starting a process."
        ),
    )
    validation_study_init.add_argument(
        "config",
        type=Path,
        help="Completed pilot-calibrated Deformetrica atlas configuration.",
    )
    validation_study_init.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New Validation Lab directory; it is never overwritten.",
    )
    validation_study_init.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.20,
        help="Untouched subject fraction reserved before validation (default: 0.20).",
    )
    validation_study_init.add_argument(
        "--resamples",
        type=int,
        default=5,
        help="Predeclared training-cohort resamples (default: 5).",
    )
    validation_study_init.add_argument(
        "--resample-fraction",
        type=float,
        default=0.80,
        help="Training subjects per resample (default: 0.80).",
    )
    validation_study_init.add_argument(
        "--max-iterations",
        type=int,
        help="Optional validation override; default is the calibrated config value.",
    )

    validation_study_status = subparsers.add_parser(
        "reference-validation-study-status",
        help="Verify and show one Validation Lab study and report status.",
    )
    validation_study_status.add_argument("study_directory", type=Path)
    validation_study_status.add_argument("--json", action="store_true")

    validation_study_run = subparsers.add_parser(
        "reference-validation-study-run",
        help="Run or resume every frozen Validation Lab comparison.",
    )
    validation_study_run.add_argument("study_directory", type=Path)

    holdout_study_init = subparsers.add_parser(
        "reference-holdout-study-init",
        help=(
            "Bind completed training-only finalist models and prepare fixed-template "
            "registration of the untouched Validation Lab holdout."
        ),
    )
    holdout_study_init.add_argument("validation_study_directory", type=Path)
    holdout_study_init.add_argument(
        "--max-iterations",
        type=int,
        help="Optional holdout override; default is the parent validation value.",
    )

    holdout_study_status = subparsers.add_parser(
        "reference-holdout-study-status",
        help="Verify and show one fixed-template holdout study and report status.",
    )
    holdout_study_status.add_argument("study_directory", type=Path)
    holdout_study_status.add_argument("--json", action="store_true")

    holdout_study_run = subparsers.add_parser(
        "reference-holdout-study-run",
        help="Run or resume every frozen fixed-template holdout registration.",
    )
    holdout_study_run.add_argument("study_directory", type=Path)

    validation_synthetic_create = subparsers.add_parser(
        "reference-validation-synthetic-create",
        help="Create independent analytic local/global/mixed ground-truth meshes.",
    )
    validation_synthetic_create.add_argument("template", type=Path)
    validation_synthetic_create.add_argument("--output", required=True, type=Path)
    validation_synthetic_create.add_argument(
        "--subjects-per-family",
        type=int,
        default=6,
        help="Known-correspondence subjects per deformation family (default: 6).",
    )

    validation_synthetic_evaluate = subparsers.add_parser(
        "reference-validation-synthetic-evaluate",
        help="Compare one recovered mesh with ordered synthetic ground truth.",
    )
    validation_synthetic_evaluate.add_argument("recovered", type=Path)
    validation_synthetic_evaluate.add_argument("truth", type=Path)

    synthetic_recovery_init = subparsers.add_parser(
        "modern-synthetic-recovery-init",
        help="Freeze paired Euclidean/Sobolev full-atlas synthetic recovery configs.",
    )
    synthetic_recovery_init.add_argument("benchmark_directory", type=Path)
    synthetic_recovery_init.add_argument("--output", required=True, type=Path)
    synthetic_recovery_init.add_argument("--cycles", type=int, default=100)
    synthetic_recovery_init.add_argument("--control-points", type=int, default=9)
    synthetic_recovery_init.add_argument(
        "--recovery-metric",
        choices=("ordered-vertex", "surface"),
        default="surface",
        help=(
            "Assessment metric for the landmark-free Current workflow "
            "(default: surface)."
        ),
    )

    synthetic_recovery_design_verify = subparsers.add_parser(
        "modern-synthetic-recovery-design-verify",
        help="Verify a prospective Modern synthetic recovery design.",
    )
    synthetic_recovery_design_verify.add_argument("design_directory", type=Path)

    synthetic_recovery_assess = subparsers.add_parser(
        "modern-synthetic-recovery-assess",
        help="Assess paired Modern runs against exact synthetic ground truth.",
    )
    synthetic_recovery_assess.add_argument("design_directory", type=Path)
    synthetic_recovery_assess.add_argument("euclidean_run", type=Path)
    synthetic_recovery_assess.add_argument("sobolev_run", type=Path)
    synthetic_recovery_assess.add_argument("--output", required=True, type=Path)

    synthetic_recovery_assessment_verify = subparsers.add_parser(
        "modern-synthetic-recovery-assessment-verify",
        help="Recompute and verify a Modern synthetic recovery assessment.",
    )
    synthetic_recovery_assessment_verify.add_argument("assessment_directory", type=Path)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an atlas configuration before any computation starts.",
    )
    validate_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    validate_parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Validate parameter structure without requiring input files to exist.",
    )
    validate_parser.add_argument(
        "--report",
        nargs="?",
        type=Path,
        const=_AUTO_REPORT,
        help="Write a self-contained HTML report; optionally choose its path.",
    )
    validate_parser.add_argument(
        "--force-report",
        action="store_true",
        help="Explicitly replace an existing preflight report.",
    )
    reference_plan_parser = subparsers.add_parser(
        "reference-plan",
        help="Print the exact read-only preparation plan for one explicit run ID.",
    )
    reference_plan_parser.add_argument(
        "config", type=Path, help="Path to a reference atlas YAML file."
    )
    reference_plan_parser.add_argument(
        "--run-id",
        required=True,
        help="Explicit future run identifier; no destination is created.",
    )
    reference_plan_parser.add_argument(
        "--report",
        type=Path,
        help="Write a new self-contained HTML review page without replacing any file.",
    )
    reference_plan_verify_parser = subparsers.add_parser(
        "reference-plan-verify",
        help="Strictly verify saved reference preparation JSON and optional HTML.",
    )
    reference_plan_verify_parser.add_argument(
        "plan", type=Path, help="Saved reference preparation plan JSON file."
    )
    reference_plan_verify_parser.add_argument(
        "--report",
        type=Path,
        help="Optional saved HTML review page to compare with exact regeneration.",
    )
    reference_plan_verify_parser.add_argument(
        "--expect-fingerprint",
        help="Optional externally recorded canonical plan SHA-256.",
    )
    reference_plan_verify_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write exact verification evidence to a new file; an existing path is never replaced."
        ),
    )
    reference_plan_approve_parser = subparsers.add_parser(
        "reference-plan-approve",
        help="Bind preparation-only approval to one freshly recomputed exact plan.",
    )
    reference_plan_approve_parser.add_argument(
        "config", type=Path, help="Path to the current reference atlas YAML file."
    )
    reference_plan_approve_parser.add_argument(
        "--run-id",
        required=True,
        help="Exact future run identifier reviewed in the approved plan.",
    )
    reference_plan_approve_parser.add_argument(
        "--approve-fingerprint",
        required=True,
        help="Canonical SHA-256 copied from the previously reviewed exact plan.",
    )
    reference_plan_approve_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New immutable approval request JSON; an existing path is never replaced.",
    )
    reference_plan_approval_verify_parser = subparsers.add_parser(
        "reference-plan-approval-verify",
        help="Strictly verify a saved preparation-only approval without mutation.",
    )
    reference_plan_approval_verify_parser.add_argument(
        "request", type=Path, help="Saved reference preparation approval request JSON."
    )
    reference_plan_approval_verify_parser.add_argument(
        "--current-config",
        type=Path,
        help="Also require a fresh current plan to match the embedded approved plan exactly.",
    )
    reference_plan_approval_verify_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write exact verification evidence to a new file; an existing path is never replaced."
        ),
    )
    reference_preparation_status_parser = subparsers.add_parser(
        "reference-preparation-status",
        help="Read-only classify exact state for one hash-bound preparation approval.",
    )
    reference_preparation_status_parser.add_argument(
        "request", type=Path, help="Saved reference preparation approval request JSON."
    )
    reference_preparation_status_parser.add_argument(
        "--current-config",
        type=Path,
        required=True,
        help="Current config that must still exactly reproduce the approved plan.",
    )
    reference_preparation_status_parser.add_argument(
        "--expect-request-sha256",
        required=True,
        help="Independently recorded SHA-256 of the complete approval-request file.",
    )
    reference_preparation_status_output = (
        reference_preparation_status_parser.add_mutually_exclusive_group()
    )
    reference_preparation_status_output.add_argument(
        "--json",
        action="store_true",
        help="Print the complete versioned machine-readable reconciliation report.",
    )
    reference_preparation_status_output.add_argument(
        "--output",
        type=Path,
        help="Write exact report bytes to a new file; an existing path is never replaced.",
    )
    reference_preparation_status_verify_parser = subparsers.add_parser(
        "reference-preparation-status-verify",
        help="Strictly verify one saved reconciliation report without external-state reads.",
    )
    reference_preparation_status_verify_parser.add_argument(
        "report", type=Path, help="Saved deterministic reconciliation report JSON."
    )
    reference_preparation_status_verify_parser.add_argument(
        "--expect-report-sha256",
        required=True,
        help="Independently recorded SHA-256 of the complete saved report file.",
    )
    reference_preparation_status_verify_parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Write exact verification evidence to a new file; an existing path is never replaced."
        ),
    )
    reference_prepare_approved_parser = subparsers.add_parser(
        "reference-prepare-approved",
        help="Atomically prepare one externally hash-bound approval without execution.",
    )
    reference_prepare_approved_parser.add_argument(
        "request", type=Path, help="Saved preparation-only approval request JSON."
    )
    reference_prepare_approved_parser.add_argument(
        "--current-config",
        type=Path,
        required=True,
        help="Current reference atlas config that must exactly reproduce the approved plan.",
    )
    reference_prepare_approved_parser.add_argument(
        "--expect-request-sha256",
        required=True,
        help="Independently recorded SHA-256 of the complete approval-request file.",
    )
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Create a new immutable run directory without starting computation.",
    )
    prepare_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    prepare_parser.add_argument("--run-id", help="Explicit unique run identifier.")
    prepare_parser.add_argument(
        "--output-directory",
        type=Path,
        help="Override the configured run root for this preparation.",
    )

    execute_parser = subparsers.add_parser(
        "execute",
        help="Verify and execute a prepared run exactly once.",
    )
    execute_parser.add_argument("run_directory", type=Path)

    run_parser = subparsers.add_parser(
        "run",
        help="Prepare a new run directory and execute it immediately.",
    )
    run_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    run_parser.add_argument("--run-id", help="Explicit unique run identifier.")
    run_parser.add_argument(
        "--output-directory",
        type=Path,
        help="Override the configured run root for this run.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Create and execute an immutable successor from an inventoried checkpoint.",
    )
    resume_parser.add_argument("source_run", type=Path)
    resume_parser.add_argument("--run-id", help="Explicit unique successor run identifier.")
    resume_parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare the successor without starting Deformetrica.",
    )

    recover_parser = subparsers.add_parser(
        "recover",
        help="Finalize an abandoned started run as interrupted without executing it.",
    )
    recover_parser.add_argument("run_directory", type=Path)
    recover_parser.add_argument(
        "--reason",
        required=True,
        help="Human-readable explanation of the unclean stop.",
    )
    recover_parser.add_argument(
        "--confirm-process-stopped",
        action="store_true",
        help="Confirm that no Deformetrica process is still writing to this run.",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Read the latest append-only lifecycle state for a run.",
    )
    status_parser.add_argument("run_directory", type=Path)

    report_parser = subparsers.add_parser(
        "report",
        help="Create a self-contained HTML convergence and result report.",
    )
    report_parser.add_argument("run_directory", type=Path)
    report_parser.add_argument(
        "--output",
        type=Path,
        help="Report destination (default: RUN_DIRECTORY/result-report.html).",
    )
    report_parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing DiffeoForge result report.",
    )

    scientific_report_parser = subparsers.add_parser(
        "scientific-report",
        help=(
            "Create an evidence-bound scientific atlas report with methods, claim matrix, "
            "subject QC, and optional robustness evidence."
        ),
    )
    scientific_report_parser.add_argument("run_directory", type=Path)
    scientific_report_parser.add_argument(
        "--validation-study",
        type=Path,
        help="Completed neighboring-parameter Validation Lab directory.",
    )
    scientific_report_parser.add_argument(
        "--holdout-study",
        type=Path,
        help="Completed fixed-template heldout-confirmation directory.",
    )
    scientific_report_parser.add_argument(
        "--pca-stability",
        type=Path,
        help="Verified Reference or Modern PCA-stability artifact directory.",
    )
    scientific_report_parser.add_argument(
        "--decision-review",
        type=Path,
        help=(
            "Source-bound registration-QC review JSON. If omitted, the latest review "
            "for the run is used when available."
        ),
    )
    scientific_report_parser.add_argument(
        "--output",
        type=Path,
        help="Absent output directory (default: sibling RUN-scientific-report).",
    )

    scientific_report_verify_parser = subparsers.add_parser(
        "scientific-report-verify",
        help="Reverify a scientific report, its exact inventory, and all source hashes.",
    )
    scientific_report_verify_parser.add_argument("report_directory", type=Path)

    compare_parser = subparsers.add_parser(
        "compare-reference",
        help="Compare selected run outputs with a versioned numerical reference.",
    )
    compare_parser.add_argument("run_directory", type=Path)
    compare_parser.add_argument("reference_directory", type=Path)
    return parser


def _prompt_units() -> str:
    if not sys.stdin.isatty():
        raise ConfigurationError(
            "--units is required when diffeoforge init is not running interactively."
        )
    print("Choose the coordinate unit used by every mesh:")
    for index, unit in enumerate(SUPPORTED_UNITS, start=1):
        print(f"  {index}. {unit}")
    value = input("Unit number or name: ").strip()
    if value.isdigit() and 1 <= int(value) <= len(SUPPORTED_UNITS):
        return SUPPORTED_UNITS[int(value) - 1]
    if value in SUPPORTED_UNITS:
        return value
    raise ConfigurationError(f"Unsupported unit: {value!r}")


def _prompt_template(mesh_directory: Path) -> Path | None:
    detected = detect_template(mesh_directory)
    if detected is not None:
        return detected
    if not sys.stdin.isatty():
        return None
    value = input(
        "No template.vtk was found. Enter the template path relative to the mesh directory: "
    ).strip()
    return Path(value) if value else None


def _execution_outcome(run_directory: Path, return_code: int) -> int:
    snapshot = run_status(run_directory)
    if snapshot["status"] == "interrupted":
        result = snapshot.get("result") or {}
        checkpoint = result.get("checkpoint") or {}
        print("Run interrupted safely.", file=sys.stderr)
        if checkpoint.get("available"):
            print(
                "Checkpoint integrity matches the output inventory. Resume with: "
                f'diffeoforge resume "{run_directory}"',
                file=sys.stderr,
            )
        else:
            print(
                "No checkpoint was written before the interruption; this run cannot be resumed.",
                file=sys.stderr,
            )
        return 130
    if return_code != 0:
        print(f"ERROR: Deformetrica returned {return_code}.", file=sys.stderr)
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        report = run_doctor(args.workspace, engine=args.engine, image=args.image)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        else:
            for check in report.checks:
                print(f"[{check.status.upper():4}] {check.label}: {check.summary}")
                if check.guidance:
                    print(f"       -> {check.guidance}")
            print(f"Overall status: {report.status}")
        return 0 if report.ready else 1

    if args.command == "init":
        try:
            units = args.units or _prompt_units()
            template = args.template or _prompt_template(args.mesh_directory)
            report_path = default_preflight_report_path(args.config)
            if not args.no_report and report_path.exists() and not args.force:
                raise ConfigurationError(
                    f"Preflight report already exists and will not be overwritten: {report_path}"
                )
            result = initialize_project(
                args.mesh_directory,
                units=units,
                config_path=args.config,
                template=template,
                subject_pattern=args.subject_pattern,
                project_name=args.project_name,
                runs_directory=args.runs_directory,
                attachment_kernel_width=args.attachment_kernel_width,
                deformation_kernel_width=args.deformation_kernel_width,
                initial_control_point_spacing=args.control_point_spacing,
                noise_std=args.noise_std,
                device=args.device,
                threads=args.threads,
                random_seed=args.random_seed,
                image=args.image,
                overwrite=args.force,
            )
            print(f"Configuration created: {result.config_path}")
            print(f"Template: {result.preflight.inputs.template}")
            print(f"Subject meshes: {len(result.preflight.subjects)}")
            if result.derived_parameters:
                print(
                    "WARNING: exploratory geometry-scaled values were generated for: "
                    + ", ".join(result.derived_parameters)
                )
                print("Review these values before scientific use.")
            if not args.no_report:
                written_report = write_preflight_report(
                    result.preflight,
                    report_path,
                    overwrite=args.force,
                )
                print(f"Preflight report: {written_report}")
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-reference-qualification-init":
        try:
            from diffeoforge.modern_reference_qualification import (
                DESIGN_HTML_NAME,
                DESIGN_JSON_NAME,
                create_modern_reference_qualification,
                verify_modern_reference_qualification_design,
            )

            destination = create_modern_reference_qualification(
                args.reference_run,
                args.output,
                subject_count=args.subjects,
                max_cycles=args.cycles,
                threads=args.threads,
                tile_size=args.tile_size,
                optimizer_direction=args.optimizer_direction,
                lbfgs_history_size=args.lbfgs_history_size,
                lbfgs_initial_step_size=args.lbfgs_initial_step_size,
                line_search_condition=args.line_search_condition,
                strong_wolfe_curvature_constant=args.strong_wolfe_curvature_constant,
                strong_wolfe_maximum_step_size=args.strong_wolfe_maximum_step_size,
                subject_batch_size=args.subject_batch_size,
                runtime_device=args.device,
                qualification_scope=args.scope,
                template_gradient=args.template_gradient,
                sobolev_kernel_width_ratio=args.sobolev_kernel_width_ratio,
            )
            design = verify_modern_reference_qualification_design(destination)
            print(
                f"Prospective {args.scope.replace('_', '-')} qualification created: {destination}"
            )
            print(f"Subjects: {len(design['subjects'])}")
            print(
                "Frozen Modern config: "
                f"{destination / design['modern_workflow']['config_path']}"
            )
            print(f"Machine-readable design: {destination / DESIGN_JSON_NAME}")
            print(f"Review page: {destination / DESIGN_HTML_NAME}")
            print("No Modern optimizer was run and no comparison result exists yet.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-reference-qualification-verify":
        try:
            from diffeoforge.modern_reference_qualification import (
                verify_modern_reference_qualification_design,
            )

            design = verify_modern_reference_qualification_design(args.design_directory)
            print(f"Fixed-reference qualification verified: {args.design_directory.resolve()}")
            print(f"Subjects: {len(design['subjects'])}")
            print("The design contains no Modern result and remains prospective.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-reference-qualification-continue":
        try:
            from diffeoforge.modern_reference_qualification import (
                CONFIG_NAME,
                create_modern_reference_qualification_continuation,
                verify_modern_reference_qualification_design,
            )

            destination = create_modern_reference_qualification_continuation(
                args.design_directory,
                args.modern_run,
                args.output,
                max_cycles=args.cycles,
                threads=args.threads,
            )
            design = verify_modern_reference_qualification_design(destination)
            print(f"Prospective continuation qualification created: {destination}")
            print(f"Subjects: {len(design['subjects'])}")
            print(f"Frozen Modern config: {destination / CONFIG_NAME}")
            print("The parent result is hash-bound; no successor optimizer was run yet.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-reference-qualification-assess":
        try:
            from diffeoforge.modern_reference_qualification import (
                assess_modern_reference_qualification,
                verify_modern_reference_qualification_assessment,
            )

            def assessment_progress(completed: int, total: int, filename: str) -> None:
                print(
                    f"Assessment metrics: subject {completed}/{total} complete: {filename}",
                    flush=True,
                )

            destination = assess_modern_reference_qualification(
                args.design_directory,
                args.modern_run,
                args.output,
                metric_workers=args.metric_workers,
                progress_callback=assessment_progress,
            )

            def assessment_verification_progress(
                completed: int, total: int, filename: str
            ) -> None:
                print(
                    f"Independent verification: subject {completed}/{total} complete: "
                    f"{filename}",
                    flush=True,
                )

            assessment = verify_modern_reference_qualification_assessment(
                destination,
                metric_workers=args.metric_workers,
                progress_callback=assessment_verification_progress,
            )
            print(f"Fixed-reference qualification assessed: {destination}")
            print(f"Engineering gate result: {assessment['decision']['status']}")
            print("This result does not establish biological validity or atlas equivalence.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-reference-qualification-assessment-verify":
        try:
            from diffeoforge.modern_reference_qualification import (
                verify_modern_reference_qualification_assessment,
            )

            def standalone_verification_progress(
                completed: int, total: int, filename: str
            ) -> None:
                print(
                    f"Independent verification: subject {completed}/{total} complete: "
                    f"{filename}",
                    flush=True,
                )

            assessment = verify_modern_reference_qualification_assessment(
                args.assessment_directory,
                metric_workers=args.metric_workers,
                progress_callback=standalone_verification_progress,
            )
            print(
                "Fixed-reference qualification assessment verified: "
                f"{args.assessment_directory.resolve()}"
            )
            print(f"Engineering gate result: {assessment['decision']['status']}")
            print("All external metrics were recomputed from the bound design and run.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-continuation-init":
        try:
            from diffeoforge.modern_continuation import (
                CONFIG_NAME,
                PLAN_HTML_NAME,
                create_modern_continuation,
                verify_modern_continuation,
            )

            destination = create_modern_continuation(
                args.parent_run,
                args.output,
                max_cycles=args.cycles,
                threads=args.threads,
            )
            plan = verify_modern_continuation(destination)
            print(f"Prospective Modern continuation created: {destination}")
            print(f"Subjects: {len(plan['subjects'])}")
            print(f"Frozen config: {destination / CONFIG_NAME}")
            print(f"Review page: {destination / PLAN_HTML_NAME}")
            print("No successor optimizer was run.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-continuation-verify":
        try:
            from diffeoforge.modern_continuation import verify_modern_continuation

            plan = verify_modern_continuation(args.plan_directory)
            print(f"Modern continuation verified: {args.plan_directory.resolve()}")
            print(f"Subjects: {len(plan['subjects'])}")
            print("The plan contains no successor result and remains prospective.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-continuation-verify-run":
        try:
            from diffeoforge.modern_continuation import verify_modern_continuation_run

            result = verify_modern_continuation_run(
                args.plan_directory,
                args.successor_run,
            )
            bundle = result["bundle"]
            print(f"Modern continuation run verified: {args.successor_run.resolve()}")
            print(
                "Initial objective matches the parent final state within the "
                "declared numerical tolerance."
            )
            print(
                "Termination: "
                f"{bundle['optimizer']['termination_reason']}; "
                f"converged={str(bundle['optimizer']['converged']).lower()}"
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-checkpoint-recovery-init":
        try:
            from diffeoforge.modern_checkpoint_recovery import (
                CONFIG_NAME,
                HTML_NAME,
                create_modern_checkpoint_recovery,
                verify_modern_checkpoint_recovery,
            )

            destination = create_modern_checkpoint_recovery(
                args.private_directory,
                args.output,
                max_cycles=args.cycles,
                threads=args.threads,
            )
            plan = verify_modern_checkpoint_recovery(destination)
            print(f"Prospective Modern checkpoint recovery created: {destination}")
            print(
                "Recovered complete cycle: "
                f"{plan['source']['checkpoint_cycle']} of "
                f"{plan['source']['original_cycle_cap']}"
            )
            print(f"Frozen config: {destination / CONFIG_NAME}")
            print(f"Review page: {destination / HTML_NAME}")
            print("The abandoned directory was not modified; no successor optimizer was run.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-checkpoint-recovery-verify":
        try:
            from diffeoforge.modern_checkpoint_recovery import (
                verify_modern_checkpoint_recovery,
            )

            plan = verify_modern_checkpoint_recovery(args.plan_directory)
            print(f"Modern checkpoint recovery verified: {args.plan_directory.resolve()}")
            print(f"Subjects: {len(plan['subjects'])}")
            print("The plan contains no successor result and remains prospective.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-checkpoint-recovery-verify-run":
        try:
            from diffeoforge.modern_checkpoint_recovery import (
                verify_modern_checkpoint_recovery_run,
            )

            result = verify_modern_checkpoint_recovery_run(
                args.plan_directory,
                args.successor_run,
            )
            bundle = result["bundle"]
            print(f"Modern checkpoint recovery run verified: {args.successor_run.resolve()}")
            print("Initial objective matches the frozen complete-cycle checkpoint.")
            print(
                "Termination: "
                f"{bundle['optimizer']['termination_reason']}; "
                f"converged={str(bundle['optimizer']['converged']).lower()}"
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-init":
        try:
            from diffeoforge.modern_workflow import initialize_modern_workflow

            units = args.units or _prompt_units()
            template = args.template or _prompt_template(args.mesh_directory)
            config_path = initialize_modern_workflow(
                args.mesh_directory,
                units=units,
                config_path=args.config,
                template=template,
                subject_pattern=args.subject_pattern,
                project_name=args.project_name,
                output_directory=args.output_directory,
                landmarks_file=args.landmarks,
                control_point_count=args.control_points,
                attachment_kernel_width=args.attachment_kernel_width,
                deformation_kernel_width=args.deformation_kernel_width,
                noise_variance=args.noise_variance,
                max_cycles=args.max_cycles,
                threads=args.threads,
                runtime_device=args.device,
                random_seed=args.random_seed,
                pairwise_mode=args.pairwise_mode,
                query_tile_size=args.query_tile_size,
                source_tile_size=args.source_tile_size,
                template_gradient=args.template_gradient,
                sobolev_kernel_width_ratio=args.sobolev_kernel_width_ratio,
                overwrite=args.force,
            )
            print(f"Modern workflow configuration created: {config_path}")
            print("WARNING: Geometry-scaled starter values are exploratory.")
            print("Review every parameter before running the modern engine.")
            print(f"Next: diffeoforge modern-plan {config_path}")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-private-status":
        try:
            from diffeoforge.private_runs import discover_private_runs

            discovery = discover_private_runs(args.destination)
            report = discovery.as_dict()
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(f"Destination: {discovery.destination}")
                print(f"Status: {discovery.status}")
                print(f"Ready for new run: {'yes' if discovery.ready_for_new_run else 'no'}")
                if discovery.candidates:
                    print("Private unpublished candidates:")
                    for candidate in discovery.candidates:
                        print(f"  [{candidate.status}] {candidate.path}")
                        print(f"      {candidate.reason}")
                else:
                    print("Private unpublished candidates: none")
                print("No files were deleted, renamed, resumed, published, or rewritten.")
        except (OSError, RuntimeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0 if discovery.ready_for_new_run else 1

    if args.command == "modern-remote-package":
        try:
            from diffeoforge.remote_atlas_job import create_remote_atlas_job

            job = create_remote_atlas_job(args.config, args.output)
            print(f"Portable Modern atlas request created: {job}")
            print("No upload, network request, authentication, or computation was performed.")
            print("Review specimen filenames and privacy requirements before transfer.")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, OSError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-package-verify":
        try:
            from diffeoforge.remote_atlas_job import verify_remote_atlas_job

            manifest = verify_remote_atlas_job(args.job_directory)
            print(f"Portable Modern atlas request verified: {args.job_directory.resolve()}")
            print(f"Subject meshes: {len(manifest['input']['subjects'])}")
            print(f"Requested device: {manifest['execution']['device']}")
            print("No upload, network request, authentication, or computation was performed.")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, OSError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-run":
        try:
            from diffeoforge.remote_atlas_job import run_remote_atlas_job

            result = run_remote_atlas_job(
                args.job_directory,
                args.output,
                progress_callback=_show_modern_progress,
            )
            print(f"Remote Modern atlas result completed and request-bound: {result}")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, OSError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-result-verify":
        try:
            from diffeoforge.remote_atlas_job import verify_remote_atlas_result

            result = verify_remote_atlas_result(args.job_directory, args.result_directory)
            print(f"Remote Modern atlas result verified: {args.result_directory.resolve()}")
            print(f"Subject meshes: {len(result['input']['subjects'])}")
            print(f"Execution device: {result['engine']['device']}")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, OSError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-token-init":
        try:
            from diffeoforge.remote_atlas_transport import create_remote_token_file

            token_file = create_remote_token_file(args.output)
            print(f"Remote bearer-token file created: {token_file}")
            print("The secret was not printed. Keep this file private and out of Git.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-server":
        manager = None
        server = None
        try:
            from diffeoforge.remote_atlas_server import (
                RemoteAtlasJobManager,
                create_remote_atlas_http_server,
            )
            from diffeoforge.remote_atlas_transport import load_remote_token

            token = load_remote_token(args.token_file)
            manager = RemoteAtlasJobManager(
                args.root,
                worker_count=args.workers,
                max_active_jobs=args.max_active_jobs,
            )
            server = create_remote_atlas_http_server(
                manager,
                token,
                host=args.host,
                port=args.port,
                tls_certificate=args.tls_certificate,
                tls_private_key=args.tls_private_key,
                max_upload_bytes=args.max_upload_bytes,
            )
            scheme = "https" if args.tls_certificate is not None else "http"
            address, port = server.server_address[:2]
            print(f"DiffeoForge remote atlas server listening on {scheme}://{address}:{port}")
            print(f"Persistent server root: {manager.root}")
            print("Raw meshes and specimen filenames remain server-side until explicit deletion.")
            try:
                server.serve_forever(poll_interval=0.5)
            except KeyboardInterrupt:
                print("Remote atlas server stopping; active jobs become interrupted on restart.")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        finally:
            if server is not None:
                server.server_close()
            if manager is not None:
                manager.close(wait=False)
        return 0

    if args.command == "modern-remote-submit":
        try:
            client = _remote_client_from_args(args)
            submission_id = args.submission_id or uuid.uuid4().hex
            print(f"Remote submission ID: {submission_id}", flush=True)
            state = client.submit(
                args.job_directory,
                submission_id=submission_id,
            )
            print(json.dumps(state, indent=2, ensure_ascii=False))
            print(f"Remote job accepted: {state['job_id']}")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-status":
        try:
            client = _remote_client_from_args(args)
            state = client.status(args.job_id)
            print(json.dumps(state, indent=2, ensure_ascii=False))
            if args.events:
                events = client.events(
                    args.job_id,
                    after=args.after,
                    limit=args.limit,
                )
                print(json.dumps(events, indent=2, ensure_ascii=False))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-wait":
        try:
            import time

            if not 0.1 <= args.poll_seconds <= 3600:
                raise ValueError("--poll-seconds must be between 0.1 and 3600")
            if (args.download is None) != (args.job_directory is None):
                raise ValueError(
                    "--download and --job-directory must be supplied together"
                )
            client = _remote_client_from_args(args)
            cursor = -1
            terminal = {"completed", "failed", "cancelled", "interrupted"}
            while True:
                while True:
                    event_page = client.events(args.job_id, after=cursor)
                    for event in event_page["events"]:
                        print(json.dumps(event, ensure_ascii=False), flush=True)
                    cursor = event_page["next_after"]
                    if not event_page["has_more"]:
                        break
                state = client.status(args.job_id)
                if state["status"] in terminal:
                    break
                time.sleep(args.poll_seconds)
            print(json.dumps(state, indent=2, ensure_ascii=False))
            if state["status"] == "completed" and args.download is not None:
                result = client.download(
                    args.job_id,
                    args.job_directory,
                    args.download,
                )
                print(f"Remote result downloaded and request-bound: {result}")
            if state["status"] == "completed":
                return 0
            if state["status"] == "cancelled":
                return 130
            return 3
        except KeyboardInterrupt:
            print(
                "Wait stopped locally; the remote job was not cancelled.",
                file=sys.stderr,
            )
            return 130
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2

    if args.command == "modern-remote-cancel":
        try:
            state = _remote_client_from_args(args).cancel(args.job_id)
            print(json.dumps(state, indent=2, ensure_ascii=False))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-download":
        try:
            result = _remote_client_from_args(args).download(
                args.job_id,
                args.job_directory,
                args.output,
            )
            print(f"Remote result downloaded and request-bound: {result}")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-remote-delete":
        try:
            result = _remote_client_from_args(args).delete(args.job_id)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-run":
        try:
            from diffeoforge.modern_bundle import verify_modern_atlas_bundle
            from diffeoforge.modern_workflow import (
                run_modern_workflow,
                verify_modern_workflow,
            )

            run_directory = run_modern_workflow(
                args.config,
                destination=args.output,
                progress_callback=_show_modern_progress,
            )
            manifest = verify_modern_workflow(run_directory)
            print(f"Modern workflow completed: {run_directory}")
            print(f"Subject meshes: {len(manifest['input']['subjects'])}")
            print(f"Preprocessing: {manifest['preprocessing']['id']}")
            bundle = run_directory / manifest["result_bundle"]["path"]
            bundle_manifest = verify_modern_atlas_bundle(bundle)
            print(f"Atlas/PCA bundle: {bundle}")
            print(f"PCA scree plot: {bundle / bundle_manifest['pca']['plots']['scree_path']}")
            print(f"PCA scores plot: {bundle / bundle_manifest['pca']['plots']['scores_path']}")
            secondary_plot = bundle_manifest["pca"]["plots"].get("scores_pc2_pc3_path")
            if secondary_plot is None:
                reason = bundle_manifest["pca"]["plots"].get(
                    "scores_pc2_pc3_unavailable_reason",
                    "PC3 is not available",
                )
                print(f"PCA PC2 vs PC3 plot: unavailable ({reason})")
            else:
                print(f"PCA PC2 vs PC3 plot: {bundle / secondary_plot}")
            print(
                "PCA deformation meshes: "
                f"{bundle / Path(bundle_manifest['pca']['deformations']['mean_path']).parent}"
            )
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca":
        try:
            from diffeoforge.reference_pca import (
                verify_reference_pca_bundle,
                write_reference_pca_bundle,
            )

            bundle = write_reference_pca_bundle(
                args.run_directory,
                args.output,
                pca_components=args.components,
            )
            verified = verify_reference_pca_bundle(bundle, source_run=args.run_directory)
            print(f"Verified Deformetrica momenta PCA created: {bundle}")
            print(f"Subjects: {verified.manifest['inputs']['subjects']}")
            print(f"Control points: {verified.manifest['inputs']['control_point_count']}")
            print(f"Components: {verified.pca.number_of_components}")
            print(
                "PCA method: centered linear PCA by deterministic float64 SVD (not RBF KernelPCA)"
            )
            print(f"PCA scores: {bundle / verified.manifest['pca']['scores_path']}")
            print(f"PCA scree plot: {bundle / verified.manifest['pca']['plots']['scree_path']}")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-verify":
        try:
            from diffeoforge.reference_pca import verify_reference_pca_bundle

            verified = verify_reference_pca_bundle(
                args.bundle_directory,
                source_run=args.source_run,
            )
            print(f"Deformetrica momenta PCA verified: {verified.bundle_directory}")
            print(f"Subjects: {verified.manifest['inputs']['subjects']}")
            print(f"Components: {verified.pca.number_of_components}")
            print("Raw parameter hashes and recomputed PCA tables match.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-deformation-design":
        try:
            from diffeoforge.reference_pca_deformations import (
                create_reference_pca_deformation_design,
                verify_reference_pca_deformation_design,
            )

            destination = create_reference_pca_deformation_design(
                args.run_directory,
                args.output,
                pca_bundle=args.pca_bundle,
                components=args.components,
                standard_deviations=args.standard_deviations,
            )
            design = verify_reference_pca_deformation_design(
                destination,
                source_run=args.run_directory,
            )
            shooting = design["shooting"]
            print(f"Prospective reference PCA Shooting design created: {destination}")
            print(f"Endpoint momenta: {shooting['endpoint_count']}")
            print(f"Requested PCs: {shooting['requested_components']}")
            print(f"Endpoint distance: ±{shooting['standard_deviations']} SD")
            print("No Deformetrica process was started and no endpoint mesh exists yet.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-deformation-design-verify":
        try:
            from diffeoforge.reference_pca_deformations import (
                verify_reference_pca_deformation_design,
            )

            design = verify_reference_pca_deformation_design(
                args.design_directory,
                source_run=args.source_run,
            )
            print(f"Reference PCA Shooting design verified: {args.design_directory.resolve()}")
            print(f"Endpoint momenta: {design['shooting']['endpoint_count']}")
            print("Exact PCA recomputation and source bindings match; no run is claimed.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-deformation-run":
        try:
            from diffeoforge.reference_pca_deformations import (
                execute_reference_pca_deformation_design,
                verify_reference_pca_deformation_result,
            )

            result_directory = execute_reference_pca_deformation_design(
                args.design_directory,
                args.output,
                timeout_seconds=args.timeout_seconds,
            )
            result = verify_reference_pca_deformation_result(result_directory)
            print(f"Verified reference PCA deformation result: {result_directory}")
            print(f"Deformetrica Shooting endpoints: {len(result['endpoints'])}")
            print(f"Elapsed: {result['execution']['duration_seconds']:.1f} seconds")
            print("Endpoint meshes are structural visualizations, not biological validation.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-deformation-verify":
        try:
            from diffeoforge.reference_pca_deformations import (
                verify_reference_pca_deformation_result,
            )

            result = verify_reference_pca_deformation_result(
                args.result_directory,
                source_run=args.source_run,
            )
            print(f"Reference PCA deformation result verified: {args.result_directory.resolve()}")
            print(f"Deformetrica Shooting endpoints: {len(result['endpoints'])}")
            print("Nested design, source bindings, inventory, hashes, and VTK topology match.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-stability":
        try:
            from diffeoforge.reference_pca_stability import (
                verify_reference_pca_stability,
                write_reference_pca_stability,
            )

            artifact = write_reference_pca_stability(
                args.reference_bundle,
                args.comparison_bundle,
                args.output,
                variance_target=args.variance_target,
                component_count=args.components,
            )
            verified = verify_reference_pca_stability(artifact)
            print(f"Verified paired PCA stability evidence created: {artifact}")
            print(f"Score linear CKA: {verified.evidence.score_linear_cka:.9g}")
            print(
                "Score distance-rank correlation: "
                f"{verified.evidence.score_distance_rank_correlation:.9g}"
            )
            if verified.evidence.feature_subspace_available:
                print(
                    "Minimum principal cosine: "
                    f"{verified.evidence.minimum_principal_cosine:.9g}"
                )
            else:
                print(
                    "Feature-subspace comparison unavailable: "
                    f"{verified.evidence.feature_subspace_unavailable_reason}"
                )
            print("This is numerical stability evidence, not biological validation.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-pca-stability-verify":
        try:
            from diffeoforge.reference_pca_stability import (
                verify_reference_pca_stability,
            )

            verified = verify_reference_pca_stability(args.artifact_directory)
            print(f"Paired PCA stability evidence verified: {verified.artifact_directory}")
            print("Both PCA bundles and the exact stability calculation match.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-pca-stability":
        try:
            from diffeoforge.modern_pca_stability import (
                verify_modern_pca_stability,
                write_modern_pca_stability,
            )

            artifact = write_modern_pca_stability(
                args.reference_bundle,
                args.comparison_bundle,
                args.output,
                variance_target=args.variance_target,
                component_count=args.components,
            )
            verified = verify_modern_pca_stability(artifact)
            print(f"Verified Modern PCA stability evidence created: {artifact}")
            print(f"Score linear CKA: {verified.evidence.score_linear_cka:.9g}")
            print(
                "Score distance-rank correlation: "
                f"{verified.evidence.score_distance_rank_correlation:.9g}"
            )
            if verified.evidence.feature_subspace_available:
                print(
                    "Minimum principal cosine: "
                    f"{verified.evidence.minimum_principal_cosine:.9g}"
                )
            else:
                print(
                    "Feature-subspace comparison unavailable: "
                    f"{verified.evidence.feature_subspace_unavailable_reason}"
                )
            print("This is numerical stability evidence, not biological validation.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-pca-stability-verify":
        try:
            from diffeoforge.modern_pca_stability import (
                verify_modern_pca_stability,
            )

            verified = verify_modern_pca_stability(args.artifact_directory)
            print(f"Modern PCA stability evidence verified: {verified.artifact_directory}")
            print("Both Modern bundles and the exact stability calculation match.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-plan":
        try:
            from diffeoforge.modern_workload import (
                REPORT_HTML_NAME,
                REPORT_JSON_NAME,
                plan_modern_workload,
            )

            report_directory = plan_modern_workload(
                args.config,
                destination=args.output,
                overwrite=args.force,
            )
            report = json.loads((report_directory / REPORT_JSON_NAME).read_text(encoding="utf-8"))
            largest_execution_bytes = report["payload_model"][
                "largest_single_execution_xyz_difference_tensor_bytes"
            ]
            print(f"Modern workload plan created: {report_directory}")
            print(f"Subject meshes: {report['input']['subject_count']}")
            print(
                "Optimizer evaluation upper bound: "
                f"{report['optimizer_bound']['objective_gradient_evaluation_upper_bound']}"
            )
            print(
                f"Largest dense-equivalent execution XYZ payload: {largest_execution_bytes} bytes"
            )
            print(f"Pairwise execution: {report['engine']['pairwise_evaluation']['mode']}")
            print(f"Machine-readable report: {report_directory / REPORT_JSON_NAME}")
            print(f"Review report: {report_directory / REPORT_HTML_NAME}")
            print("WARNING: This is not a peak-RAM estimate or runtime forecast.")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark":
        try:
            from diffeoforge.modern_benchmark import (
                REPORT_HTML_NAME,
                REPORT_JSON_NAME,
                benchmark_modern_objective,
            )

            report_directory = benchmark_modern_objective(
                args.config,
                subject_count=args.subjects,
                repeats=args.repeats,
                warmup_evaluations=args.warmups,
                tile_autograd_strategy=args.tile_autograd_strategy,
                query_tile_size=args.query_tile_size,
                source_tile_size=args.source_tile_size,
                destination=args.output,
                overwrite=args.force,
            )
            report = json.loads((report_directory / REPORT_JSON_NAME).read_text(encoding="utf-8"))
            wall_ms = report["summary"]["wall_time_ns"]["median"] / 1_000_000
            peak_mib = report["summary"]["sampled_peak_rss_bytes"]["median"] / 1024**2
            print(f"Modern objective benchmark created: {report_directory}")
            print(f"Selected subjects: {report['input']['selected_subject_count']}")
            print(f"Fresh-process repeats: {report['configuration']['repeats']}")
            if report["benchmark_version"] == "0.4":
                source_pairwise = report["configuration"]["source_pairwise_evaluation"]
                pairwise = report["configuration"]["effective_pairwise_evaluation"]
                print(
                    "Source-declared tile rows: "
                    f"{source_pairwise['query_tile_size']} x "
                    f"{source_pairwise['source_tile_size']}"
                )
                print(
                    "Effective benchmark-only tile rows: "
                    f"{pairwise['query_tile_size']} x {pairwise['source_tile_size']}"
                )
            else:
                pairwise = report["configuration"]["pairwise_evaluation"]
            print(f"Pairwise execution: {pairwise['mode']}")
            print(f"Tile autograd strategy: {report['configuration']['tile_autograd_strategy']}")
            print(f"Median measured objective+gradient wall time: {wall_ms:.3f} ms")
            print(f"Median sampled process RSS: {peak_mib:.2f} MiB")
            print(f"Machine-readable report: {report_directory / REPORT_JSON_NAME}")
            print(f"Review report: {report_directory / REPORT_HTML_NAME}")
            print("WARNING: Do not extrapolate this objective-only measurement to 300 subjects.")
        except ImportError as error:
            print(
                "ERROR: Modern benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark":
        try:
            from diffeoforge.modern_optimizer_benchmark import (
                REPORT_HTML_NAME,
                REPORT_JSON_NAME,
                benchmark_modern_optimizer,
            )

            def show_optimizer_benchmark_progress(event) -> None:
                record = event.record
                block = "initial" if record.block is None else record.block
                print(
                    f"Benchmark repeat {event.repeat}/{event.total_repeats}: "
                    f"cycle {record.cycle}, {block} {record.status}; "
                    f"elapsed {event.optimizer_elapsed_ns / 1e9:.1f} s; "
                    f"objective={record.objective:.12g}",
                    flush=True,
                )

            report_directory = benchmark_modern_optimizer(
                args.config,
                subject_count=args.subjects,
                max_cycles=args.cycles,
                repeats=args.repeats,
                warmup_runs=args.warmups,
                destination=args.output,
                overwrite=args.force,
                progress_callback=show_optimizer_benchmark_progress,
            )
            report = json.loads((report_directory / REPORT_JSON_NAME).read_text(encoding="utf-8"))
            optimizer_seconds = report["summary"]["optimizer_wall_time_ns"]["median"] / 1e9
            preparation_seconds = (
                report["summary"]["target_preparation_wall_time_ns"]["median"] / 1e9
            )
            sample = report["samples"][0]
            print(f"Modern optimizer benchmark created: {report_directory}")
            print(f"Selected subjects: {report['input']['selected_subject_count']}")
            print(f"Measured cycle cap: {report['configuration']['measured_max_cycles']}")
            print(f"Fresh-process repeats: {report['configuration']['repeats']}")
            print(f"Median target-cache preparation: {preparation_seconds:.3f} s")
            print(f"Median optimizer wall time: {optimizer_seconds:.3f} s")
            print(
                "Objective/gradient evaluations: "
                f"{sample['objective_evaluations']}/{sample['gradient_evaluations']}"
            )
            print(
                "Line-search candidates without backward pass: "
                f"{sample['line_search_candidates_without_gradient']}"
            )
            print(
                "Repeat-consistent results: "
                f"{str(report['repeat_consistency']['consistent']).lower()}"
            )
            print(f"Machine-readable report: {report_directory / REPORT_JSON_NAME}")
            print(f"Review report: {report_directory / REPORT_HTML_NAME}")
            print("WARNING: This limited-cycle benchmark is not a convergence or ETA result.")
        except ImportError as error:
            print(
                "ERROR: Modern optimizer benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-verify":
        try:
            from diffeoforge.modern_optimizer_benchmark import (
                verify_modern_optimizer_benchmark_report,
            )

            report = verify_modern_optimizer_benchmark_report(args.report_directory)
            print(f"Modern optimizer benchmark verified: {args.report_directory.resolve()}")
            print(f"Fresh-process repeats: {report['configuration']['repeats']}")
            print(
                "Repeat-consistent results: "
                f"{str(report['repeat_consistency']['consistent']).lower()}"
            )
        except ImportError as error:
            print(
                "ERROR: Modern optimizer benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-design":
        try:
            from diffeoforge.modern_optimizer_benchmark_design import (
                DESIGN_HTML_NAME,
                DESIGN_JSON_NAME,
                DESIGN_SIDECAR_NAME,
                create_modern_optimizer_benchmark_design,
                verify_modern_optimizer_benchmark_design,
            )

            design_directory = create_modern_optimizer_benchmark_design(
                args.config,
                subject_counts=args.subjects,
                cycle_caps=args.cycles,
                repeats_per_condition=args.repeats,
                warmup_runs=args.warmups,
                order_seed=args.order_seed,
                destination=args.output,
            )
            design = verify_modern_optimizer_benchmark_design(design_directory)
            protocol = design["protocol"]
            print(f"Prospective optimizer scaling design created: {design_directory}")
            print(f"Subject-prefix sizes: {protocol['subject_counts']}")
            print(f"Cycle caps: {protocol['cycle_caps']}")
            print(
                "Frozen condition count: "
                f"{protocol['condition_count']}/{protocol['maximum_condition_count']}"
            )
            print(f"Deterministic order seed: {protocol['order_seed']}")
            print(f"Machine-readable design: {design_directory / DESIGN_JSON_NAME}")
            print(f"Integrity sidecar: {design_directory / DESIGN_SIDECAR_NAME}")
            print(f"Review page: {design_directory / DESIGN_HTML_NAME}")
            print("WARNING: No optimizer has been run and no performance claim is made.")
        except ImportError as error:
            print(
                "ERROR: Modern optimizer design dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-design-verify":
        try:
            from diffeoforge.modern_optimizer_benchmark_design import (
                verify_modern_optimizer_benchmark_design,
            )

            design_directory = args.design_directory.expanduser().resolve()
            design = verify_modern_optimizer_benchmark_design(design_directory)
            protocol = design["protocol"]
            print(f"Prospective optimizer scaling design verified: {design_directory}")
            print(
                "Frozen condition count: "
                f"{protocol['condition_count']}/{protocol['maximum_condition_count']}"
            )
            print("No optimizer result or performance claim is present.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-study":
        try:
            from diffeoforge.modern_optimizer_benchmark_study import (
                run_modern_optimizer_benchmark_study,
                verify_modern_optimizer_benchmark_study_run,
            )

            def show_optimizer_study_progress(event) -> None:
                condition = event.condition
                detail = ""
                if condition is not None:
                    detail = (
                        f"; {condition.condition_id}; "
                        f"{condition.subject_count} subjects; "
                        f"{condition.cycle_cap} cycles"
                    )
                observation = event.observation
                if observation is not None:
                    optimizer = observation.optimizer
                    elapsed_seconds = observation.optimizer_elapsed_ns / 1e9
                    eta = ""
                    if optimizer.completed_decisions > 0:
                        remaining_seconds = elapsed_seconds * (
                            optimizer.maximum_decisions - optimizer.completed_decisions
                        ) / optimizer.completed_decisions
                        remaining = (
                            f"{remaining_seconds:.0f} s"
                            if remaining_seconds < 60
                            else f"{remaining_seconds / 60:.1f} min"
                        )
                        eta = f"; observed ETA to decision cap ~{remaining}"
                    elapsed = (
                        f"{elapsed_seconds:.1f} s"
                        if elapsed_seconds < 60
                        else f"{elapsed_seconds / 60:.1f} min"
                    )
                    detail += (
                        f"; repeat {observation.repeat}/{observation.total_repeats}; "
                        f"decision {optimizer.completed_decisions}/"
                        f"{optimizer.maximum_decisions}; cycle {optimizer.cycle}/"
                        f"{optimizer.max_cycles}; block {optimizer.block or 'initial'}; "
                        f"{optimizer.status}; elapsed {elapsed}"
                        f"{eta}"
                    )
                print(
                    "Optimizer study progress "
                    f"[{event.completed_conditions}/{event.total_conditions}] "
                    f"{event.status}{detail}",
                    flush=True,
                )

            run_directory = run_modern_optimizer_benchmark_study(
                args.design_directory,
                args.config,
                destination=args.output,
                progress_callback=show_optimizer_study_progress,
            )
            manifest = verify_modern_optimizer_benchmark_study_run(run_directory)
            print(f"Frozen optimizer benchmark study completed: {run_directory}")
            print(f"Verified raw conditions: {len(manifest['conditions'])}")
            print(
                "No automatic comparison or convergence claim was produced; only an "
                "observed decision-rate ETA to the configured cap was shown, not a fitted "
                "scaling ETA."
            )
        except ImportError as error:
            print(
                "ERROR: Modern optimizer study dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-study-status":
        try:
            from diffeoforge.modern_optimizer_benchmark_study import (
                inspect_modern_optimizer_benchmark_study_run,
            )

            status = inspect_modern_optimizer_benchmark_study_run(args.run_directory)
            if args.json:
                print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Optimizer study status: {status['status']}")
                print(
                    "Strictly verified raw reports: "
                    f"{status['verified_report_count']}/{status['total_condition_count']}"
                )
                print(
                    "State-recorded completed conditions: "
                    f"{status['state_completed_condition_count']}"
                )
                print(f"Execution lock: {status['lock']['status']}")
                if status["next_condition"] is not None:
                    condition = status["next_condition"]
                    print(
                        "Next frozen condition: "
                        f"{condition['condition_id']} "
                        f"({condition['subject_count']} subjects, "
                        f"{condition['cycle_cap']} cycles)"
                    )
                if status["reconciliation_required"]:
                    print(
                        "RECOVERABLE: Valid report evidence is ahead of atomic state; "
                        "the runner can reconcile it."
                    )
                print(
                    "Completion manifest: "
                    f"{status['completion_manifest_status']}; "
                    f"verified={str(status['completion_manifest_verified']).lower()}"
                )
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-study-verify":
        try:
            from diffeoforge.modern_optimizer_benchmark_study import (
                verify_modern_optimizer_benchmark_study_run,
            )

            run_directory = args.run_directory.expanduser().resolve()
            manifest = verify_modern_optimizer_benchmark_study_run(run_directory)
            print(f"Frozen optimizer benchmark study verified: {run_directory}")
            print(f"Verified raw conditions: {len(manifest['conditions'])}")
            print(
                "No automatic comparison or convergence claim is present; any live ETA was "
                "an observed decision-rate estimate to the configured cap, not a fitted "
                "scaling ETA."
            )
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-study-compare":
        try:
            from diffeoforge.modern_optimizer_benchmark_comparison import (
                compare_modern_optimizer_benchmark_studies,
                verify_modern_optimizer_benchmark_comparison,
            )

            destination = compare_modern_optimizer_benchmark_studies(
                args.baseline_run,
                args.candidate_run,
                args.output,
            )
            comparison = verify_modern_optimizer_benchmark_comparison(destination)
            ratios = comparison["performance"]["candidate_to_baseline_median_ratios"]
            print(f"Optimizer study comparison created and verified: {destination}")
            print(
                "Comparison dimension: "
                f"{comparison.get('comparison_dimension', 'pairwise_evaluation')}"
            )
            print(
                "Candidate/baseline median optimizer-time ratio: "
                f"{ratios['optimizer_wall_time_ns']:.6g}"
            )
            print(
                "Discrete work and outcomes match: "
                f"{str(comparison['numerical_agreement']['all_discrete_work_and_outcomes_match']).lower()}"
            )
            print("No automatic winner, safe preset, ETA, or scaling claim was produced.")
        except ImportError as error:
            print(
                "ERROR: Modern optimizer comparison dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-optimizer-benchmark-study-comparison-verify":
        try:
            from diffeoforge.modern_optimizer_benchmark_comparison import (
                verify_modern_optimizer_benchmark_comparison,
            )

            comparison = verify_modern_optimizer_benchmark_comparison(
                args.comparison_directory
            )
            print(
                "Optimizer study comparison verified: "
                f"{args.comparison_directory.resolve()}"
            )
            print(
                "Comparison dimension: "
                f"{comparison.get('comparison_dimension', 'pairwise_evaluation')}"
            )
            print(
                "Discrete work and outcomes match: "
                f"{str(comparison['numerical_agreement']['all_discrete_work_and_outcomes_match']).lower()}"
            )
            print("All source studies and comparison fields were recomputed.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-design":
        try:
            from diffeoforge.modern_benchmark_design import (
                DESIGN_HTML_NAME,
                DESIGN_JSON_NAME,
                DESIGN_SIDECAR_NAME,
                create_modern_benchmark_design,
                verify_modern_benchmark_design,
            )

            design_directory = create_modern_benchmark_design(
                args.config,
                subject_counts=args.subjects,
                repeats_per_condition=args.repeats,
                warmup_evaluations=args.warmups,
                order_seed=args.order_seed,
                destination=args.output,
            )
            design = verify_modern_benchmark_design(design_directory)
            print(f"Prospective benchmark design created: {design_directory}")
            print(f"Paired subject-prefix sizes: {design['protocol']['subject_counts']}")
            print(f"Frozen condition count: {len(design['conditions'])}")
            print(f"Deterministic order seed: {design['protocol']['order_seed']}")
            print(f"Machine-readable design: {design_directory / DESIGN_JSON_NAME}")
            print(f"Integrity sidecar: {design_directory / DESIGN_SIDECAR_NAME}")
            print(f"Review page: {design_directory / DESIGN_HTML_NAME}")
            print("WARNING: No benchmark has been run and no performance claim is made.")
        except ImportError as error:
            print(
                "ERROR: Modern benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-design-verify":
        try:
            from diffeoforge.modern_benchmark_design import (
                verify_modern_benchmark_design,
            )

            design_directory = args.design_directory.expanduser().resolve()
            design = verify_modern_benchmark_design(design_directory)
            print(f"Prospective benchmark design verified: {design_directory}")
            print(f"Frozen condition count: {len(design['conditions'])}")
            print("No benchmark result or performance claim is present.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-matrix-design":
        try:
            from diffeoforge.modern_benchmark_matrix_design import (
                MATRIX_DESIGN_HTML_NAME,
                MATRIX_DESIGN_JSON_NAME,
                MATRIX_DESIGN_SIDECAR_NAME,
                collect_modern_benchmark_matrix_design,
                default_modern_benchmark_matrix_design_path,
                verify_modern_benchmark_matrix_design,
                write_modern_benchmark_matrix_design,
            )

            prospective_design = collect_modern_benchmark_matrix_design(
                args.config,
                subject_counts=args.subjects,
                tile_shapes=args.tile_shape,
                repeats_per_condition=args.repeats,
                warmup_evaluations=args.warmups,
                order_seed=args.order_seed,
            )
            prospective_protocol = prospective_design["protocol"]
            print(
                "Pre-publication full-factorial review: "
                f"{prospective_protocol['cell_count']} cells; "
                f"{prospective_protocol['condition_count']}/"
                f"{prospective_protocol['maximum_condition_count']} conditions."
            )
            design_directory = (
                default_modern_benchmark_matrix_design_path(args.config)
                if args.output is None
                else args.output
            )
            design_directory = write_modern_benchmark_matrix_design(
                prospective_design, design_directory
            )
            design = verify_modern_benchmark_matrix_design(design_directory)
            protocol = design["protocol"]
            print(f"Prospective benchmark matrix design created: {design_directory}")
            print(f"Subject-prefix sizes: {protocol['subject_counts']}")
            print(
                "Ordered query/source tile shapes: "
                + ", ".join(
                    f"{shape['query_tile_size']}x{shape['source_tile_size']}"
                    for shape in protocol["tile_shapes"]
                )
            )
            print(f"Frozen full-factorial cells: {protocol['cell_count']}")
            print(
                "Frozen condition count: "
                f"{protocol['condition_count']}/{protocol['maximum_condition_count']}"
            )
            print(f"Deterministic order seed: {protocol['order_seed']}")
            print(f"Machine-readable design: {design_directory / MATRIX_DESIGN_JSON_NAME}")
            print(f"Integrity sidecar: {design_directory / MATRIX_DESIGN_SIDECAR_NAME}")
            print(f"Review page: {design_directory / MATRIX_DESIGN_HTML_NAME}")
            print("WARNING: No benchmark has been run and no performance claim is made.")
        except ImportError as error:
            print(
                "ERROR: Modern benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-matrix-design-verify":
        try:
            from diffeoforge.modern_benchmark_matrix_design import (
                verify_modern_benchmark_matrix_design,
            )

            design_directory = args.design_directory.expanduser().resolve()
            design = verify_modern_benchmark_matrix_design(design_directory)
            protocol = design["protocol"]
            print(f"Prospective benchmark matrix design verified: {design_directory}")
            print(f"Frozen full-factorial cells: {protocol['cell_count']}")
            print(
                "Frozen condition count: "
                f"{protocol['condition_count']}/{protocol['maximum_condition_count']}"
            )
            print("No benchmark result or performance claim is present.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-matrix-study":
        try:
            from diffeoforge.modern_benchmark_matrix_study import (
                MANIFEST_NAME,
                run_modern_benchmark_matrix_study,
                verify_modern_benchmark_matrix_study_run,
            )

            def show_matrix_study_progress(event) -> None:
                condition = ""
                if event.condition is not None:
                    condition = (
                        f"; {event.condition.condition_id}; "
                        f"{event.condition.tile_autograd_strategy}; "
                        f"{event.condition.subject_count} subjects; "
                        f"tiles {event.condition.query_tile_size}x"
                        f"{event.condition.source_tile_size}"
                    )
                print(
                    "Matrix study progress "
                    f"[{event.completed_conditions}/{event.total_conditions} conditions] "
                    f"{event.status}{condition}: {event.message}",
                    flush=True,
                )

            run_directory = run_modern_benchmark_matrix_study(
                args.design_directory,
                args.config,
                destination=args.output,
                progress_callback=show_matrix_study_progress,
            )
            manifest = verify_modern_benchmark_matrix_study_run(run_directory)
            print(f"Frozen benchmark matrix study completed and verified: {run_directory}")
            print(f"Separate raw v0.4 condition reports: {len(manifest['conditions'])}")
            print(f"Completion manifest: {run_directory / MANIFEST_NAME}")
            print("WARNING: No automatic comparison or performance claim was produced.")
        except ImportError as error:
            print(
                "ERROR: Modern benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-matrix-study-status":
        try:
            from diffeoforge.modern_benchmark_matrix_study import (
                inspect_modern_benchmark_matrix_study_run,
            )

            status = inspect_modern_benchmark_matrix_study_run(args.run_directory)
            if args.json:
                print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Matrix study status: {status['status']}")
                print(
                    "Strictly verified raw v0.4 reports: "
                    f"{status['verified_report_count']}/{status['total_condition_count']}"
                )
                print(
                    "State-recorded completed conditions: "
                    f"{status['state_completed_condition_count']}"
                )
                print(f"Execution lock: {status['lock']['status']}")
                if status["next_condition"] is not None:
                    condition = status["next_condition"]
                    plan = condition["effective_pairwise_evaluation"]
                    print(
                        "Next frozen matrix condition: "
                        f"{condition['condition_id']} "
                        f"({condition['tile_autograd_strategy']}, "
                        f"{condition['subject_count']} subjects, "
                        f"tiles {plan['query_tile_size']}x{plan['source_tile_size']})"
                    )
                if status["reconciliation_required"]:
                    print(
                        "RECOVERABLE: Valid report evidence is ahead of atomic state; "
                        "the matrix runner can reconcile it."
                    )
                print(
                    "Completion manifest: "
                    f"{status['completion_manifest_status']}; "
                    f"verified={str(status['completion_manifest_verified']).lower()}"
                )
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-matrix-study-verify":
        try:
            from diffeoforge.modern_benchmark_matrix_study import (
                MANIFEST_NAME,
                verify_modern_benchmark_matrix_study_run,
            )

            run_directory = args.run_directory.resolve()
            manifest = verify_modern_benchmark_matrix_study_run(run_directory)
            print(f"Completed benchmark matrix study verified: {run_directory}")
            print(f"Separate raw v0.4 condition reports: {len(manifest['conditions'])}")
            print(f"Completion manifest: {run_directory / MANIFEST_NAME}")
            print("No automatic comparison or performance claim is present.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-study":
        try:
            from diffeoforge.modern_benchmark_study import (
                MANIFEST_NAME,
                run_modern_benchmark_study,
                verify_modern_benchmark_study_run,
            )

            def show_study_progress(event) -> None:
                condition = ""
                if event.condition is not None:
                    condition = (
                        f"; {event.condition.condition_id}; "
                        f"{event.condition.tile_autograd_strategy}; "
                        f"{event.condition.subject_count} subjects"
                    )
                print(
                    "Study progress "
                    f"[{event.completed_conditions}/{event.total_conditions} conditions] "
                    f"{event.status}{condition}: {event.message}",
                    flush=True,
                )

            run_directory = run_modern_benchmark_study(
                args.design_directory,
                args.config,
                destination=args.output,
                progress_callback=show_study_progress,
            )
            manifest = verify_modern_benchmark_study_run(run_directory)
            print(f"Frozen benchmark study completed and verified: {run_directory}")
            print(f"Separate raw condition reports: {len(manifest['conditions'])}")
            print(f"Completion manifest: {run_directory / MANIFEST_NAME}")
            print("WARNING: No automatic comparison or performance claim was produced.")
        except ImportError as error:
            print(
                "ERROR: Modern benchmark dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-study-status":
        try:
            from diffeoforge.modern_benchmark_study import (
                inspect_modern_benchmark_study_run,
            )

            status = inspect_modern_benchmark_study_run(args.run_directory)
            if args.json:
                print(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Study status: {status['status']}")
                print(
                    "Strictly verified raw reports: "
                    f"{status['verified_report_count']}/{status['total_condition_count']}"
                )
                print(
                    "State-recorded completed conditions: "
                    f"{status['state_completed_condition_count']}"
                )
                print(f"Execution lock: {status['lock']['status']}")
                if status["next_condition"] is not None:
                    condition = status["next_condition"]
                    print(
                        "Next frozen condition: "
                        f"{condition['condition_id']} "
                        f"({condition['tile_autograd_strategy']}, "
                        f"{condition['subject_count']} subjects)"
                    )
                if status["reconciliation_required"]:
                    print(
                        "RECOVERABLE: Valid report evidence is ahead of atomic state; "
                        "the runner can reconcile it."
                    )
                print(
                    "Completion manifest: "
                    f"{status['completion_manifest_status']}; "
                    f"verified={str(status['completion_manifest_verified']).lower()}"
                )
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-benchmark-study-verify":
        try:
            from diffeoforge.modern_benchmark_study import (
                MANIFEST_NAME,
                verify_modern_benchmark_study_run,
            )

            run_directory = args.run_directory.resolve()
            manifest = verify_modern_benchmark_study_run(run_directory)
            print(f"Completed benchmark study verified: {run_directory}")
            print(f"Separate raw condition reports: {len(manifest['conditions'])}")
            print(f"Completion manifest: {run_directory / MANIFEST_NAME}")
            print("No automatic comparison or performance claim is present.")
        except (RuntimeError, OSError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-verify":
        try:
            from diffeoforge.modern_bundle import verify_modern_atlas_bundle
            from diffeoforge.modern_workflow import verify_modern_workflow

            manifest = verify_modern_workflow(args.run_directory)
            run_directory = args.run_directory.resolve()
            bundle = run_directory / manifest["result_bundle"]["path"]
            bundle_manifest = verify_modern_atlas_bundle(bundle)
            print(f"Modern workflow verified: {run_directory}")
            print(f"Subject meshes: {len(manifest['input']['subjects'])}")
            print(f"PCA scree plot: {bundle / bundle_manifest['pca']['plots']['scree_path']}")
            secondary_plot = bundle_manifest["pca"]["plots"].get("scores_pc2_pc3_path")
            if secondary_plot is None:
                reason = bundle_manifest["pca"]["plots"].get(
                    "scores_pc2_pc3_unavailable_reason",
                    "PC3 is not available",
                )
                print(f"PCA PC2 vs PC3 plot: unavailable ({reason})")
            else:
                print(f"PCA PC2 vs PC3 plot: {bundle / secondary_plot}")
        except ImportError as error:
            print(
                "ERROR: Modern engine dependencies are missing; install "
                "diffeoforge[modern-engine].",
                file=sys.stderr,
            )
            print(f"       {error}", file=sys.stderr)
            return 2
        except (ConfigurationError, RuntimeError, ValueError, TypeError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-validation-synthetic-create":
        try:
            manifest = write_synthetic_validation_benchmark(
                args.template,
                args.output,
                subjects_per_family=args.subjects_per_family,
            )
            print(f"Synthetic validation benchmark created: {manifest.parent}")
            print(f"Ground-truth manifest: {manifest}")
            print(
                "Ordered vertex correspondence is known; analytic anatomy is not a "
                "substitute for independent biological validation."
            )
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-validation-synthetic-evaluate":
        try:
            result = evaluate_synthetic_correspondence_error(args.recovered, args.truth)
            print(f"Known-correspondence vertices: {result.vertex_count}")
            print(f"Vertex RMSE: {result.vertex_rmse:.9g}")
            print(f"Vertex error p95: {result.vertex_p95:.9g}")
            print(f"Vertex error maximum: {result.vertex_maximum:.9g}")
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-synthetic-recovery-init":
        try:
            from diffeoforge.modern_synthetic_recovery import (
                create_modern_synthetic_recovery_design,
            )

            design = create_modern_synthetic_recovery_design(
                args.benchmark_directory,
                args.output,
                max_cycles=args.cycles,
                control_point_count=args.control_points,
                recovery_metric=args.recovery_metric.replace("-", "_"),
            )
            print(f"Prospective synthetic recovery design created: {design.parent}")
            print(f"Euclidean config: {design.parent / 'modern-euclidean.yaml'}")
            print(f"Sobolev config: {design.parent / 'modern-sobolev.yaml'}")
            print("No atlas optimization was started.")
        except (
            ConfigurationError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-synthetic-recovery-design-verify":
        try:
            from diffeoforge.modern_synthetic_recovery import (
                verify_modern_synthetic_recovery_design,
            )

            design = verify_modern_synthetic_recovery_design(args.design_directory)
            print("Synthetic recovery design verification: PASS")
            print(f"Subjects: {design['benchmark']['subjects']}")
            print(
                "Recovery metric: "
                f"{design['protocol'].get('recovery_metric', 'ordered_vertex')}"
            )
            print(
                f"Engine implementation: {design['protocol']['arms'][0]['engine_implementation']}"
            )
        except (
            ConfigurationError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-synthetic-recovery-assess":
        try:
            from diffeoforge.modern_synthetic_recovery import (
                assess_modern_synthetic_recovery,
            )

            assessment = assess_modern_synthetic_recovery(
                args.design_directory,
                args.euclidean_run,
                args.sobolev_run,
                args.output,
            )
            value = json.loads(assessment.read_text(encoding="utf-8"))
            print(f"Synthetic recovery assessment created: {assessment.parent}")
            for arm in value["arms"]:
                print(
                    f"{arm['arm_id']}: {arm['decision']}; "
                    f"reconstruction p95/diagonal="
                    f"{arm['pooled_reconstruction_error']['p95_over_template_diagonal']:.9g}"
                )
            print("Paired comparison is descriptive; no superiority winner is selected.")
        except (
            ConfigurationError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "modern-synthetic-recovery-assessment-verify":
        try:
            from diffeoforge.modern_synthetic_recovery import (
                verify_modern_synthetic_recovery_assessment,
            )

            value = verify_modern_synthetic_recovery_assessment(args.assessment_directory)
            print("Synthetic recovery assessment verification: PASS")
            for arm in value["arms"]:
                print(f"{arm['arm_id']}: {arm['decision']}")
        except (
            ConfigurationError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-validation-study-init":
        try:
            snapshot = create_reference_validation_study(
                args.config,
                args.output,
                holdout_fraction=args.holdout_fraction,
                resample_count=args.resamples,
                resample_fraction=args.resample_fraction,
                maximum_iterations=args.max_iterations,
            )
            print(f"Validation Lab study created: {snapshot.study_directory}")
            print(
                f"Frozen design: {len(snapshot.plan.finalists)} finalists; "
                f"{len(snapshot.plan.training_subjects)} training subjects; "
                f"{len(snapshot.plan.heldout_subjects)} untouched heldout subjects; "
                f"{len(snapshot.runs)} atlas runs."
            )
            print(f"Plan fingerprint: {snapshot.plan.fingerprint}")
            print("No process was started.")
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-validation-study-status":
        try:
            snapshot = load_reference_validation_study(args.study_directory)
            value = {
                "study_directory": str(snapshot.study_directory),
                "study_id": snapshot.study_id,
                "status": snapshot.status,
                "plan_fingerprint": snapshot.plan.fingerprint,
                "completed_run_count": snapshot.completed_run_count,
                "run_count": len(snapshot.runs),
                "runs": [
                    {
                        "run_id": run.run_id,
                        "finalist_id": run.finalist_id,
                        "cohort_id": run.cohort_id,
                        "status": run.status,
                        "attempts": run.attempts,
                        "error": run.error,
                    }
                    for run in snapshot.runs
                ],
                "assessment": (
                    None if snapshot.assessment is None else snapshot.assessment.as_manifest()
                ),
                "report_json_path": (
                    None if snapshot.report_json_path is None else str(snapshot.report_json_path)
                ),
                "report_html_path": (
                    None if snapshot.report_html_path is None else str(snapshot.report_html_path)
                ),
            }
            if args.json:
                print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Validation Lab: {snapshot.study_directory}")
                print(f"Status: {snapshot.status}")
                print(f"Runs: {snapshot.completed_run_count}/{len(snapshot.runs)} complete")
                if snapshot.assessment is not None:
                    print(f"Evidence: {snapshot.assessment.confidence}")
                    print(
                        "Preferred finalist: "
                        f"{snapshot.assessment.recommended_finalist_id or 'none'}"
                    )
                if snapshot.report_html_path is not None:
                    print(f"Report: {snapshot.report_html_path}")
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-validation-study-run":
        try:
            before = load_reference_validation_study(args.study_directory)
            run_order = {run.run_id: index for index, run in enumerate(before.runs, start=1)}

            def show_validation_event(event) -> None:
                kind = str(event["event"])
                run_id = str(event.get("run_id", ""))
                prefix = f"[run {run_order.get(run_id, '?')}/{len(before.runs)} {run_id}]"
                if kind == "worker_event":
                    worker = event["worker_event"]
                    if worker["kind"] == "phase":
                        print(f"{prefix} {worker['payload']['message']}", flush=True)
                elif kind == "run_started":
                    print(f"{prefix} started", flush=True)
                elif kind == "run_completed":
                    evidence = event["evidence"]
                    print(
                        f"{prefix} completed; external surface p95 "
                        f"{float(evidence['external_residual_p95']):.6g}",
                        flush=True,
                    )
                elif kind in {"run_failed", "run_interrupted"}:
                    print(f"{prefix} {kind}: {event['error']}", flush=True)

            result = ReferenceValidationStudyRunner(args.study_directory).run_all(
                event_callback=show_validation_event
            )
            print(
                f"Validation status: {result.status}; "
                f"{result.completed_run_count}/{len(result.runs)} runs complete"
            )
            if result.assessment is not None:
                print(f"Evidence: {result.assessment.confidence}")
                print(f"Preferred finalist: {result.assessment.recommended_finalist_id or 'none'}")
                print(f"Report: {result.report_html_path}")
                print(
                    "Claim scope: robustness within the frozen finalist search space; "
                    "heldout and biological validation gates remain."
                )
        except KeyboardInterrupt:
            print(
                "Validation interrupted. Completed runs remain immutable; run this "
                "command again to continue.",
                file=sys.stderr,
            )
            return 130
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-holdout-study-init":
        try:
            snapshot = create_reference_holdout_study(
                args.validation_study_directory,
                maximum_iterations=args.max_iterations,
            )
            print(f"Fixed-template holdout study created: {snapshot.study_directory}")
            print(
                f"Frozen design: {len(snapshot.finalist_ids)} trained finalists; "
                f"{len(snapshot.heldout_subjects)} untouched subjects; "
                f"{len(snapshot.runs)} registration runs."
            )
            print("No process was started. Template and control points are hash-bound.")
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-holdout-study-status":
        try:
            snapshot = load_reference_holdout_study(args.study_directory)
            value = {
                "study_directory": str(snapshot.study_directory),
                "study_id": snapshot.study_id,
                "parent_study_id": snapshot.parent_study_id,
                "status": snapshot.status,
                "heldout_subject_count": len(snapshot.heldout_subjects),
                "completed_run_count": snapshot.completed_run_count,
                "run_count": len(snapshot.runs),
                "runs": [
                    {
                        "run_id": run.run_id,
                        "finalist_id": run.finalist_id,
                        "status": run.status,
                        "attempts": run.attempts,
                        "error": run.error,
                    }
                    for run in snapshot.runs
                ],
                "assessment": (
                    None if snapshot.assessment is None else snapshot.assessment.as_manifest()
                ),
                "report_json_path": (
                    None if snapshot.report_json_path is None else str(snapshot.report_json_path)
                ),
                "report_html_path": (
                    None if snapshot.report_html_path is None else str(snapshot.report_html_path)
                ),
            }
            if args.json:
                print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Fixed-template holdout: {snapshot.study_directory}")
                print(f"Status: {snapshot.status}")
                print(f"Runs: {snapshot.completed_run_count}/{len(snapshot.runs)} complete")
                if snapshot.assessment is not None:
                    print(f"Evidence: {snapshot.assessment.status}")
                    print(
                        f"Heldout preference: {snapshot.assessment.preferred_finalist_id or 'none'}"
                    )
                if snapshot.report_html_path is not None:
                    print(f"Report: {snapshot.report_html_path}")
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-holdout-study-run":
        try:
            before = load_reference_holdout_study(args.study_directory)
            run_order = {run.run_id: index for index, run in enumerate(before.runs, start=1)}

            def show_holdout_event(event) -> None:
                kind = str(event["event"])
                run_id = str(event.get("run_id", ""))
                prefix = f"[run {run_order.get(run_id, '?')}/{len(before.runs)} {run_id}]"
                if kind == "worker_event":
                    worker = event["worker_event"]
                    if worker["kind"] == "phase":
                        print(f"{prefix} {worker['payload']['message']}", flush=True)
                    elif worker["kind"] == "progress":
                        payload = worker["payload"]
                        print(
                            f"{prefix} iteration {payload['iteration']}/"
                            f"{payload['maximum_iterations']}; elapsed "
                            f"{float(payload['elapsed_seconds']):.1f} s",
                            flush=True,
                        )
                elif kind == "run_started":
                    print(f"{prefix} started", flush=True)
                elif kind == "run_completed":
                    evidence = event["evidence"]
                    print(
                        f"{prefix} completed; heldout surface p95 "
                        f"{float(evidence['external_residual_p95']):.6g}",
                        flush=True,
                    )
                elif kind in {"run_failed", "run_interrupted"}:
                    print(f"{prefix} {kind}: {event['error']}", flush=True)

            result = ReferenceHoldoutStudyRunner(args.study_directory).run_all(
                event_callback=show_holdout_event
            )
            print(
                f"Holdout status: {result.status}; "
                f"{result.completed_run_count}/{len(result.runs)} runs complete"
            )
            if result.assessment is not None:
                print(f"Evidence: {result.assessment.status}")
                print(f"Heldout preference: {result.assessment.preferred_finalist_id or 'none'}")
                print(f"Report: {result.report_html_path}")
        except KeyboardInterrupt:
            print(
                "Holdout interrupted. Completed runs remain immutable; run this "
                "command again to continue.",
                file=sys.stderr,
            )
            return 130
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-study-init":
        try:
            snapshot = create_reference_calibration_study(
                args.config,
                args.output,
                pilot_max_iterations=args.pilot_max_iterations,
            )
            assert snapshot.current_stage is not None
            print(f"Calibration study created: {snapshot.study_directory}")
            print(
                f"Pilot cohort: {snapshot.plan.pilot_subject_count} subjects; "
                f"plan {snapshot.plan.fingerprint}"
            )
            print(
                f"Current stage: {snapshot.current_stage.order}/"
                f"{len(snapshot.plan.stages)} — {snapshot.current_stage.title}"
            )
            print(f"Prepared candidates: {len(snapshot.candidates)}; no atlas run started.")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-study-extend":
        try:
            safety_limits: dict[str, tuple[float, float]] = {}
            for declared in args.limit:
                if "=" not in declared:
                    raise ValueError(
                        "Each --limit must use PARAMETER=LOW:HIGH syntax"
                    )
                parameter, rendered_bounds = declared.split("=", maxsplit=1)
                if not parameter or ":" not in rendered_bounds:
                    raise ValueError(
                        "Each --limit must use PARAMETER=LOW:HIGH syntax"
                    )
                lower_text, upper_text = rendered_bounds.split(":", maxsplit=1)
                if parameter in safety_limits:
                    raise ValueError(f"Duplicate --limit for {parameter}")
                safety_limits[parameter] = (float(lower_text), float(upper_text))
            snapshot = create_reference_calibration_search_extension_study(
                args.source_study_directory,
                args.output,
                safety_limits=safety_limits,
                outward_steps=args.outward_steps,
            )
            assert snapshot.current_stage is not None
            pending = [
                candidate
                for candidate in snapshot.candidates
                if candidate.status == "pending"
            ]
            print(f"Calibration search successor created: {snapshot.study_directory}")
            print(f"Successor plan: {snapshot.plan.fingerprint}")
            print(
                f"Preserved candidates: {len(snapshot.candidates) - len(pending)}; "
                f"new outward candidates: {len(pending)}"
            )
            for candidate in pending:
                planned = next(
                    item
                    for item in snapshot.current_stage.candidates
                    if item.candidate_id == candidate.candidate_id
                )
                values = ", ".join(
                    f"{name}={value:.9g}" for name, value in planned.parameter_values
                )
                print(f"  {candidate.candidate_id}: {values}")
            print("No process was started. Run the successor with reference-calibration-study-run.")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-study-status":
        try:
            snapshot = load_reference_calibration_study(args.study_directory)
            value = {
                "study_directory": str(snapshot.study_directory),
                "study_id": snapshot.study_id,
                "status": snapshot.status,
                "plan_fingerprint": snapshot.plan.fingerprint,
                "current_stage": (
                    None
                    if snapshot.current_stage is None
                    else {
                        "stage_id": snapshot.current_stage.stage_id,
                        "order": snapshot.current_stage.order,
                        "title": snapshot.current_stage.title,
                    }
                ),
                "candidates": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "label": candidate.label,
                        "status": candidate.status,
                        "attempts": candidate.attempts,
                        "config_path": str(candidate.config_path),
                        "run_directory": (
                            None
                            if candidate.run_directory is None
                            else str(candidate.run_directory)
                        ),
                        "metrics": candidate.metrics,
                        "error": candidate.error,
                    }
                    for candidate in snapshot.candidates
                ],
                "selected_values": dict(snapshot.selected_values),
                "selected_candidate_ids": dict(snapshot.selected_candidate_ids),
                "event_count": snapshot.event_count,
                "final_config_path": (
                    None if snapshot.final_config_path is None else str(snapshot.final_config_path)
                ),
                "report_json_path": (
                    None if snapshot.report_json_path is None else str(snapshot.report_json_path)
                ),
                "report_html_path": (
                    None if snapshot.report_html_path is None else str(snapshot.report_html_path)
                ),
            }
            if args.json:
                print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Calibration study: {snapshot.study_directory}")
                print(f"Status: {snapshot.status}")
                if snapshot.current_stage is not None:
                    print(
                        f"Stage {snapshot.current_stage.order}/"
                        f"{len(snapshot.plan.stages)}: "
                        f"{snapshot.current_stage.title}"
                    )
                    for candidate in snapshot.candidates:
                        detail = ""
                        if candidate.metrics is not None:
                            detail = (
                                f"; residual p95 "
                                f"{float(candidate.metrics['residual_p95']):.6g}; "
                                f"runtime "
                                f"{float(candidate.metrics['runtime_seconds']):.1f} s"
                            )
                        print(
                            f"  {candidate.candidate_id}: {candidate.status}"
                            f" (attempts {candidate.attempts}){detail}"
                        )
                if snapshot.final_config_path is not None:
                    print(f"Selected full-cohort config: {snapshot.final_config_path}")
                if snapshot.report_html_path is not None:
                    print(f"Pilot recommendation report: {snapshot.report_html_path}")
                print(f"Verified event records: {snapshot.event_count}")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-study-run":
        try:
            before = load_reference_calibration_study(args.study_directory)
            if before.current_stage is None:
                raise ConfigurationError("Calibration study is already complete")
            candidate_order = {
                candidate.candidate_id: index
                for index, candidate in enumerate(before.candidates, start=1)
            }

            def show_calibration_event(event) -> None:
                kind = str(event["event"])
                candidate_id = str(event.get("candidate_id", ""))
                prefix = (
                    f"[candidate {candidate_order.get(candidate_id, '?')}/"
                    f"{len(before.candidates)} {candidate_id}]"
                )
                if kind == "candidate_worker_event":
                    worker = event["worker_event"]
                    worker_kind = worker["kind"]
                    payload = worker["payload"]
                    if worker_kind == "phase":
                        print(f"{prefix} {payload['message']}", flush=True)
                    elif worker_kind == "progress":
                        print(
                            f"{prefix} iteration {payload['iteration']}/"
                            f"{payload['maximum_iterations']}",
                            flush=True,
                        )
                    elif worker_kind == "activity":
                        print(
                            f"{prefix} active for {float(payload['elapsed_seconds']):.0f} s",
                            flush=True,
                        )
                elif kind == "candidate_started":
                    print(f"{prefix} started", flush=True)
                elif kind == "candidate_completed":
                    metrics = event["metrics"]
                    print(
                        f"{prefix} completed in "
                        f"{float(metrics['runtime_seconds']):.1f} s; "
                        f"surface-distance QC p95 "
                        f"{float(metrics['residual_p95']):.6g}",
                        flush=True,
                    )
                elif kind in {"candidate_failed", "candidate_interrupted"}:
                    print(f"{prefix} {kind}: {event['error']}", flush=True)
                elif kind == "stage_awaiting_review":
                    if not args.complete:
                        print("All candidate attempts finished; researcher selection is required.")
                elif kind == "automatic_stage_selected":
                    print(
                        f"[stage {event['completed_stage_count']}/"
                        f"{event['stage_count']}] provisional automatic selection: "
                        f"{candidate_id}",
                        flush=True,
                    )

            runner = ReferenceCalibrationStudyRunner(args.study_directory)
            result = (
                runner.run_complete_automatic_pilot(event_callback=show_calibration_event)
                if args.complete
                else runner.run_current_stage(event_callback=show_calibration_event)
            )
            print(f"Calibration status: {result.status}")
            if result.status == "completed":
                print(f"Recommended full-cohort config: {result.final_config_path}")
                print(f"Recommendation report: {result.report_html_path}")
                print(
                    "This is a provisional pilot recommendation; full-cohort "
                    "confirmation remains required."
                )
            elif result.status == "awaiting_review":
                print(
                    "No next stage was prepared automatically. Compare the completed "
                    "candidate evidence and record one explicit selection. Visual QC "
                    "is optional."
                )
        except KeyboardInterrupt:
            print(
                "Calibration interrupted. Completed candidate runs remain immutable; "
                "run this command again to continue with a new attempt.",
                file=sys.stderr,
            )
            return 130
        except (ConfigurationError, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-study-review":
        try:
            approved = set(args.approve)
            rejected = set(args.reject)
            overlap = approved & rejected
            if overlap:
                raise ValueError(
                    "The same candidate cannot pass and fail optional visual QC: "
                    + ", ".join(sorted(overlap))
                )
            approvals = {candidate_id: True for candidate_id in approved} | {
                candidate_id: False for candidate_id in rejected
            }
            result, assessment = record_reference_calibration_stage_review(
                args.study_directory,
                visual_approvals=approvals,
                selected_candidate_id=args.select,
            )
            print(f"Recorded assessment: {assessment.fingerprint}")
            print(f"Researcher selected: {args.select}")
            if result.current_stage is None:
                print(f"Calibration complete: {result.final_config_path}")
                print("The selected configuration still requires a full-cohort confirmation run.")
            else:
                print(
                    f"Prepared stage {result.current_stage.order}/"
                    f"{len(result.plan.stages)}: {result.current_stage.title}"
                )
                print(f"Pending candidate runs: {len(result.candidates)}")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-calibration-plan":
        try:
            mesh_directory = args.mesh_directory.expanduser().resolve()
            if not mesh_directory.is_dir():
                raise ConfigurationError(f"Mesh directory does not exist: {mesh_directory}")
            if args.template is None:
                template = detect_template(mesh_directory)
                if template is None:
                    raise ConfigurationError(
                        "No unambiguous supported file named template was found; "
                        "pass --template explicitly"
                    )
            else:
                template = args.template.expanduser()
                if not template.is_absolute():
                    template = mesh_directory / template
                template = template.resolve()
                if not template.is_file() or not is_supported_surface_path(template):
                    raise ConfigurationError(
                        f"Template is not a supported surface mesh: {template}"
                    )
            subjects = tuple(
                path.resolve()
                for path in sorted(
                    mesh_directory.glob(args.subject_pattern),
                    key=lambda candidate: candidate.name.casefold(),
                )
                if (
                    path.is_file()
                    and is_supported_surface_path(path)
                    and path.resolve() != template
                )
            )
            recommendation = recommend_reference_parameters(
                (template, *subjects),
                alignment_basis="declared_gpa",
                surface_detail_intent=args.surface_detail,
                deformation_scale_intent=args.deformation_scale,
                expected_shape_disparity=args.expected_shape_disparity,
            )
            plan = build_reference_calibration_plan(
                recommendation,
                coordinate_unit=args.units,
                requested_pilot_subject_count=args.pilot_subjects,
                smallest_relevant_feature=args.smallest_relevant_feature,
                pilot_subject_declarations=(
                    ()
                    if args.pilot_declarations is None
                    else read_pilot_subject_declarations(args.pilot_declarations)
                ),
            )
            exported = export_reference_calibration_plan(
                plan,
                args.output,
                recommendation=recommendation,
                overwrite=args.force,
            )
            print(plan.summary_text())
            print(f"Plan JSON: {exported.json_path}")
            print(f"Methods report: {exported.html_path}")
            print(f"Geometry evidence: {exported.recommendation_path}")
            print(f"JSON SHA-256: {exported.json_sha256}")
        except (
            ConfigurationError,
            FileExistsError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "validate":
        try:
            load_config(args.config)
            print(f"Configuration schema valid: {args.config.resolve()}")
            if args.schema_only and args.report is not None:
                raise ConfigurationError("--report cannot be combined with --schema-only.")
            if not args.schema_only:
                preflight = collect_preflight(args.config)
                print(f"Input directory: {preflight.inputs.input_directory}")
                print(f"Template: {preflight.inputs.template}")
                print(f"Subject meshes: {preflight.inputs.subject_count}")
                print(
                    "Template geometry: "
                    f"{preflight.template.points} points, {preflight.template.cells} triangles"
                )
                point_counts = [subject.points for subject in preflight.subjects]
                print(
                    "Subject geometry: "
                    f"{min(point_counts)}-{max(point_counts)} points; all triangular VTK PolyData"
                )
                if args.report is not None:
                    destination = None if args.report == _AUTO_REPORT else args.report
                    report_path = write_preflight_report(
                        preflight,
                        destination,
                        overwrite=args.force_report,
                    )
                    print(f"Preflight report: {report_path}")
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "prepare":
        try:
            run_directory = prepare_run(
                args.config,
                run_id=args.run_id,
                output_directory=args.output_directory,
            )
            print(f"Prepared run: {run_directory}")
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-plan":
        try:
            plan = plan_reference_preparation(args.config, run_id=args.run_id)
            report_path = None
            if args.report is not None:
                report_path = write_reference_preparation_plan_report(plan, args.report)
            json.dump(plan, sys.stdout, indent=2, ensure_ascii=True, sort_keys=True)
            sys.stdout.write("\n")
            if report_path is not None:
                encoded_path = json.dumps(str(report_path), ensure_ascii=True)
                print(f"Reference preparation report: {encoded_path}", file=sys.stderr)
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-plan-verify":
        try:
            evidence = verify_saved_reference_preparation_plan(
                args.plan,
                report_path=args.report,
                expected_fingerprint=args.expect_fingerprint,
            )
            payload = serialize_reference_preparation_plan_verification(evidence)
            if args.output is None:
                _write_stdout_bytes(payload)
            else:
                written = write_reference_preparation_plan_verification(
                    evidence,
                    args.output,
                )
                if written.read_bytes() != payload:
                    raise ConfigurationError(
                        f"Saved plan verification evidence changed after writing: {written}"
                    )
                encoded_path = json.dumps(str(written), ensure_ascii=True)
                print(f"Saved plan verification evidence: {encoded_path}")
                print(f"Evidence SHA-256: {hashlib.sha256(payload).hexdigest()}")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-plan-approve":
        try:
            request = create_reference_preparation_approval(
                args.config,
                run_id=args.run_id,
                approved_fingerprint=args.approve_fingerprint,
            )
            written = write_reference_preparation_approval(request, args.output)
            json.dump(request, sys.stdout, indent=2, ensure_ascii=True, sort_keys=True)
            sys.stdout.write("\n")
            encoded_path = json.dumps(str(written), ensure_ascii=True)
            print(f"Reference preparation approval: {encoded_path}", file=sys.stderr)
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-plan-approval-verify":
        try:
            evidence = verify_saved_reference_preparation_approval(
                args.request,
                current_config_path=args.current_config,
            )
            payload = serialize_reference_preparation_approval_verification(evidence)
            if args.output is None:
                _write_stdout_bytes(payload)
            else:
                written = write_reference_preparation_approval_verification(
                    evidence,
                    args.output,
                )
                if written.read_bytes() != payload:
                    raise ConfigurationError(
                        f"Saved approval verification evidence changed after writing: {written}"
                    )
                encoded_path = json.dumps(str(written), ensure_ascii=True)
                print(f"Saved approval verification evidence: {encoded_path}")
                print(f"Evidence SHA-256: {hashlib.sha256(payload).hexdigest()}")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-preparation-status":
        try:
            report = reconcile_reference_preparation(
                args.request,
                current_config_path=args.current_config,
                expected_request_sha256=args.expect_request_sha256,
            )
            if args.json:
                _write_stdout_bytes(serialize_reference_preparation_reconciliation(report))
            elif args.output is not None:
                payload = serialize_reference_preparation_reconciliation(report)
                written = write_reference_preparation_reconciliation(
                    report,
                    args.output,
                )
                if written.read_bytes() != payload:
                    raise ConfigurationError(
                        f"Saved reconciliation report changed after writing: {written}"
                    )
                print(f"Saved reconciliation report: {written}")
                print(f"Report SHA-256: {hashlib.sha256(payload).hexdigest()}")
            else:
                print(f"Status: {report['status']}")
                print(f"Approved run: {report['approved_plan']['run_id']}")
                destination = report["destination"]
                print(f"Destination [{destination['status']}]: {destination['path']}")
                stages = report["private_stages"]
                print(f"Exact private stages: {len(stages)}")
                for stage in stages:
                    print(f"- [{stage['status']}] {stage['path']}: {stage['reason']}")
                print(
                    "No files were deleted, renamed, published, resumed, prepared, "
                    "executed, repaired, or rewritten."
                )
            return 1 if report["action_required"] else 0
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2

    if args.command == "reference-preparation-status-verify":
        try:
            evidence = verify_saved_reference_preparation_reconciliation(
                args.report,
                expected_report_sha256=args.expect_report_sha256,
            )
            payload = serialize_reference_preparation_reconciliation_verification(evidence)
            if args.output is None:
                _write_stdout_bytes(payload)
            else:
                written = write_reference_preparation_reconciliation_verification(
                    evidence,
                    args.output,
                )
                if written.read_bytes() != payload:
                    raise ConfigurationError(
                        f"Saved reconciliation verification evidence changed: {written}"
                    )
                print(f"Saved reconciliation verification evidence: {written}")
                print(f"Evidence SHA-256: {hashlib.sha256(payload).hexdigest()}")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "reference-prepare-approved":
        try:
            evidence = prepare_approved_reference_run(
                args.request,
                current_config_path=args.current_config,
                expected_request_sha256=args.expect_request_sha256,
            )
            json.dump(evidence, sys.stdout, indent=2, ensure_ascii=True, sort_keys=True)
            sys.stdout.write("\n")
        except (ConfigurationError, OSError, TypeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "execute":
        try:
            return_code = execute_run(args.run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return _execution_outcome(args.run_directory.resolve(), return_code)

    if args.command == "run":
        try:
            run_directory = prepare_run(
                args.config,
                run_id=args.run_id,
                output_directory=args.output_directory,
            )
            print(f"Prepared run: {run_directory}")
            return_code = execute_run(run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return _execution_outcome(run_directory, return_code)

    if args.command == "resume":
        try:
            run_directory = prepare_resume_run(args.source_run, run_id=args.run_id)
            print(f"Prepared resume run: {run_directory}")
            print(
                "WARNING: Deformetrica 4.3 restores parameters and iteration but "
                "reinitializes gradients and line-search step sizes; exact trajectory "
                "continuity is not guaranteed."
            )
            print(
                "SECURITY: Continue only with a trusted source run; Deformetrica loads "
                "the checkpoint as a Python Pickle."
            )
            if args.prepare_only:
                return 0
            return_code = execute_run(run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return _execution_outcome(run_directory, return_code)

    if args.command == "recover":
        try:
            result = recover_run(
                args.run_directory,
                reason=args.reason,
                confirm_process_stopped=args.confirm_process_stopped,
            )
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        status = str(result["status"])
        checkpoint = result["checkpoint"]
        if status == "completed":
            print(f"Reconciled completed terminal run: {args.run_directory.resolve()}")
        else:
            print(f"Recovered run as {status}: {args.run_directory.resolve()}")
        if status in {"failed", "interrupted"} and checkpoint["available"]:
            print(
                "Checkpoint integrity matches the output inventory. Resume with: "
                f'diffeoforge resume "{args.run_directory.resolve()}"'
            )
        elif status in {"failed", "interrupted"}:
            print("No checkpoint is available; this run cannot be resumed.")
        return 0

    if args.command == "status":
        try:
            status = run_status(args.run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    if args.command == "report":
        try:
            report = collect_run_report(args.run_directory)
            report_path = write_result_report(
                report,
                args.output,
                overwrite=args.force,
            )
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(f"Run status: {report.result['status']}")
        print(f"Convergence observations: {len(report.convergence)}")
        print(f"Result report: {report_path}")
        return 0

    if args.command == "scientific-report":
        try:
            report = collect_scientific_atlas_report(
                args.run_directory,
                validation_study=args.validation_study,
                holdout_study=args.holdout_study,
                pca_stability=args.pca_stability,
                decision_review=args.decision_review,
            )
            artifact = write_scientific_atlas_report(report, args.output)
        except (OSError, RuntimeError, TypeError, ValueError, ScientificReportError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        supported = sum(claim.status == "supported" for claim in report.claims)
        print(f"Scientific claims supported: {supported} of {len(report.claims)}")
        print(
            f"Subjects prioritized for inspection: "
            f"{sum(item.inspection_priority for item in report.subjects)}"
        )
        print(f"Scientific report: {artifact.directory}")
        return 0

    if args.command == "scientific-report-verify":
        try:
            artifact = verify_scientific_atlas_report(args.report_directory)
        except (OSError, RuntimeError, TypeError, ValueError, ScientificReportError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(f"Scientific report verified: {artifact.directory}")
        return 0

    if args.command == "compare-reference":
        try:
            report = compare_reference_run(args.run_directory, args.reference_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 4

    raise AssertionError(f"Unhandled command: {args.command}")
