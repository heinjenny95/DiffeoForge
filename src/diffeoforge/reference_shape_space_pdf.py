# ruff: noqa: E501
"""Project-level PDF export for a verified shape-space comparison."""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_shape_space_comparison import (
    AGREEMENT_HEATMAP_2D_SVG,
    AGREEMENT_HEATMAP_HIGH_DIM_SVG,
    COMPARISON_MANIFEST,
    COMPARISON_VERSION,
    DEFAULT_PROFILE_SVG,
    PAIRWISE_METRICS_CSV,
    REPORT_HTML,
    SCORE_OVERVIEW_SVG,
    ReferenceShapeSpaceComparison,
    verify_reference_shape_space_comparison,
)
from diffeoforge.strict_json import load_strict_json_object

PDF_EXPORT_VERSION = "0.1"
PDF_PROVENANCE_SUFFIX = ".provenance.json"
PDF_SIDECAR_SUFFIX = ".provenance.sha256"
PDF_GENERATOR = "diffeoforge_reference_shape_space_pdf"


class ReferenceShapeSpacePdfError(RuntimeError):
    """Raised when a comparison PDF cannot be created or verified."""


@dataclass(frozen=True)
class ReferenceShapeSpacePdfExport:
    pdf_path: Path
    provenance_path: Path
    sidecar_path: Path
    provenance: dict[str, Any]


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _ascii(value: object) -> str:
    text = str(value)
    replacements = {
        "\u00a0": " ",
        "\u00d7": "x",
        "\u03b3": "gamma",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return text.encode("ascii", "replace").decode("ascii")


def _slug(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", _ascii(value)).strip("-.")
    return normalized or "comparison"


def default_reference_shape_space_pdf_path(
    project_directory: Path | str,
    comparison: ReferenceShapeSpaceComparison,
) -> Path:
    """Return the stable project-root destination for one verified comparison."""

    project = Path(project_directory).expanduser()
    if not project.is_dir() or project.is_symlink():
        raise ReferenceShapeSpacePdfError(
            f"DiffeoForge project directory is missing or symbolic: {project}"
        )
    project = project.resolve()
    manifest = comparison.manifest
    source = manifest.get("source")
    selection = manifest.get("selection")
    if not isinstance(source, dict) or not isinstance(selection, dict):
        raise ReferenceShapeSpacePdfError(
            "PDF export requires a version 0.4 selection-bound comparison"
        )
    run_id = _slug(source.get("run_id", "run"))
    fingerprint = _slug(selection.get("selection_fingerprint", "selection"))[:12]
    return project / f"shape-space-comparison-{run_id}-{fingerprint}.pdf"


def _reportlab_dependencies() -> tuple[Any, ...]:
    try:
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.platypus import (
            LongTable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        from svglib.svglib import svg2rlg
    except ImportError as error:
        raise ReferenceShapeSpacePdfError(
            "PDF export dependencies are unavailable; install the DiffeoForge desktop extra"
        ) from error
    return (
        Drawing,
        colors,
        TA_CENTER,
        TA_LEFT,
        A4,
        landscape,
        getSampleStyleSheet,
        ParagraphStyle,
        mm,
        canvas,
        LongTable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
        svg2rlg,
    )


def _metric(value: object) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _pdf_bytes(comparison: ReferenceShapeSpaceComparison) -> bytes:
    (
        _Drawing,
        colors,
        TA_CENTER,
        TA_LEFT,
        A4,
        landscape,
        get_sample_style_sheet,
        ParagraphStyle,
        mm,
        canvas,
        LongTable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
        svg2rlg,
    ) = _reportlab_dependencies()

    manifest = comparison.manifest
    if manifest.get("artifact_version") != COMPARISON_VERSION:
        raise ReferenceShapeSpacePdfError(
            f"PDF export requires comparison artifact version {COMPARISON_VERSION}"
        )
    agreement = manifest.get("agreement_analysis")
    methods = manifest.get("methods")
    source = manifest.get("source")
    decision = manifest.get("default_decision")
    if not all(isinstance(value, dict) for value in (agreement, source, decision)):
        raise ReferenceShapeSpacePdfError("Comparison manifest lacks PDF report fields")
    if not isinstance(methods, list) or not methods:
        raise ReferenceShapeSpacePdfError("Comparison manifest has no methods")

    page_size = landscape(A4)
    page_width, page_height = page_size
    left_margin = right_margin = 15 * mm
    top_margin = 18 * mm
    bottom_margin = 15 * mm
    available_width = page_width - left_margin - right_margin
    available_height = page_height - top_margin - bottom_margin
    buffer = io.BytesIO()

    styles = get_sample_style_sheet()
    title_style = ParagraphStyle(
        "DiffeoForgeTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#17343a"),
        alignment=TA_LEFT,
        spaceAfter=8 * mm,
    )
    h1_style = ParagraphStyle(
        "DiffeoForgeHeading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=colors.HexColor("#17343a"),
        spaceAfter=4 * mm,
    )
    h2_style = ParagraphStyle(
        "DiffeoForgeSubheading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#178a78"),
        spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "DiffeoForgeBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#17343a"),
        spaceAfter=3 * mm,
    )
    small_style = ParagraphStyle(
        "DiffeoForgeSmall",
        parent=body_style,
        fontSize=7,
        leading=9,
        spaceAfter=0,
    )
    tiny_style = ParagraphStyle(
        "DiffeoForgeTiny",
        parent=body_style,
        fontSize=5.4,
        leading=6.5,
        spaceAfter=0,
    )
    center_style = ParagraphStyle(
        "DiffeoForgeCenter",
        parent=small_style,
        alignment=TA_CENTER,
    )

    def paragraph(value: object, style: Any = body_style) -> Any:
        return Paragraph(html.escape(_ascii(value)), style)

    def table_style(*, header: bool = True, tiny: bool = False) -> Any:
        font_size = 5.1 if tiny else 7
        commands: list[tuple[Any, ...]] = [
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d9da")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ]
        if header:
            commands.extend(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dcebea")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17343a")),
                ]
            )
        return TableStyle(commands)

    def svg_drawing(name: str) -> Any:
        svg_path = comparison.artifact_directory / name
        try:
            sanitized = _ascii(svg_path.read_text(encoding="utf-8"))
            sanitized = re.sub(
                r"<title\b[^>]*>.*?</title>",
                "",
                sanitized,
                flags=re.IGNORECASE | re.DOTALL,
            )
            drawing = svg2rlg(io.BytesIO(sanitized.encode("ascii")))
        except (OSError, UnicodeError, ValueError) as error:
            raise ReferenceShapeSpacePdfError(f"Could not render comparison figure: {name}") from error
        if drawing is None or not drawing.width or not drawing.height:
            raise ReferenceShapeSpacePdfError(f"Comparison figure is empty: {name}")
        maximum_width = available_width
        maximum_height = available_height - 20 * mm
        scale = min(maximum_width / drawing.width, maximum_height / drawing.height)
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        return drawing

    manifest_hash = sha256_file(comparison.artifact_directory / COMPARISON_MANIFEST)
    run_id = _ascii(source.get("run_id", "unknown"))
    subject_count = int(source.get("subjects", 0))
    dimensions = tuple(int(value) for value in agreement.get("dimensions", ()))
    if not dimensions:
        raise ReferenceShapeSpacePdfError("Comparison manifest has no agreement dimensions")
    profile_dimension = dimensions[0]
    labels = {str(method["method_id"]): str(method["label"]) for method in methods}
    reference_method_id = str(agreement["visual_reference_method_id"])
    pairwise_rows = list(agreement.get("pairwise", ()))

    story: list[Any] = [
        Spacer(1, 11 * mm),
        paragraph("DiffeoForge", h2_style),
        paragraph("Shape-space method comparison", title_style),
        paragraph(
            f"{decision['status']}: {decision['reason']}",
            ParagraphStyle(
                "DiffeoForgeOutcome",
                parent=body_style,
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=16,
                borderColor=colors.HexColor("#178a78"),
                borderWidth=1,
                borderPadding=10,
                backColor=colors.HexColor("#eef7f5"),
                spaceAfter=8 * mm,
            ),
        ),
    ]
    metadata = [
        [paragraph("Run", small_style), paragraph(run_id, small_style)],
        [paragraph("Subjects", small_style), paragraph(subject_count, small_style)],
        [paragraph("Selected methods", small_style), paragraph(len(methods), small_style)],
        [paragraph("Visual reference", small_style), paragraph(labels[reference_method_id], small_style)],
        [paragraph("Comparison created", small_style), paragraph(manifest.get("created_at", "unknown"), small_style)],
        [paragraph("Comparison manifest SHA-256", small_style), paragraph(manifest_hash, small_style)],
    ]
    metadata_table = Table(metadata, colWidths=(42 * mm, available_width - 42 * mm))
    metadata_table.setStyle(table_style(header=False))
    story.extend(
        [
            metadata_table,
            Spacer(1, 7 * mm),
            paragraph("How to interpret", h1_style),
            paragraph(
                "Raw ordination axes may rotate, reflect, change scale, or swap order. The "
                "overview centers, unit-scales, and orthogonally aligns the first two axes "
                "for display only; exported scores are unchanged. Distance correlation "
                "summarizes global specimen geometry, Procrustes correlation removes rigid "
                "axis ambiguity and scale, five-nearest-neighbor overlap describes local "
                "neighborhoods, and outlier overlap asks whether the same unusual specimens "
                "remain prominent. These are descriptive statistics, not p-values.",
            ),
            paragraph(
                f"Machine-readable exact values remain in {PAIRWISE_METRICS_CSV}; the "
                f"interactive evidence report remains in {REPORT_HTML} inside the verified "
                "comparison bundle.",
                small_style,
            ),
            PageBreak(),
        ]
    )

    figure_pages = (
        ("Aligned two-axis score overview", SCORE_OVERVIEW_SVG),
        (f"Methods versus the reference at {profile_dimension} dimensions", DEFAULT_PROFILE_SVG),
        (f"Pairwise distance agreement at {profile_dimension} dimensions", AGREEMENT_HEATMAP_2D_SVG),
        (f"Pairwise distance agreement at {dimensions[-1]} dimensions", AGREEMENT_HEATMAP_HIGH_DIM_SVG),
    )
    for title, filename in figure_pages:
        story.extend([paragraph(title, h1_style), svg_drawing(filename), PageBreak()])

    story.append(paragraph("Overall agreement statistics", h1_style))
    summary_header = [
        "Dimensions",
        "Pairs",
        "Median distance r",
        "Minimum distance r",
        "Median Procrustes r",
        "Median 5-NN overlap",
        "Median outlier overlap",
        "Weakest pair",
    ]
    summary_data: list[list[Any]] = [[paragraph(item, center_style) for item in summary_header]]
    for summary in agreement.get("summaries", ()):
        weakest = summary.get("weakest_pair_by_distance_correlation")
        weakest_text = "n/a"
        if isinstance(weakest, dict):
            weakest_text = (
                f"{labels.get(str(weakest['method_a_id']), weakest['method_a_id'])} vs "
                f"{labels.get(str(weakest['method_b_id']), weakest['method_b_id'])} "
                f"({_metric(weakest['pairwise_distance_correlation'])}, "
                f"{str(weakest['agreement_grade']).replace('_', ' ')})"
            )
        summary_data.append(
            [
                paragraph(summary["dimensions"], small_style),
                paragraph(summary["pair_count"], small_style),
                paragraph(_metric(summary["median_pairwise_distance_correlation"]), small_style),
                paragraph(_metric(summary["minimum_pairwise_distance_correlation"]), small_style),
                paragraph(_metric(summary["median_orthogonal_procrustes_correlation"]), small_style),
                paragraph(_metric(summary["median_nearest_neighbor_overlap"]), small_style),
                paragraph(_metric(summary["median_top_outlier_overlap"]), small_style),
                paragraph(weakest_text, small_style),
            ]
        )
    summary_widths = [17, 13, 23, 23, 25, 25, 25, 94]
    summary_table = Table(summary_data, colWidths=[width * mm for width in summary_widths], repeatRows=1)
    summary_table.setStyle(table_style())
    story.extend([summary_table, Spacer(1, 7 * mm)])

    story.append(paragraph(f"Methods versus the visual reference ({profile_dimension}D)", h1_style))
    profile_header = [
        "Method",
        "Tangent distance r",
        "Stress",
        "CKA",
        "Tangent outliers",
        "Distance r to reference",
        "Procrustes r",
        "5-NN overlap",
        "Pair outliers",
        "Grade",
    ]
    profile_data: list[list[Any]] = [[paragraph(item, tiny_style) for item in profile_header]]
    for method in methods:
        method_id = str(method["method_id"])
        evaluation = method["evaluations"][str(profile_dimension)]
        pair = next(
            (
                row
                for row in pairwise_rows
                if int(row["dimensions"]) == profile_dimension
                and {str(row["method_a_id"]), str(row["method_b_id"])}
                == {method_id, reference_method_id}
            ),
            None,
        )
        reference = method_id == reference_method_id
        values = [
            method["label"],
            _metric(evaluation["distance_correlation"]),
            _metric(evaluation["normalized_stress_after_scale"]),
            _metric(evaluation["centered_kernel_alignment_to_lddmm_pca"]),
            _metric(evaluation["top_outlier_overlap"]),
            "1.000" if reference else _metric(pair["pairwise_distance_correlation"]),
            "1.000" if reference else _metric(pair["orthogonal_procrustes_correlation"]),
            "1.000" if reference else _metric(pair["nearest_neighbor_overlap"]),
            "1.000" if reference else _metric(pair["top_outlier_overlap"]),
            "reference" if reference else str(pair["agreement_grade"]).replace("_", " "),
        ]
        profile_data.append([paragraph(value, tiny_style) for value in values])
    profile_widths = [61, 19, 17, 15, 19, 24, 19, 18, 18, 24]
    profile_table = Table(profile_data, colWidths=[width * mm for width in profile_widths], repeatRows=1)
    profile_table.setStyle(table_style(tiny=True))
    story.extend([profile_table, PageBreak()])

    story.extend(
        [
            paragraph("Exact pairwise agreement appendix", h1_style),
            paragraph(
                "Values are rounded to three decimals for print. The verified CSV named "
                f"{PAIRWISE_METRICS_CSV} preserves the full precision.",
                small_style,
            ),
        ]
    )
    pair_header = [
        "Method A",
        "Method B",
        "Dims",
        "Distance r",
        "Procrustes r",
        "CKA",
        "5-NN",
        "Outliers",
        "Grade",
    ]
    pair_data: list[list[Any]] = [[paragraph(item, tiny_style) for item in pair_header]]
    for row in pairwise_rows:
        values = [
            labels.get(str(row["method_a_id"]), row["method_a_id"]),
            labels.get(str(row["method_b_id"]), row["method_b_id"]),
            row["dimensions"],
            _metric(row["pairwise_distance_correlation"]),
            _metric(row["orthogonal_procrustes_correlation"]),
            _metric(row["centered_kernel_alignment"]),
            _metric(row["nearest_neighbor_overlap"]),
            _metric(row["top_outlier_overlap"]),
            str(row["agreement_grade"]).replace("_", " "),
        ]
        pair_data.append([paragraph(value, tiny_style) for value in values])
    pair_widths = [67, 67, 12, 20, 22, 15, 15, 17, 24]
    pair_table = LongTable(
        pair_data,
        colWidths=[width * mm for width in pair_widths],
        repeatRows=1,
        splitByRow=1,
    )
    pair_table.setStyle(table_style(tiny=True))
    story.extend([pair_table, PageBreak()])

    story.extend(
        [
            Spacer(1, 14 * mm),
            paragraph("Scientific boundary", h1_style),
            paragraph(manifest["scientific_boundary"]),
            paragraph(agreement["scientific_boundary"]),
            Spacer(1, 8 * mm),
            paragraph("What this report supports", h2_style),
            paragraph(
                "It compares numerical representations of the same completed atlas and "
                "documents how strongly those representations retain global geometry, "
                "local neighborhoods, and prominent outliers.",
            ),
            paragraph("What this report does not establish", h2_style),
            paragraph(
                "It does not establish biological group separation, registration validity, "
                "causation, statistical significance, or an exact geodesic principal "
                "analysis. Exploratory nonlinear views do not automatically provide "
                "shootable Deformetrica momenta.",
            ),
        ]
    )

    footer_hash = manifest_hash[:12]

    def page_frame(pdf_canvas: Any, document: Any) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setTitle("DiffeoForge shape-space method comparison")
        pdf_canvas.setAuthor("DiffeoForge")
        pdf_canvas.setSubject(f"Verified comparison for run {run_id}")
        pdf_canvas.setFont("Helvetica", 6.5)
        pdf_canvas.setFillColor(colors.HexColor("#52666b"))
        pdf_canvas.drawString(left_margin, 7 * mm, f"DiffeoForge | run {run_id} | manifest {footer_hash}")
        pdf_canvas.drawRightString(page_width - right_margin, 7 * mm, f"Page {document.page}")
        pdf_canvas.restoreState()

    class InvariantCanvas(canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)

    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title="DiffeoForge shape-space method comparison",
        author="DiffeoForge",
    )
    try:
        document.build(story, onFirstPage=page_frame, onLaterPages=page_frame, canvasmaker=InvariantCanvas)
    except Exception as error:
        if isinstance(error, ReferenceShapeSpacePdfError):
            raise
        raise ReferenceShapeSpacePdfError("Could not compose the shape-space PDF") from error
    payload = buffer.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise ReferenceShapeSpacePdfError("Generated shape-space report is not a PDF")
    return payload


