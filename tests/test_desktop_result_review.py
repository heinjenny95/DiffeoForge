from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.desktop.result_review import (  # noqa: E402
    ModernResultReviewError,
    review_modern_result,
    verify_result_artifact,
)
from diffeoforge.desktop.worker_protocol import sha256_file  # noqa: E402
from diffeoforge.modern_workflow import (  # noqa: E402
    load_modern_workflow_config,
    run_modern_workflow,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-07-17T12:00:00+00:00"


def _run_result(tmp_path: Path) -> Path:
    config = copy.deepcopy(load_modern_workflow_config(EXAMPLE_CONFIG))
    meshes = ROOT / "examples" / "synthetic" / "meshes"
    config["input"]["directory"] = str(meshes)
    config["input"]["template"] = str(meshes / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = str(tmp_path / "unused")
    source = tmp_path / "modern.yaml"
    source.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return run_modern_workflow(
        source,
        destination=tmp_path / "modern-result",
        created_at=FIXED_TIME,
    )


def test_verified_modern_result_exposes_bounded_summary_and_inventory(
    tmp_path: Path,
) -> None:
    run = _run_result(tmp_path)

    review = review_modern_result(run)

    assert review.run_directory == run.resolve()
    assert review.project_name == "synthetic-modern-atlas"
    assert review.created_at == FIXED_TIME
    assert review.workflow_manifest_sha256 == sha256_file(review.workflow_manifest_path)
    assert review.bundle_manifest_sha256 == sha256_file(review.bundle_manifest_path)
    assert review.optimizer_converged is False
    assert review.optimizer_termination_reason == "max_cycles"
    assert review.optimizer_cycles_completed == 1
    assert review.optimizer_max_cycles == 1
    assert {item.label for item in review.overview} >= {
        "Project",
        "Engine",
        "Dataset",
        "Template",
    }
    assert {item.label for item in review.optimization} >= {
        "Termination",
        "Objective",
        "Subject residuals",
    }
    assert review.pca[0].label == "PCA space"
    assert any(item.label == "PC1" for item in review.pca)
    assert {artifact.key for artifact in review.artifacts} >= {
        "estimated-template",
        "optimizer-history",
        "pca-summary",
        "pca-scores",
        "pca-scree",
        "pca-score-plot",
        "pca-deformation-definition",
        "pca-mean-shape",
        "mesh-quality-json",
        "mesh-quality-csv",
    }
    assert len({artifact.key for artifact in review.artifacts}) == len(review.artifacts)
    assert all(artifact.path.is_file() for artifact in review.artifacts)
    assert any("biological" in boundary.lower() for boundary in review.scientific_boundaries)
    assert verify_result_artifact(review, "pca-scree") == review.artifact("pca-scree").path


def test_artifact_handoff_refuses_tampering_manifest_changes_and_path_escape(
    tmp_path: Path,
) -> None:
    run = _run_result(tmp_path)
    review = review_modern_result(run)
    artifact = review.artifact("pca-scree")
    original = artifact.path.read_bytes()

    artifact.path.write_bytes(original + b"\n<!-- changed -->\n")
    with pytest.raises(ModernResultReviewError, match="artifact changed"):
        verify_result_artifact(review, artifact.key)
    artifact.path.write_bytes(original)
    assert verify_result_artifact(review, artifact.key) == artifact.path

    outside = tmp_path / "outside.svg"
    outside.write_bytes(original)
    escaped = replace(
        review,
        artifacts=(
            replace(
                artifact,
                path=outside,
                bytes=outside.stat().st_size,
                sha256=sha256_file(outside),
            ),
        ),
    )
    with pytest.raises(ModernResultReviewError, match="escapes"):
        verify_result_artifact(escaped, artifact.key)

    workflow_manifest = review.workflow_manifest_path
    workflow_manifest.write_bytes(workflow_manifest.read_bytes() + b"\n")
    with pytest.raises(ModernResultReviewError, match="Workflow manifest changed"):
        verify_result_artifact(review, artifact.key)


def test_unknown_artifact_key_is_not_opened(tmp_path: Path) -> None:
    review = review_modern_result(_run_result(tmp_path))

    with pytest.raises(ModernResultReviewError, match="Unknown result artifact"):
        verify_result_artifact(review, "not-in-the-inventory")
