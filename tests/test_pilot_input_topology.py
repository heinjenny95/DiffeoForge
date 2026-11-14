"""Cached input guidance tests; no scientific fits or geometry parsing."""

import hashlib
import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from diffeoforge import pilot_input_topology as policy


def test_snapshot_hint_reads_only_selected_pair_and_never_reverifies_chain(
    tmp_path, monkeypatch
):
    from diffeoforge import reference_calibration_study as study

    a, da, _ = write_cached(tmp_path, name="a.vtk")
    b, db, _ = write_cached(tmp_path, name="b.vtk", payload=b"else")
    manifest = dict(
        inputs=dict(
            template=dict(copy=a.name, sha256=da),
            subjects=[dict(copy=b.name, sha256=db)],
        )
    )
    monkeypatch.setattr(
        study, "_verify_manifest", lambda _: pytest.fail("Ancestor verification")
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path, plan=SimpleNamespace(pilot_subject_count=1)
    )
    assert (
        policy.prepare_for_snapshot(snapshot, manifest, cache_roots=[tmp_path])[
            "status"
        ]
        == "no_difference_detected_in_cached_counts"
    )
    manifest["inputs"]["subjects"].append(
        dict(copy="must-not-load.vtk", sha256="0" * 64)
    )
    assert (
        policy.prepare_for_snapshot(snapshot, manifest, cache_roots=[tmp_path])[
            "status"
        ]
        == "unknown"
    )


def test_multi_subject_scope_never_reads_manifest_or_hashes_meshes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        policy, "_digest_file", lambda _: pytest.fail("Whole cohort hash")
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path, plan=SimpleNamespace(pilot_subject_count=6)
    )
    assert (
        policy.prepare_for_snapshot(snapshot, {}, cache_roots=[])["status"] == "unknown"
    )


def test_inconsistent_typed_cached_counts_stay_unknown(tmp_path, monkeypatch):
    from diffeoforge import mesh_inspection_cache

    path, digest, _ = write_cached(tmp_path)
    meta, quality = mesh_inspection_cache.vtk_check(path, digest, [tmp_path])
    monkeypatch.setattr(
        mesh_inspection_cache,
        "vtk_check",
        lambda *a, **k: (meta, replace(quality, euler_characteristic=99)),
    )
    assert policy.load_cached(path, digest, [tmp_path]) is None


def test_default_cache_roots_are_explicit_not_recent_project_scan(
    tmp_path, monkeypatch
):
    from diffeoforge.desktop import recent_projects

    a, da, _ = write_cached(tmp_path, name="a.vtk")
    b, db, _ = write_cached(tmp_path, name="b.vtk", payload=b"else")
    original = tmp_path / "project/atlas.yaml"
    store = tmp_path / "settings/recent.json"
    manifest = dict(
        inputs=dict(
            template=dict(copy=a.name, sha256=da),
            subjects=[dict(copy=b.name, sha256=db)],
        ),
        source_config=dict(original_path=str(original)),
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path, plan=SimpleNamespace(pilot_subject_count=1)
    )
    monkeypatch.setattr(recent_projects, "default_store_path", lambda: store)
    monkeypatch.setattr(
        recent_projects, "load_recent_projects", lambda: pytest.fail("Project scan")
    )
    roots = []

    def selected(*args):
        roots.extend(args[-1])
        return policy.triage(None, None)

    monkeypatch.setattr(policy, "selected_pair", selected)
    policy.prepare_for_snapshot(snapshot, manifest)
    assert roots == [tmp_path, original.parent, store.parent / "cache/mesh-inspections"]


def test_selected_input_cannot_escape_study(tmp_path):
    outside = tmp_path.parent / "outside.vtk"
    outside.write_bytes(b"same")
    manifest = dict(
        inputs=dict(
            template=dict(copy="../outside.vtk", sha256="a" * 64),
            subjects=[dict(copy="../outside.vtk", sha256="a" * 64)],
        )
    )
    snapshot = SimpleNamespace(
        study_directory=tmp_path, plan=SimpleNamespace(pilot_subject_count=1)
    )
    with pytest.raises(ValueError, match="escapes"):
        policy.prepare_for_snapshot(snapshot, manifest, cache_roots=[])


def test_background_guidance_prepares_hint_once_before_many_options(monkeypatch):
    from diffeoforge import guided_strategy, reference_guided_pilot
    from diffeoforge.desktop import pilot_view_preparation as view

    snapshot = SimpleNamespace(current_stage=SimpleNamespace(order=1))
    manifest = object()
    hint = dict(status="unknown")
    calls = []
    monkeypatch.setattr(reference_guided_pilot, "record", lambda s: {"phase": "screen"})
    monkeypatch.setattr(
        guided_strategy, "state", lambda s: dict(options=list(range(40)))
    )

    def prepare(s, m):
        assert s is snapshot and m is manifest
        calls.append("hint")
        return hint

    def previews(s, context):
        for _ in context["options"]:
            assert context["input_topology"] is hint
        calls.append("options")
        return context

    monkeypatch.setattr(policy, "prepare_for_snapshot", prepare)
    monkeypatch.setattr(guided_strategy, "prepare_proposals", previews)
    result = view._guidance(snapshot, manifest)
    assert result["input_topology"] is hint and calls == ["hint", "options"]
    view._guidance(snapshot, manifest)
    assert calls == ["hint", "options", "hint", "options"]


