"""Exact refined face support, independent of deformed endpoint positions."""

from copy import deepcopy

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import reconstruction_material_lineage as lineage
from diffeoforge.mesh import sha256_file
from diffeoforge.reconstruction_feedback import topology_sha256
from diffeoforge.regional_fit import _save
from diffeoforge.source_refinement import subdivide


def stage(root, before, vertices, faces, chosen, name):
    folder = root / name
    folder.mkdir()
    selected = np.zeros(len(faces), bool)
    selected[chosen] = True
    refined, triangles, parents = subdivide(vertices, faces, selected)
    split = faces[selected]
    edges = np.unique(np.sort(np.concatenate(
        (split[:, [0, 1]], split[:, [1, 2]], split[:, [2, 0]])), axis=1), axis=0)
    grid = folder / "grid.vtk"
    _save(grid, refined, triangles)
    parent_path, edge_path = folder / "parents.npy", folder / "edges.npy"
    np.save(parent_path, parents)
    np.save(edge_path, edges)
    after = dict(reference_source=dict(path=str(grid), sha256=sha256_file(grid)), prefix=None)
    if before.get("prefix"):
        after["prefix"] = dict(before["prefix"],
                               reference_source=deepcopy(after["reference_source"]))
    result = lineage.append_stage(before, after, parent_path, edge_path,
                                  old_geometry=(vertices, faces),
                                  new_geometry=(refined, triangles))
    return result, refined, triangles, parents


@pytest.fixture
def chain(tmp_path):
    vertices, faces = map(np.asarray, cube())
    grid = tmp_path / "original.vtk"
    _save(grid, vertices, faces)
    root = dict(reference_source=dict(path=str(grid), sha256=sha256_file(grid)), prefix=None)
    first, v1, f1, p1 = stage(tmp_path, root, vertices, faces, [0, 3], "first")
    last, v2, f2, p2 = stage(tmp_path, first, v1, f1, [0, 1, 2], "second")
    return dict(root=root, first=first, last=last, vertices=(vertices, v1, v2),
                faces=(faces, f1, f2), parents=(p1, p2))


def evidence(vertices, faces, ids):
    return dict(sha256="a" * 64, topology_sha256=topology_sha256(vertices, faces),
                face_ids=ids)


def resign(row):
    from pathlib import Path

    path = Path(row["path"])
    row.update(sha256=sha256_file(path), bytes=path.stat().st_size)


def test_old_evaluation_without_lineage_keeps_exact_topology_policy():
    assert lineage.from_evaluation({}) is None
    assert lineage.from_evaluation(dict(source_refinement=dict(stages=[]))) is None


def test_multistage_support_follows_exact_ancestor_children_without_moving_mark(chain):
    obj = lineage.from_evaluation(chain["last"])
    v, f, parents = chain["vertices"], chain["faces"], chain["parents"]
    for start, selected_ids in ((0, [0, 4]), (1, [0, 2, 3]), (2, [0, 1])):
        mark = evidence(v[start], f[start], selected_ids)
        original = deepcopy(mark)
        expected = np.zeros(len(f[start]), bool)
        expected[selected_ids] = True
        for mapping in parents[start:]:
            expected = expected[mapping]
        # Arbitrary endpoint displacement changes geometry but not material IDs.
        actual = obj.material_mask(v[-1] + [5, -2, 8], f[-1], mark)
        np.testing.assert_array_equal(actual, expected)
        assert actual.dtype == bool and mark == original
    assert all(not p.flags.writeable for p in obj._parents)


def test_shared_material_prefixes_require_both_the_sealed_root_and_exact_endpoint(chain):
    current = lineage.from_evaluation(chain["last"])
    grid = chain["last"]["material_lineage"]
    valid_root = grid["root"]["sha256"]
    topology = grid["current"]["topology_sha256"]
    prefixes = current.shared_vertex_prefixes(valid_root, topology)
    assert prefixes[valid_root] == len(chain["vertices"][0])
    assert prefixes[grid["current"]["sha256"]] == len(chain["vertices"][-1])
    assert current.shared_vertex_prefixes("other-template", topology) == {}
    assert current.shared_vertex_prefixes(valid_root, "other-endpoint") == {}


def test_factory_and_mapping_do_not_rewrite_receipts_or_files(chain):
    original = deepcopy(chain["last"])
    obj = lineage.from_evaluation(chain["last"])
    obj.material_mask(chain["vertices"][-1], chain["faces"][-1],
                      evidence(chain["vertices"][0], chain["faces"][0], [0]))
    assert chain["last"] == original
    assert lineage.from_evaluation(chain["last"])


