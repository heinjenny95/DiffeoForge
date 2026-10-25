"""Public geometric fixtures. Native end-to-end evidence is qualified separately."""

import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import regional_pilot
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save, apply_xml, assets, prepare, read_plan, validate_scope
from diffeoforge.regional_quality import measure


def fixture(tmp_path, *, guides=True):
    v, f = cube()
    sv = np.vstack([v * 0.3 + [x, 0, z] for x, z in [(-2, 0), (2, 0), (0, 5)]])
    tv = sv.copy()
    tv[:8, 0] += 0.4
    tv[8:16, 0] -= 0.4
    faces = np.vstack([f + 8 * i for i in range(3)])
    _save(tmp_path / "source.vtk", sv, faces)
    _save(tmp_path / "target.vtk", tv, faces)
    region = dict(
        shape="box", bounds=[-3, 3, -1, 1, -1, 1], center=[0, 0, 0], radius=4, symptom="gap"
    )
    declaration = prepare(
        tmp_path / "regional",
        tmp_path / "source.vtk",
        tmp_path / "target.vtk",
        [region],
        focus_width=0.1,
        focus_noise=0.02,
        protection_noise=0.001,
        protection_halo=0.2,
        guide_noise=0.001 if guides else None,
        retained_path=tmp_path / "source.vtk",
    )
    config = load_config(Path(__file__).parents[1] / "examples/minimal-atlas.yaml")
    config["input"].update(
        template=str(tmp_path / "source.vtk"), directory=str(tmp_path), subject_pattern="target.vtk"
    )
    config["optimization"].update(freeze_template=True, freeze_control_points=True)
    config["project"]["parameter_provenance"] = dict(regional_fit=declaration)
    return config, sv, tv, faces


def test_explicit_objective_is_immutable_singleton_and_native_terms_are_bound(tmp_path):
    config, *_ = fixture(tmp_path)
    original = {p: sha256_file(p) for p in tmp_path.glob("*.vtk")}
    plan = read_plan(config)
    assert [r["id"] for r in plan["objects"]] == ["focus", "protect", "featureguides"]
    assert len(plan["guidance"]) == 2 and not plan["anatomical_approval"]
    validate_scope(
        config,
        SimpleNamespace(
            subject_count=1, template=tmp_path / "source.vtk", subjects=[tmp_path / "target.vtk"]
        ),
    )
    model = ET.fromstring('<model><template><object id="surface" /></template></model>')
    data = ET.fromstring('<data-set><subject id="s"><visit /></subject></data-set>')
    apply_xml(config, model, data)
    assert len(model.findall("template/object")) == 4
    assert len(data.findall("subject/visit/filename")) == 3
    assert len(assets(config)) == 7
    assert all(sha256_file(p) == digest for p, digest in original.items())
    bad = deepcopy(config)
    bad["optimization"]["freeze_template"] = False
    with pytest.raises(ValueError, match="frozen"):
        validate_scope(bad)
    with pytest.raises(ValueError, match="source or target"):
        validate_scope(
            config,
            SimpleNamespace(
                subject_count=2,
                template=tmp_path / "source.vtk",
                subjects=[tmp_path / "target.vtk"] * 2,
            ),
        )
    row = plan["objects"][0]["target"]
    with (tmp_path / "regional" / row["copy"]).open("a") as out:
        out.write("changed")
    with pytest.raises(ValueError, match="geometry changed"):
        read_plan(config)


def test_spacing_can_improve_without_changing_parts_but_outside_and_shape_regressions_fail(
    tmp_path,
):
    config, _, target, faces = fixture(tmp_path)
    _save(tmp_path / "perfect.vtk", target, faces)
    quality = measure(config, tmp_path / "perfect.vtk")
    assert quality["numerical_selection_suitable"] and quality["local_improved"]
    assert quality["requires_visual_review"] and not quality["anatomical_approval"]
    distorted = target.copy()
    distorted[:8, 1] *= 0.8
    distorted[16:, 0] += 0.2
    _save(tmp_path / "bad.vtk", distorted, faces)
    quality = measure(config, tmp_path / "bad.vtk")
    assert not quality["shape_preserved"] and not quality["outside_preserved"]
    assert not quality["numerical_selection_suitable"]


def proposal_data():
    ref = dict(
        target="shape.vtk",
        method="varifold",
        values=dict(
            attachment_kernel_width=0.06,
            noise_std=0.02,
            deformation_kernel_width=0.1,
            initial_control_point_spacing=0.3,
        ),
    )
    return dict(
        anchor=ref,
        current_reference=dict(ref, candidate_id="new"),
        regions=[dict(symptom="gap")],
        severe=True,
        context=dict(cases=[], feedback={}),
        current=SimpleNamespace(metrics={}),
    )


def test_mixed_marked_areas_do_not_force_shape_preservation_on_shape_errors():
    gap = dict(symptom="gap", purpose="problem")
    bent = dict(symptom="curvature", purpose="problem")
    good = dict(symptom="unsure", purpose="fixed")
    problem, guides, fixed = regional_pilot.split_regions([gap, bent, good])
    assert problem == [gap, bent] and guides == [gap] and fixed == [good]
    assert not regional_pilot.split_regions([good])[0]


