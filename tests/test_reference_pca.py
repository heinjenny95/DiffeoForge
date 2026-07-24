from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.cli import main
from diffeoforge.desktop.reference_result_review import review_reference_result
from diffeoforge.desktop.result_review import ModernResultReviewError, verify_result_artifact
from diffeoforge.mesh import sha256_file
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
    records = [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in (controls_path, momenta_path)
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
        "reference-momenta",
        "reference-control-points",
        "pca-summary",
        "pca-scores",
        "pca-scree",
        "pca-score-plot",
        "optimizer-convergence-plot",
        "reference-convergence",
    }
    assert verify_result_artifact(review, "pca-score-plot").is_file()
    assert review.execution_duration_seconds == 60.0
    assert review.optimizer_termination_reason == "tolerance_threshold"


def test_desktop_reference_review_rechecks_artifact_before_open(tmp_path: Path) -> None:
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    review.artifact("pca-scores").path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ModernResultReviewError, match="changed after result review"):
        verify_result_artifact(review, "pca-scores")


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
