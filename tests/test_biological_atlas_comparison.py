from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import biological_atlas_comparison as group
from diffeoforge.analysis.pca import principal_component_analysis
from diffeoforge.atlas_comparison import AtlasComparisonError
from diffeoforge.mesh import sha256_file
from diffeoforge.pca_metadata import PCAMetadataError


def _sources(tmp_path, monkeypatch):
    values = np.array([[-3.0, -1.0], [-3.0, 1.0], [-2.0, 0.0], [3.0, 1.0], [3.0, -1.0], [2.0, 0.0]])
    labels = tuple(f"shape{i}.vtk" for i in range(len(values)))

    def source(name, points):
        directory = tmp_path / name
        bundle = directory / "pca"
        bundle.mkdir(parents=True)
        run_manifest = directory / "manifest.json"
        pca_manifest = bundle / "manifest.json"
        for path in run_manifest, pca_manifest:
            path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            run_directory=directory,
            project_name=name,
            engine_route="deformetrica_reference",
            workflow_manifest_path=run_manifest,
            workflow_manifest_sha256=sha256_file(run_manifest),
            bundle_directory=bundle,
            bundle_manifest_path=pca_manifest,
            bundle_manifest_sha256=sha256_file(pca_manifest),
            registration_qc=(),
            pca=principal_component_analysis(points, sample_labels=labels, feature_space="test"),
        )

    left, right = source("First & saved", values), source("Second", values[:, ::-1])
    right.pca = replace(right.pca, sample_labels=labels[::-1], scores=right.pca.scores[::-1])
    sources = {review.run_directory: review for review in (left, right)}

    def review(path, *, create_pca_if_missing):
        assert create_pca_if_missing is False
        return sources[Path(path)]

    monkeypatch.setattr(group.atlas, "_review", review)
    monkeypatch.setattr(group.atlas, "_pca", lambda source: source.pca)
    monkeypatch.setattr(
        group,
        "compare_group_anatomy",
        lambda *args: {"available": False, "unavailable_reason": "Template lineage differs"},
    )
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(
        "subject,class\n"
        + "".join(
            f"{label},{'A' if index < 3 else 'B & C'}\n" for index, label in enumerate(labels)
        ),
        encoding="utf-8",
    )
    return left, right, metadata


def _write(left, right, metadata, target):
    return group.write_group_comparison(
        left.run_directory,
        right.run_directory,
        metadata,
        target,
        id_column="subject",
        group_column="class",
        reference_level="A",
        comparison_level="B & C",
    )


def test_report_pairs_verified_scores_leaves_sources_unchanged(tmp_path, monkeypatch):
    left, right, metadata = _sources(tmp_path, monkeypatch)
    target = tmp_path / "comparison"
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = _write(left, right, metadata, target)
    assert report == target / group.REPORT_NAME
    assert set(p.name for p in target.iterdir()) == {group.REPORT_NAME, group.DATA_NAME}
    assert {p: p.read_bytes() for p in before} == before
    page = report.read_text(encoding="utf-8")
    assert "B &amp; C" in page and "First &amp; saved" in page
    assert "Template lineage differs" in page
    assert "1.000" in page
    with pytest.raises(FileExistsError):
        _write(left, right, metadata, target)


def test_reject_metadata_missing_specimen_and_source_nested_output(tmp_path, monkeypatch):
    left, right, metadata = _sources(tmp_path, monkeypatch)
    with pytest.raises(AtlasComparisonError, match="outside"):
        _write(left, right, metadata, left.run_directory / "comparison")
    metadata.write_text("subject,class\nshape0.vtk,A\n", encoding="utf-8")
    target = tmp_path / "comparison"
    with pytest.raises(PCAMetadataError, match="exactly match"):
        _write(left, right, metadata, target)
    assert not target.exists()