def test_missing_detail_beyond_source_tip_gets_a_movable_source_patch(tmp_path):
    config, sv, tv, faces = fixture(tmp_path, guides=False)
    source_centres, target_centres = sv[faces].mean(1), tv[faces].mean(1)
    distances = np.linalg.norm(target_centres[:, None] - source_centres[None, :], axis=2).min(1)
    index = np.argmax(distances)
    radius = min(0.08, distances[index] / 3)
    region = dict(center=target_centres[index].tolist(), radius=radius, symptom="detail")
    declaration = prepare(
        tmp_path / "missing-tip", tmp_path / "source.vtk", tmp_path / "target.vtk", [region],
        focus_width=0.1, focus_noise=0.02, protection_noise=0.001, protection_halo=0.1,
        retained_path=tmp_path / "source.vtk")
    config["project"]["parameter_provenance"]["regional_fit"] = declaration
    plan = read_plan(config)
    assert len(plan["inferred_source_regions"]) == 1
    assert plan["protection_vertex_ids"] and not plan["guidance"]
    quality = measure(config, tmp_path / "source.vtk")
    assert not quality["local_improved"] and np.isfinite(quality["active_surface_p95"])


def test_feedback_recipes_keep_preference_and_balance_transitions_without_promoting_attempt(
    monkeypatch,
):
    from diffeoforge import reference_guided_pilot as guided

    monkeypatch.setattr(guided, "record", lambda _: dict(goal="regional", pilot_order=[1, 2]))
    data = proposal_data()
    first = regional_pilot.proposal(None, "x", data, symptom="gap")
    assert first["regional_recipe"]["focus_noise"] == 0.006
    assert first["anchor"] == data["anchor"] and first["initialization"] == "learned"
    data["current"].metrics = dict(
        attachment_comparison=dict(
            subjects={
                "shape.vtk": dict(
                    regional_quality=dict(outside_preserved=True, shape_preserved=True)
                )
            }
        )
    )
    data["context"]["cases"] = [dict(family="regional", target="shape.vtk")]
    second = regional_pilot.proposal(None, "x", data, symptom="gap")
    assert second["regional_recipe"]["focus_noise"] == 0.0003
    assert second["initialization_reference"] == data["current_reference"]
    assert second["anchor"] == data["anchor"]
    quality = data["current"].metrics["attachment_comparison"]["subjects"]["shape.vtk"][
        "regional_quality"]
    for key in ("no_new_intersection_flags", "temporal_grid_stable"):
        quality[key] = False
        assert regional_pilot.proposal(None, "x", data, symptom="gap")[
            "initialization_reference"] == data["anchor"]
        quality[key] = True
    data["context"]["feedback"] = dict(x=dict(feedback=dict(outcome="worse")))
    assert (
        regional_pilot.proposal(None, "x", data, symptom="gap")["initialization_reference"]
        == data["anchor"]
    )
    blocked = regional_pilot.proposal(None, "x", data, symptom="topology")
    assert not blocked["available"] and "topological" in blocked["blocked_reason"]
    residual = regional_pilot.proposal(None, "x", data, symptom="curvature")
    assert residual["initialization"] == "residual"
    assert residual["values"]["deformation_kernel_width"] == 0.05


def test_shared_atlas_scope_cannot_inherit_single_form_terms(tmp_path):
    config, *_ = fixture(tmp_path)
    config["optimization"]["freeze_control_points"] = False
    with pytest.raises(ValueError, match="two subject|frozen"):
        validate_input_paths(config, tmp_path / "atlas.yaml")
    entry = config["project"]["parameter_provenance"]["regional_fit"]
    path = Path(entry["manifest"])
    data = json.loads(path.read_text())
    data["objects"][0]["kernel_width"] = -1
    path.write_text(json.dumps(data))
    entry["sha256"] = sha256_file(path)
    with pytest.raises(ValueError, match="surface scale"):
        read_plan(config)


def test_original_source_grid_is_bound_and_staged_with_residual(tmp_path):
    import shutil

    config, *_ = fixture(tmp_path, guides=False)
    entry = config["project"]["parameter_provenance"]["regional_fit"]
    path = Path(entry["manifest"])
    data = json.loads(path.read_text())
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "manifest.json").write_text("{}")
    rows = {}
    for key, name in [("source", "residual-source.vtk"),
                      ("original_source_grid", "original-grid.vtk")]:
        copied = path.parent / name
        shutil.copyfile(tmp_path / "source.vtk", copied)
        rows[key] = dict(copy=name, sha256=sha256_file(copied), bytes=copied.stat().st_size)
    data["residual"] = dict(rows, parent_run=str(parent),
                            parent_manifest_sha256=sha256_file(parent / "manifest.json"))
    path.write_text(json.dumps(data))
    entry["sha256"] = sha256_file(path)
    assert any(str(staged).endswith("original-grid.vtk") for _, staged, _ in assets(config))
    (path.parent / "original-grid.vtk").write_text("changed")
    with pytest.raises(ValueError, match="Original source grid changed"):
        read_plan(config)


