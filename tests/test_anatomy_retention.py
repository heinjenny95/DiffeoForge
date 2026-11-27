"""Known geometry lost at each handoff, unmeasured material, and saved evidence integrity."""

from types import SimpleNamespace

import pytest

from diffeoforge import anatomy_retention as retention
from diffeoforge import anatomy_retention_sources as sources
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.reconstruction_feedback import topology_sha256

FACES = [[0, 1, 2], [3, 4, 5]]
VERTICES = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [3, 0, 0], [4, 0, 0], [3, 1, 0]]


def surface(tmp, name, height=0, faces=FACES):
    vertices = [[x, y, height if x < 2 else 0] for x, y, _ in VERTICES]
    path = write_vtk_polydata(tmp / name, vertices, faces)
    return retention.SurfaceEvidence(path, sha256_file(path))


def marks(original):
    return [dict(version="surface-region-v2", source_sha256=original.sha256,
                 space="original_mesh_coordinates", center=[x + 1 / 3, 1 / 3, 0],
                 radius=.6, purpose=purpose, symptom="shape")
            for x, purpose in ((0, "problem"), (3, "fixed"))]


def test_each_stage_measures_actual_surfaces_and_same_approved_areas(tmp_path):
    original = surface(tmp_path, "subject.vtk")
    approved = surface(tmp_path, "individual.vtk")
    stages = [sources._stage("approved", approved, material_template=original)]
    for key, displacement in (("transfer", 0), ("common", .2), ("pilot_joint", .05),
                              ("atlas", .4)):
        stages.append(sources._stage(key, surface(tmp_path, key + ".vtk", displacement),
                                    material_template=original))
    report = retention.assess_stages("subject.vtk", original, marks(original), stages)
    entries = {(row.stage_key, row.area, row.metric): row for row in report.rows}
    for key, displacement in (("transfer", 0), ("common", .2), ("pilot_joint", .05),
                              ("atlas", .4)):
        for metric in retention.AREA_METRICS:
            assert entries[key, 0, metric].observed == pytest.approx(
                (100 * displacement / 17**.5,) * 2, abs=1e-5)
            assert entries[key, 0, metric].change == ("worse" if displacement else "unclear")
            assert entries[key, 1, metric].change == "unclear"
        assert entries[key, None, "p99"].change == ("worse" if displacement else "unclear")
        assert entries[key, 1, "fixed_material_max"].observed == (0, 0)
    assert "A, whole surface" in report.summary
    assert "after fitting the original before joint testing" in report.summary
    joint = next(s for s in report.stages if s.key == "pilot_joint")
    assert "decreased" in joint.reason
    assert "increased" in report.stages[-1].reason


def test_gaps_and_changed_material_do_not_erase_other_marks(tmp_path):
    original = surface(tmp_path, "individual.vtk")
    changed = surface(tmp_path, "common.vtk", .2, list(reversed(FACES)))
    regions = marks(original)
    regions[0]["reconstruction"] = dict(sha256=original.sha256,
        topology_sha256=topology_sha256(VERTICES, FACES), face_ids=[0])
    report = retention.assess_stages("original", original, regions, [
        sources._stage("approved", original), sources._stage("transfer", reason="No capture"),
        sources._stage("common", changed)])
    assert all(r.change == "unavailable" for r in report.rows if r.stage_key == "transfer")
    assert all(r.change == "unavailable" for r in report.rows
               if r.stage_key == "common" and r.area == 0)
    assert all(r.change == "unclear" for r in report.rows
               if r.stage_key == "common" and r.area == 1 and r.metric in retention.AREA_METRICS)
    assert all(r.change == "unavailable" for r in report.rows
               if r.stage_key == "common" and r.area == 1 and r.metric in retention.fixed.METRICS)
    assert next(r for r in report.rows if r.stage_key == "common" and r.metric == "p95").observed
    assert "timing" in report.summary