def test_disclosure_expands_warning_navigation_only_and_never_does_io(monkeypatch):
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from diffeoforge.desktop import guided_diagnosis
    from diffeoforge.desktop.guided_input_checks import input_checks

    app = QApplication.instance() or QApplication([])
    window = object()
    reference = object()
    calls = []
    monkeypatch.setattr(
        guided_diagnosis, "inspect_inputs", lambda w, r: calls.append((w, r))
    )
    monkeypatch.setattr(
        policy, "load_cached", lambda *a, **k: pytest.fail("Qt cache IO")
    )
    panel = QWidget()
    layout = QVBoxLayout(panel)
    hint = policy.triage(evidence(0), evidence(2))
    disclosure = input_checks(window, layout, dict(input_topology=hint), reference)
    assert disclosure.toggle_button.isChecked()
    buttons = [
        b
        for b in disclosure.findChildren(QPushButton)
        if b is not disclosure.toggle_button
    ]
    assert len(buttons) == 1 and "border:" in buttons[0].styleSheet()
    assert all(label.wordWrap() for label in disclosure.findChildren(QLabel))
    buttons[0].click()
    assert calls == [(window, reference)]
    panel.close()
    app.processEvents()


def test_unknown_disclosure_stays_collapsed_and_core_has_no_qualified_report_loader():
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    from diffeoforge.desktop.guided_input_checks import input_checks

    app = QApplication.instance() or QApplication([])
    panel = QWidget()
    disclosure = input_checks(
        object(),
        QVBoxLayout(panel),
        dict(input_topology=policy.triage(None, None)),
        None,
    )
    assert not disclosure.toggle_button.isChecked()
    assert not hasattr(policy, "load_qualified_closed_proof")
    panel.close()
    app.processEvents()


def evidence(chi=2, *, components=1, isolated=0, digest="a" * 64, **changes):
    # Generic count fixture only; it is not claimed to be a mesh or a genus proof.
    values = dict(
        sha256=digest,
        definitions_version="0.1",
        points=4 + isolated,
        triangles=4,
        unique_edges=8 - chi,
        isolated_vertices=isolated,
        euler_characteristic=chi + isolated,
        face_components=components,
        boundary_edges=0,
        manifold_edges=8 - chi,
        nonmanifold_edges=0,
        inconsistent_winding_edges=0,
        duplicate_faces=0,
        zero_area_faces=0,
        connectivity_sha256="c" * 64,
    )
    values.update(changes)
    return policy.Evidence(**values)