def _paths_for_pdf(pdf_path: Path) -> tuple[Path, Path]:
    return (
        pdf_path.with_name(pdf_path.name + PDF_PROVENANCE_SUFFIX),
        pdf_path.with_name(pdf_path.name + PDF_SIDECAR_SUFFIX),
    )


def _write_bytes_exclusive(destination: Path, payload: bytes) -> None:
    with destination.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_reference_shape_space_pdf(
    comparison: ReferenceShapeSpaceComparison | Path | str,
    project_directory: Path | str,
    destination: Path | str | None = None,
) -> ReferenceShapeSpacePdfExport:
    """Create or reverify one deterministic, source-bound project PDF."""

    verified = (
        verify_reference_shape_space_comparison(comparison.artifact_directory)
        if isinstance(comparison, ReferenceShapeSpaceComparison)
        else verify_reference_shape_space_comparison(comparison)
    )
    project = Path(project_directory).expanduser()
    if not project.is_dir() or project.is_symlink():
        raise ReferenceShapeSpacePdfError(
            f"DiffeoForge project directory is missing or symbolic: {project}"
        )
    project = project.resolve()
    target = (
        default_reference_shape_space_pdf_path(project, verified)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.parent != project:
        raise ReferenceShapeSpacePdfError(
            "Shape-space PDF destination must be directly inside the DiffeoForge project directory"
        )
    if target.suffix.lower() != ".pdf":
        raise ReferenceShapeSpacePdfError("Shape-space PDF destination must end in .pdf")
    provenance_path, sidecar_path = _paths_for_pdf(target)
    existing = tuple(path.exists() for path in (target, provenance_path, sidecar_path))
    if any(existing):
        if all(existing):
            return verify_reference_shape_space_pdf(target, verified)
        raise FileExistsError(
            "Shape-space PDF export is incomplete and will not be overwritten: "
            f"{target}"
        )

    pdf_payload = _pdf_bytes(verified)
    manifest_path = verified.artifact_directory / COMPARISON_MANIFEST
    source = verified.manifest["source"]
    selection = verified.manifest["selection"]
    provenance: dict[str, Any] = {
        "export_version": PDF_EXPORT_VERSION,
        "generator": PDF_GENERATOR,
        "source_artifact_version": verified.manifest["artifact_version"],
        "source_comparison_directory": str(verified.artifact_directory),
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_run_id": source["run_id"],
        "source_selection_fingerprint": selection["selection_fingerprint"],
        "source_created_at": verified.manifest["created_at"],
        "pdf": {
            "path": target.name,
            "bytes": len(pdf_payload),
            "sha256": hashlib.sha256(pdf_payload).hexdigest(),
        },
    }
    provenance_payload = _canonical_json(provenance)
    created: list[Path] = []
    try:
        _write_bytes_exclusive(target, pdf_payload)
        created.append(target)
        write_text_safely(provenance_path, provenance_payload, overwrite=False)
        created.append(provenance_path)
        write_text_safely(
            sidecar_path,
            hashlib.sha256(provenance_payload.encode("utf-8")).hexdigest() + "\n",
            overwrite=False,
        )
        created.append(sidecar_path)
        return verify_reference_shape_space_pdf(target, verified)
    except Exception:
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def verify_reference_shape_space_pdf(
    pdf_path: Path | str,
    comparison: ReferenceShapeSpaceComparison | Path | str | None = None,
) -> ReferenceShapeSpacePdfExport:
    """Rebind a PDF export to its exact comparison and regenerated PDF bytes."""

    target = Path(pdf_path).expanduser().resolve()
    provenance_path, sidecar_path = _paths_for_pdf(target)
    for path, label in (
        (target, "PDF"),
        (provenance_path, "PDF provenance"),
        (sidecar_path, "PDF provenance sidecar"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ReferenceShapeSpacePdfError(f"Shape-space {label} is missing or symbolic: {path}")
    try:
        expected_provenance_hash = sidecar_path.read_text(encoding="ascii").strip()
        provenance_payload = provenance_path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise ReferenceShapeSpacePdfError("Could not read shape-space PDF provenance") from error
    if expected_provenance_hash != hashlib.sha256(provenance_payload).hexdigest():
        raise ReferenceShapeSpacePdfError("Shape-space PDF provenance SHA-256 differs")
    try:
        provenance = load_strict_json_object(
            provenance_payload,
            provenance_path,
            label="Shape-space PDF provenance",
        )
    except (ConfigurationError, OSError) as error:
        raise ReferenceShapeSpacePdfError(str(error)) from error
    expected_keys = {
        "export_version",
        "generator",
        "source_artifact_version",
        "source_comparison_directory",
        "source_manifest_sha256",
        "source_run_id",
        "source_selection_fingerprint",
        "source_created_at",
        "pdf",
    }
    if set(provenance) != expected_keys:
        raise ReferenceShapeSpacePdfError("Shape-space PDF provenance fields differ")
    if (
        provenance.get("export_version") != PDF_EXPORT_VERSION
        or provenance.get("generator") != PDF_GENERATOR
        or provenance.get("source_artifact_version") != COMPARISON_VERSION
    ):
        raise ReferenceShapeSpacePdfError("Shape-space PDF provenance version differs")
    pdf_record = provenance.get("pdf")
    if not isinstance(pdf_record, dict) or set(pdf_record) != {"path", "bytes", "sha256"}:
        raise ReferenceShapeSpacePdfError("Shape-space PDF inventory fields differ")
    if pdf_record["path"] != target.name:
        raise ReferenceShapeSpacePdfError("Shape-space PDF filename differs from provenance")
    try:
        pdf_size = target.stat().st_size
        pdf_hash = sha256_file(target)
    except OSError as error:
        raise ReferenceShapeSpacePdfError("Could not hash shape-space PDF") from error
    if pdf_record["bytes"] != pdf_size or pdf_record["sha256"] != pdf_hash:
        raise ReferenceShapeSpacePdfError("Shape-space PDF bytes differ from provenance")

    verified = (
        verify_reference_shape_space_comparison(provenance["source_comparison_directory"])
        if comparison is None
        else (
            verify_reference_shape_space_comparison(comparison.artifact_directory)
            if isinstance(comparison, ReferenceShapeSpaceComparison)
            else verify_reference_shape_space_comparison(comparison)
        )
    )
    expected_source = verified.manifest["source"]
    expected_selection = verified.manifest["selection"]
    expected_values = {
        "source_artifact_version": verified.manifest["artifact_version"],
        "source_comparison_directory": str(verified.artifact_directory),
        "source_manifest_sha256": sha256_file(
            verified.artifact_directory / COMPARISON_MANIFEST
        ),
        "source_run_id": expected_source["run_id"],
        "source_selection_fingerprint": expected_selection["selection_fingerprint"],
        "source_created_at": verified.manifest["created_at"],
    }
    for key, expected in expected_values.items():
        if provenance.get(key) != expected:
            raise ReferenceShapeSpacePdfError(
                f"Shape-space PDF provenance differs from comparison: {key}"
            )
    regenerated = _pdf_bytes(verified)
    if target.read_bytes() != regenerated:
        raise ReferenceShapeSpacePdfError(
            "Shape-space PDF differs from deterministic regeneration"
        )
    return ReferenceShapeSpacePdfExport(
        pdf_path=target,
        provenance_path=provenance_path,
        sidecar_path=sidecar_path,
        provenance=provenance,
    )
