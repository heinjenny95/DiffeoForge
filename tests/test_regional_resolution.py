from copy import deepcopy
from types import SimpleNamespace

import pytest

from diffeoforge.regional_resolution import response


def fixture():
    marks = [
        dict(
            version="surface-box-v1",
            source_sha256="f" * 64,
            shape="box",
            bounds=[0.0, 1.0, 0.0, 1.0, float(i), float(i + 1)],
            center=[0.5, 0.5, i + 0.5],
            radius=1.0,
            purpose="problem",
            symptom="detail",
            space="original_mesh_coordinates",
        )
        for i in range(3)
    ]
    measured = []
    for mark, distance in zip(marks, [0.10, 0.016, 0.013], strict=True):
        region = {k: v for k, v in mark.items() if k != "space"}
        measured.append(
            dict(
                region=region,
                selected_faces=50,
                repeats=[
                    dict(original_to_fit_p95=distance),
                    dict(original_to_fit_p95=distance * 0.99),
                ],
            )
        )
    quality = dict(
        marked_regions=deepcopy(marks),
        numerical_selection_suitable=True,
        local_improved=True,
        outside_preserved=True,
        shape_preserved=True,
        transition_preserved=True,
        no_new_intersection_flags=True,
        spatial_resolution_sufficient=True,
        temporal_grid_stable=True,
    )
    metrics = dict(
        maximum_iterations=600,
        attachment_comparison=dict(
            subjects={
                "sample.vtk": dict(
                    regional_quality=quality, marked_regions=dict(measurements=measured)
                )
            }
        ),
    )
    current = SimpleNamespace(candidate_id="trial", metrics=metrics)
    data = dict(
        current=current,
        regions=marks,
        current_reference=dict(target="sample.vtk", values=dict(deformation_kernel_width=0.36)),
        context=dict(feedback={"trial": dict(feedback=dict(outcome="better"))}),
    )
    info = dict(strategy=dict(regional_recipe=dict(focus_width=0.06)))
    return data, info, dict(regional_continuation=dict(verified=True))


def test_remaining_area_is_not_hidden_by_improved_large_areas():
    data, info, numerical = fixture()
    old = deepcopy(data["regions"])
    result = response(data, info, numerical, "detail")
    assert result["worst_original_to_fit_p95"] == 0.10
    assert result["next_focus_width"] == 0.06  # Reach the still-missing surface first.
    assert result["next_movement_width"] == 0.18
    assert result["current_broad_field_retained"] is True
    assert result["anatomical_approval"] is False
    assert data["regions"] == old


def test_reached_surface_can_test_finer_detail_capture():
    data, info, numerical = fixture()
    rows = data["current"].metrics["attachment_comparison"]["subjects"]["sample.vtk"][
        "marked_regions"
    ]["measurements"]
    for row in rows:
        row["repeats"] = [dict(original_to_fit_p95=0.02), dict(original_to_fit_p95=0.019)]
    result = response(data, info, numerical, None)
    assert result["next_focus_width"] == pytest.approx(0.042)
    assert result["next_movement_width"] == 0.18


@pytest.mark.parametrize(
    "symptom", ["gap", "position", "thickness", "curvature", "topology", "unsure"]
)
def test_other_explanations_keep_their_existing_routes(symptom):
    assert response(*fixture(), symptom) is None


@pytest.mark.parametrize("local_reason", ["gap", "position", "thickness", "curvature"])
def test_specific_area_reason_is_respected_in_a_mixed_detail_review(local_reason):
    data, info, numerical = fixture()
    data["regions"][1]["symptom"] = local_reason
    assert response(data, info, numerical, "detail") is None


@pytest.mark.parametrize("cap", [120, 200, True])
def test_short_or_invalid_allowance_does_not_trigger_new_basis(cap):
    data, info, numerical = fixture()
    data["current"].metrics["maximum_iterations"] = cap
    assert response(data, info, numerical, "detail") is None


@pytest.mark.parametrize(
    "key",
    [
        "numerical_selection_suitable",
        "outside_preserved",
        "shape_preserved",
        "transition_preserved",
        "no_new_intersection_flags",
        "spatial_resolution_sufficient",
        "temporal_grid_stable",
        "local_improved",
    ],
)
def test_incomplete_or_unsafe_quality_never_selects_new_basis(key):
    data, info, numerical = fixture()
    data["current"].metrics["attachment_comparison"]["subjects"]["sample.vtk"]["regional_quality"][
        key
    ] = False
    assert response(data, info, numerical, "missing") is None


def test_untrusted_or_mismatched_measurements_keep_existing_route():
    data, info, numerical = fixture()
    assert response(data, info, None, "detail") is None
    rows = data["current"].metrics["attachment_comparison"]["subjects"]["sample.vtk"][
        "marked_regions"
    ]["measurements"]
    rows[0]["region"]["source_sha256"] = "0" * 64
    assert response(data, info, numerical, "detail") is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True])
def test_bad_distance_is_unknown_instead_of_a_finer_recommendation(bad):
    data, info, numerical = fixture()
    rows = data["current"].metrics["attachment_comparison"]["subjects"]["sample.vtk"][
        "marked_regions"
    ]["measurements"]
    rows[0]["repeats"][0]["original_to_fit_p95"] = bad
    assert response(data, info, numerical, "detail") is None
