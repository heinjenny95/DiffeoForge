from __future__ import annotations

import csv
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from diffeoforge.cli import main
from diffeoforge.desktop.reference_result_review import (
    export_registration_qc_review,
    load_registration_qc_draft,
    review_reference_result,
    save_registration_qc_draft,
)
from diffeoforge.desktop.result_review import ModernResultReviewError, verify_result_artifact
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.mesh_quality import MeshQualitySettings
from diffeoforge.modern_reference_qualification import (
    ASSESSMENT_HTML_NAME,
    ASSESSMENT_JSON_NAME,
    ASSESSMENT_SIDECAR_NAME,
    CONFIG_NAME,
    ModernReferenceQualificationError,
    _render_assessment_html,
    _screen_subject_candidates,
    assess_modern_reference_qualification,
    create_modern_reference_qualification,
    create_modern_reference_qualification_continuation,
    verify_modern_reference_qualification_assessment,
    verify_modern_reference_qualification_design,
)
from diffeoforge.modern_workflow import run_modern_workflow
from diffeoforge.reference_pca import (
    REFERENCE_PCA_MANIFEST,
    REFERENCE_PCA_SIDECAR,
    ReferencePCAError,
    load_reference_momenta,
    read_deformetrica_control_points,
    read_deformetrica_momenta,
    verify_reference_pca_bundle,
    write_reference_pca_bundle,
)
from diffeoforge.runs import prepare_run


