import json
from pathlib import Path

import numpy as np
import pytest
from test_runs import write_run_config

from diffeoforge.config import load_config
from diffeoforge.mesh_resolution_study import (
    PLAN,
    THRESHOLDS,
    assess_study,
    compare_scores,
    freeze_study,
    load_study,
)


def approved_plan(tmp_path):
    import vtk

    paths = []
    for level in ("high", "low"):
        folder = tmp_path / level
        folder.mkdir()
        paths.append(write_run_config(folder))
    for name in ("template.vtk", "subject-a.vtk", "subject-b.vtk"):
        sphere = vtk.vtkSphereSource()
        sphere.SetThetaResolution(10)
        sphere.SetPhiResolution(8)
        sphere.Update()
        writer = vtk.vtkPolyDataWriter()
        writer.SetFileName(str(paths[0].parent / "meshes" / name))
        writer.SetInputData(sphere.GetOutput())
        assert writer.Write()
        reducer = vtk.vtkDecimatePro()
        reducer.SetInputData(sphere.GetOutput())
        reducer.SetTargetReduction(0.6)
        reducer.Update()
        writer.SetFileName(str(paths[1].parent / "meshes" / name))
        writer.SetInputData(reducer.GetOutput())
        assert writer.Write()
    spec = {
        "study_version": "0.1",
        "researcher_approved": True,
        "reference_level": "high",
        "components": 1,
        "thresholds": {key: (0.9 if key == "minimum_score_cka" else 0.1) for key in THRESHOLDS},
        "levels": [],
    }
    for key, path in zip(("high", "low"), paths, strict=True):
        spec["levels"].append(
            {
                "id": key,
                "config": str(path),
                "provenance": [
                    {
                        "derived": str(path.parent / "meshes" / name),
                        "source": str(paths[0].parent / "meshes" / name),
                        "method": "identity" if key == "high" else "synthetic vtkDecimatePro",
                        "tool_version": vtk.vtkVersion.GetVTKVersion(),
                        "parameters": {"target_reduction": 0 if key == "high" else 0.6},
                    }
                    for name in ("template.vtk", "subject-a.vtk", "subject-b.vtk")
                ],
            }
        )
    path = tmp_path / "approved-plan.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path, spec


def test_freeze_preserves_meshes_and_builds_prospectively_bound_run_configs(tmp_path):
    source, spec = approved_plan(tmp_path)
    original = {p: p.read_bytes() for p in tmp_path.rglob("*.vtk")}
    root = freeze_study(source, tmp_path / "study")
    plan = load_study(root)
    assert {p: p.read_bytes() for p in original} == original
    assert plan["reference_level"] == "high"
    assert plan["levels"][0]["median_subject_faces"] > plan["levels"][1]["median_subject_faces"]
    for level in plan["levels"]:
        config = load_config(level["run_config"]["path"])
        assert config["project"]["mesh_resolution_study"] == {
            "fingerprint": plan["design_fingerprint"],
            "level": level["id"],
        }
        assert Path(config["input"]["directory"]).is_absolute()
    with pytest.raises(FileExistsError):
        freeze_study(source, root)
    changed = Path(spec["levels"][1]["provenance"][0]["derived"])
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="source changed"):
        load_study(root)


