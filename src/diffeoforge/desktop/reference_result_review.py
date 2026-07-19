"""Qt-independent review of verified Deformetrica momenta PCA results."""

from __future__ import annotations

from pathlib import Path

from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    ModernResultReviewError,
    ResultArtifactKind,
    ResultReviewItem,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    REFERENCE_PCA_MANIFEST,
    ReferencePCAError,
    verify_reference_pca_bundle,
    write_reference_pca_bundle,
)
from diffeoforge.result_report import collect_run_report

_PCA_DISPLAY_LIMIT = 10


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.3g} {unit}"


def _pca_items(bundle_manifest: dict, ratios: tuple[float, ...]) -> tuple[ResultReviewItem, ...]:
    pca = bundle_manifest["pca"]
    items = [
        ResultReviewItem(
            "PCA space",
            f"{pca['components']} components · rank {pca['numerical_rank']}",
            "Centered linear PCA of Deformetrica subject initial momenta.",
        ),
        ResultReviewItem(
            "Total variance",
            f"{float(pca['total_variance']):.6g}",
            "Variance in the documented control-point/Cartesian momenta feature space.",
        ),
    ]
    cumulative = 0.0
    for index, ratio in enumerate(ratios[:_PCA_DISPLAY_LIMIT], start=1):
        cumulative += ratio
        items.append(
            ResultReviewItem(
                f"PC{index}",
                f"{ratio * 100:.3f}% · cumulative {cumulative * 100:.3f}%",
                "Explained-variance ratio; the component sign is conventional.",
            )
        )
    if len(ratios) > _PCA_DISPLAY_LIMIT:
        items.append(
            ResultReviewItem(
                "Additional components",
                str(len(ratios) - _PCA_DISPLAY_LIMIT),
                "Complete values remain available in the verified JSON and CSV files.",
            )
        )
    plots = pca["plots"]
    if plots["scores_pc2_pc3_path"] is None:
        items.append(
            ResultReviewItem(
                "PC2 vs PC3 plot",
                "unavailable",
                str(plots["scores_pc2_pc3_unavailable_reason"]),
            )
        )
    else:
        items.append(
            ResultReviewItem(
                "Standard score plots",
                "PC1 vs PC2 and PC2 vs PC3",
                "Both plots use the same verified score matrix and subject ordering.",
            )
        )
    return tuple(items)