def _completed_reference_run(tmp_path: Path) -> Path:
    example = Path(__file__).parents[1] / "examples" / "minimal-atlas.yaml"
    run = prepare_run(example, run_id="reference-pca-test", output_directory=tmp_path)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    subjects = [record for record in manifest["inputs"] if record["role"] == "subject"]
    output = run / "output"
    momenta_path = output / "DeterministicAtlas__EstimatedParameters__Momenta.txt"
    momenta_rows = []
    for subject_index in range(len(subjects)):
        for point_index in range(2):
            momenta_rows.append(
                (
                    0.25 + subject_index + point_index * 0.1,
                    -0.5 + subject_index**2 * 0.2 - point_index * 0.05,
                    subject_index * 0.4 + point_index**2 * 0.3,
                )
            )
    momenta_path.write_text(
        f"{len(subjects)} 2 3\n\n"
        + "\n".join(" ".join(format(value, ".17g") for value in row) for row in momenta_rows)
        + "\n",
        encoding="utf-8",
    )
    controls_path = output / "DeterministicAtlas__EstimatedParameters__ControlPoints.txt"
    controls_path.write_text("0 0 0\n1 0.5 -0.25\n", encoding="utf-8")
    surface_source = (
        Path(__file__).parents[1] / "examples" / "synthetic" / "meshes" / "template.vtk"
    )
    atlas_path = output / "DeterministicAtlas__EstimatedParameters__Template_surface.vtk"
    shutil.copyfile(surface_source, atlas_path)
    reconstruction_paths = []
    for subject in subjects:
        subject_name = Path(subject["staged_path"]).name
        reconstruction_path = (
            output
            / f"DeterministicAtlas__Reconstruction__surface__subject_{subject_name}.vtk"
        )
        shutil.copyfile(surface_source, reconstruction_path)
        reconstruction_paths.append(reconstruction_path)
    records = [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in (
            atlas_path,
            controls_path,
            momenta_path,
            *reconstruction_paths,
        )
    ]
    inventory_path = run / "output-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "inventory_version": "0.1",
                "created_at": "2026-07-19T08:01:00Z",
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "logs" / "convergence.csv").write_text(
        "iteration,log_likelihood,attachment,regularity\n"
        "0,-10,-9.5,-0.5\n"
        "1,-8,-7.4,-0.6\n",
        encoding="utf-8",
    )
    (run / "logs" / "deformetrica.log").write_text(
        "Iteration 0\n"
        "Log-likelihood = -10 [attachment = -9.5 ; regularity = -0.5]\n"
        "Iteration 1\n"
        "Log-likelihood = -8 [attachment = -7.4 ; regularity = -0.6]\n"
        "Tolerance threshold met. Stopping the optimization process.\n",
        encoding="utf-8",
    )
    result = {
        "result_version": "0.1",
        "run_id": "reference-pca-test",
        "status": "completed",
        "started_at": "2026-07-19T08:00:00Z",
        "ended_at": "2026-07-19T08:01:00Z",
        "duration_seconds": 60.0,
        "return_code": 0,
        "execution_error": None,
        "convergence_rows": 2,
        "outputs": {
            "file_count": len(records),
            "total_bytes": sum(record["bytes"] for record in records),
            "inventory_path": "output-inventory.json",
            "inventory_sha256": sha256_file(inventory_path),
        },
        "backend_environment": {"packages": {"deformetrica": "4.3.0"}},
        "command": {"argv": ["deformetrica", "estimate"], "environment": {}},
    }
    (run / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    with (run / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": result["started_at"], "event": "started"}) + "\n")
        handle.write(
            json.dumps(
                {
                    "timestamp": result["ended_at"],
                    "event": "completed",
                    "return_code": 0,
                    "duration_seconds": 60.0,
                }
            )
            + "\n"
        )
    return run


def test_strict_momenta_reader_preserves_deformetrica_block_order(tmp_path: Path) -> None:
    source = tmp_path / "momenta.txt"
    source.write_text(
        "2 2 3\n\n1 2 3\n4 5 6\n\n7 8 9\n10 11 12\n",
        encoding="utf-8",
    )

    observed = read_deformetrica_momenta(source)

    assert observed.shape == (2, 2, 3)
    assert observed.dtype == np.float64
    assert observed.tolist() == [
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        [[7.0, 8.0, 9.0], [10.0, 11.0, 12.0]],
    ]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("2 1\n1 2 3\n2 3 4\n", "header"),
        ("1 1 3\n1 2 3\n", "at least two"),
        ("2 1 2\n1 2\n3 4\n", "three-dimensional"),
        ("2 1 3\n1 2 3\n", "declares 2 rows"),
        ("2 1 3\n1 2 3\n4 5 6\n7 8 9\n", "extra numeric row"),
        ("2 1 3\n1 nan 3\n4 5 6\n", "non-finite"),
    ],
)
def test_strict_momenta_reader_rejects_ambiguous_or_invalid_data(
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    source = tmp_path / "momenta.txt"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(ReferencePCAError, match=message):
        read_deformetrica_momenta(source)


def test_control_points_must_match_momenta_count(tmp_path: Path) -> None:
    source = tmp_path / "controls.txt"
    source.write_text("0 0 0\n", encoding="utf-8")

    with pytest.raises(ReferencePCAError, match="declares 2 control points"):
        read_deformetrica_control_points(source, expected_count=2)


def test_reference_pca_bundle_is_source_bound_recomputed_and_nonreplacing(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)

    bundle_path = write_reference_pca_bundle(
        run,
        created_at="2026-07-19T09:00:00+00:00",
    )
    bundle = verify_reference_pca_bundle(bundle_path, source_run=run)

    source = load_reference_momenta(run)
    assert bundle.pca.sample_labels == source.subject_labels
    assert bundle.pca.number_of_components == len(source.subject_labels) - 1
    assert bundle.manifest["inputs"]["feature_order"].endswith("Cartesian x, y, z inner")
    assert (bundle_path / "analysis" / "pca-scree.svg").is_file()
    assert (bundle_path / "analysis" / "pca-scores.svg").is_file()
    assert (bundle_path / "analysis" / "deformetrica-convergence.svg").is_file()
    assert (bundle_path / "parameters" / "momenta.csv").is_file()
    assert bundle.manifest["bundle_version"] == "0.2"
    assert bundle.manifest["optimization"]["reported_stop_signal"] == "tolerance_threshold"

    with pytest.raises(FileExistsError, match="already exists"):
        write_reference_pca_bundle(run)


def test_reference_pca_rejects_source_output_tampering(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)
    inputs = load_reference_momenta(run)
    inputs.momenta_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ReferencePCAError, match="Source run evidence failed"):
        load_reference_momenta(run)


def test_reference_pca_rejects_bundle_artifact_tampering(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)
    bundle = write_reference_pca_bundle(run)
    (bundle / "analysis" / "pca-scores.csv").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ReferencePCAError, match="artifact (size|SHA-256) differs"):
        verify_reference_pca_bundle(bundle)