def test_byte_changes_and_stale_original_marks_fail_closed(tmp_path):
    original = surface(tmp_path, "original.vtk")
    fit = surface(tmp_path, "common.vtk")
    stages = [sources._stage("approved", original), sources._stage("common", fit)]
    with pytest.raises(ValueError, match="source"):
        retention.assess_stages("s", original, [dict(marks(original)[0], source_sha256="bad")],
                                stages)
    fit.path.write_bytes(fit.path.read_bytes().replace(b"DiffeoForge surface", b"Changed title"))
    with pytest.raises(ValueError, match="mesh changed"):
        retention.assess_stages("s", original, [], stages)
    with pytest.raises(InterruptedError):
        retention.assess_stages("s", original, [], stages, cancelled=lambda: True)


def test_reconstruction_only_review_uses_its_material_direction(tmp_path, monkeypatch):
    original = surface(tmp_path, "original.vtk")
    protrusion = surface(tmp_path, "approved.vtk", height=1)
    area = dict(marks(original)[0], center=[1 / 3, 1 / 3, 1], radius=.1,
                reconstruction=dict(sha256=protrusion.sha256,
                                    topology_sha256=topology_sha256(VERTICES, FACES), face_ids=[0]))
    approved = sources._stage("approved", protrusion)
    monkeypatch.setattr(sources, "approved_source", lambda *_: (original, approved, [area], None))
    result = retention.compare_approved_endpoint(dict(target="s"), protrusion.path,
                                                 protrusion.sha256)
    assert result["status"] == "comparable"
    assert "empty original space" in result["summary"]
    forward = next(r for r in result["rows"] if r["metric"] == "original_to_fit_p95")
    reverse = next(r for r in result["rows"] if r["metric"] == "fit_to_original_p95")
    assert forward["observed"] is None
    assert reverse["observed"] == pytest.approx((100 / 17**.5,) * 2)
    unknown = surface(tmp_path, "unmappable.vtk", height=1, faces=list(reversed(FACES)))
    result = retention.compare_approved_endpoint(dict(target="s"), unknown.path, unknown.sha256)
    assert result["status"] == "unmeasured"
    assert result["anatomical_approval"] is False


def test_fixed_material_sliding_on_unchanged_surface_and_unproven_lineage(tmp_path, monkeypatch):
    original = surface(tmp_path, "original.vtk")
    vertices = VERTICES[:3] + VERTICES[4:] + [VERTICES[3]]
    path = write_vtk_polydata(tmp_path / "permuted.vtk", vertices, FACES)
    candidate = retention.SurfaceEvidence(path, sha256_file(path))
    area = marks(original)[1]
    approved = sources._stage("approved", original, material_template=original)
    monkeypatch.setattr(sources, "approved_source", lambda *_: (original, approved, [area], None))
    def evaluate(material):
        return retention.compare_approved_endpoint(dict(target="s"), candidate.path,
            candidate.sha256, regions=[area], material_template_sha256=material)

    measured = evaluate(original.sha256)
    rows = {r["metric"]: r for r in measured["rows"]}
    assert measured["status"] == "regression"
    assert rows["fixed_material_max"]["observed"][0] == pytest.approx(100*(2/17)**.5)
    assert rows["fixed_material_p95"]["change"] == "worse"
    assert rows["fit_to_original_p99"]["change"] == "unclear"
    unknown = evaluate("unrelated immutable template")
    assert unknown["status"] == "unmeasured"
    assert "0.01%" in measured["summary"]
    area["purpose"] = "preserve"
    assert evaluate(original.sha256)["status"] == "comparable"

    area["purpose"] = "fixed"
    # A physical displacement below the declared dense fixed-area allowance stays eligible.
    vertices = [[x + 1e-5, y, z] for x, y, z in VERTICES]
    path = write_vtk_polydata(tmp_path / "within.vtk", vertices, FACES)
    candidate = retention.SurfaceEvidence(path, sha256_file(path))
    within = evaluate(original.sha256)
    movement = next(r for r in within["rows"] if r["metric"] == "fixed_material_max")
    assert 0 < movement["observed"][1] < .01
    assert movement["change"] == "unclear"