@pytest.mark.parametrize("symptom", ["detail", "curvature"])
def test_real_pilot_transition_stages_regional_assets_without_launching(
    tmp_path, monkeypatch, symptom
):
    import shutil

    from test_guided_pilot import run_batch
    from test_interactive_pilot import initial
    from test_pilot_region_feedback import patch

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge import result_report
    from diffeoforge.runs import prepare_run, verify_prepared_run
    from diffeoforge.surface_io import load_surface_mesh

    base = run_batch(initial(tmp_path), monkeypatch)
    target_subject = base.plan.selected_pilot_subjects[0]
    original = load_surface_mesh(
        base.study_directory / "inputs/subjects" / target_subject.filename
    ).geometry
    vertices = np.asarray(original.vertices)
    center = vertices[np.argmax(vertices[:, 0])].tolist()
    base = study.record_reference_calibration_candidate_review(
        base.study_directory,
        candidate_id="guided-varifold",
        approved=False,
        reviewed_subjects=(target_subject.filename,),
        subject_decisions={target_subject.filename: "fail"},
        problem_regions={
            target_subject.filename: [patch(target_subject.sha256, center=center, radius=0.25)]
        },
    )
    candidate = next(c for c in base.candidates if c.candidate_id == "guided-varifold")
    manifest = study._verify_manifest(base.study_directory)
    target = manifest["inputs"]["subjects"][0]
    output = candidate.run_directory / "output"
    output.mkdir()
    object_id = load_config(candidate.config_path)["model"]["object_id"]
    name = f"Fixture__Reconstruction__{object_id}__subject_" + target["filename"] + ".vtk"
    shutil.copyfile(base.study_directory / manifest['inputs']['template']['copy'], output / name)
    monkeypatch.setattr(
        result_report,
        "collect_run_report",
        lambda _: SimpleNamespace(
            inventory=[dict(path=name, sha256=sha256_file(output / name))],
            manifest=dict(effective_config=load_config(candidate.config_path)),
        ),
    )
    # Completed runs above are synthetic receipts. Supply a correspondingly
    # synthetic qualified frame; native frame qualification is tested separately.
    from diffeoforge import regional_frame

    frozen_run = candidate.run_directory
    if not (frozen_run / "manifest.json").exists():
        (frozen_run / "manifest.json").write_text("{}")
    controls, momenta = tmp_path / "frame-controls.txt", tmp_path / "frame-momenta.txt"
    controls.write_text("synthetic controls")
    momenta.write_text("synthetic momenta")
    original_source = base.study_directory / manifest["inputs"]["template"]["copy"]
    def qualified_frame(run, directory, **kwargs):
        return dict(source_run=str(run), source_manifest_sha256=sha256_file(run / "manifest.json"),
            endpoint=dict(path=str(output / name), sha256=sha256_file(output / name)),
            reference_source=dict(path=str(original_source), sha256=sha256_file(original_source)),
            timepoints=73, precision="float64", integrator="rk2",
            starting_frame_qualification=dict(temporal_stable=True),
            field_paths=dict(control_points=str(controls), momenta=str(momenta)),
            controls_sha256=sha256_file(controls), momenta_sha256=sha256_file(momenta))
    monkeypatch.setattr(regional_frame, "qualify", qualified_frame)
    protected = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    child = guided.next_action(
        base.study_directory, "adaptive_recover", "guided-varifold", goal="regional:" + symptom
    )
    config = load_config(child.candidates[0].config_path)
    plan = read_plan(config)
    expected = "learned"
    assert child.attachment_comparison["refinement"]["initialization"] == expected
    assert plan["retained_reference"] and len(plan["objects"]) == 2
    assert config["optimization"]["method"] == "lbfgs"
    assert config["model"]["deformation"]["use_rk2"]
    assert config["model"]["deformation"]["timepoints"] >= 19
    assert config["optimization"]["convergence_tolerance"] <= 1e-6
    child_manifest = study._verify_manifest(child.study_directory)
    binding_config = load_config(child.study_directory / child_manifest['source_config']['copy'])
    assert binding_config['model']['deformation']['use_rk2']
    assert binding_config['model']['deformation']['timepoints'] >= 19
    assert all(c.attempts == 0 for c in child.candidates) and not child.visual_reviews
    assert all(
        sha256_file(p) == digest for p, digest in protected.items() if p.name != study.STUDY_EVENTS
    )
    prepared = prepare_run(child.candidates[0].config_path, run_id="regional-stage-test")
    verify_prepared_run(prepared)
    assert (prepared / "input/regional/plan.json").is_file()
    if expected == "residual":
        assert plan["residual"]["inherited_fields_unchanged"]
        assert "initial_momenta" not in config["model"]["deformation"]
        model = ET.parse(prepared / "engine/model.xml")
        assert model.find("template/object/filename").text.endswith("residual-source.vtk")
    else:
        assert config['model']['deformation']['kernel_width'] == (
            base.plan.effective_values['deformation_kernel_width'])
        assert config['model']['deformation']['initial_momenta']