def review_reference_result(
    run_directory: Path | str,
    *,
    create_pca_if_missing: bool = True,
) -> ModernResultReview:
    """Verify one Deformetrica run and its deterministic, source-bound PCA snapshot."""

    run = Path(run_directory).expanduser().resolve()
    bundle_directory = run / DEFAULT_REFERENCE_PCA_DIRECTORY
    try:
        if create_pca_if_missing and not bundle_directory.exists():
            write_reference_pca_bundle(run)
        verified = verify_reference_pca_bundle(bundle_directory, source_run=run)
        report = collect_run_report(run)
    except (OSError, RuntimeError, TypeError, ValueError, ReferencePCAError) as error:
        raise ModernResultReviewError(
            f"Deformetrica result and momenta PCA did not verify: {error}"
        ) from error

    manifest = dict(verified.manifest)
    records = {str(record["path"]): record for record in manifest["artifacts"]}
    if len(records) != len(manifest["artifacts"]):
        raise ModernResultReviewError("Reference PCA contains duplicate artifact records")
    artifacts: list[ModernResultArtifact] = []

    def add_artifact(
        key: str,
        label: str,
        relative: object,
        kind: ResultArtifactKind,
        description: str,
    ) -> None:
        value = str(relative)
        record = records.get(value)
        if record is None:
            raise ModernResultReviewError(f"Displayed artifact is not inventoried: {value}")
        path = bundle_directory.joinpath(*Path(value).parts).resolve()
        try:
            path.relative_to(bundle_directory.resolve())
        except ValueError as error:
            raise ModernResultReviewError(
                f"Displayed artifact escapes the bundle: {value}"
            ) from error
        if path.is_symlink() or not path.is_file():
            raise ModernResultReviewError(f"Displayed artifact is missing or symbolic: {value}")
        size = int(record["bytes"])
        digest = str(record["sha256"])
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ModernResultReviewError(f"Displayed artifact changed: {value}")
        artifacts.append(
            ModernResultArtifact(key, label, path, kind, size, digest, description)
        )

    inputs = manifest["inputs"]
    pca = manifest["pca"]
    add_artifact(
        "reference-momenta",
        "Deformetrica momenta (raw TXT)",
        inputs["momenta"]["copied_path"],
        "txt",
        "Exact source parameter file, preserved byte-for-byte.",
    )
    add_artifact(
        "reference-control-points",
        "Deformetrica control points (raw TXT)",
        inputs["control_points"]["copied_path"],
        "txt",
        "Exact source control-point file, preserved byte-for-byte.",
    )
    for key, label, path, kind, description in (
        (
            "reference-momenta-table",
            "Momenta with subject identity (CSV)",
            "parameters/momenta.csv",
            "csv",
            "Open table preserving subject, control-point, and XYZ order.",
        ),
        (
            "reference-control-points-table",
            "Control points (CSV)",
            "parameters/control-points.csv",
            "csv",
            "Open indexed Cartesian control-point table.",
        ),
        (
            "pca-summary",
            "PCA summary (JSON)",
            pca["summary_path"],
            "json",
            "Method, feature order, rank, variance, and sign convention.",
        ),
        (
            "pca-scores",
            "PCA scores (CSV)",
            pca["scores_path"],
            "csv",
            "All subject scores in immutable manifest order.",
        ),
        (
            "pca-loadings",
            "PCA loadings (CSV)",
            pca["loadings_path"],
            "csv",
            "Component loadings for every control-point/Cartesian feature.",
        ),
        (
            "pca-scree",
            "PCA scree plot (SVG)",
            pca["plots"]["scree_path"],
            "svg",
            "Static explained-variance plot from the recomputed PCA.",
        ),
        (
            "pca-score-plot",
            "PCA scores: PC1 vs PC2 (SVG)",
            pca["plots"]["scores_path"],
            "svg",
            "Static subject score plot with explained variance on both axes.",
        ),
    ):
        add_artifact(key, label, path, kind, description)
    secondary = pca["plots"]["scores_pc2_pc3_path"]
    if secondary is not None:
        add_artifact(
            "pca-score-plot-pc2-pc3",
            "PCA scores: PC2 vs PC3 (SVG)",
            secondary,
            "svg",
            "Static secondary score plot from the same verified PCA matrix.",
        )

    ratios = tuple(float(value) for value in verified.pca.explained_variance_ratio)
    backend = report.manifest["backend"]
    result = report.result
    configured_max = int(report.manifest["effective_config"]["optimization"]["max_iterations"])
    final_iteration = report.final_iteration or 0
    total_output_bytes = sum(int(record["bytes"]) for record in report.inventory)
    passed_checks = sum(check.status == "pass" for check in report.checks)
    project_name = str(report.manifest["project"]["name"])
    units = str(report.manifest["effective_config"]["input"]["units"])
    overview = (
        ResultReviewItem("Project", project_name, "Name stored in the immutable run manifest."),
        ResultReviewItem(
            "Engine",
            f"Deformetrica reference · contract {backend['contract_version']}",
            "External reference engine route that generated the atlas parameters.",
        ),
        ResultReviewItem(
            "Dataset",
            f"{inputs['subjects']} subjects · {units}",
            "Subject count and declared coordinate unit bound before execution.",
        ),
        ResultReviewItem(
            "Parameter space",
            f"{inputs['control_point_count']} control points · {inputs['dimension']}D",
            "Dimensions declared by the Deformetrica momenta header and cross-checked.",
        ),
        ResultReviewItem(
            "PCA method",
            "centered linear float64 SVD",
            "Transparent default; this is not the old notebook's RBF KernelPCA.",
        ),
    )
    optimization = (
        ResultReviewItem(
            "Execution",
            f"completed · return code {result['return_code']}",
            "Terminal engine execution state independently verified by the parent.",
        ),
        ResultReviewItem(
            "Observed iterations",
            f"final {final_iteration} · configured cap {configured_max}",
            "The cap is not a convergence target and completion does not prove convergence.",
        ),
        ResultReviewItem(
            "Duration",
            f"{float(result['duration_seconds']):.1f} seconds",
            "Measured wall-clock duration stored in terminal run evidence.",
        ),
        ResultReviewItem(
            "Stop interpretation",
            report.stop_interpretation,
            "Bounded interpretation derived from observed history and configured cap.",
        ),
    )
    quality = (
        ResultReviewItem(
            "Run evidence",
            f"{passed_checks} of {len(report.checks)} checks passed",
            "Manifest, event, inventory, result, and actual output-file integrity checks.",
        ),
        ResultReviewItem(
            "Deformetrica outputs",
            f"{len(report.inventory)} files · {_format_bytes(total_output_bytes)}",
            "Exact terminal output inventory; unlisted files cause verification failure.",
        ),
        ResultReviewItem(
            "PCA snapshot",
            f"{len(manifest['artifacts'])} files",
            "Copied raw parameters, open tables, static plots, hashes, and recomputation contract.",
        ),
    )
    workflow_manifest = run / "manifest.json"
    bundle_manifest = bundle_directory / REFERENCE_PCA_MANIFEST
    return ModernResultReview(
        run_directory=run,
        bundle_directory=bundle_directory,
        project_name=project_name,
        created_at=str(manifest["created_at"]),
        workflow_manifest_path=workflow_manifest,
        workflow_manifest_sha256=sha256_file(workflow_manifest),
        bundle_manifest_path=bundle_manifest,
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        optimizer_converged=None,
        optimizer_termination_reason="completion_observed_convergence_not_established",
        optimizer_cycles_completed=final_iteration,
        optimizer_max_cycles=configured_max,
        overview=overview,
        optimization=optimization,
        pca=_pca_items(manifest, ratios),
        quality=quality,
        artifacts=tuple(artifacts),
        scientific_boundaries=(
            str(manifest["scientific_boundary"]),
            "A completed Deformetrica process and improving objective do not by themselves "
            "establish adequate registration or optimizer convergence.",
            "The linear momenta PCA is descriptive and does not establish taxonomic, "
            "biological, group-separation, or causal claims.",
        ),
        pca_pc2_pc3_unavailable_reason=(
            None
            if secondary is not None
            else str(pca["plots"]["scores_pc2_pc3_unavailable_reason"])
        ),
        optimizer_convergence_plot_unavailable_reason=(
            "A verified Deformetrica convergence SVG has not yet been derived from the "
            "terminal convergence table. The table remains in the source run."
        ),
        engine_route="deformetrica_reference",
    )