def test_recovered_final_stage_directs_reader_to_latest_evidence(tmp_path):
    original = surface(tmp_path, "subject.vtk")
    temporary_loss = surface(tmp_path, "start.vtk", .5)
    report = retention.assess_stages("s", original, [], [
        sources._stage("approved", original), sources._stage("transfer", temporary_loss),
        sources._stage("atlas", original)])
    assert "last measured surface" in report.summary
    assert "before spending more iterations" not in report.summary


def test_before_joint_snapshot_uses_bound_specimen_and_full_geometry(tmp_path):
    import json

    from diffeoforge.reference_atlas_handoff import EARLY_CHECK

    output = tmp_path / "output"
    output.mkdir()
    actual = surface(output, "before.vtk")
    record = dict(index=1, path=actual.path.name, sha256=actual.sha256)
    plan = dict(subject_labels=["other", "target"], pilot_indices=[1])
    path = output / EARLY_CHECK
    path.write_text(json.dumps(dict(version="0.1", pilot_momenta_preserved_exactly=True,
                                   **plan, meshes=[dict(index=1, before=record)])))
    inventory = [dict(path=EARLY_CHECK, sha256=sha256_file(path)), record]
    report = SimpleNamespace(run_directory=tmp_path, inventory=inventory)
    assert sources._atlas_start(report, plan, "target") == actual
    record["sha256"] = "other"
    with pytest.raises(ValueError, match="missing"):
        sources._atlas_start(report, plan, "target")


def test_shooting_a_saved_field_is_independent_of_later_optimizer_and_log_settings():
    from copy import deepcopy
    from pathlib import Path

    from diffeoforge.config import load_config

    config = load_config(Path(__file__).parents[1] / "examples/minimal-atlas.yaml")
    current = deepcopy(config)
    current["optimization"].update(save_every_n_iterations=17, max_line_search_iterations=7)
    assert sources._flow_settings(config) == sources._flow_settings(current)
    current["model"]["deformation"]["timepoints"] += 1
    assert sources._flow_settings(config) != sources._flow_settings(current)


