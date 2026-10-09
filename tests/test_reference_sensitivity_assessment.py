from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import diffeoforge.reference_sensitivity_assessment as sensitivity_module
from diffeoforge.cli import main
from diffeoforge.mesh import read_vtk_polydata, sha256_file, write_vtk_polydata
from diffeoforge.reference_sensitivity_assessment import (
    ReferenceSensitivityAssessmentError,
    verify_reference_sensitivity_assessment,
    write_reference_sensitivity_assessment,
)

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "examples" / "synthetic" / "meshes" / "template.vtk"


def _fake_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, winner: str = "center"):
    study = tmp_path / "validation-study"
    report_directory = study / "report"
    report_directory.mkdir(parents=True)
    for relative, content in (
        ("validation-study.json", "{}\n"),
        ("events.jsonl", '{"event":"study_created"}\n'),
        ("report/validation-report.json", "{}\n"),
    ):
        (study / relative).write_text(content, encoding="utf-8")

    finalists = (
        SimpleNamespace(finalist_id="local", values={"attachment_kernel_width": 0.8}),
        SimpleNamespace(finalist_id="center", values={"attachment_kernel_width": 1.0}),
        SimpleNamespace(finalist_id="global", values={"attachment_kernel_width": 1.2}),
    )
    labels = tuple(f"subject-{index:02d}.vtk" for index in range(6))
    base = np.asarray(
        [
            [
                (index + 0.2, index**2 * 0.1 + 0.3, index * 0.4 - 0.2),
                (index * 0.3 + 0.1, -index * 0.2, index**2 * 0.05 + 0.4),
            ]
            for index in range(6)
        ],
        dtype=np.float64,
    )
    source_mesh = read_vtk_polydata(TEMPLATE)
    inputs_by_run = {}
    runs = []
    shifts = {"local": -0.001, "center": 0.0, "global": 0.001}
    scales = {"local": 0.99, "center": 1.0, "global": 1.01}
    residuals = tuple((label, 0.1 + index * 0.02) for index, label in enumerate(labels))
    for finalist in finalists:
        run_id = f"training-confirmation--{finalist.finalist_id}"
        run_directory = study / "runs" / run_id
        output = run_directory / "output"
        output.mkdir(parents=True)
        for name in ("manifest.json", "result.json", "output-inventory.json"):
            (run_directory / name).write_text(f'{{"run":"{run_id}"}}\n', encoding="utf-8")
        atlas = output / "estimated-template.vtk"
        shift = shifts[finalist.finalist_id]
        write_vtk_polydata(
            atlas,
            tuple((x + shift, y, z) for x, y, z in source_mesh.vertices),
            source_mesh.triangles,
        )
        controls = output / "control-points.txt"
        controls.write_text("0 0 0\n1 0 0\n", encoding="ascii")
        momenta = output / "momenta.txt"
        momenta.write_text(finalist.finalist_id + "\n", encoding="ascii")
        atlas_record = {
            "path": "estimated-template.vtk",
            "bytes": atlas.stat().st_size,
            "sha256": sha256_file(atlas),
        }
        fake_inputs = SimpleNamespace(
            run_directory=run_directory.resolve(),
            run_report=SimpleNamespace(inventory=(atlas_record,)),
            subject_labels=labels,
            momenta=base * scales[finalist.finalist_id],
            momenta_record={"sha256": sha256_file(momenta)},
            control_points_record={"sha256": sha256_file(controls)},
        )
        inputs_by_run[run_directory.resolve()] = fake_inputs
        runs.append(
            SimpleNamespace(
                run_id=run_id,
                finalist_id=finalist.finalist_id,
                cohort_id="training-confirmation",
                status="completed",
                run_directory=run_directory.resolve(),
                evidence=SimpleNamespace(
                    atlas_path=str(atlas.resolve()),
                    subject_residual_p95=residuals,
                ),
            )
        )
    assessment = SimpleNamespace(
        status="robust_within_search_space",
        recommended_finalist_id=winner,
        practical_error_margin=0.1,
        practical_error_margin_basis="test geometric margin",
    )
    snapshot = SimpleNamespace(
        study_directory=study.resolve(),
        study_id="reference-validation-test",
        status="completed",
        report_json_path=(study / "report" / "validation-report.json").resolve(),
        assessment=assessment,
        runs=tuple(runs),
        plan=SimpleNamespace(
            finalists=finalists,
            fingerprint="a" * 64,
            training_subjects=labels,
            template_diagonal=10.0,
        ),
    )
    monkeypatch.setattr(
        sensitivity_module,
        "load_reference_validation_study",
        lambda path: snapshot,
    )
    monkeypatch.setattr(
        sensitivity_module,
        "load_reference_momenta",
        lambda path: inputs_by_run[Path(path).resolve()],
    )
    return snapshot


def test_sensitivity_assessment_recomputes_all_existing_training_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _fake_study(tmp_path, monkeypatch)

    artifact = write_reference_sensitivity_assessment(
        snapshot.study_directory,
        tmp_path / "assessment",
        created_at="2026-08-30T10:00:00+00:00",
    )

    report = artifact.manifest
    assert report["status"] == "stable_within_tested_neighborhood"
    assert report["gates"] == {
        "templates_stable": True,
        "high_residual_subjects_stable": True,
        "pca_structure_stable": True,
        "robust_parent_parameter_preference": True,
        "preferred_parameter_at_tested_boundary": False,
    }
    assert len(report["pairwise_comparisons"]) == 3
    assert all(
        item["pca_structure"]["score_linear_cka"] == pytest.approx(1.0)
        for item in report["pairwise_comparisons"]
    )
    assert verify_reference_sensitivity_assessment(artifact.artifact_directory) == artifact


def test_sensitivity_assessment_flags_a_preferred_width_at_search_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _fake_study(tmp_path, monkeypatch, winner="local")

    artifact = write_reference_sensitivity_assessment(
        snapshot.study_directory,
        tmp_path / "boundary-assessment",
        created_at="2026-08-30T10:00:00+00:00",
    )

    assert artifact.manifest["status"] == "search_boundary_reached"
    assert artifact.manifest["search_boundary"]["at_tested_boundary"] is True
    assert artifact.manifest["search_boundary"]["parameters"][0]["location"] == "minimum"
    assert "extend" in artifact.manifest["next_step"].lower()


def test_sensitivity_assessment_rejects_changed_rendered_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _fake_study(tmp_path, monkeypatch)
    artifact = write_reference_sensitivity_assessment(
        snapshot.study_directory,
        tmp_path / "assessment",
        created_at="2026-08-30T10:00:00+00:00",
    )
    html_path = artifact.artifact_directory / "sensitivity-assessment.html"
    html_path.write_text(html_path.read_text(encoding="utf-8") + "changed", encoding="utf-8")

    with pytest.raises(ReferenceSensitivityAssessmentError, match="HTML differs"):
        verify_reference_sensitivity_assessment(artifact.artifact_directory)


def test_sensitivity_assessment_cli_never_starts_an_atlas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _fake_study(tmp_path, monkeypatch)
    destination = tmp_path / "cli-assessment"

    assert (
        main(
            [
                "reference-sensitivity-assess",
                str(snapshot.study_directory),
                "--output",
                str(destination),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "No atlas process was started" in output
    assert "stable_within_tested_neighborhood" in output

    assert main(["reference-sensitivity-verify", str(destination)]) == 0
    assert "exactly recomputed" in capsys.readouterr().out
