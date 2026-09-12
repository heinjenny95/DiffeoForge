from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import diffeoforge.pca_metadata as metadata_module
from diffeoforge.analysis.pca import principal_component_analysis
from diffeoforge.cli import main
from diffeoforge.pca_metadata import (
    PCAMetadataError,
    verify_pca_metadata_analysis,
    write_pca_metadata_analysis,
)


def _source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    labels = tuple(f"subject-{index:02d}.vtk" for index in range(6))
    features = np.asarray(
        [
            (index * 0.4, index**2 * 0.1 + 0.2, (-1) ** index * 0.3 + index * 0.1)
            for index in range(6)
        ],
        dtype=np.float64,
    )
    pca = principal_component_analysis(
        features,
        feature_space="test-shape-features",
        sample_labels=labels,
    )
    bundle = tmp_path / "verified-pca"
    bundle.mkdir()
    source = {
        "kind": "test_pca",
        "directory": str(bundle.resolve()),
        "manifest_name": "test.json",
        "manifest_sha256": "a" * 64,
    }
    monkeypatch.setattr(metadata_module, "_source_bundle", lambda path: (pca, source))
    return labels, bundle


def _metadata(path: Path, labels: tuple[str, ...]) -> Path:
    rows = ["subject,sex,body_size,location,specimen_label"]
    for index, label in enumerate(labels):
        rows.append(
            f"{label},{'female' if index % 2 else 'male'},"
            f"{10 + index * 0.5},{'north' if index < 2 else 'south' if index < 4 else 'west'},"
            f"voucher-{index:03d}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_metadata_is_joined_after_pca_and_exports_descriptive_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels, bundle = _source(tmp_path, monkeypatch)
    source = _metadata(tmp_path / "metadata.csv", labels)

    artifact = write_pca_metadata_analysis(
        bundle,
        source,
        tmp_path / "metadata-analysis",
        created_at="2026-08-30T12:00:00+00:00",
    )

    analysis = artifact.manifest["analysis"]
    kinds = {item["name"]: item["kind"] for item in analysis["metadata"]["columns"]}
    assert kinds == {
        "sex": "categorical",
        "body_size": "continuous",
        "location": "categorical",
        "specimen_label": "identifier_or_high_cardinality",
    }
    assert analysis["metadata"]["subject_count"] == 6
    assert analysis["categorical_group_summaries"]
    assert analysis["continuous_pc_associations"]
    assert "do not force" in analysis["scientific_boundary"]
    assert (artifact.artifact_directory / "joined-pca-metadata.csv").is_file()
    assert len(tuple((artifact.artifact_directory / "plots").glob("*.svg"))) == 3
    assert verify_pca_metadata_analysis(artifact.artifact_directory) == artifact


def test_metadata_requires_exact_subject_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels, bundle = _source(tmp_path, monkeypatch)
    source = _metadata(tmp_path / "metadata.csv", labels[:-1])

    with pytest.raises(PCAMetadataError, match="exactly match"):
        write_pca_metadata_analysis(bundle, source, tmp_path / "analysis")


def test_metadata_verification_rejects_changed_source_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels, bundle = _source(tmp_path, monkeypatch)
    source = _metadata(tmp_path / "metadata.csv", labels)
    artifact = write_pca_metadata_analysis(bundle, source, tmp_path / "analysis")
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PCAMetadataError, match="source CSV changed"):
        verify_pca_metadata_analysis(artifact.artifact_directory)


def test_pca_metadata_cli_states_post_pca_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    labels, bundle = _source(tmp_path, monkeypatch)
    source = _metadata(tmp_path / "metadata.csv", labels)
    destination = tmp_path / "cli-analysis"

    assert (
        main(
            [
                "pca-metadata",
                str(bundle),
                str(source),
                "--output",
                str(destination),
            ]
        )
        == 0
    )
    assert "joined after PCA" in capsys.readouterr().out
    assert main(["pca-metadata-verify", str(destination)]) == 0
    assert "figures, tables, and hashes match" in capsys.readouterr().out