@pytest.mark.parametrize("fault", ["approval", "threshold", "origin", "reference", "settings"])
def test_study_refuses_unapproved_or_confounded_comparisons(tmp_path, fault):
    path, spec = approved_plan(tmp_path)
    if fault == "approval":
        spec["researcher_approved"] = False
    elif fault == "threshold":
        spec["thresholds"].pop("pc_extreme_p95_mesh_units")
    elif fault == "origin":
        spec["levels"][1]["provenance"][1]["source"] = spec["levels"][1]["provenance"][1]["derived"]
    elif fault == "reference":
        spec["reference_level"] = "low"
    else:
        import yaml

        config = Path(spec["levels"][1]["config"])
        value = yaml.safe_load(config.read_text())
        value["model"]["noise_std"] *= 2
        config.write_text(yaml.safe_dump(value), encoding="utf-8")
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError):
        freeze_study(path, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_no_face_count_claim_without_all_declared_results(tmp_path):
    path, _ = approved_plan(tmp_path)
    root = freeze_study(path, tmp_path / "study")
    with pytest.raises(ValueError, match="every frozen mesh level"):
        assess_study(root, {}, tmp_path / "report")
    assert not (tmp_path / "report").exists()
    assert (root / PLAN).exists()


@pytest.mark.parametrize("fault", ["relative", "duplicate"])
def test_study_provenance_rejects_ambiguous_mesh_identity(tmp_path, fault):
    path, spec = approved_plan(tmp_path)
    if fault == "relative":
        spec["levels"][0]["provenance"][0]["source"] = "template.vtk"
    else:
        spec["levels"][0]["provenance"].append(spec["levels"][0]["provenance"][0])
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="absolute|Duplicate"):
        freeze_study(path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_score_subspace_comparison_handles_sign_rotation_and_different_feature_bases():
    rng = np.random.default_rng(123)
    scores = rng.normal(size=(12, 3))
    rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
    cka, angle = compare_scores(scores, scores @ rotation, 3)
    assert cka == pytest.approx(1)
    assert angle < 2e-6
    other = rng.normal(size=(12, 3))
    other_cka, other_angle = compare_scores(scores, other, 3)
    assert other_cka < 0.8 and other_angle > 10
    with pytest.raises(ValueError, match="not available"):
        compare_scores(np.ones((5, 3)), np.ones((5, 3)), 3)


def test_completed_fixture_reports_missing_native_extremes_without_claiming_resolution(
    tmp_path, monkeypatch
):
    import shutil
    from datetime import datetime, timedelta

    import test_reference_pca as fixture

    from diffeoforge.mesh import sha256_file
    from diffeoforge.runs import prepare_run

    path, _ = approved_plan(tmp_path)
    root = freeze_study(path, tmp_path / "study")
    plan = load_study(root)
    assignments = {}
    for level in plan["levels"]:
        config = Path(level["run_config"]["path"])
        monkeypatch.setattr(
            fixture, "prepare_run", lambda _source, cfg=config, **kw: prepare_run(cfg, **kw)
        )
        run = fixture._completed_reference_run(tmp_path / level["id"] / "completed")
        manifest = json.loads((run / "manifest.json").read_text())
        source = next(
            run / row["staged_path"] for row in manifest["inputs"] if row["role"] == "template"
        )
        for output in (run / "output").glob("*.vtk"):
            shutil.copyfile(source, output)
        inventory_path = run / "output-inventory.json"
        inventory = json.loads(inventory_path.read_text())
        for row in inventory["files"]:
            output = run / "output" / row["path"]
            row.update(bytes=output.stat().st_size, sha256=sha256_file(output))
        inventory_path.write_text(json.dumps(inventory))
        result_path = run / "result.json"
        result = json.loads(result_path.read_text())
        start = datetime.fromisoformat(manifest["created_at"])
        result.update(
            started_at=start.isoformat(),
            ended_at=(start + timedelta(seconds=1)).isoformat(),
            duration_seconds=1.0,
        )
        result["outputs"].update(
            inventory_sha256=sha256_file(inventory_path),
            total_bytes=sum(row["bytes"] for row in inventory["files"]),
        )
        result_path.write_text(json.dumps(result))
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        for event in events:
            if event["event"] in ("started", "completed"):
                event["timestamp"] = result[
                    "started_at" if event["event"] == "started" else "ended_at"
                ]
                if event["event"] == "completed":
                    event["duration_seconds"] = 1.0
        (run / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))
        assignments[level["id"]] = run
    report = assess_study(root, assignments, tmp_path / "report")
    evidence = json.loads((report / "assessment.json").read_text())
    assert evidence["smallest_supported_tested_level"] is None
    assert all(row["measurements"]["minimum_score_cka"] > 0.99 for row in evidence["levels"])
    assert all(
        any("shape changes along PC axes" in reason for reason in row["next_actions"])
        for row in evidence["levels"]
    )
    assert "No face-count recommendation is supported" in (report / "report.html").read_text()
