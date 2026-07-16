"""Command-line entry point for the pre-alpha workflow scaffold."""

from __future__ import annotations

import argparse
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

    modern_verify_parser = subparsers.add_parser(
        "modern-verify",
        help="Verify an immutable modern workflow run and its nested atlas/PCA bundle.",
    )
    modern_verify_parser.add_argument("run_directory", type=Path)

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
                overwrite=args.force,
            )
            print(f"Modern workflow configuration created: {config_path}")
            print("WARNING: Geometry-scaled starter values are exploratory.")
            print("Review every parameter before running the modern engine.")
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

    if args.command == "modern-run":
        try:
            from diffeoforge.modern_workflow import (
                run_modern_workflow,
                verify_modern_workflow,
            )

            run_directory = run_modern_workflow(
                args.config,
                destination=args.output,
            )
            manifest = verify_modern_workflow(run_directory)
            print(f"Modern workflow completed: {run_directory}")
            print(f"Subject meshes: {len(manifest['input']['subjects'])}")
            print(f"Preprocessing: {manifest['preprocessing']['id']}")
            print(f"Atlas/PCA bundle: {run_directory / manifest['result_bundle']['path']}")
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

    if args.command == "modern-verify":
        try:
            from diffeoforge.modern_workflow import verify_modern_workflow

            manifest = verify_modern_workflow(args.run_directory)
            print(f"Modern workflow verified: {args.run_directory.resolve()}")
            print(f"Subject meshes: {len(manifest['input']['subjects'])}")
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
