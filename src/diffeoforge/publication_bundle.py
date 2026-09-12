"""Immutable publication-facing exports from already verified atlas evidence.

This module copies open, source-bound artifacts; it does not rerun an atlas,
alter a PCA, render an unverified deformation path, or mutate source results.
"""

from __future__ import annotations

import csv
import html
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.result_review import ModernResultArtifact, verify_result_artifact
from diffeoforge.mesh import sha256_file
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.scientific_report import (
    SCIENTIFIC_REPORT_MANIFEST,
    ScientificReportError,
    collect_scientific_atlas_report,
    verify_scientific_atlas_report,
    write_scientific_atlas_report,
)

PUBLICATION_BUNDLE_VERSION = "0.1"
PUBLICATION_MANIFEST = "publication-manifest.json"
PUBLICATION_SIDECAR = "publication-manifest.sha256"
PUBLICATION_INDEX = "publication-index.html"
PUBLICATION_CAPTIONS = "figure-captions.csv"
PUBLICATION_README = "README.txt"
SCIENTIFIC_REPORT_DIRECTORY = "scientific-report"


class PublicationBundleError(RuntimeError):
    """Raised when a publication export cannot be safely created or verified."""


@dataclass(frozen=True)
class PublicationBundleArtifact:
    """One immutable publication directory and its verified manifest."""

    directory: Path
    manifest: Mapping[str, Any]


