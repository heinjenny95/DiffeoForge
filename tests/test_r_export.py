"""R round trips and preservation gates on public, synthetic results only."""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pytest
from test_reference_pca import _completed_reference_run

from diffeoforge.analysis.landmarks import write_landmark_csv
from diffeoforge.desktop.reference_result_review import review_reference_result
from diffeoforge.r_export import export_landmarks_to_r, export_pca_to_r


def _rscript():
    path = shutil.which("Rscript")
    if path:
        return path
    roots = sorted(
        Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob("R/R-*/bin/Rscript.exe")
    )
    if not roots:
        pytest.skip("No local R runtime is available")
    return str(roots[-1])


def _run_r(directory, expression):
    script = directory / "check-export.R"
    script.write_text(expression+"\n", encoding="utf-8")
    result = subprocess.run(
        [_rscript(), "--vanilla", str(script)], cwd=directory,
        env={**os.environ, "LC_ALL": "C"}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _unpack(path, directory):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        metadata = json.loads(archive.read("export-manifest.json"))
        for record in metadata["files"]:
            data = archive.read(record["path"])
            assert len(data) == record["bytes"]
            assert hashlib.sha256(data).hexdigest() == record["sha256"]
        archive.extractall(directory)
    return metadata


def _inventory(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_base_r_loads_exact_reviewed_metric_scores_without_mutating_source(tmp_path):
    run = _completed_reference_run(tmp_path / "run", three_components=True)
    review = review_reference_result(run)
    before = _inventory(run)
    path = export_pca_to_r(review, tmp_path / "pca.zip")
    manifest = _unpack(path, tmp_path / "R")
    assert manifest["method_id"] == "lddmm_deformation_kernel_pca"
    assert manifest["scores_recomputed"] is False
    _run_r(tmp_path / "R", 'source("load_pca.R"); write.csv(score_matrix, "roundtrip.csv")')
    with (tmp_path / "R/roundtrip.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    with (tmp_path / "R/scores.csv").open(newline="", encoding="utf-8") as stream:
        original = list(csv.reader(stream))
    assert [r[0] for r in rows[1:]] == [r[0] for r in original[1:]]
    np.testing.assert_allclose(
        np.array([r[1:] for r in rows[1:]], float),
        np.array([r[1:] for r in original[1:]], float), rtol=1e-14, atol=1e-14,
    )
    assert _inventory(run) == before
    with pytest.raises(FileExistsError):
        export_pca_to_r(review, path)
    with pytest.raises(ValueError, match="outside"):
        export_pca_to_r(review, run / "for-R.zip")


def test_changed_reviewed_scores_block_export_and_leave_no_partial_zip(tmp_path):
    run = _completed_reference_run(tmp_path / "run")
    review = review_reference_result(run)
    review.artifact("pca-scores").path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed"):
        export_pca_to_r(review, tmp_path / "refused.zip")
    assert not (tmp_path / "refused.zip").exists()


def _landmarks(tmp_path, names=("template.vtk", "001", "002", "003")):
    base = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [.1, .2, 1]])
    values = np.array([base * [1+i*.1, 1-i*.05, 1+i*.2] + i for i in range(len(names))])
    source = tmp_path / "landmarks.csv"
    write_landmark_csv(source, names, ("001", "002", "NA", "tip, distal"), values)
    return source, names, values


def test_landmarks_roundtrip_keeps_axes_labels_units_and_excludes_template(tmp_path):
    source, names, values = _landmarks(tmp_path)
    before = source.read_bytes()
    path = export_landmarks_to_r(source, names, tmp_path / "geomorph.zip",
                                 template_name=names[0], coordinate_unit="millimeter")
    manifest = _unpack(path, tmp_path / "R")
    assert manifest["subject_labels"] == list(names[1:])
    assert manifest["alignment_applied"] is False
    assert manifest["coordinate_unit"] == "millimeter"
    assert manifest["homology_approval"] is False
    _run_r(tmp_path / "R", '''source("load_landmarks.R")
stopifnot(identical(dim(coords), c(4L,3L,3L)),
          identical(dimnames(coords)[[3]], c("001","002","003")),
          identical(dimnames(coords)[[1]], c("001","002","NA","tip, distal")))
write.table(as.vector(aperm(coords, c(3,1,2))), "values.txt", row.names=FALSE, col.names=FALSE)
''')
    # R's column-major traversal is checked independently, not by reusing the exporter.
    loaded = np.loadtxt(tmp_path / "R/values.txt").reshape((3, 4, 3), order="F")
    np.testing.assert_allclose(loaded, values[1:], rtol=1e-14, atol=1e-14)
    assert source.read_bytes() == before


def test_generated_geomorph_example_runs_a_separate_landmark_analysis(tmp_path):
    source, names, _ = _landmarks(tmp_path)
    path = export_landmarks_to_r(source, names, tmp_path / "geomorph.zip", template_name=names[0])
    _unpack(path, tmp_path / "R")
    availability = _run_r(tmp_path / "R", 'cat(requireNamespace("geomorph", quietly=TRUE))')
    if availability.stdout.strip() != "TRUE":
        pytest.skip("geomorph is not installed in the local R runtime")
    _run_r(tmp_path / "R", '''source("analyze_geomorph.R")
stopifnot(identical(dim(gpa$coords), dim(coords)), nrow(landmark_pca$x) == 3L)
''')


@pytest.mark.parametrize("problem", ["missing", "order", "nonfinite", "collinear"])
def test_invalid_homology_tables_cannot_be_exported(tmp_path, problem):
    source, names, values = _landmarks(tmp_path)
    if problem == "missing":
        lines = source.read_text().splitlines()
        source.write_text("\n".join(lines[:-1])+"\n")
    elif problem == "order":
        rows = list(csv.reader(source.read_text().splitlines()))
        rows[-1][1] = "different label"
        with source.open("w", newline="") as stream:
            csv.writer(stream).writerows(rows)
    elif problem == "nonfinite":
        source.write_text(source.read_text().replace("0.0", "nan", 1))
    else:
        values[:] = np.arange(4)[:, None] * np.array([1, 0, 0])
        source.unlink()
        write_landmark_csv(source, names, ("001", "002", "NA", "tip, distal"), values)
    with pytest.raises((RuntimeError, ValueError)):
        export_landmarks_to_r(source, names, tmp_path / "bad.zip", template_name=names[0])
    assert not (tmp_path / "bad.zip").exists()


def test_landmark_source_change_during_packaging_prevents_publication(tmp_path, monkeypatch):
    source, names, _ = _landmarks(tmp_path)
    original = zipfile.ZipFile.testzip

    def change(archive):
        source.write_text(source.read_text()+"\n")
        return original(archive)

    monkeypatch.setattr(zipfile.ZipFile, "testzip", change)
    with pytest.raises(ValueError, match="changed"):
        export_landmarks_to_r(source, names, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_labels_with_unicode_quotes_and_r_syntax_remain_data(tmp_path):
    names = ("template.vtk", "Taxon ä, quoted", "=system('never run')", '"003"')
    source, names, _ = _landmarks(tmp_path, names)
    path = export_landmarks_to_r(source, names, tmp_path / "labels.zip", template_name=names[0])
    _unpack(path, tmp_path / "R")
    _run_r(tmp_path / "R", '''source("load_landmarks.R")
hex <- vapply(dimnames(coords)[[3]], function(x)
  paste(as.character(charToRaw(enc2utf8(x))), collapse=""), character(1))
writeLines(hex, "labels-hex.txt", useBytes=TRUE)
''')
    # C-locale printing can escape Unicode even when R retains the right UTF-8 bytes.
    assert (tmp_path / "R/labels-hex.txt").read_text().splitlines() == [
        name.encode("utf-8").hex() for name in names[1:]
    ]


def test_racing_destination_is_preserved_without_leaving_a_partial_export(tmp_path, monkeypatch):
    source, names, _ = _landmarks(tmp_path)
    target = tmp_path / "race.zip"
    original = zipfile.ZipFile.testzip

    def race(archive):
        target.write_bytes(b"preserve the other export")
        return original(archive)

    monkeypatch.setattr(zipfile.ZipFile, "testzip", race)
    with pytest.raises(FileExistsError):
        export_landmarks_to_r(source, names, target)
    assert target.read_bytes() == b"preserve the other export"
    assert not list(tmp_path.glob(".*.tmp"))
