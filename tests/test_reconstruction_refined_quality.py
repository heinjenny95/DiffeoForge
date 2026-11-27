"""Post-fit QC follows marked material through subdivision, without editing marks."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_reconstruction_feedback import bridge
from test_reconstruction_material_lineage import stage

from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_regions import measure
from diffeoforge.reconstruction_material_lineage import from_evaluation
from diffeoforge.regional_quality import _distances


def refined_bridge(tmp_path):
    _, fit_path, original, fit, row = bridge(tmp_path)
    root = dict(reference_source=dict(path=str(fit_path), sha256=sha256_file(fit_path)),
                prefix=None)
    receipt, vertices, faces, parents = stage(
        tmp_path, root, fit.vertices, fit.triangles,
        row['reconstruction']['face_ids'], 'subdivided')
    moved = SimpleNamespace(vertices=vertices+[0, 0, .15], triangles=faces)
    return original, fit, moved, row, receipt, parents


def test_both_postfit_consumers_follow_children_of_the_same_inspected_faces(tmp_path):
    original, fit, refined, row, receipt, parents = refined_bridge(tmp_path)
    saved = deepcopy(row)
    with pytest.raises(ValueError, match='connectivity changed'):
        measure(original, refined, [row])

    lineage = from_evaluation(receipt)
    actual, = measure(original, refined, [row], material_lineage=lineage)
    old = np.zeros(len(fit.triangles), bool)
    old[row['reconstruction']['face_ids']] = True
    descendants = int(old[parents].sum())
    assert descendants > old.sum()
    assert actual['reverse_selected_faces'] == descendants
    assert actual['region'] == row == saved
    assert all(r['forward_count'] == 0 and r['reverse_count'] == 2048
               and r['fit_to_original_p95'] > .15 for r in actual['repeats'])

    # Regional QC samples the declared original support and the SAME transported
    # reconstruction faces. The forward distance of these parallel planes is known.
    target_ids = list(range(len(original.triangles)))
    checked = _distances(original.vertices, original.triangles,
        refined.vertices, refined.triangles, [row], target_face_ids=target_ids,
        material_lineage=lineage)
    assert len(checked) == 2
    assert all(np.isclose(r['original_to_fit_mean'], .15)
               and r['fit_to_original_mean'] > .15 for r in checked)
    assert row == saved


def test_rejected_ancestry_still_blocks_postfit_measurement(tmp_path):
    original, _, refined, row, receipt, _ = refined_bridge(tmp_path)
    lineage = from_evaluation(receipt)
    forged = deepcopy(row)
    forged['reconstruction']['topology_sha256'] = 'f'*64
    with pytest.raises(ValueError, match='ancestor'):
        measure(original, refined, [forged], material_lineage=lineage)
    with pytest.raises(ValueError, match='current grid'):
        measure(original, SimpleNamespace(vertices=refined.vertices,
                                         triangles=refined.triangles[::-1]),
                [row], material_lineage=lineage)

    # Verification is live, including after an operation-local object was built.
    path = receipt['material_lineage']['stages'][0]['parent_faces']['path']
    parents = np.load(path)
    parents[0] = (int(parents[0])+1) % 800
    np.save(path, parents)
    with pytest.raises(ValueError, match='evidence changed'):
        measure(original, refined, [row], material_lineage=lineage)


def test_inherited_mark_prepares_and_follows_the_exact_faces_in_the_next_fit(tmp_path):
    from diffeoforge.reconstruction_feedback import material_mask
    from diffeoforge.reconstruction_material_lineage import on_staged_grid, starting_evidence
    from diffeoforge.regional_fit import prepare, read_plan
    from diffeoforge.regional_warm_support import assess
    from diffeoforge.surface_io import load_surface_mesh

    _, fit, _, mark, inspected, parents = refined_bridge(tmp_path)
    saved_mark = deepcopy(mark)
    grid = Path(inspected["reference_source"]["path"])
    refined = load_surface_mesh(grid).geometry
    source = np.isin(parents, mark["reconstruction"]["face_ids"])
    expected_vertices = np.unique(np.asarray(refined.triangles)[source])
    evidence = starting_evidence(inspected["reference_source"], {}, inspected)
    controls = tmp_path / "controls.txt"
    np.savetxt(controls, np.asarray(refined.vertices)[expected_vertices])
    record = dict(refinement=dict(initialization="learned"),
                  controls=dict(copy=controls.name, sha256=sha256_file(controls)))
    residual = dict(control_coverage=dict(version="source-target-coverage-v1",
                                          maximum_local_support_distance=.001))
    target = tmp_path / "original.vtk"
    support = assess(tmp_path, record, residual, grid, grid, grid, target, [mark], [],
                     material_evaluation=evidence)
    assert support["passed"] and support["material_vertices"] == len(expected_vertices)

    local = prepare(tmp_path / "next", grid, target, [mark], focus_width=.2, focus_noise=.1,
                    protection_noise=.1, retained_path=grid, material_evaluation=evidence)
    plan = read_plan(dict(project=dict(parameter_provenance=dict(regional_fit=local))))
    assert plan["focus_regions"] == [saved_mark]
    assert plan["material_selection"]["source_faces"] == np.flatnonzero(source).tolist()
    assert len(plan["focus_target_face_ids"]) > 0  # The original has a hole inside this brush.
    assert plan["reconstruction_target_support"][0]["biological_correspondence_claim"] is False

    # The scientific run stages a byte-identical original grid at a new path.
    # A second round of subdivision must retain both generations of face ancestry.
    staged = tmp_path / "staged-original.vtk"
    staged.write_bytes(grid.read_bytes())
    info = dict(path=str(staged), sha256=sha256_file(staged))
    incoming = dict(reference_source=info, prefix=dict(reference_source=info, prefix=None))
    rebound = on_staged_grid(incoming, plan["starting_material_lineage"])
    final, v, f, p2 = stage(tmp_path, rebound, np.asarray(refined.vertices),
                            np.asarray(refined.triangles), np.flatnonzero(source)[:2],
                            "second-refinement")
    for receipt in (final, final["prefix"]):
        chosen = material_mask(v, f, [mark], lineage=from_evaluation(receipt))
        np.testing.assert_array_equal(chosen, source[p2])
    assert len(final["material_lineage"]["stages"]) == 2
    assert inspected["material_lineage"]["current"]["path"] == str(grid)
    assert len(fit.triangles) < len(refined.triangles) and mark == saved_mark
    assert "material_lineage" not in incoming

    staged.write_bytes(staged.read_bytes() + b" ")
    with pytest.raises(ValueError, match="evidence changed"):
        on_staged_grid(incoming, plan["starting_material_lineage"])
    assert starting_evidence(dict(sha256="f" * 64), inspected) is None


def test_original_only_successor_keeps_old_reconstruction_patch_for_later_review(
        tmp_path, monkeypatch):
    from diffeoforge import (
        config,
        reference_fixed_shooting,
        regional_evaluation,
        regional_quality,
        source_refinement,
    )
    from diffeoforge.reconstruction_feedback import material_mask
    from diffeoforge.reconstruction_material_lineage import starting_evidence
    from diffeoforge.regional_fit import prepare, read_plan
    from diffeoforge.surface_io import load_surface_mesh

    _, _, _, mark, inspected, parents = refined_bridge(tmp_path)
    grid = Path(inspected["reference_source"]["path"])
    copied = tmp_path / "original-source-grid.vtk"
    copied.write_bytes(grid.read_bytes())
    expected = np.isin(parents, mark["reconstruction"]["face_ids"])
    original_only = {k: v for k, v in mark.items() if k != "reconstruction"}
    original_only["center"] = [.75, 0, 0]
    local = prepare(tmp_path / "original-only", copied, tmp_path / "original.vtk", [original_only],
                    focus_width=.2, focus_noise=.1, protection_noise=.1, retained_path=copied,
                    material_evaluation=starting_evidence(inspected["reference_source"], inspected))
    settings = dict(input=dict(subject_pattern="original.vtk"),
                    project=dict(parameter_provenance=dict(regional_fit=local)))
    plan = read_plan(settings)
    for key in ("retained_run", "automatic_reference_run"):
        run = tmp_path / key
        run.mkdir()
        (run / "manifest.json").write_text("{}")
        plan[key] = dict(path=str(run), manifest_sha256=sha256_file(run / "manifest.json"))
    monkeypatch.setattr(config, "load_config", lambda _: settings)
    monkeypatch.setattr(config, "validate_input_paths", lambda *_: SimpleNamespace(
        template=copied, input_directory=tmp_path))
    monkeypatch.setattr(regional_quality, "read_plan", lambda _: plan)

    # Deterministic identity fields on the staged material for all three runs.
    def evaluate(run, destination, *, count=73, _source=None, **kwargs):
        destination.mkdir(parents=True)
        grid = Path(_source or copied)
        identity = dict(path=str(grid), sha256=sha256_file(grid))
        return dict(source_run=str(run), reference_source=identity, endpoint=identity,
                    prefix=None, timepoints=count)

    monkeypatch.setattr(regional_evaluation, "evaluate", evaluate)
    monkeypatch.setattr(reference_fixed_shooting, "movement", lambda *_: {"maximum": 0.})
    monkeypatch.setattr(source_refinement, "refine_evaluation",
                        lambda run, receipt, *a, **k: receipt)
    checked = regional_quality.evaluate_and_measure(
        tmp_path / "qc", dict(attachment_comparison=dict(regional_objective=True)),
        SimpleNamespace(candidate_id="test", config_path=tmp_path / "atlas.yaml"), tmp_path / "run")
    geometry = load_surface_mesh(copied).geometry
    for key in ("evaluation", "baseline_evaluation", "automatic_baseline_evaluation"):
        # A later edit may reinstate the old reconstruction mark after the intervening
        # correction used only original geometry. All reviewed references keep its exact IDs.
        lineage = from_evaluation(checked[key])
        actual = material_mask(geometry.vertices, geometry.triangles, [mark], lineage=lineage)
        np.testing.assert_array_equal(actual, expected)
