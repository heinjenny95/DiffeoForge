"""Command-line entry point for the pre-alpha workflow scaffold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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

_AUTO_REPORT = Path("__diffeoforge_auto_report__")


def _write_stdout_bytes(payload: bytes) -> None:
    """Write exact machine-readable bytes when stdout exposes a binary buffer."""

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload.decode("utf-8"))
        return
    buffer.write(payload)
    buffer.flush()


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
        help="Create an explicit starter configuration for the modern CPU/float64 path.",
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
    modern_init_parser.add_argument("--force", action="store_true")

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
        help="Measure declared multi-cycle optimizer runs in fresh CPU processes.",
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
                random_seed=args.random_seed,
                pairwise_mode=args.pairwise_mode,
                query_tile_size=args.query_tile_size,
                source_tile_size=args.source_tile_size,
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

    if args.command == "modern-run":
        try:
            from diffeoforge.modern_bundle import verify_modern_atlas_bundle
            from diffeoforge.modern_workflow import (
                run_modern_workflow,
                verify_modern_workflow,
            )

            def show_progress(event) -> None:
                stage = f"{event.completed_stages}/{event.total_stages} stages"
                if event.optimizer is None:
                    print(
                        f"Progress [{stage}] {event.phase} {event.status}: {event.message}",
                        flush=True,
                    )
                    return
                optimizer = event.optimizer
                decision = (
                    f"{optimizer.completed_decisions}/{optimizer.maximum_decisions} decisions"
                )
                block = "initial" if optimizer.block is None else optimizer.block
                print(
                    f"Progress [{stage}; optimizer {decision}] cycle "
                    f"{optimizer.cycle}/{optimizer.max_cycles} {block} {optimizer.status}; "
                    f"objective={optimizer.objective:.12g}; "
                    f"line-search={optimizer.line_search_evaluations}",
                    flush=True,
                )

            run_directory = run_modern_workflow(
                args.config,
                destination=args.output,
                progress_callback=show_progress,
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
                "Largest dense-equivalent execution XYZ payload: "
                f"{largest_execution_bytes} bytes"
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

            report_directory = benchmark_modern_optimizer(
                args.config,
                subject_count=args.subjects,
                max_cycles=args.cycles,
                repeats=args.repeats,
                warmup_runs=args.warmups,
                destination=args.output,
                overwrite=args.force,
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
        checkpoint = result["checkpoint"]
        print(f"Recovered run as interrupted: {args.run_directory.resolve()}")
        if checkpoint["available"]:
            print(
                "Checkpoint integrity matches the output inventory. Resume with: "
                f'diffeoforge resume "{args.run_directory.resolve()}"'
            )
        else:
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

    if args.command == "compare-reference":
        try:
            report = compare_reference_run(args.run_directory, args.reference_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 4

    raise AssertionError(f"Unhandled command: {args.command}")
