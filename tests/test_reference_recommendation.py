from pathlib import Path

import pytest

from diffeoforge.reference_recommendation import recommend_reference_parameters

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _cohort() -> tuple[Path, ...]:
    return (
        MESH_DIRECTORY / "template.vtk",
        *sorted(MESH_DIRECTORY.glob("subject-*.vtk")),
    )


def test_data_assisted_reference_recommendation_is_deterministic() -> None:
    first = recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="fine",
        deformation_scale_intent="local",
    )
    second = recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="fine",
        deformation_scale_intent="local",
    )

    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.mesh_count == 6
    assert first.subject_count == 5
    assert first.template_filename == "template.vtk"
    assert first.template_diagonal > 0
    assert first.cohort_median_diagonal > 0
    assert first.median_edge_to_diagonal_ratio > 0
    assert first.attachment_kernel_width_ratio >= first.sampling_floor_ratio
    assert first.deformation_kernel_width_ratio == pytest.approx(0.05)
    assert first.control_point_spacing_ratio == pytest.approx(0.05)
    assert first.provisional_noise_std_ratio == pytest.approx(
        first.attachment_kernel_width_ratio * 0.25
    )
    assert first.parameter_ratios["noise_std"] == pytest.approx(
        first.provisional_noise_std_ratio
    )
    assert first.effective_values["attachment_kernel_width"] == pytest.approx(
        first.attachment_kernel_width_ratio * first.template_diagonal
    )
    assert first.provenance["fingerprint"] == first.fingerprint
    assert first.provenance["parameter_ratios"] == first.parameter_ratios
    assert first.provenance["alignment_basis"] == "declared_gpa"
    assert "cannot prove homologous alignment" in " ".join(first.warnings)


def test_user_intent_changes_only_the_corresponding_nominal_scales() -> None:
    fine_local = recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="fine",
        deformation_scale_intent="local",
    )
    coarse_global = recommend_reference_parameters(
        _cohort(),
        alignment_basis="declared_gpa",
        surface_detail_intent="coarse",
        deformation_scale_intent="global",
    )

    assert coarse_global.attachment_kernel_width_ratio >= (
        fine_local.attachment_kernel_width_ratio
    )
    assert coarse_global.deformation_kernel_width_ratio == pytest.approx(0.20)
    assert coarse_global.control_point_spacing_ratio == pytest.approx(0.20)
    assert coarse_global.fingerprint != fine_local.fingerprint


def test_diffeoforge_gpa_requires_bound_transforms() -> None:
    with pytest.raises(
        ValueError,
        match="requires transforms and an alignment fingerprint",
    ):
        recommend_reference_parameters(
            _cohort(),
            alignment_basis="diffeoforge_gpa",
            surface_detail_intent="balanced",
            deformation_scale_intent="balanced",
        )
