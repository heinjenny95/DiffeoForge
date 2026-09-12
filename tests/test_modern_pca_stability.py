from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import diffeoforge.modern_pca_stability as stability_module
from diffeoforge.analysis import principal_component_analysis
from diffeoforge.cli import main
from diffeoforge.mesh import sha256_file
from diffeoforge.modern_pca_stability import (
    MODERN_PCA_STABILITY_MANIFEST,
    MODERN_PCA_STABILITY_SIDECAR,
    ModernPCAStabilityError,
    VerifiedModernPCABundle,
    verify_modern_pca_stability,
    write_modern_pca_stability,
)


def _bundle(
    root: Path,
    *,
    offset: float = 0.0,
    control_hash: str = "c" * 64,
) -> VerifiedModernPCABundle:
    root.mkdir()
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
        "bundle_version": "0.1",
        "engine": {"implementation_version": "1.6"},
        "parameters": {"subjects": 5, "control_points": 1},
    }
    return VerifiedModernPCABundle(
        bundle_directory=root.resolve(),
        manifest=manifest,
        pca=pca,
        manifest_sha256=marker * 64,
        momenta_sha256=marker * 64,
        control_points_sha256=control_hash,
    )


def _install_fake_verifier(
    monkeypatch: pytest.MonkeyPatch,
    *bundles: VerifiedModernPCABundle,
) -> None:
    by_path = {bundle.bundle_directory: bundle for bundle in bundles}

    def verify(path):
        resolved = Path(path).expanduser().resolve()
        if resolved not in by_path:
            raise RuntimeError("unknown Modern bundle")
        return by_path[resolved]

    monkeypatch.setattr(stability_module, "verify_modern_pca_bundle", verify)


def test_modern_pca_stability_is_immutable_bound_and_control_identity_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(
        tmp_path / "comparison",
        offset=0.3,
        control_hash="d" * 64,
    )
    _install_fake_verifier(monkeypatch, reference, comparison)

    destination = write_modern_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        component_count=2,
        created_at="2026-08-27T08:00:00+00:00",
    )
    verified = verify_modern_pca_stability(destination)

    assert verified.evidence.reference_component_count == 2
    assert verified.evidence.feature_subspace_available is False
    assert "feature-space" in str(
        verified.evidence.feature_subspace_unavailable_reason
    )
    assert verified.manifest["reference"]["control_points_sha256"] == "c" * 64
    assert verified.manifest["comparison"]["control_points_sha256"] == "d" * 64
    assert set(path.name for path in destination.iterdir()) == {
        MODERN_PCA_STABILITY_MANIFEST,
        MODERN_PCA_STABILITY_SIDECAR,
    }
    with pytest.raises(FileExistsError, match="already exists"):
        write_modern_pca_stability(
            reference.bundle_directory,
            comparison.bundle_directory,
            destination,
            component_count=2,
        )


def test_modern_pca_stability_rejects_changed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)
    destination = write_modern_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        component_count=2,
    )
    manifest_path = destination / MODERN_PCA_STABILITY_MANIFEST
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["evidence"]["score_linear_cka"] = 0.0
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / MODERN_PCA_STABILITY_SIDECAR).write_text(
        sha256_file(manifest_path) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ModernPCAStabilityError, match="exact recomputation"):
        verify_modern_pca_stability(destination)


def test_modern_pca_stability_rejects_changed_source_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    comparison = _bundle(tmp_path / "comparison", offset=0.3)
    _install_fake_verifier(monkeypatch, reference, comparison)
    destination = write_modern_pca_stability(
        reference.bundle_directory,
        comparison.bundle_directory,
        tmp_path / "stability",
        variance_target=0.75,
    )
    changed = VerifiedModernPCABundle(
        **{
            **reference.__dict__,
            "momenta_sha256": "f" * 64,
        }
    )
    _install_fake_verifier(monkeypatch, changed, comparison)

    with pytest.raises(ModernPCAStabilityError, match="source hashes changed"):
        verify_modern_pca_stability(destination)


def test_modern_pca_stability_requires_distinct_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _bundle(tmp_path / "reference")
    _install_fake_verifier(monkeypatch, reference)

    with pytest.raises(ModernPCAStabilityError, match="distinct"):
        write_modern_pca_stability(
            reference.bundle_directory,
            reference.bundle_directory,
            tmp_path / "stability",
        )


def test_modern_pca_stability_cli_creates_and_reverifies(
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
                "modern-pca-stability",
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

    assert main(["modern-pca-stability-verify", str(destination)]) == 0
    assert "exact stability calculation match" in capsys.readouterr().out
