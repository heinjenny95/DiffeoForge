from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import diffeoforge.reference_pca_stability as stability_module
from diffeoforge.analysis import principal_component_analysis
from diffeoforge.cli import main
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import REFERENCE_PCA_MANIFEST, ReferencePCABundle
from diffeoforge.reference_pca_stability import (
    REFERENCE_PCA_STABILITY_MANIFEST,
    REFERENCE_PCA_STABILITY_SIDECAR,
    ReferencePCAStabilityError,
    verify_reference_pca_stability,
    write_reference_pca_stability,
)


def _bundle(root: Path, *, offset: float = 0.0) -> ReferencePCABundle:
    root.mkdir()
    (root / REFERENCE_PCA_MANIFEST).write_text("{}\n", encoding="utf-8")
    features = np.array(
        [
            [1.0 + offset, 2.0, -0.5],
            [0.2, -1.0 + offset, 1.5],
            [-1.2, 0.4, 2.1 + offset],
            [2.4, -0.2, -1.0],
            [0.7, 1.8, 0.3],
        ],
        dtype=np.float64,
    )
    pca = principal_component_analysis(
        features,
        feature_space="subject_initial_momenta_cartesian",
        feature_labels=["cp0:x", "cp0:y", "cp0:z"],
        sample_labels=[f"subject-{index}" for index in range(5)],
    )
    marker = "a" if offset == 0 else "b"
    manifest = {
        "bundle_version": "0.2",
        "inputs": {
            "subjects": 5,
            "control_point_count": 1,
            "subject_labels": list(pca.sample_labels),
            "momenta": {"sha256": marker * 64},
            "control_points": {"sha256": "c" * 64},
        },
    }
    return ReferencePCABundle(root.resolve(), manifest, pca)


def _install_fake_verifier(monkeypatch, *bundles: ReferencePCABundle) -> None:
    by_path = {bundle.bundle_directory: bundle for bundle in bundles}

    def verify(path):
        resolved = Path(path).expanduser().resolve()
        if resolved not in by_path:
            raise RuntimeError("unknown PCA bundle")
        return by_path[resolved]

    monkeypatch.setattr(stability_module, "verify_reference_pca_bundle", verify)


def test_reference_pca_stability_is_immutable_bound_and_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)

    destination = write_reference_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        component_count=2,
        created_at="2026-08-25T14:00:00+00:00",
    )
    verified = verify_reference_pca_stability(destination)

    assert verified.evidence.reference_component_count == 2
    assert verified.manifest["reference"]["manifest_sha256"] == sha256_file(
        reference.bundle_directory / REFERENCE_PCA_MANIFEST
    )
    assert verified.manifest["comparison"]["momenta_sha256"] == "b" * 64
    assert set(path.name for path in destination.iterdir()) == {
        REFERENCE_PCA_STABILITY_MANIFEST,
        REFERENCE_PCA_STABILITY_SIDECAR,
    }
    with pytest.raises(FileExistsError, match="already exists"):
        write_reference_pca_stability(
            reference.bundle_directory,
            comparison.bundle_directory,
            destination,
            component_count=2,
        )


def test_reference_pca_stability_rejects_changed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)
    destination = write_reference_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        component_count=2,
    )
    manifest_path = destination / REFERENCE_PCA_STABILITY_MANIFEST
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["evidence"]["score_linear_cka"] = 0.0
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / REFERENCE_PCA_STABILITY_SIDECAR).write_text(
        sha256_file(manifest_path) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ReferencePCAStabilityError, match="exact recomputation"):
        verify_reference_pca_stability(destination)


def test_reference_pca_stability_rejects_changed_source_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)
    destination = write_reference_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        variance_target=0.75,
    )
    (reference.bundle_directory / REFERENCE_PCA_MANIFEST).write_text(
        "{\"changed\": true}\n", encoding="utf-8"
    )

    with pytest.raises(ReferencePCAStabilityError, match="source hashes changed"):
        verify_reference_pca_stability(destination)


def test_reference_pca_stability_requires_distinct_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    _install_fake_verifier(monkeypatch, reference)

    with pytest.raises(ReferencePCAStabilityError, match="distinct"):
        write_reference_pca_stability(
            reference.bundle_directory,
            reference.bundle_directory,
            tmp_path / "stability",
        )


def test_reference_pca_stability_cli_creates_and_reverifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)
    destination = tmp_path / "stability"

    assert (
        main(
            [
                "reference-pca-stability",
                str(reference.bundle_directory),
                str(comparison.bundle_directory),
                "--output",
                str(destination),
                "--components",
                "2",
            ]
        )
        == 0
    )
    creation = capsys.readouterr().out
    assert "Score linear CKA" in creation
    assert "not biological validation" in creation

    assert main(["reference-pca-stability-verify", str(destination)]) == 0
    assert "exact stability calculation match" in capsys.readouterr().out
