from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import diffeoforge.atlas_comparison as comparison_module
from diffeoforge.analysis.pca import principal_component_analysis
from diffeoforge.atlas_comparison import (
    AtlasComparisonError,
    verify_atlas_comparison,
    write_atlas_comparison,
)
from diffeoforge.cli import main
from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "examples" / "synthetic" / "meshes" / "template.vtk"


def _sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    labels = tuple(f"subject-{index:02d}.vtk" for index in range(6))
    features = np.asarray(
        [(index, index**2 * 0.1, (-1) ** index * 0.2) for index in range(6)],
        dtype=np.float64,
    )
    pcas = {
        "first": principal_component_analysis(
            features,
            feature_space="momenta:test",
            sample_labels=labels,
        ),
        "second": principal_component_analysis(
            features * 1.02,
            feature_space="momenta:test",
            sample_labels=labels,
        ),
    }
    mesh = read_vtk_polydata(TEMPLATE)
    reviews = {}
    atlas_by_run = {}
    for source_index, name in enumerate(("first", "second")):
        run = (tmp_path / name).resolve()
        bundle = run / "bundle"
        bundle.mkdir(parents=True)
        atlas = run / "atlas.vtk"
        write_vtk_polydata(
            atlas,
            tuple(
                (x + source_index * 0.002, y, z)
                for x, y, z in mesh.vertices
            ),
            mesh.triangles,
        )
        reviews[run] = SimpleNamespace(
            run_directory=run,
            project_name=name,
            engine_route="modern" if name == "first" else "deformetrica_reference",
            workflow_manifest_path=run / "workflow.json",
            workflow_manifest_sha256=("a" if name == "first" else "b") * 64,
            bundle_directory=bundle,
            bundle_manifest_path=bundle / "manifest.json",
            bundle_manifest_sha256=("c" if name == "first" else "d") * 64,
            optimizer_converged=True,
            optimizer_termination_reason="criterion_met",
            optimizer_cycles_completed=12,
            optimizer_max_cycles=50,
            execution_duration_seconds=100.0 + source_index,
            registration_qc=tuple(
                SimpleNamespace(
                    subject_name=label,
                    residual_p95=0.1 + index * 0.01 + source_index * 0.002,
                )
                for index, label in enumerate(labels)
            ),
        )
        atlas_by_run[run] = atlas

    monkeypatch.setattr(
        comparison_module,
        "_review",
        lambda path: reviews[Path(path).resolve()],
    )
    monkeypatch.setattr(
        comparison_module,
        "_pca",
        lambda review: pcas[review.project_name],
    )
    monkeypatch.setattr(
        comparison_module,
        "verify_result_artifact",
        lambda review, key: atlas_by_run[review.run_directory],
    )
    return reviews


def test_atlas_comparison_reports_templates_residuals_outliers_and_pca(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviews = _sources(tmp_path, monkeypatch)
    destination = tmp_path / "comparison"

    write_atlas_comparison(
        tmp_path / "first",
        tmp_path / "second",
        destination,
        first_label="Modern Sobolev",
        second_label="Deformetrica more-local",
        created_at="2026-08-30T14:00:00+00:00",
    )
    report = verify_atlas_comparison(destination)

    assert report["estimated_template_distance"]["available"] is True
    assert report["estimated_template_distance"]["ordered_vertex_p95"] == pytest.approx(
        0.002
    )
    assert report["registration_residuals"]["paired"]["subject_count"] == 6
    assert report["high_residual_subject_overlap"]["jaccard"] == pytest.approx(1.0)
    assert report["pca_stability"]["score_linear_cka"] == pytest.approx(1.0)
    assert "does not select" in report["scientific_boundary"]
    assert set(report["sources"]) == {"first", "second"}
    assert len(reviews) == 2


def test_atlas_comparison_rejects_changed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sources(tmp_path, monkeypatch)
    destination = tmp_path / "comparison"
    write_atlas_comparison(tmp_path / "first", tmp_path / "second", destination)
    html_path = destination / "atlas-comparison.html"
    html_path.write_text(html_path.read_text(encoding="utf-8") + "changed", encoding="utf-8")

    with pytest.raises(AtlasComparisonError, match="artifact changed"):
        verify_atlas_comparison(destination)


def test_atlas_comparison_cli_makes_no_automatic_winner_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _sources(tmp_path, monkeypatch)
    destination = tmp_path / "cli-comparison"

    assert (
        main(
            [
                "atlas-compare",
                str(tmp_path / "first"),
                str(tmp_path / "second"),
                "--output",
                str(destination),
                "--first-label",
                "Sobolev",
                "--second-label",
                "Euclidean",
            ]
        )
        == 0
    )
    assert "No automatic winner was selected" in capsys.readouterr().out
    assert main(["atlas-compare-verify", str(destination)]) == 0
    assert "exactly recomputed" in capsys.readouterr().out
