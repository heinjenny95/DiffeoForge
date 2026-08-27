from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")

from diffeoforge.modern_synthetic_recovery import (
    ASSESSMENT_NAME,
    assess_modern_synthetic_recovery,
    create_modern_synthetic_recovery_design,
    verify_modern_synthetic_recovery_assessment,
    verify_modern_synthetic_recovery_design,
)
from diffeoforge.modern_workflow import run_modern_workflow
from diffeoforge.reference_validation_synthetic import (
    write_synthetic_validation_benchmark,
)

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "examples" / "synthetic" / "meshes" / "template.vtk"


def _design(
    tmp_path: Path,
    *,
    cycles: int = 1,
    attachment_type: str = "current",
    recovery_metric: str = "attachment_native",
) -> Path:
    benchmark = tmp_path / "benchmark"
    write_synthetic_validation_benchmark(TEMPLATE, benchmark, subjects_per_family=3)
    design = tmp_path / "design"
    create_modern_synthetic_recovery_design(
        benchmark,
        design,
        max_cycles=cycles,
        attachment_type=attachment_type,
        recovery_metric=recovery_metric,
        created_at="2026-08-27T00:00:00+00:00",
    )
    return design


def test_recovery_design_is_self_contained_and_changes_only_template_gradient(
    tmp_path: Path,
) -> None:
    design_root = _design(tmp_path)

    design = verify_modern_synthetic_recovery_design(design_root)

    assert design["status"] == "prospective_no_modern_results"
    assert design["benchmark"]["subjects"] == 9
    assert [arm["template_gradient"] for arm in design["protocol"]["arms"]] == [
        "euclidean",
        "sobolev",
    ]
    assert design["protocol"]["recovery_metric"] == "symmetric_vertex_to_triangle_surface"
    assert (design_root / "inputs" / "benchmark" / "template.vtk").is_file()


def test_recovery_assessment_recomputes_native_surface_metrics(tmp_path: Path) -> None:
    design_root = _design(tmp_path)
    euclidean_run = run_modern_workflow(design_root / "modern-euclidean.yaml")
    sobolev_run = run_modern_workflow(design_root / "modern-sobolev.yaml")

    assessment = assess_modern_synthetic_recovery(
        design_root,
        euclidean_run,
        sobolev_run,
        tmp_path / "assessment",
        created_at="2026-08-27T01:00:00+00:00",
    )
    value = verify_modern_synthetic_recovery_assessment(assessment.parent)

    assert assessment.name == ASSESSMENT_NAME
    assert value["comparison_decision"] == "descriptive_no_predeclared_superiority_gate"
    assert value["recovery_metric"] == "symmetric_vertex_to_triangle_surface"
    assert [arm["arm_id"] for arm in value["arms"]] == ["euclidean", "sobolev"]
    assert all(len(arm["subjects"]) == 9 for arm in value["arms"])
    assert all(
        arm["pooled_reconstruction_error"]["p95_over_template_diagonal"] >= 0.0
        for arm in value["arms"]
    )
    persisted = json.loads(assessment.read_text(encoding="utf-8"))
    assert persisted == value


def test_landmark_recovery_design_binds_correspondence_aware_attachment(
    tmp_path: Path,
) -> None:
    design_root = _design(tmp_path, attachment_type="landmark")

    design = verify_modern_synthetic_recovery_design(design_root)

    assert design["protocol"]["shared_settings"]["attachment_type"] == "landmark"
    assert design["protocol"]["recovery_metric"] == "ordered_vertex"


def test_current_recovery_can_explicitly_preserve_legacy_ordered_metric(
    tmp_path: Path,
) -> None:
    design_root = _design(tmp_path, recovery_metric="ordered_vertex")

    design = verify_modern_synthetic_recovery_design(design_root)

    assert design["protocol"]["recovery_metric"] == "ordered_vertex"
    assert set(design["protocol"]["predeclared_arm_gates"]) == {
        "require_verified_workflow",
        "require_optimizer_convergence",
        "minimum_pooled_vertex_error_reduction_fraction",
        "maximum_pooled_reconstruction_p95_over_template_diagonal",
        "maximum_generating_template_p95_over_template_diagonal",
    }