def write_cached(tmp_path, payload=b"same", *, name="sample.vtk", chi=2):
    from diffeoforge.mesh import MeshMetadata
    from diffeoforge.mesh_quality import MeshQualityResult, MetricSummary
    from diffeoforge.project_checkpoint import save_checkpoint

    path = tmp_path / name
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    meta = MeshMetadata(
        str(path),
        len(payload),
        digest,
        "3.0",
        "ASCII",
        "POLYDATA",
        4,
        4,
        True,
        (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        3**0.5,
    )
    q = MetricSummary(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    quality = MeshQualityResult(
        points=4,
        triangles=4,
        unique_edges=8 - chi,
        connectivity_sha256="c" * 64,
        isolated_vertices=0,
        duplicate_faces=0,
        boundary_edges=0,
        manifold_edges=8 - chi,
        nonmanifold_edges=0,
        face_connected_components=1,
        euler_characteristic=chi,
        inconsistently_oriented_manifold_edges=0,
        zero_area_faces=0,
        zero_length_edge_faces=0,
        undefined_angle_faces=0,
        bounding_box_diagonal=3**0.5,
        total_surface_area=4.0,
        minimum_area_over_bbox_diagonal_squared=0.1,
        triangle_area=q,
        minimum_angle_degrees=q,
        edge_ratio=q,
    )
    key = "vtk-1-" + hashlib.sha256(f"{digest}:0.1".encode()).hexdigest()
    save_checkpoint(tmp_path, key, (meta, quality))
    return path, digest, tmp_path / ".diffeoforge/checks" / (key + ".json")


def test_different_euler_is_only_potential_and_never_global_trial_block():
    hint = policy.triage(evidence(0), evidence(2, digest="b" * 64))
    assert hint["status"] == "potential_structure_mismatch"
    assert hint["confirmed_component_genera"] is None and not hint["automatic_approval"]
    assert (
        not hint["block_all_geometry_trials"]
        and hint["external_geometry_trials_remain_available"]
    )
    assert not hint["local_region_irreducibility_inferred"]


def test_isolated_vertices_are_removed_from_euler_comparison_but_disclosed():
    hint = policy.triage(evidence(2), evidence(2, isolated=1))
    assert not hint["reasons"] and hint["status"] == "input_review_needed"
    assert "isolated_vertices" in hint["input_review_issues"]


def test_component_change_is_potential_structure_mismatch():
    hint = policy.triage(evidence(), evidence(components=2))
    assert "different_connected_surface_part_counts" in hint["reasons"]


def test_open_boundary_presence_is_potential_not_exact_genus():
    opened = evidence(boundary_edges=3, manifold_edges=3)
    hint = policy.triage(evidence(), opened)
    assert (
        "one_surface_has_open_boundaries" in hint["reasons"]
        and hint["confirmed_component_genera"] is None
    )
    assert policy.triage(opened, opened)["status"] == "open_surface_comparison_limited"


@pytest.mark.parametrize(
    "changes",
    [
        dict(nonmanifold_edges=1, manifold_edges=5),
        dict(inconsistent_winding_edges=1),
        dict(duplicate_faces=1),
        dict(zero_area_faces=1),
    ],
)
def test_input_flags_direct_to_inspection_without_false_approval(changes):
    hint = policy.triage(evidence(), evidence(**changes))
    assert hint["status"] == "unknown" and hint["input_review_recommended"]
    assert not hint["automatic_approval"] and not hint["block_all_geometry_trials"]


def test_unsafe_counts_never_turn_euler_difference_into_structure_claim():
    hint = policy.triage(evidence(0), evidence(2, inconsistent_winding_edges=1))
    assert hint["status"] == "unknown" and hint["confirmed_component_genera"] is None


def test_rule_mismatch_stays_unknown():
    hint = policy.triage(evidence(), evidence(definitions_version="future"))
    assert hint["status"] == "unknown"


def test_raw_resolution_counts_are_not_topology_differences():
    a = evidence()
    # Different V/E/F with the same used Euler/components/closed-state must not warn.
    b = replace(a, points=10, unique_edges=24, triangles=16, manifold_edges=24)
    assert policy.triage(a, b)["status"] == "no_difference_detected_in_cached_counts"


def test_equal_cached_counts_are_not_topology_or_anatomy_certification():
    hint = policy.triage(evidence(), evidence(digest="b" * 64))
    assert hint["status"] == "no_difference_detected_in_cached_counts"
    assert (
        "do not prove" in hint["message"] and hint["confirmed_component_genera"] is None
    )


def test_absent_cache_is_unknown_without_work_launch():
    assert policy.triage(None, evidence())["status"] == "unknown"


def test_inconsistent_count_packet_is_rejected():
    with pytest.raises(ValueError):
        evidence(unique_edges=999)
    with pytest.raises(ValueError):
        evidence(face_components=True)


def test_real_typed_cache_reused_without_geometry_parse(tmp_path, monkeypatch):
    import diffeoforge.surface_io as io

    path, digest, _ = write_cached(tmp_path)
    monkeypatch.setattr(
        io, "load_surface_mesh", lambda *a, **k: pytest.fail("Geometry parsed")
    )
    value = policy.load_cached(path, digest, [tmp_path])
    assert value.sha256 == digest and value.used_euler == 2


def test_corrupt_or_absent_cache_is_unknown_without_revalidation(tmp_path, monkeypatch):
    import diffeoforge.surface_io as io

    path, digest, cache = write_cached(tmp_path)
    monkeypatch.setattr(
        io, "load_surface_mesh", lambda *a, **k: pytest.fail("Geometry parsed")
    )
    doc = json.loads(cache.read_text())
    doc["sha256"] = "0" * 64
    cache.write_text(json.dumps(doc))
    assert policy.load_cached(path, digest, [tmp_path]) is None
    assert policy.load_cached(path, digest, []) is None


def test_same_size_same_mtime_content_change_rejected(tmp_path):
    path, digest, _ = write_cached(tmp_path)
    info = path.stat()
    path.write_bytes(b"else")
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(ValueError, match="content changed"):
        policy.load_cached(path, digest, [tmp_path])


def test_file_replacement_during_hash_rejected(tmp_path, monkeypatch):
    path, digest, _ = write_cached(tmp_path)
    original = policy._digest_file

    def replace_during_read(p):
        result = original(p)
        replacement = p.with_suffix(".replacement")
        replacement.write_bytes(p.read_bytes())
        replacement.replace(p)
        return result

    monkeypatch.setattr(policy, "_digest_file", replace_during_read)
    with pytest.raises(ValueError, match="identity changed"):
        policy.load_cached(path, digest, [tmp_path])


def test_pair_is_loaded_once_then_40_presentation_uses_do_no_io(tmp_path, monkeypatch):
    a, da, _ = write_cached(tmp_path, name="a.vtk")
    b, db, _ = write_cached(tmp_path, name="b.vtk", payload=b"else")
    original = policy._digest_file
    calls = []

    def observe(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(policy, "_digest_file", observe)
    hint = policy.selected_pair(a, b, da, db, [tmp_path])
    assert len(calls) == 2
    for _ in range(40):
        assert hint["status"] == "no_difference_detected_in_cached_counts"
    assert len(calls) == 2
    policy.selected_pair(a, b, da, db, [tmp_path])
    assert len(calls) == 4
