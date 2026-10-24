from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from diffeoforge.analysis.alignment_scaling_sensitivity import (  # noqa: E402
    ASSESSED_MODES,
    alignment_scaling_sensitivity_csv_rows,
    build_alignment_scaling_sensitivity,
)
from diffeoforge.analysis.mesh_scaling import (  # noqa: E402
    MeshScaleMetrics,
    MeshScalingMode,
)


def _metric(vertex_size: float, surface_size: float) -> MeshScaleMetrics:
    return MeshScaleMetrics(
        vertex_centroid_size=vertex_size,
        area_weighted_rms_radius=surface_size,
        surface_area=surface_size**2,
        area_weighted_centroid=(0.0, 0.0, 0.0),
    )


def test_scaling_sensitivity_compares_all_modes_without_claiming_atlas_robustness() -> None:
    report = build_alignment_scaling_sensitivity(
        ("a.vtk", "b.vtk"),
        (100, 200),
        (_metric(10.0, 2.0), _metric(20.0, 4.0)),
        (5.0, 20.0),
        selected_mode=MeshScalingMode.PAMS_AREA_WEIGHTED,
        target_size=1.0,
    )

    assert report["computed_without_atlas_reruns"] is True
    assert "does not establish" in str(report["interpretation_scope"])
    assert len(report["modes"]) == len(ASSESSED_MODES)
    assert report["warnings"]
    rows = alignment_scaling_sensitivity_csv_rows(report)
    assert rows[0][0] == "filename"
    assert rows[1][0] == "a.vtk"
    assert len(rows) == 3


def test_scaling_sensitivity_rejects_mismatched_cohort_lengths() -> None:
    with pytest.raises(ValueError, match="same mesh cohort"):
        build_alignment_scaling_sensitivity(
            ("a.vtk", "b.vtk"),
            (100,),
            (_metric(10.0, 2.0),),
            (5.0,),
            selected_mode=MeshScalingMode.PRESERVE_SIZE,
            target_size=1.0,
        )
