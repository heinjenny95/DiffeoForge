import json
from dataclasses import replace

import numpy as np
import pytest

from diffeoforge.analysis.atlas_group_anatomy import compare_group_anatomy
from diffeoforge.desktop.result_review import (
    ModernResultArtifact,
    ModernResultReview,
    RegistrationQCItem,
)
from diffeoforge.mesh import sha256_file, write_vtk_polydata

_VERTICES = ((0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2))
_FACES = ((0, 1, 2), (0, 3, 1))
_REFERENCE = ("reference-a", "reference-b")
_COMPARISON = ("comparison-a", "comparison-b")


def _review(run, *, amplitude, vertex=0, faces=_FACES, title="Common template"):
    staged = run / "input" / "template" / "template.vtk"
    staged.parent.mkdir(parents=True)
    write_vtk_polydata(staged, _VERTICES, _FACES, title=title)
    manifest = run / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": [
                    {
                        "role": "template",
                        "staged_path": "input/template/template.vtk",
                        "geometry": {"bytes": staged.stat().st_size, "sha256": sha256_file(staged)},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bundle = run / "analysis"
    bundle.mkdir()
    bundle_manifest = bundle / "manifest.json"
    bundle_manifest.write_text("{}", encoding="utf-8")
    artifacts = []
    items = []
    for index, subject in enumerate((*_REFERENCE, *_COMPARISON)):
        points = np.asarray(_VERTICES, dtype=float)
        points[:, 1] += 0.125 if index % 2 else -0.125
        if subject in _COMPARISON:
            points[vertex, 2] += amplitude
        key = f"rec-{subject}"
        mesh = write_vtk_polydata(bundle / f"{key}.vtk", points, faces)
        artifacts.append(
            ModernResultArtifact(
                key,
                subject,
                mesh,
                "vtk",
                mesh.stat().st_size,
                sha256_file(mesh),
                "",
            ),
        )
        items.append(RegistrationQCItem(index + 1, subject, 0, "", key))
    return ModernResultReview(
        run_directory=run,
        bundle_directory=bundle,
        project_name="Synthetic group comparison",
        created_at="",
        workflow_manifest_path=manifest,
        workflow_manifest_sha256=sha256_file(manifest),
        bundle_manifest_path=bundle_manifest,
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        optimizer_converged=None,
        optimizer_termination_reason="",
        optimizer_cycles_completed=0,
        optimizer_max_cycles=0,
        overview=(),
        optimization=(),
        pca=(),
        quality=(),
        artifacts=tuple(artifacts),
        scientific_boundaries=(),
        engine_route="deformetrica_reference",
        registration_qc=tuple(items),
    )


def test_common_ordered_surface_localizes_signed_group_effect(tmp_path):
    first = _review(tmp_path / "first", amplitude=0.25)
    second = _review(tmp_path / "second", amplitude=-0.5)
    result = compare_group_anatomy(first, second, _REFERENCE, _COMPARISON)

    assert result["available"] is True
    assert result["group_counts"] == {"reference": 2, "comparison": 2}
    assert result["basis"]["vertex_count"] == 4
    assert result["basis"]["template_diagonal"] == pytest.approx(np.sqrt(12))
    assert result["effect_rms_fraction"]["first"] == pytest.approx(0.25 / 6)
    assert result["effect_rms_fraction"]["second"] == pytest.approx(0.5 / 6)
    assert result["effect_direction_cosine"] == pytest.approx(-1)
    assert result["top_effect_overlap"]["jaccard"] == 1
    assert result["template_outline"] == np.asarray(_VERTICES).tolist()
    point = result["top_vertices"]["second"][0]
    assert point["index"] == 0
    assert point["coordinate"] == [0, 0, 0]
    assert point["effect_fraction"] == pytest.approx([0, 0, -0.5 / np.sqrt(12)])
    json.dumps(result, allow_nan=False)


def test_disjoint_effect_locations_have_no_top_overlap_or_direction_agreement(tmp_path):
    first = _review(tmp_path / "first", amplitude=0.25)
    second = _review(tmp_path / "second", amplitude=0.25, vertex=2)
    result = compare_group_anatomy(first, second, _REFERENCE, _COMPARISON)

    assert result["available"] is True
    assert result["top_effect_overlap"]["shared_count"] == 0
    assert result["effect_direction_cosine"] == 0


@pytest.mark.parametrize(
    ("options", "reason"),
    (
        ({"title": "Different source identity"}, "different verified staged template bytes"),
        ({"faces": _FACES[::-1]}, "ordered vertex and triangle connectivity"),
    ),
)
def test_comparison_is_unavailable_when_material_evidence_cannot_support_it(
    tmp_path,
    options,
    reason,
):
    first = _review(tmp_path / "first", amplitude=0.25)
    second = _review(tmp_path / "second", **({"amplitude": 0.5} | options))
    result = compare_group_anatomy(first, second, _REFERENCE, _COMPARISON)

    assert result["available"] is False
    assert reason in result["unavailable_reason"]


def test_comparison_rechecks_bound_reconstruction_and_engine_identity(tmp_path):
    first = _review(tmp_path / "first", amplitude=0.25)
    second = _review(tmp_path / "second", amplitude=0.5)
    unsupported = compare_group_anatomy(
        first,
        replace(second, engine_route="modern"),
        _REFERENCE,
        _COMPARISON,
    )
    assert unsupported["available"] is False
    second.artifacts[0].path.write_bytes(b"Different reconstruction")
    changed = compare_group_anatomy(first, second, _REFERENCE, _COMPARISON)
    assert changed["available"] is False
    assert "changed" in changed["unavailable_reason"]


def test_present_group_effect_can_be_compared_with_no_detected_effect(tmp_path):
    first = _review(tmp_path / "first", amplitude=0.25)
    second = _review(tmp_path / "second", amplitude=0)
    result = compare_group_anatomy(first, second, _REFERENCE, _COMPARISON)
    assert result["available"] is True
    assert result["effect_rms_fraction"]["first"] > 0
    assert result["effect_rms_fraction"]["second"] == 0
    assert result["effect_direction_cosine"] is None
    assert result["top_effect_overlap"]["jaccard"] is None
    assert result["top_vertices"]["first"]
    assert not result["top_vertices"]["second"]
