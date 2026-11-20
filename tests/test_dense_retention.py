"""Retain patches must not depend on a sparse global sample or a p95 aggregate."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save, prepare, read_plan
from diffeoforge.regional_preservation import assess


def dense_plan(tmp_path):
    n = 51
    x, y = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    plane = np.c_[x.ravel(), y.ravel(), np.zeros(n * n)]
    i, j = np.meshgrid(np.arange(n - 1), np.arange(n - 1))
    a = (i * n + j).ravel()
    faces = np.vstack([np.c_[a, a + 1, a + n], np.c_[a + 1, a + n + 1, a + n]])
    v, f = cube()
    vertices = np.vstack([plane, v * .2 + [3, 0, 0], v * .2 + [6, 0, 0]])
    faces = np.vstack([faces, f + len(plane), f + len(plane) + len(v)])
    _save(tmp_path / "source.vtk", vertices, faces)
    _save(tmp_path / "target.vtk", vertices, faces)
    fixed = dict(shape="box", bounds=[-.1, 1.1, -.1, 1.1, -.1, .1],
                 center=[.5, .5, 0], radius=1., purpose="fixed", symptom="detail")
    problem = dict(center=[3, 0, 0], radius=.8, purpose="problem", symptom="detail")
    declaration = prepare(tmp_path / "plan", tmp_path / "source.vtk", tmp_path / "target.vtk",
                          [problem], focus_width=.2, focus_noise=.01, protection_noise=.02,
                          retained_path=tmp_path / "source.vtk", protection_halo=.1,
                          fixed_regions=[fixed])
    config = load_config(Path(__file__).parents[1] / "examples/minimal-atlas.yaml")
    config["project"]["parameter_provenance"] = dict(regional_fit=declaration)
    return config, vertices, faces


def test_retained_patch_has_every_vertex_and_separate_native_weight(tmp_path):
    config, points, _ = dense_plan(tmp_path)
    plan = read_plan(config)
    assert set(plan["fixed_vertex_ids"]) == set(range(51 * 51))
    assert len(plan["fixed_vertex_ids"]) > len(plan["protection_vertex_ids"])
    fixed = next(o for o in plan["objects"] if o["id"] == "fixed")
    ordinary = next(o for o in plan["objects"] if o["id"] == "protect")
    assert fixed["kind"] == "Landmark" and fixed["noise_std"] < ordinary["noise_std"]
    assert fixed["noise_std"] <= plan["fixed_protection"]["limit"] / 4
    assert plan["fixed_protection"]["vertices"] == 51 * 51
    assert not plan["fixed_protection"]["anatomical_approval"]
    assert sha256_file(tmp_path / "source.vtk") == plan["retained_reference"]["sha256"]


def test_collapse_between_global_samples_fails_dense_maximum_check(tmp_path):
    config, points, faces = dense_plan(tmp_path)
    plan = read_plan(config)
    identifier = next(i for i in plan["fixed_vertex_ids"]
                      if i not in plan["protection_vertex_ids"])
    moved = points.copy()
    moved[identifier, 2] += .1
    assert np.array_equal(moved[plan["protection_vertex_ids"]],
                          points[plan["protection_vertex_ids"]])
    result = assess(moved, points, faces, plan["fixed_regions"], plan["fixed_protection"]["limit"])
    assert not result["passed"] and result["maximum"] == .1
    assert result["checked_vertices"] == 51 * 51
    assert assess(points, points, faces, plan["fixed_regions"], result["limit"])["passed"]


def test_bound_declared_fixed_coverage_cannot_be_truncated(tmp_path):
    config, _, _ = dense_plan(tmp_path)
    entry = config["project"]["parameter_provenance"]["regional_fit"]
    path = Path(entry["manifest"])
    plan = read_plan(config)
    plan["fixed_vertex_ids"] = plan["fixed_vertex_ids"][:9]
    path.write_text(json.dumps(plan), encoding="utf-8")
    entry["sha256"] = sha256_file(path)
    with pytest.raises(ValueError, match="Retain-area protection"):
        read_plan(config)


def test_live_review_reports_the_same_protection_violation(tmp_path):
    from diffeoforge.pilot_live_review import fixed_preservation

    config, points, faces = dense_plan(tmp_path)
    plan = read_plan(config)
    points[plan["fixed_vertex_ids"][0], 2] += .1
    result = fixed_preservation(dict(manifest=dict(effective_config=config)), points, faces)
    assert result["available"] and not result["passed"]
    assert result["checked_vertices"] == 51 * 51 and result["maximum"] == .1
    assert not result["anatomical_approval"]


def test_legacy_preview_audits_whole_retained_patch_not_its_old_nine_points(tmp_path):
    from diffeoforge.pilot_live_review import fixed_preservation

    config, points, faces = dense_plan(tmp_path)
    plan = read_plan(config)
    plan.pop("fixed_protection")
    plan["objects"] = [o for o in plan["objects"] if o["id"] != "fixed"]
    plan["fixed_vertex_ids"] = plan["fixed_vertex_ids"][:9]
    entry = config["project"]["parameter_provenance"]["regional_fit"]
    Path(entry["manifest"]).write_text(json.dumps(plan), encoding="utf-8")
    entry["sha256"] = sha256_file(Path(entry["manifest"]))
    points[100, 2] += .1
    manifest = dict(effective_config=config,
                    inputs=[dict(role="subject", staged_path="target.vtk")],
                    protected_artifacts=[dict(path="target.vtk", sha256=sha256_file(
                        tmp_path / "target.vtk"))])
    result = fixed_preservation(dict(manifest=manifest, run=tmp_path), points, faces)
    assert result["available"] and result["legacy_objective"]
    assert not result["passed"] and result["checked_vertices"] == 51 * 51


@pytest.mark.parametrize("available,passed", [(True, False), (True, True), (False, False)])
def test_live_panel_warns_instead_of_implying_retain_area_is_preserved(
        tmp_path, monkeypatch, available, passed):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_full_review_geometry import model

    from diffeoforge.desktop.pilot_live_review import PilotLiveReviewPanel

    app = QApplication.instance() or QApplication([])
    panel = PilotLiveReviewPanel()
    panel._generation = "public-preview"
    bound = dict(receipt=dict(active_seconds=600, accepted_updates=427),
                 fixed_preservation=dict(available=available, passed=passed))
    try:
        panel._loaded("public-preview", (bound, (model(tmp_path / "a", True),
                                                model(tmp_path / "b", True))))
        assert panel.finish_button.isEnabled() and panel.continue_button.isEnabled()
        assert panel.note.objectName() == ("status" if passed else "statusWarning")
        assert ("within their declared" if passed else "has not passed" if available else
                "could not be verified") in panel.note.text()
        assert not panel._sent
    finally:
        panel.timer.stop()
        panel.close()
        app.processEvents()