@pytest.mark.parametrize("at", ["before_root", "root", "second_grid", "proof", "second_stage"])
def test_cancellation_is_polled_between_grid_loads_and_proofs_without_mutation(
    chain, monkeypatch, at,
):
    from pathlib import Path

    receipt = deepcopy(chain["last"])
    before = deepcopy(receipt)
    state = dict(cancel=at == "before_root", grids=0, proofs=0)
    files = {row["path"]: sha256_file(Path(row["path"]))
             for step in receipt["material_lineage"]["stages"]
             for row in step.values()}
    checked, proof = lineage._checked_grid, lineage._verify_stage

    def grid(row):
        result = checked(row)
        state["grids"] += 1
        if (at == "root" and state["grids"] == 1
                or at == "second_grid" and state["grids"] == 2):
            state["cancel"] = True
        return result

    def verify(*args):
        proof(*args)
        state["proofs"] += 1
        if at == "proof":
            state["cancel"] = True

    events = []

    def progress(event):
        events.append(event)
        if at == "second_stage" and "stage 2 of" in event["message"]:
            state["cancel"] = True

    monkeypatch.setattr(lineage, "_checked_grid", grid)
    monkeypatch.setattr(lineage, "_verify_stage", verify)
    with pytest.raises(InterruptedError, match="saved fit and marks retained"):
        lineage.from_evaluation(receipt, cancelled=lambda: state["cancel"], event_callback=progress)
    assert receipt == before
    assert all(sha256_file(Path(path)) == digest for path, digest in files.items())
    assert all(e["event"] == "qualification_phase" for e in events)
    if at == "before_root":
        assert state["grids"] == state["proofs"] == 0 and not events
    elif at in {"root", "second_grid"}:
        assert state["proofs"] == 0
    else:
        assert state["proofs"] == 1


def test_mask_retains_cancellation_between_live_evidence_checks(chain):
    state = dict(cancel=False)
    obj = lineage.from_evaluation(chain["last"], cancelled=lambda: state["cancel"])
    mark = evidence(chain["vertices"][0], chain["faces"][0], [0])
    before = deepcopy(mark)
    state["cancel"] = True
    with pytest.raises(InterruptedError):
        obj.material_mask(chain["vertices"][-1], chain["faces"][-1], mark)
    assert mark == before


@pytest.mark.parametrize("change", ["different_current", "unknown_ancestor", "face_out_of_range"])
def test_unknown_or_wrong_grid_cannot_reinterpret_a_mark(chain, change):
    obj = lineage.from_evaluation(chain["last"])
    vertices, faces = chain["vertices"][-1], chain["faces"][-1]
    mark = evidence(chain["vertices"][0], chain["faces"][0], [0])
    if change == "different_current":
        faces = faces[::-1]
    elif change == "unknown_ancestor":
        mark["topology_sha256"] = "f" * 64
    else:
        mark["face_ids"] = [len(chain["faces"][0])]
    with pytest.raises(ValueError):
        obj.material_mask(vertices, faces, mark)


@pytest.mark.parametrize("change", ["missing_stage", "reordered", "current", "reference"])
def test_disconnected_or_relabelled_chain_is_rejected(chain, change):
    receipt = deepcopy(chain["last"])
    data = receipt["material_lineage"]
    if change == "missing_stage":
        data["stages"].pop(0)
    elif change == "reordered":
        data["stages"].reverse()
    elif change == "current":
        data["current"] = deepcopy(data["root"])
    else:
        receipt["reference_source"] = chain["root"]["reference_source"]
    with pytest.raises(ValueError):
        lineage.from_evaluation(receipt)


@pytest.mark.parametrize("after_verification", [False, True])
def test_changed_or_missing_parent_map_is_rejected(chain, after_verification):
    from pathlib import Path

    obj = lineage.from_evaluation(chain["last"]) if after_verification else None
    path = Path(chain["last"]["material_lineage"]["stages"][0]["parent_faces"]["path"])
    path.unlink()
    with pytest.raises(ValueError, match="evidence changed"):
        if obj:
            obj.material_mask(chain["vertices"][-1], chain["faces"][-1],
                              evidence(chain["vertices"][0], chain["faces"][0], [0]))
        else:
            lineage.from_evaluation(chain["last"])