def test_reference_pca_recomputes_internally_consistent_tables(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)
    bundle = write_reference_pca_bundle(run)
    scores_path = bundle / "analysis" / "pca-scores.csv"
    with scores_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[1][1] = format(float(rows[1][1]) + 1.0, ".17g")
    with scores_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    manifest_path = bundle / REFERENCE_PCA_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(
        item for item in manifest["artifacts"] if item["path"] == "analysis/pca-scores.csv"
    )
    record["bytes"] = scores_path.stat().st_size
    record["sha256"] = sha256_file(scores_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle / REFERENCE_PCA_SIDECAR).write_text(
        sha256_file(manifest_path) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ReferencePCAError, match="PCA scores values differ"):
        verify_reference_pca_bundle(bundle)


def test_reference_pca_regenerates_convergence_plot_during_verification(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)
    bundle = write_reference_pca_bundle(run)
    plot_path = bundle / "analysis" / "deformetrica-convergence.svg"
    plot_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>\n", encoding="utf-8")
    manifest_path = bundle / REFERENCE_PCA_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(
        item
        for item in manifest["artifacts"]
        if item["path"] == "analysis/deformetrica-convergence.svg"
    )
    record["bytes"] = plot_path.stat().st_size
    record["sha256"] = sha256_file(plot_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle / REFERENCE_PCA_SIDECAR).write_text(
        sha256_file(manifest_path) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ReferencePCAError, match="differs from deterministic regeneration"):
        verify_reference_pca_bundle(bundle)


def test_desktop_reference_review_creates_and_exposes_verified_pca(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)

    review = review_reference_result(run)

    assert review.engine_route == "deformetrica_reference"
    assert review.optimizer_converged is None
    assert review.project_name == "minimal-example"
    assert {artifact.key for artifact in review.artifacts} >= {
        "estimated-template",
        "reference-momenta",
        "reference-control-points",
        "pca-summary",
        "pca-scores",
        "pca-scree",
        "pca-score-plot",
        "optimizer-convergence-plot",
        "reference-convergence",
        "subject-reconstruction-1",
    }
    assert verify_result_artifact(review, "pca-score-plot").is_file()
    assert verify_result_artifact(review, "estimated-template").is_file()
    assert review.execution_duration_seconds == 60.0
    assert review.optimizer_termination_reason == "tolerance_threshold"
    assert len(review.registration_qc) == 5
    assert [item.residual_p95 for item in review.registration_qc] == sorted(
        (item.residual_p95 for item in review.registration_qc),
        reverse=True,
    )
    first_qc = review.registration_qc[0]
    assert verify_result_artifact(review, first_qc.original_artifact_key).is_file()
    assert verify_result_artifact(review, first_qc.reconstruction_artifact_key).is_file()


