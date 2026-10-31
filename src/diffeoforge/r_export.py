"""Verified, non-overwriting R handoffs; no fitting or implicit alignment."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from diffeoforge.analysis.landmarks import read_landmark_csv
from diffeoforge.analysis.pca_artifacts import pca_csv_label
from diffeoforge.desktop.result_review import ModernResultReview, verify_result_artifact
from diffeoforge.mesh import sha256_file

BASE_R = '''# Run from the extracted export folder. Only base R is required.
specimens <- read.csv("specimens.csv", stringsAsFactors = FALSE, check.names = FALSE,
                      encoding = "UTF-8", na.strings = character(),
                      colClasses = c(subject_label = "character"))
scores <- read.csv("scores.csv", stringsAsFactors = FALSE, check.names = FALSE,
                   encoding = "UTF-8", na.strings = character(),
                   colClasses = c(subject_label = "character"))
variance <- read.csv("variance.csv", stringsAsFactors = FALSE, check.names = FALSE)
stopifnot(identical(scores$subject_label, specimens$subject_label))
score_matrix <- as.matrix(scores[-1])
rownames(score_matrix) <- scores$subject_label
stopifnot(is.numeric(score_matrix), all(is.finite(score_matrix)))
# These are the saved DiffeoForge scores, not a new prcomp() of raw momenta.
# Join your metadata by subject_label, never by an assumed file order.
if (ncol(score_matrix) >= 2L && interactive()) {
  plot(score_matrix[, 1], score_matrix[, 2], xlab = "PC1", ylab = "PC2", asp = 1)
  text(score_matrix[, 1], score_matrix[, 2], labels = rownames(score_matrix), pos = 3)
}
'''

LANDMARK_R = '''# Run from the extracted export folder. Loading needs only base R.
specimens <- read.csv("specimens.csv", stringsAsFactors = FALSE, check.names = FALSE,
                      encoding = "UTF-8", na.strings = character(),
                      colClasses = c(subject_label = "character"))
landmarks <- read.csv("landmarks.csv", stringsAsFactors = FALSE, check.names = FALSE,
                      encoding = "UTF-8", na.strings = character(),
                      colClasses = c(landmark = "character"))
points <- read.csv("coordinates.csv", check.names = FALSE)
p <- nrow(landmarks)
n <- nrow(specimens)
stopifnot(nrow(points) == p * n, p >= 3L, n >= 2L)
coords <- array(NA_real_, dim = c(p, 3L, n),
                dimnames = list(landmarks$landmark, c("x", "y", "z"),
                                specimens$subject_label))
for (i in seq_len(n)) {
  rows <- points[points$specimen_index == i, ]
  stopifnot(identical(as.integer(rows$landmark_index), seq_len(p)))
  coords[, , i] <- as.matrix(rows[c("x", "y", "z")])
}
stopifnot(all(is.finite(coords)))
# coords contains the original supplied landmark coordinates, without a new GPA.
'''

GEOMORPH_R = '''# This is a separate landmark analysis, not the saved LDDMM atlas PCA.
source("load_landmarks.R", encoding = "UTF-8")
if (!requireNamespace("geomorph", quietly = TRUE)) {
  stop("Install geomorph in your R environment before running this example.")
}
# All points are fixed homologous landmarks. No semilandmark sliding is assumed.
# gpagen removes landmark centroid size; this differs from surface-size scaling.
gpa <- geomorph::gpagen(coords, PrinAxes = FALSE, print.progress = FALSE)
landmark_pca <- geomorph::gm.prcomp(gpa$coords)
if (interactive()) plot(landmark_pca)
'''


def _csv(rows) -> bytes:
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode("utf-8")


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _publish(target, files, metadata, *, protected=(), recheck):
    target = Path(target).expanduser()
    if target.is_symlink():
        raise ValueError("Choose a regular new ZIP file")
    target = target.resolve()
    if target.suffix.lower() != ".zip":
        raise ValueError("R exports must use a .zip destination")
    if any(target.is_relative_to(Path(root).resolve()) for root in protected):
        raise ValueError("Choose an export destination outside the saved result")
    if target.exists():
        raise FileExistsError("Choose a new filename; existing R exports are preserved")
    records = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    ]
    files = {**files, "export-manifest.json": _json({
        "export_version": "0.1", "created_at": datetime.now(UTC).isoformat(),
        "files": records, **metadata,
    })}
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(stage, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(name, data)
        with zipfile.ZipFile(stage) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(files):
                raise ValueError("R export failed its archive verification")
            for name, data in files.items():
                if archive.read(name) != data:
                    raise ValueError("R export failed its byte verification")
        recheck()
        # A same-directory exclusive link prevents a racing export from being overwritten.
        os.link(stage, target)
        return target
    finally:
        stage.unlink(missing_ok=True)


def export_pca_to_r(review: ModernResultReview, target: Path) -> Path:
    """Export the exact reviewed PCA, preserving metric, sample order and signs."""
    summary_path = verify_result_artifact(review, "pca-summary")
    score_path = verify_result_artifact(review, "pca-scores")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    labels = summary["sample_labels"]
    components = summary["number_of_components"]
    if len(labels) < 2 or len(set(labels)) != len(labels) or components < 1:
        raise ValueError("Saved PCA requires unique specimens and at least one component")
    with score_path.open(encoding="utf-8", newline="") as stream:
        scores = list(csv.reader(stream))
    expected_header = ["subject_label", *[f"PC{i+1}" for i in range(components)]]
    if (scores[0] != expected_header or len(scores) != len(labels) + 1
            or [r[0] for r in scores[1:]] != [pca_csv_label(s) for s in labels]):
        raise ValueError("Saved PCA score order does not match its specimen identities")
    values = np.asarray([row[1:] for row in scores[1:]], dtype=np.float64)
    if values.shape != (len(labels), components) or not np.isfinite(values).all():
        raise ValueError("Saved PCA scores must be a complete finite matrix")
    variance = np.asarray(summary["explained_variance"], dtype=np.float64)
    ratios = np.asarray(summary["explained_variance_ratio"], dtype=np.float64)
    if (variance.shape != (components,) or ratios.shape != (components,)
            or not np.isfinite(variance).all() or not np.isfinite(ratios).all()
            or np.any(variance < 0) or np.any(ratios < 0)):
        raise ValueError("Saved PCA variance must be finite and nonnegative")
    files = {
        "scores.csv": _csv([expected_header, *[
            [label, *row[1:]] for label, row in zip(labels, scores[1:], strict=True)
        ]]),
        "specimens.csv": _csv([["row_index", "subject_label"], *enumerate(labels, 1)]),
        "variance.csv": _csv([["component", "variance", "variance_ratio"], *[
            [f"PC{i+1}", format(v, ".17g"), format(r, ".17g")]
            for i, (v, r) in enumerate(zip(variance, ratios, strict=True))
        ]]),
        "pca-summary.json": summary_path.read_bytes(),
        "load_pca.R": BASE_R.encode(),
        "README.txt": (
            "Extract this ZIP, set R's working directory to the extracted folder, then run\n"
            "source('load_pca.R', encoding='UTF-8')\n\n"
            f"Saved method: {review.pca_method_label}\n"
            "Scores preserve the saved metric, order and component signs. No PCA or atlas\n"
            "was refitted. Join metadata using subject_label. Do not substitute prcomp()\n"
            "of raw Cartesian momenta for the LDDMM-metric PCA.\n"
            "This handoff does not approve registration quality, anatomy or group effects.\n"
        ).encode(),
    }
    keys = ["pca-summary", "pca-scores"]
    if any(a.key == "pca-loadings" for a in review.artifacts):
        files["loadings.csv"] = verify_result_artifact(review, "pca-loadings").read_bytes()
        keys.append("pca-loadings")

    def recheck():
        for key in keys:
            verify_result_artifact(review, key)

    return _publish(target, files, {
        "kind": "saved_pca_for_base_r", "method_id": review.pca_method_id,
        "subject_labels": labels, "scores_recomputed": False,
        "source_manifests": {
            "workflow_sha256": review.workflow_manifest_sha256,
            "bundle_sha256": review.bundle_manifest_sha256,
        },
        "sources": [{"key": key, "sha256": review.artifact(key).sha256} for key in keys],
    }, protected=(review.run_directory, review.bundle_directory,
                  *review.additional_artifact_roots), recheck=recheck)


def export_landmarks_to_r(source, mesh_files, target, *, template_name=None, coordinate_unit=None):
    """Export supplied fixed landmarks, never momentum or independent mesh vertices."""
    source = Path(source).expanduser().resolve()
    source_hash = sha256_file(source)
    names = tuple(mesh_files)
    labels, values = read_landmark_csv(source, names)
    if template_name is not None and template_name not in names:
        raise ValueError("The excluded template must belong to the declared landmark cohort")
    indices = [i for i, name in enumerate(names) if name != template_name]
    if len(indices) < 2:
        raise ValueError("Export at least two subjects after excluding the template")
    values = values[indices]
    names = tuple(names[i] for i in indices)
    for configuration in values:
        if np.linalg.matrix_rank(configuration - configuration.mean(axis=0)) < 2:
            raise ValueError("Landmarks must include three distinct non-collinear points")
    files = {
        "specimens.csv": _csv([["specimen_index", "subject_label"], *enumerate(names, 1)]),
        "landmarks.csv": _csv([["landmark_index", "landmark"], *enumerate(labels, 1)]),
        "coordinates.csv": _csv([["specimen_index", "landmark_index", "x", "y", "z"], *[
            [i+1, j+1, *[format(v, ".17g") for v in point]]
            for i, specimen in enumerate(values) for j, point in enumerate(specimen)
        ]]),
        "load_landmarks.R": LANDMARK_R.encode(),
        "analyze_geomorph.R": GEOMORPH_R.encode(),
        "README.txt": (
            b"Extract this ZIP and set R's working directory to the extracted folder.\n"
            b"source('load_landmarks.R', encoding='UTF-8') loads coords[p, 3, n] using base R.\n"
            b"source('analyze_geomorph.R', encoding='UTF-8') explicitly runs a separate\n"
            b"fixed-landmark GPA and PCA with an already installed geomorph package.\n\n"
            b"Coordinates are the original supplied landmark CSV values. No alignment,\n"
            b"unit conversion, resampling or semilandmark sliding was applied by this export.\n"
            b"The initial template is excluded when declared. Specimen and landmark order\n"
            b"are explicit in the companion tables. Biological homology remains your review.\n"
            b"geomorph GPA removes landmark centroid size; this differs from DiffeoForge's\n"
            b"surface-size policies. The landmark PCA is not the LDDMM atlas PCA.\n"
        ),
    }

    def recheck():
        if sha256_file(source) != source_hash:
            raise ValueError("Landmark CSV changed during export")

    return _publish(target, files, {
        "kind": "fixed_landmarks_for_geomorph", "source_sha256": source_hash,
        "subject_labels": list(names), "landmark_labels": list(labels),
        "coordinate_unit": coordinate_unit, "coordinate_frame": "supplied_landmark_csv",
        "excluded_template": template_name, "alignment_applied": False,
        "homology_approval": False, "array_order": "landmark, xyz, specimen",
    }, recheck=recheck)