@pytest.mark.parametrize("change", ["wrong_parent", "short_map", "float_map", "midpoint",
                                     "old_vertex", "child_winding", "edge"])
def test_even_resigned_forged_subdivision_is_rejected(chain, change):
    receipt = deepcopy(chain["first"])
    step = receipt["material_lineage"]["stages"][0]
    if change in {"wrong_parent", "short_map", "float_map"}:
        row = step["parent_faces"]
        parents = np.load(row["path"])
        if change == "wrong_parent":
            parents[0] = (int(parents[0]) + 1) % len(chain["faces"][0])
        elif change == "short_map":
            parents = parents[:-1]
        else:
            parents = parents.astype(float)
        np.save(row["path"], parents)
        resign(row)
    elif change == "edge":
        row = step["split_edges"]
        edges = np.load(row["path"])
        edges[0] = [0, 0]
        np.save(row["path"], edges)
        resign(row)
    else:
        vertices, faces = chain["vertices"][1].copy(), chain["faces"][1].copy()
        if change == "midpoint":
            vertices[-1, 0] += .01
        elif change == "old_vertex":
            vertices[0, 0] += .01
        else:
            faces[0] = faces[0, ::-1]
        _save(step["new_grid"]["path"], vertices, faces)
        resign(step["new_grid"])
        step["new_grid"]["topology_sha256"] = topology_sha256(vertices, faces)
        receipt["material_lineage"]["current"] = deepcopy(step["new_grid"])
        receipt["reference_source"]["sha256"] = step["new_grid"]["sha256"]
    with pytest.raises(ValueError):
        lineage.from_evaluation(receipt)


def test_refinement_continuation_preserves_preceding_chain_and_prefix(chain, tmp_path):
    before = deepcopy(chain["first"])
    before["prefix"] = dict(reference_source=deepcopy(before["reference_source"]), prefix=None)
    # A temporal replay can retain the original grid and chain with a new endpoint.
    replay = deepcopy(before)
    replay["endpoint"] = dict(path="separate-temporal-replay.vtk")
    result, vertices, faces, _ = stage(tmp_path, replay, chain["vertices"][1],
                                      chain["faces"][1], [1], "continued")
    assert len(result["material_lineage"]["stages"]) == 2
    assert len(before["material_lineage"]["stages"]) == 1
    assert lineage.from_evaluation(result).material_mask(
        vertices, faces, evidence(chain["vertices"][0], chain["faces"][0], [0])).any()
    assert lineage.from_evaluation(result["prefix"])


def test_refine_evaluation_records_provable_lineage_without_an_optimizer(tmp_path, monkeypatch):
    from diffeoforge import regional_evaluation, source_refinement

    vertices, faces = map(np.asarray, cube())
    source, endpoint = tmp_path / "source.vtk", tmp_path / "endpoint.vtk"
    _save(source, vertices, faces)
    _save(endpoint, vertices + .2, faces)
    receipt = dict(source_run="synthetic-field", timepoints=73, controls_sha256="q",
                   momenta_sha256="p", prefix=None,
                   reference_source=dict(path=str(source), sha256=sha256_file(source)),
                   endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)))
    monkeypatch.setattr(source_refinement, "coarse_input_contacts", lambda *_: dict(clean=True))
    calls = []

    def selected(_receipt, _source, fitted, *_args, **_kwargs):
        chosen = np.zeros(len(fitted.triangles), bool)
        if not calls:
            chosen[0] = True
        calls.append(1)
        return chosen

    def evaluate_points(_run, points, destination, **_kwargs):
        destination.mkdir()
        path = destination / "endpoint.vtk"
        _save(path, points + .2)
        return dict(source_run="synthetic-field", timepoints=73, controls_sha256="q",
                    momenta_sha256="p", prefix=None,
                    endpoint=dict(path=str(path), sha256=sha256_file(path)))

    monkeypatch.setattr(source_refinement, "_selection", selected)
    monkeypatch.setattr(regional_evaluation, "evaluate_points", evaluate_points)
    result = source_refinement.refine_evaluation(
        "synthetic-field", receipt, tmp_path / "refinement",
        dict(guidance=False, focus_regions=[], objects=[dict(id="focus", kernel_width=.1)]),
        cancelled=lambda: False, event_callback=None)
    obj = lineage.from_evaluation(result)
    assert obj and len(result["material_lineage"]["stages"]) == 1
    assert "material_lineage" not in receipt
    assert sha256_file(source) == receipt["reference_source"]["sha256"]