def test_registration_qc_review_export_is_explicit_and_non_overwriting(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    first_subject = review.registration_qc[0].subject_name

    first = export_registration_qc_review(review, {first_subject: "uncertain"})
    second = export_registration_qc_review(review, {first_subject: "pass"})
    payload = json.loads(first.path.read_text(encoding="utf-8"))

    assert first.path != second.path
    assert first.path.is_file()
    assert first.sha256_path.is_file()
    assert first.sha256 == sha256_file(first.path)
    assert payload["summary"] == {
        "reviewed_count": 1,
        "subject_count": 5,
        "unreviewed_count": 4,
    }
    assert payload["subjects"][0]["decision"] == "uncertain"
    assert "not an automatic biological exclusion" in payload["scientific_boundary"]


def test_registration_qc_draft_round_trips_and_is_bound_to_verified_source(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    first_subject = review.registration_qc[0].subject_name

    draft = save_registration_qc_draft(review, {first_subject: "pass"})

    assert draft.name == "registration-qc-draft.json"
    assert load_registration_qc_draft(review) == {first_subject: "pass"}

    payload = json.loads(draft.read_text(encoding="utf-8"))
    payload["source"]["analysis_manifest_sha256"] = "0" * 64
    draft.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModernResultReviewError, match="different verified run"):
        load_registration_qc_draft(review)


def test_modern_reference_qualification_design_is_prospective_and_tamper_evident(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path / "reference")

    destination = create_modern_reference_qualification(
        run,
        tmp_path / "qualification-design",
        subject_count=3,
        max_cycles=1,
        threads=1,
        tile_size=32,
        created_at="2026-08-22T00:00:00+00:00",
    )
    design = verify_modern_reference_qualification_design(destination)
    config = yaml.safe_load((destination / CONFIG_NAME).read_text(encoding="utf-8"))

    assert design["status"] == "prospective_no_modern_results"
    assert len(design["subjects"]) == 3
    assert design["protocol"]["modern_result_existed_at_freeze"] is False
    assert design["design_version"] == "0.2"
    assert design["protocol"]["quality_screening"]["excluded_candidates"] == []
    assert all("source_quality" in record for record in design["subjects"])
    assert config["optimization"]["block_order"] == ["momenta"]
    assert config["initialization"]["control_points"]["method"] == "file"
    assert config["runtime"]["pairwise_evaluation"]["autograd_strategy"] == "recompute"
    assert config["runtime"]["pairwise_evaluation"]["query_tile_size"] == 32
    assert config["runtime"]["pairwise_evaluation"]["source_tile_size"] == 32

    modern_run = run_modern_workflow(
        destination / CONFIG_NAME,
        destination=tmp_path / "modern-run",
        created_at="2026-08-22T01:00:00+00:00",
    )
    assessment_path = assess_modern_reference_qualification(
        destination,
        modern_run,
        tmp_path / "assessment",
        created_at="2026-08-22T02:00:00+00:00",
    )
    assessment = json.loads(
        (assessment_path / ASSESSMENT_JSON_NAME).read_text(encoding="utf-8")
    )
    assert verify_modern_reference_qualification_assessment(assessment_path) == assessment
    assert (
        main(
            [
                "modern-reference-qualification-assessment-verify",
                str(assessment_path),
            ]
        )
        == 0
    )
    assessment_html = assessment_path / ASSESSMENT_HTML_NAME
    original_assessment_html = assessment_html.read_text(encoding="utf-8")
    assessment_html.write_text("tampered", encoding="utf-8")
    with pytest.raises(ModernReferenceQualificationError, match="HTML differs"):
        verify_modern_reference_qualification_assessment(assessment_path)
    assessment_html.write_text(original_assessment_html, encoding="utf-8", newline="\n")

    assert assessment["decision"]["status"] in {
        "pass",
        "fail",
        "inconclusive_not_converged",
    }
    assert len(assessment["subjects"]) == 3
    assert assessment["metrics"]["pooled_modern_to_reference_residual_ratio"] >= 0
    assert assessment["assessment_version"] == "0.3"
    assert assessment["optimizer"]["engine_implementation"] == "0.3"
    assert len(assessment["optimizer"]["history_sha256"]) == 64
    trajectory = assessment["optimizer"]["trajectory"]
    assert trajectory["initial_objective"] == pytest.approx(
        trajectory["records"][0]["objective"]
    )
    assert trajectory["final_objective"] == pytest.approx(
        assessment["optimizer"]["final_objective"]
    )
    assert trajectory["objective_gain"] >= 0.0
    assert trajectory["objective_nondecreasing"] is True
    assert trajectory["decision_count"] == len(trajectory["records"]) - 1
    assert trajectory["accepted_decisions"] == 1

    for legacy_version in ("0.2", "0.1"):
        legacy_path = tmp_path / f"assessment-{legacy_version}"
        shutil.copytree(assessment_path, legacy_path)
        legacy = json.loads(json.dumps(assessment))
        legacy["assessment_version"] = legacy_version
        if legacy_version == "0.2":
            legacy["optimizer"].pop("trajectory")
        else:
            legacy.pop("optimizer")
            legacy.pop("continuation_verification", None)
        legacy_json = legacy_path / ASSESSMENT_JSON_NAME
        legacy_json.write_text(
            json.dumps(legacy, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (legacy_path / ASSESSMENT_HTML_NAME).write_text(
            _render_assessment_html(legacy),
            encoding="utf-8",
            newline="\n",
        )
        (legacy_path / ASSESSMENT_SIDECAR_NAME).write_text(
            f"{sha256_file(legacy_json)}  {ASSESSMENT_JSON_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        assert verify_modern_reference_qualification_assessment(legacy_path) == legacy

    continuation_path = create_modern_reference_qualification_continuation(
        destination,
        modern_run,
        tmp_path / "qualification-continuation",
        max_cycles=2,
        threads=1,
        created_at="2026-08-22T03:00:00+00:00",
    )
    continuation = verify_modern_reference_qualification_design(continuation_path)
    continuation_config = yaml.safe_load(
        (continuation_path / CONFIG_NAME).read_text(encoding="utf-8")
    )
    assert continuation["design_version"] == "0.4"
    assert continuation["protocol"]["continuation"]["parent_cycles_completed"] == 1
    assert continuation["protocol"]["continuation"]["parent_engine_implementation"] == "0.3"
    assert continuation["protocol"]["continuation"]["expected_engine_implementation"] == "0.3"
    assert math.isfinite(
        continuation["protocol"]["continuation"]["parent_final_objective"]
    )
    assert continuation_config["schema_version"] == "0.4"
    assert continuation_config["initialization"]["momenta"] == {
        "method": "file",
        "path": "inputs/initial-momenta.csv",
    }
    assert continuation_config["optimization"]["step_initialization"] == (
        "previous_accepted"
    )
    assert continuation_config["optimization"]["max_cycles"] == 2

    successor_run = run_modern_workflow(
        continuation_path / CONFIG_NAME,
        destination=tmp_path / "modern-successor-run",
        created_at="2026-08-22T04:00:00+00:00",
    )
    successor_assessment_path = assess_modern_reference_qualification(
        continuation_path,
        successor_run,
        tmp_path / "successor-assessment",
        created_at="2026-08-22T05:00:00+00:00",
    )
    successor_assessment = json.loads(
        (successor_assessment_path / ASSESSMENT_JSON_NAME).read_text(encoding="utf-8")
    )
    assert (
        verify_modern_reference_qualification_assessment(successor_assessment_path)
        == successor_assessment
    )
    assert successor_assessment["continuation_verification"][
        "initial_objective_matches"
    ] is True
    assert successor_assessment["continuation_verification"][
        "successor_engine_implementation"
    ] == "0.3"

    subject = destination / design["subjects"][0]["source"]["path"]
    subject.write_bytes(subject.read_bytes() + b"tamper")
    with pytest.raises(ModernReferenceQualificationError, match="differs"):
        verify_modern_reference_qualification_design(destination)


def test_reference_qualification_skips_quality_failure_in_prospective_order(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    inputs = run / "inputs"
    inputs.mkdir(parents=True)
    vertices = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, -1.0, 0.0),
    )
    invalid = write_vtk_polydata(
        inputs / "invalid.vtk",
        vertices,
        ((0, 1, 2), (1, 0, 3), (0, 1, 4)),
    )
    valid_a = write_vtk_polydata(
        inputs / "valid-a.vtk",
        vertices[:4],
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    )
    valid_b = write_vtk_polydata(
        inputs / "valid-b.vtk",
        vertices[:4],
        ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    )
    paths = (invalid, valid_a, valid_b)
    records = {
        path.name: {
            "staged_path": path.relative_to(run).as_posix(),
            "geometry": {"sha256": sha256_file(path)},
        }
        for path in paths
    }
    order = tuple(path.name for path in paths)
    roles = {name: "prospective test order" for name in order}

    selected, excluded = _screen_subject_candidates(
        run,
        records,
        order,
        roles,
        subject_count=2,
        settings=MeshQualitySettings(require_single_component=True),
    )

    assert selected == ("valid-a.vtk", "valid-b.vtk")
    assert [record["filename"] for record in excluded] == ["invalid.vtk"]
    assert excluded[0]["failed_gates"] == ["non-manifold edges"]


def test_desktop_reference_review_rechecks_artifact_before_open(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    review.artifact("pca-scores").path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ModernResultReviewError, match="changed after result review"):
        verify_result_artifact(review, "pca-scores")


def test_desktop_reference_review_rechecks_output_atlas_before_internal_render(
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    atlas = review.artifact("estimated-template")

    assert verify_result_artifact(review, atlas.key) == atlas.path
    atlas.path.write_bytes(atlas.path.read_bytes() + b"\n")

    with pytest.raises(ModernResultReviewError, match="changed after result review"):
        verify_result_artifact(review, atlas.key)


def test_reference_pca_cli_creates_and_strictly_verifies_bundle(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    run = _completed_reference_run(tmp_path)

    assert main(["reference-pca", str(run), "--components", "1"]) == 0
    created = capsys.readouterr()
    assert "centered linear PCA" in created.out
    bundle = run / "analysis" / "reference-result-analysis-v0.2"

    assert main(["reference-pca-verify", str(bundle), "--source-run", str(run)]) == 0
    verified = capsys.readouterr()
    assert "Raw parameter hashes and recomputed PCA tables match" in verified.out
