"""Qt-independent, fail-closed summaries of verified Modern result bundles."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from diffeoforge.desktop.worker_protocol import sha256_file

ResultArtifactKind = Literal["csv", "json", "svg", "vtk"]
_PCA_DISPLAY_LIMIT = 10
_HISTORY_COLUMNS = (
    "cycle",
    "block",
    "status",
    "objective",
    "attachment",
    "regularity",
    "gradient_norm",
    "accepted_step_size",
    "line_search_evaluations",
)


class ModernResultReviewError(RuntimeError):
    """Raised when result evidence is unsafe, inconsistent, or no longer verified."""


@dataclass(frozen=True)
class ResultReviewItem:
    """One display-ready result value with a bounded interpretation."""

    label: str
    value: str
    explanation: str


@dataclass(frozen=True)
class ModernResultArtifact:
    """One inventory-bound result artifact that may be handed to a local viewer."""

    key: str
    label: str
    path: Path
    kind: ResultArtifactKind
    bytes: int
    sha256: str
    description: str


@dataclass(frozen=True)
class ModernResultReview:
    """Read-only summary created only from a fully verified Modern workflow."""

    run_directory: Path
    bundle_directory: Path
    project_name: str
    created_at: str
    workflow_manifest_path: Path
    workflow_manifest_sha256: str
    bundle_manifest_path: Path
    bundle_manifest_sha256: str
    optimizer_converged: bool
    optimizer_termination_reason: str
    optimizer_cycles_completed: int
    optimizer_max_cycles: int
    overview: tuple[ResultReviewItem, ...]
    optimization: tuple[ResultReviewItem, ...]
    pca: tuple[ResultReviewItem, ...]
    quality: tuple[ResultReviewItem, ...]
    artifacts: tuple[ModernResultArtifact, ...]
    scientific_boundaries: tuple[str, ...]
    pca_pc2_pc3_unavailable_reason: str | None = None
    optimizer_convergence_plot_unavailable_reason: str | None = None

    def artifact(self, key: str) -> ModernResultArtifact:
        for artifact in self.artifacts:
            if artifact.key == key:
                return artifact
        raise KeyError(key)


def _safe_bundle_path(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernResultReviewError(f"{label} must be a nonempty POSIX-style path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise ModernResultReviewError(f"{label} is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ModernResultReviewError(f"{label} escapes the result bundle") from error
    if path.is_symlink() or not path.is_file():
        raise ModernResultReviewError(f"{label} is missing or symbolic: {value}")
    return path.resolve()


def _safe_bundle_directory(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModernResultReviewError("Nested result bundle must be a nonempty POSIX-style path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise ModernResultReviewError(f"Nested result bundle path is unsafe: {value!r}")
    directory = root.joinpath(*relative.parts)
    try:
        resolved = directory.resolve()
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ModernResultReviewError("Nested result bundle escapes the workflow") from error
    if directory.is_symlink() or not directory.is_dir():
        raise ModernResultReviewError("Nested result bundle is missing or symbolic")
    return resolved


def _json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernResultReviewError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ModernResultReviewError(f"{label} must contain one JSON object: {path}")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModernResultReviewError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ModernResultReviewError(f"{label} must be finite")
    return number


def _format_number(value: object) -> str:
    return f"{_finite_number(value, 'Result value'):.6g}"


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.3g} {unit}"


def _read_history(path: Path, optimizer: dict) -> tuple[int, float, float]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ModernResultReviewError(f"Optimizer history is not readable: {path}") from error
    if not rows:
        raise ModernResultReviewError("Optimizer history contains no observations")
    if fieldnames[: len(_HISTORY_COLUMNS)] != _HISTORY_COLUMNS:
        raise ModernResultReviewError("Optimizer history columns differ from the bundle contract")
    try:
        initial = float(rows[0]["objective"])
        final = float(rows[-1]["objective"])
    except (TypeError, ValueError) as error:
        raise ModernResultReviewError("Optimizer history contains an invalid objective") from error
    if not math.isfinite(initial) or not math.isfinite(final):
        raise ModernResultReviewError("Optimizer history objective must be finite")
    manifest_final = _finite_number(optimizer["final_objective"], "Final objective")
    if final != manifest_final:
        raise ModernResultReviewError(
            "Final optimizer history objective differs from the bundle manifest"
        )
    return len(rows), initial, final


def _read_pca_summary(path: Path, pca: dict) -> tuple[float, ...]:
    summary = _json_object(path, "PCA summary")
    expected = {
        "number_of_components": pca["components"],
        "numerical_rank": pca["numerical_rank"],
        "total_variance": pca["total_variance"],
        "feature_space": pca["feature_space"],
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ModernResultReviewError(f"PCA summary {key} differs from the bundle manifest")
    ratios_value = summary.get("explained_variance_ratio")
    if not isinstance(ratios_value, list) or len(ratios_value) != pca["components"]:
        raise ModernResultReviewError("PCA explained-variance ratio count differs")
    ratios = tuple(_finite_number(value, "PCA explained-variance ratio") for value in ratios_value)
    if any(value < 0 or value > 1 for value in ratios) or sum(ratios) > 1 + 1e-12:
        raise ModernResultReviewError("PCA explained-variance ratios are outside [0, 1]")
    for component in pca["deformations"]["components"]:
        index = component["component"] - 1
        if not math.isclose(
            ratios[index],
            float(component["explained_variance_ratio"]),
            rel_tol=0,
            abs_tol=1e-15,
        ):
            raise ModernResultReviewError(f"PCA deformation ratio differs for {component['label']}")
    return ratios


def review_modern_result(directory: Path | str) -> ModernResultReview:
    """Fully verify one Modern workflow, then collect a bounded read-only summary."""

    run_directory = Path(directory).expanduser().resolve()
    try:
        from diffeoforge.modern_bundle import MANIFEST_NAME as BUNDLE_MANIFEST_NAME
        from diffeoforge.modern_workflow import MANIFEST_NAME as WORKFLOW_MANIFEST_NAME
        from diffeoforge.modern_workflow import verify_modern_workflow

        workflow = verify_modern_workflow(run_directory)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        raise ModernResultReviewError(f"Modern result did not verify: {error}") from error

    workflow_manifest_path = run_directory / WORKFLOW_MANIFEST_NAME
    workflow_manifest_sha256 = sha256_file(workflow_manifest_path)
    if _json_object(workflow_manifest_path, "Modern workflow manifest") != workflow:
        raise ModernResultReviewError("Workflow manifest changed after verification")
    if sha256_file(workflow_manifest_path) != workflow_manifest_sha256:
        raise ModernResultReviewError("Workflow manifest changed while results were read")
    bundle_value = workflow["result_bundle"]["path"]
    bundle_directory = _safe_bundle_directory(run_directory, bundle_value)
    bundle_manifest_path = bundle_directory / BUNDLE_MANIFEST_NAME
    bundle_manifest_sha256 = sha256_file(bundle_manifest_path)
    if bundle_manifest_sha256 != workflow["result_bundle"]["manifest_sha256"]:
        raise ModernResultReviewError("Nested bundle manifest hash changed after verification")
    bundle = _json_object(bundle_manifest_path, "Modern result bundle manifest")
    if sha256_file(bundle_manifest_path) != bundle_manifest_sha256:
        raise ModernResultReviewError("Bundle manifest changed while results were read")

    artifact_records = {record["path"]: record for record in bundle["artifacts"]}
    if len(artifact_records) != len(bundle["artifacts"]):
        raise ModernResultReviewError("Result bundle contains duplicate artifact records")

    artifacts: list[ModernResultArtifact] = []

    def add_artifact(
        key: str,
        label: str,
        value: object,
        kind: ResultArtifactKind,
        description: str,
    ) -> None:
        if not isinstance(value, str) or value not in artifact_records:
            raise ModernResultReviewError(f"Displayed artifact is not inventoried: {value!r}")
        record = artifact_records[value]
        path = _safe_bundle_path(bundle_directory, value, label=label)
        try:
            expected_bytes = int(record["bytes"])
            expected_sha256 = str(record["sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise ModernResultReviewError(
                f"Displayed artifact has an invalid inventory record: {value!r}"
            ) from error
        if path.stat().st_size != expected_bytes or sha256_file(path) != expected_sha256:
            raise ModernResultReviewError(
                f"Displayed artifact changed after workflow verification: {value}"
            )
        artifacts.append(
            ModernResultArtifact(
                key=key,
                label=label,
                path=path,
                kind=kind,
                bytes=expected_bytes,
                sha256=expected_sha256,
                description=description,
            )
        )

    optimizer = bundle["optimizer"]
    convergence_plot_path = optimizer.get("convergence_plot_path")
    convergence_plot_unavailable_reason = None
    if convergence_plot_path is None:
        convergence_plot_unavailable_reason = (
            "This result predates the verified optimizer-convergence plot artifact."
        )
    history_path = _safe_bundle_path(
        bundle_directory,
        optimizer["history_path"],
        label="Optimizer history",
    )
    history_rows, initial_objective, final_objective = _read_history(history_path, optimizer)
    pca = bundle["pca"]
    pca_summary_path = _safe_bundle_path(
        bundle_directory,
        pca["summary_path"],
        label="PCA summary",
    )
    ratios = _read_pca_summary(pca_summary_path, pca)
    cumulative = 0.0
    pca_items: list[ResultReviewItem] = [
        ResultReviewItem(
            "PCA space",
            f"{pca['components']} components · rank {pca['numerical_rank']}",
            "PCA of subject-specific initial momenta; not a taxonomic axis.",
        ),
        ResultReviewItem(
            "Total variance",
            _format_number(pca["total_variance"]),
            "Variance in the documented momenta feature space.",
        ),
    ]
    for index, ratio in enumerate(ratios[:_PCA_DISPLAY_LIMIT], start=1):
        cumulative += ratio
        pca_items.append(
            ResultReviewItem(
                f"PC{index}",
                f"{ratio * 100:.3f}% · cumulative {cumulative * 100:.3f}%",
                "Explained-variance ratio; the axis sign is conventional.",
            )
        )
    if len(ratios) > _PCA_DISPLAY_LIMIT:
        pca_items.append(
            ResultReviewItem(
                "Additional components",
                str(len(ratios) - _PCA_DISPLAY_LIMIT),
                "Complete values remain available in pca-summary.json and pca-scores.csv.",
            )
        )

    plots = pca["plots"]
    secondary_plot_path = plots.get("scores_pc2_pc3_path")
    secondary_unavailable_reason = plots.get("scores_pc2_pc3_unavailable_reason")
    if secondary_plot_path is None:
        if secondary_unavailable_reason is None:
            secondary_unavailable_reason = (
                "This result predates the mandatory PC2-versus-PC3 plot artifact."
            )
        pca_items.append(
            ResultReviewItem(
                "PC2 vs PC3 plot",
                "unavailable",
                str(secondary_unavailable_reason),
            )
        )
    else:
        pca_items.append(
            ResultReviewItem(
                "Standard score plots",
                "PC1 vs PC2 and PC2 vs PC3",
                "Both plots use the same verified score matrix and subject ordering.",
            )
        )

    add_artifact(
        "estimated-template",
        "Estimated template (VTK)",
        bundle["template"]["path"],
        "vtk",
        "Template surface estimated by the Modern atlas.",
    )
    add_artifact(
        "optimizer-history",
        "Optimization history (CSV)",
        optimizer["history_path"],
        "csv",
        "Committed block decisions and objective components.",
    )
    if convergence_plot_path is not None:
        add_artifact(
            "optimizer-convergence-plot",
            "Optimizer convergence (SVG)",
            convergence_plot_path,
            "svg",
            "Static, script-free objective and block-gradient trajectories.",
        )
    add_artifact(
        "pca-summary",
        "PCA summary (JSON)",
        pca["summary_path"],
        "json",
        "Complete variance, rank, and sign convention.",
    )
    add_artifact(
        "pca-scores",
        "PCA-Scores (CSV)",
        pca["scores_path"],
        "csv",
        "Open table of all subject scores.",
    )
    add_artifact(
        "pca-scree",
        "PCA scree plot (SVG)",
        pca["plots"]["scree_path"],
        "svg",
        "Static, script-free SVG of explained variance.",
    )
    add_artifact(
        "pca-score-plot",
        "PCA scores: PC1 vs PC2 (SVG)",
        pca["plots"]["scores_path"],
        "svg",
        "Static, script-free SVG with explained variance on both axes.",
    )
    if secondary_plot_path is not None:
        add_artifact(
            "pca-score-plot-pc2-pc3",
            "PCA scores: PC2 vs PC3 (SVG)",
            secondary_plot_path,
            "svg",
            "Static, script-free SVG using the same score matrix and subject ordering.",
        )
    deformations = pca["deformations"]
    add_artifact(
        "pca-deformation-definition",
        "PCA deformation contract (JSON)",
        deformations["definition_path"],
        "json",
        "Equation, standard deviations, sign convention, and interpretation boundary.",
    )
    add_artifact(
        "pca-mean-shape",
        "PCA mean-momenta shape (VTK)",
        deformations["mean_path"],
        "vtk",
        "Template endpoint for the mean subject momenta.",
    )
    for component in deformations["components"]:
        key = component["label"].lower()
        add_artifact(
            f"{key}-minus",
            f"{component['label']} −{deformations['standard_deviations']:g} SD (VTK)",
            component["minus_path"],
            "vtk",
            "Endpoint along the negative, sign-conventional PCA direction.",
        )
        add_artifact(
            f"{key}-plus",
            f"{component['label']} +{deformations['standard_deviations']:g} SD (VTK)",
            component["plus_path"],
            "vtk",
            "Endpoint along the positive, sign-conventional PCA direction.",
        )
    quality = bundle["quality"]
    add_artifact(
        "mesh-quality-json",
        "Output-Mesh-QC (JSON)",
        quality["report_path"],
        "json",
        "Recomputed geometry and topology evidence for all output meshes.",
    )
    add_artifact(
        "mesh-quality-csv",
        "Output-Mesh-QC (CSV)",
        quality["csv_path"],
        "csv",
        "Tabular output-mesh QC for further analysis.",
    )

    residuals = tuple(
        _finite_number(subject["residual"], "Subject residual") for subject in bundle["subjects"]
    )
    preprocessing = workflow["preprocessing"]
    pairwise = workflow["engine"].get("pairwise_evaluation", {"mode": "dense"})
    history_value = (
        f"{history_rows} rows · "
        f"{optimizer['total_line_search_evaluations']} line-search evaluations"
    )
    objective_value = (
        f"initial {_format_number(initial_objective)} · final {_format_number(final_objective)}"
    )
    component_value = (
        f"Attachment {_format_number(optimizer['final_attachment'])} · "
        f"Regularity {_format_number(optimizer['final_regularity'])}"
    )
    artifact_bytes = sum(int(record["bytes"]) for record in bundle["artifacts"])
    overview = (
        ResultReviewItem("Project", str(workflow["project"]["name"]), "Manifested name."),
        ResultReviewItem(
            "Engine",
            f"{workflow['engine']['id']} · {pairwise['mode']} · CPU/float64",
            "Numerical route actually manifested by the workflow.",
        ),
        ResultReviewItem(
            "Dataset",
            f"{len(bundle['subjects'])} subjects · {workflow['input']['units']}",
            "Subject count and declared coordinate unit of the verified run.",
        ),
        ResultReviewItem(
            "Template",
            f"{bundle['template']['points']} points · {bundle['template']['triangles']} triangles",
            "Geometry of the estimated output template.",
        ),
        ResultReviewItem(
            "Control points",
            str(bundle["parameters"]["control_points"]),
            "Manifested dimension of the momenta parameter space.",
        ),
        ResultReviewItem(
            "Procrustes",
            "yes" if preprocessing["id"] == "generalized_procrustes" else "no",
            "Generalized Procrustes preprocessing of the published workflow.",
        ),
    )
    optimization = (
        ResultReviewItem(
            "Termination",
            f"{optimizer['termination_reason']} · converged={str(optimizer['converged']).lower()}",
            "Technical optimizer state; not a statement of biological validity.",
        ),
        ResultReviewItem(
            "Cycles",
            f"{optimizer['cycles_completed']} of {optimizer['settings']['max_cycles']}",
            "Fully completed block cycles.",
        ),
        ResultReviewItem(
            "Committed history",
            history_value,
            "Rejected candidates are not reported as accepted progress.",
        ),
        ResultReviewItem(
            "Convergence plot",
            "verified" if convergence_plot_path is not None else "unavailable",
            (
                "Objective components and block-gradient norms are bound to the same history."
                if convergence_plot_path is not None
                else str(convergence_plot_unavailable_reason)
            ),
        ),
        ResultReviewItem(
            "Objective",
            objective_value,
            "Numerical optimization objective; smaller or stable values are not "
            "biological evidence.",
        ),
        ResultReviewItem(
            "Final components",
            component_value,
            "Manifested decomposition of the final objective.",
        ),
        ResultReviewItem(
            "Subject residuals",
            f"min {_format_number(min(residuals))} · max {_format_number(max(residuals))}",
            "Descriptive final residuals; no automatic outlier classification.",
        ),
    )
    quality_items = (
        ResultReviewItem(
            "Input-QC",
            f"{workflow['quality']['assessed_meshes']} mesh stages",
            "Raw and effective inputs were recomputed by the workflow verifier.",
        ),
        ResultReviewItem(
            "Output-QC",
            f"{quality['assessed_meshes']} Meshes",
            "Template, reconstructions, and PCA endpoints were recomputed and checked.",
        ),
        ResultReviewItem(
            "Bundle inventory",
            f"{len(bundle['artifacts'])} files · {_format_bytes(artifact_bytes)}",
            "Exact file list with size and SHA-256; additional files are not allowed.",
        ),
    )
    boundaries = tuple(
        dict.fromkeys(
            (
                str(workflow["scientific_boundary"]),
                str(bundle["scientific_boundary"]),
                str(workflow["quality"]["scientific_boundary"]),
                str(quality["scientific_boundary"]),
                str(deformations["interpretation_boundary"]),
            )
        )
    )
    artifact_keys = [artifact.key for artifact in artifacts]
    if len(artifact_keys) != len(set(artifact_keys)):
        raise ModernResultReviewError("Displayed result artifact keys are not unique")
    return ModernResultReview(
        run_directory=run_directory,
        bundle_directory=bundle_directory,
        project_name=str(workflow["project"]["name"]),
        created_at=str(workflow["created_at"]),
        workflow_manifest_path=workflow_manifest_path,
        workflow_manifest_sha256=workflow_manifest_sha256,
        bundle_manifest_path=bundle_manifest_path,
        bundle_manifest_sha256=bundle_manifest_sha256,
        optimizer_converged=bool(optimizer["converged"]),
        optimizer_termination_reason=str(optimizer["termination_reason"]),
        optimizer_cycles_completed=int(optimizer["cycles_completed"]),
        optimizer_max_cycles=int(optimizer["settings"]["max_cycles"]),
        overview=overview,
        optimization=optimization,
        pca=tuple(pca_items),
        quality=quality_items,
        artifacts=tuple(artifacts),
        scientific_boundaries=boundaries,
        pca_pc2_pc3_unavailable_reason=(
            None if secondary_plot_path is not None else str(secondary_unavailable_reason)
        ),
        optimizer_convergence_plot_unavailable_reason=convergence_plot_unavailable_reason,
    )


def verify_result_artifact(review: ModernResultReview, key: str) -> Path:
    """Recheck manifest binding and one selected artifact immediately before opening."""

    if not isinstance(review, ModernResultReview):
        raise TypeError("review must be a ModernResultReview")
    try:
        workflow_sha256 = sha256_file(review.workflow_manifest_path)
        bundle_sha256 = sha256_file(review.bundle_manifest_path)
    except OSError as error:
        raise ModernResultReviewError("A reviewed result manifest is no longer readable") from error
    if workflow_sha256 != review.workflow_manifest_sha256:
        raise ModernResultReviewError("Workflow manifest changed after result review")
    if bundle_sha256 != review.bundle_manifest_sha256:
        raise ModernResultReviewError("Bundle manifest changed after result review")
    try:
        artifact = review.artifact(key)
    except KeyError as error:
        raise ModernResultReviewError(f"Unknown result artifact key: {key!r}") from error
    path = artifact.path
    try:
        resolved = path.resolve()
        resolved.relative_to(review.bundle_directory.resolve())
    except ValueError as error:
        raise ModernResultReviewError("Selected artifact escapes the reviewed bundle") from error
    if path.is_symlink() or not path.is_file():
        raise ModernResultReviewError("Selected result artifact is missing or symbolic")
    try:
        matches = path.stat().st_size == artifact.bytes and sha256_file(path) == artifact.sha256
    except OSError as error:
        raise ModernResultReviewError("Selected result artifact is no longer readable") from error
    if not matches:
        raise ModernResultReviewError("Selected result artifact changed after result review")
    return resolved