def default_publication_bundle_directory(run_directory: Path | str) -> Path:
    """Return a non-mutating sibling destination for one source run."""

    run = Path(run_directory).expanduser().resolve()
    return run.parent / f"{run.name}-publication"


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _artifact_record(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise PublicationBundleError("Publication artifact key has no safe filename")
    return normalized


def _publication_role(
    artifact: ModernResultArtifact,
    *,
    include_reconstructions: bool,
) -> str | None:
    if artifact.kind == "svg":
        return "figures"
    if artifact.kind in {"csv", "json", "txt"}:
        return "tables-and-evidence"
    if artifact.kind != "vtk":
        return None
    if artifact.key.startswith("estimated-template"):
        return "meshes"
    if artifact.key == "pca-mean-shape" or re.fullmatch(
        r"pc\d+-(?:minus|plus)", artifact.key
    ):
        return "meshes"
    if include_reconstructions and artifact.key.startswith("subject-reconstruction-"):
        return "reconstructions"
    return None


def _copy_review_artifact(
    root: Path,
    report,
    artifact: ModernResultArtifact,
    role: str,
) -> dict[str, object]:
    source = verify_result_artifact(report.review, artifact.key)
    if sha256_file(source) != artifact.sha256 or source.stat().st_size != artifact.bytes:
        raise PublicationBundleError(
            f"Verified source artifact changed before publication: {artifact.key}"
        )
    suffix = source.suffix.casefold()
    destination = root / role / f"{_safe_name(artifact.key)}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise PublicationBundleError(f"Publication filename collision: {destination.name}")
    shutil.copyfile(source, destination)
    if destination.stat().st_size != artifact.bytes or sha256_file(destination) != artifact.sha256:
        raise PublicationBundleError(f"Copied publication artifact differs: {artifact.key}")
    return {
        "source_key": artifact.key,
        "role": role,
        "label": artifact.label,
        "description": artifact.description,
        "kind": artifact.kind,
        "source_path": str(source),
        "source_sha256": artifact.sha256,
        "path": destination.relative_to(root).as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def _captions_csv(records: list[dict[str, object]]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("file", "label", "caption", "interpretation_boundary"))
    for record in records:
        if record["role"] != "figures":
            continue
        writer.writerow(
            (
                record["path"],
                record["label"],
                record["description"],
                (
                    "Verified descriptive visualization. PCA signs are conventional; "
                    "the figure is not independent biological validation."
                ),
            )
        )
    return output.getvalue()


def _index_html(
    *,
    project: str,
    engine: str,
    created_at: str,
    records: list[dict[str, object]],
) -> str:
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        grouped.setdefault(str(record["role"]), []).append(record)
    sections = []
    for role in ("figures", "meshes", "reconstructions", "tables-and-evidence"):
        entries = grouped.get(role, [])
        if not entries:
            continue
        items = "".join(
            "<li>"
            f'<a href="{html.escape(str(item["path"]))}">'
            f'{html.escape(str(item["label"]))}</a> — '
            f'{html.escape(str(item["description"]))}</li>'
            for item in entries
        )
        sections.append(f"<h2>{html.escape(role.replace('-', ' ').title())}</h2><ul>{items}</ul>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="generator" content="DiffeoForge publication bundle {PUBLICATION_BUNDLE_VERSION}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DiffeoForge publication bundle — {html.escape(project)}</title>
<style>body{{max-width:980px;margin:32px auto;padding:0 24px;font:15px/1.55 system-ui;
color:#173b39}}a{{color:#08766c}}.boundary{{padding:14px 18px;background:#eef7f5;
border-left:5px solid #167d72}}code{{word-break:break-all}}</style></head><body>
<h1>Publication bundle</h1><p>{html.escape(project)} · {html.escape(engine)} ·
{html.escape(created_at)}</p>
<p class="boundary"><strong>Scope:</strong> Exact verified source artifacts are copied with
SHA-256 provenance. SVG is retained as resolution-independent source artwork. No raster DPI
is guessed, no PCA is refitted, and no endpoint interpolation is presented as a verified
diffeomorphic animation.</p>
<p>The complete scientific report is in <a href="scientific-report/scientific-report.html">
scientific-report/scientific-report.html</a>. Captions are supplied in
<a href="{PUBLICATION_CAPTIONS}">{PUBLICATION_CAPTIONS}</a>.</p>
{''.join(sections)}
<h2>Reproducibility</h2><p><code>{PUBLICATION_MANIFEST}</code> inventories every byte and
binds this export to the verified workflow and analysis manifests.</p>
</body></html>"""


def _readme(*, include_reconstructions: bool) -> str:
    reconstruction_text = (
        "Subject reconstruction meshes were explicitly included."
        if include_reconstructions
        else (
            "Subject reconstructions are omitted by default to keep the bundle compact; "
            "they remain in the verified source run."
        )
    )
    return (
        "DiffeoForge publication bundle\n\n"
        "This directory contains exact copies of verified atlas figures, open tables, "
        "the estimated template, available PCA endpoint meshes, and a scientific report.\n\n"
        f"{reconstruction_text}\n\n"
        "SVG files are the canonical resolution-independent figures. Transparent PNG is "
        "not generated automatically because journal DPI, dimensions, fonts, and colour "
        "requirements must be chosen explicitly. A deformation video is not synthesized "
        "from endpoint meshes: only an inventoried time-resolved deformation path could "
        "support that export.\n\n"
        "The manifest and SHA-256 sidecar provide exact provenance. The export does not "
        "turn technical completion, residuals, PCA structure, metadata patterns, or visual "
        "appeal into biological validation.\n"
    )


def write_publication_bundle(
    run_directory: Path | str,
    destination: Path | str | None = None,
    *,
    validation_study: Path | str | None = None,
    sensitivity_assessment: Path | str | None = None,
    template_robustness: Path | str | None = None,
    holdout_study: Path | str | None = None,
    pca_stability: Path | str | None = None,
    decision_review: Path | str | None = None,
    include_reconstructions: bool = False,
    created_at: str | None = None,
) -> PublicationBundleArtifact:
    """Create and independently verify one immutable publication bundle."""

    report = collect_scientific_atlas_report(
        run_directory,
        validation_study=validation_study,
        sensitivity_assessment=sensitivity_assessment,
        template_robustness=template_robustness,
        holdout_study=holdout_study,
        pca_stability=pca_stability,
        decision_review=decision_review,
        created_at=created_at,
    )
    target = (
        default_publication_bundle_directory(report.review.run_directory)
        if destination is None
        else Path(destination).expanduser().resolve()
    )
    if target.exists() or target.is_symlink():
        raise PublicationBundleError(f"Publication destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        scientific = write_scientific_atlas_report(
            report,
            temporary / SCIENTIFIC_REPORT_DIRECTORY,
        )
        copied: list[dict[str, object]] = []
        for artifact in report.review.artifacts:
            role = _publication_role(
                artifact,
                include_reconstructions=include_reconstructions,
            )
            if role is not None:
                copied.append(_copy_review_artifact(temporary, report, artifact, role))
        write_text_safely(
            temporary / PUBLICATION_CAPTIONS,
            _captions_csv(copied),
            overwrite=False,
        )
        timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
        write_text_safely(
            temporary / PUBLICATION_INDEX,
            _index_html(
                project=report.review.project_name,
                engine=report.engine_label,
                created_at=timestamp,
                records=copied,
            ),
            overwrite=False,
        )
        write_text_safely(
            temporary / PUBLICATION_README,
            _readme(include_reconstructions=include_reconstructions),
            overwrite=False,
        )
        artifacts = [
            _artifact_record(temporary, path)
            for path in sorted(temporary.rglob("*"), key=lambda item: item.as_posix())
            if path.is_file()
        ]
        manifest = {
            "artifact_version": PUBLICATION_BUNDLE_VERSION,
            "created_at": timestamp,
            "project": report.review.project_name,
            "engine": report.review.engine_route,
            "source": {
                "run_directory": str(report.review.run_directory),
                "workflow_manifest_sha256": report.review.workflow_manifest_sha256,
                "analysis_manifest_sha256": report.review.bundle_manifest_sha256,
                "scientific_report_manifest_sha256": sha256_file(
                    scientific.directory / SCIENTIFIC_REPORT_MANIFEST
                ),
            },
            "selection": {
                "include_reconstructions": include_reconstructions,
                "copied_artifacts": copied,
            },
            "output_capabilities": {
                "vector_figures": "verified source SVG copied without modification",
                "transparent_png": "not generated; explicit journal raster settings required",
                "deformation_video": (
                    "not generated; endpoint interpolation is not a verified deformation path"
                ),
            },
            "artifacts": artifacts,
            "scientific_boundary": (
                "This export packages verified descriptive evidence. It does not establish "
                "biological validity or replace visual registration review."
            ),
        }
        manifest_path = temporary / PUBLICATION_MANIFEST
        write_text_safely(manifest_path, _canonical_json(manifest), overwrite=False)
        write_text_safely(
            temporary / PUBLICATION_SIDECAR,
            sha256_file(manifest_path) + "\n",
            overwrite=False,
            encoding="ascii",
        )
        publish_directory_exclusive(temporary, target)
        return _verify_publication_bundle(target, reverify_source=True)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _safe_artifact_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PublicationBundleError("Publication artifact path is invalid")
    relative = Path(value)
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise PublicationBundleError(f"Publication artifact path is unsafe: {value!r}")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root):
        raise PublicationBundleError(f"Publication artifact escapes the bundle: {value!r}")
    return path


def _verify_publication_bundle(
    directory: Path | str,
    *,
    reverify_source: bool,
) -> PublicationBundleArtifact:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PublicationBundleError(f"Publication directory is missing or symbolic: {root}")
    paths = tuple(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise PublicationBundleError("Publication bundle contains a symbolic path")
    manifest_path = root / PUBLICATION_MANIFEST
    sidecar_path = root / PUBLICATION_SIDECAR
    try:
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicationBundleError("Publication manifest is unreadable") from error
    if expected_digest != sha256_file(manifest_path):
        raise PublicationBundleError("Publication manifest SHA-256 differs")
    if (
        not isinstance(manifest, dict)
        or manifest.get("artifact_version") != PUBLICATION_BUNDLE_VERSION
    ):
        raise PublicationBundleError("Publication manifest version is unsupported")
    records = manifest.get("artifacts")
    if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records):
        raise PublicationBundleError("Publication artifact inventory is invalid")
    expected_files = {
        PUBLICATION_MANIFEST,
        PUBLICATION_SIDECAR,
        *(str(record["path"]) for record in records),
    }
    actual_files = {
        path.relative_to(root).as_posix() for path in paths if path.is_file()
    }
    if expected_files != actual_files:
        raise PublicationBundleError("Publication exact file inventory differs")
    for record in records:
        path = _safe_artifact_path(root, record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise PublicationBundleError(f"Publication artifact changed: {record['path']}")
    scientific = verify_scientific_atlas_report(root / SCIENTIFIC_REPORT_DIRECTORY)
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise PublicationBundleError("Publication source binding is invalid")
    if (
        sha256_file(scientific.directory / SCIENTIFIC_REPORT_MANIFEST)
        != source.get("scientific_report_manifest_sha256")
    ):
        raise PublicationBundleError("Nested scientific report binding differs")
    if reverify_source:
        report_source = scientific.manifest["source"]
        evidence = {
            str(record["role"]): str(record["sha256"])
            for record in report_source["evidence"]
        }
        if evidence.get("workflow_manifest") != source.get("workflow_manifest_sha256"):
            raise PublicationBundleError("Publication workflow binding differs")
        if evidence.get("analysis_manifest") != source.get("analysis_manifest_sha256"):
            raise PublicationBundleError("Publication analysis binding differs")
    return PublicationBundleArtifact(root, manifest)


def verify_publication_bundle(directory: Path | str) -> PublicationBundleArtifact:
    """Reverify the exact bundle, nested report, source atlas, and evidence hashes."""

    try:
        return _verify_publication_bundle(directory, reverify_source=True)
    except ScientificReportError as error:
        raise PublicationBundleError(str(error)) from error