def test_atlas_and_experiment_sources_require_bound_evidence(tmp_path, monkeypatch):
    from test_reference_pca import _completed_reference_run

    from diffeoforge.pilot_common_projection import VERSION
    from diffeoforge.reference_atlas_handoff import METHOD
    from diffeoforge.result_report import collect_run_report

    run = _completed_reference_run(tmp_path)
    report = collect_run_report(run)
    subject = next(r for r in report.manifest["inputs"] if r["role"] == "subject")
    original = retention.SurfaceEvidence(run / subject["staged_path"],
                                         subject["geometry"]["sha256"])
    target = original.path.name
    shared = sources._output(report, target)
    approved = sources._stage("approved", original)
    cohort = SimpleNamespace()
    common = [approved, sources._stage("transfer", original), sources._stage("common", shared)]
    plan = dict(method=METHOD, pilot_subject_labels=[target], source_run_manifest_sha256="sealed",
                subject_sha256={target: original.sha256})
    config = dict(project=dict(parameter_provenance=dict(recommendation=dict(
        calibration_result=dict(full_cohort_initialization=plan)))))
    assert retention.atlas_retention_targets(config) == (target,)
    assert retention.atlas_retention_targets({}) == ()
    monkeypatch.setattr(sources, "_source_joint", lambda *_: (cohort, object(), plan))
    monkeypatch.setattr(sources, "_joint_parts",
                        lambda snapshot, name, cancelled: (original, [], common.copy(), {}))
    monkeypatch.setattr(sources, "_surface", lambda *args: (shared, None))
    traced = retention.prepare_atlas_retention(run, target)
    assert traced.stages[-1].surface == shared
    assert [s.key for s in traced.stages] == [
        "approved", "transfer", "common", "pilot_joint", "atlas"]
    plan["subject_sha256"][target] = "changed"
    with pytest.raises(ValueError, match="different original"):
        retention.prepare_atlas_retention(run, target)

    from diffeoforge import pilot_common_projection as projection

    ref = dict(candidate_id="approved", target=target)
    state = dict(approved_reference=ref, projection="completed", original="pending")
    proof = dict(path=str(shared.path), sha256=shared.sha256, approved_reference=ref,
                 original_sha256=original.sha256, target=target)
    monkeypatch.setattr(projection, "contract", lambda _: dict(version=VERSION, regions=[]))
    monkeypatch.setattr(projection, "status", lambda _: state)
    monkeypatch.setattr(projection, "verified_endpoint", lambda *_: proof)
    monkeypatch.setattr(sources, "approved_source", lambda *_: (original, approved, [], None))
    projected = retention.prepare_projection_retention(tmp_path)
    assert [(s.key, bool(s.surface)) for s in projected.stages] == [
        ("approved", True), ("transfer", True), ("common", False)]
    assert retention.compare_approved_endpoint(ref, original.path, original.sha256) == {
        "status": "comparable", "rows": [dict(stage_key="transfer", area=None, metric=m,
            approved=row.approved, observed=row.approved, change="unclear")
            for m, row in zip(retention.WHOLE_METRICS, projected.rows[:2], strict=True)],
        "warnings": [],
        "summary": "Available measurements show no repeat-confirmed distance increase.",
        "anatomical_approval": False,
    }
    state["original"] = "completed"
    assert retention.prepare_projection_retention(tmp_path).stages[-1].surface == shared
    proof["original_sha256"] = "other specimen"
    with pytest.raises(ValueError, match="differ"):
        retention.prepare_projection_retention(tmp_path)


def test_verified_guided_approvals_resolve_through_joint_run(tmp_path, monkeypatch):
    from test_guided_pilot import approve, run_batch
    from test_interactive_pilot import initial

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.reference_atlas_handoff import METHOD

    current = approve(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    while guided.record(current)["phase"] != "joint":
        prepared = guided.next_action(current.study_directory, "adaptive_confirm",
                                      "guided-varifold")
        current = run_batch(prepared, monkeypatch)
        if guided.record(current)["phase"] != "joint":
            current = approve(current, "guided-varifold")
    candidate = current.candidates[0]
    run = study.calibration_candidate_run_directory(candidate)
    labels = current.attachment_comparison["joint_initialization"]["subjects"]
    plan = dict(method=METHOD, source_run_directory=str(run),
                source_run_manifest_sha256=sha256_file(run / "manifest.json"),
                pilot_subject_labels=labels)
    config = dict(project=dict(parameter_provenance=dict(recommendation=dict(
        calibration_result=dict(full_cohort_initialization=plan)))))
    target = labels[-1]
    with study.calibration_verification_scope():
        linked, saved, _ = sources._source_joint(config, target)
        assert linked.study_directory == current.study_directory
        assert saved.candidate_id == candidate.candidate_id
        original = sources._original(current, target)
        # The synthetic pilot controller emits receipts only. Its real meshes are tested above.
        monkeypatch.setattr(sources, "_surface", lambda *_: (original, None))
        report = retention.prepare_pilot_retention(linked.study_directory, saved.candidate_id,
                                                   target)
        assert report.target == target
        assert report.stages[1].surface == report.stages[0].surface
        assert "initialized the joint pilot" in report.stages[1].reason
        assert [s.surface is not None for s in report.stages] == [True, True, True, True, False]
    plan["source_run_manifest_sha256"] = "changed"
    with pytest.raises(ValueError, match="changed"):
        sources._source_joint(config, target)
