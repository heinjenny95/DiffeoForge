from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import regional_joint_surface as joint
from diffeoforge.config import load_config
from diffeoforge.pilot_adaptive_run import _red_baseline
from diffeoforge.regional_fit import _save, apply_xml, prepare, read_plan
from diffeoforge.regional_quality import measure


def surfaces(tmp_path):
    vertices, faces = cube()
    centres = np.array([[-4, 0, 0], [0, 0, 0], [4, 0, 0], [0, 0, 4], [0, 0, -4]])
    source = np.vstack([vertices * scale + centre for centre, scale in
                        zip(centres, (.18, .3, .22, .2, .3), strict=True)])
    target = source.copy()
    target[:24, 1] += 1.3
    faces = np.vstack([faces + i * 8 for i in range(5)])
    red = [dict(center=(centre + [0, 1.3, 0]).tolist(), radius=.65, symptom="unsure")
           for centre in centres[:3]]
    fixed = dict(center=centres[3].tolist(), radius=.5, purpose="fixed", symptom="unsure")
    for name, points in (("source", source), ("target", target)):
        _save(tmp_path / f"{name}.vtk", points, faces)
    cfg = load_config(Path(__file__).parents[1] / "examples/minimal-atlas.yaml")
    cfg["input"].update(template=str(tmp_path / "source.vtk"), directory=str(tmp_path),
                        subject_pattern="target.vtk")
    cfg["optimization"].update(freeze_template=True, freeze_control_points=True)
    decl = prepare(tmp_path / "plan", tmp_path / "source.vtk", tmp_path / "target.vtk", red,
                   retained_path=tmp_path / "source.vtk", automatic_path=tmp_path / "source.vtk",
                   focus_width=.2, focus_noise=.05, protection_halo=.2, protection_noise=.01,
                   fixed_regions=[fixed], joint_surface=True)
    cfg["project"]["parameter_provenance"] = dict(regional_fit=decl)
    return cfg, red, fixed, source, target, faces


def test_three_missing_brushes_produce_independent_native_terms_and_real_two_way_errors(tmp_path):
    cfg, red, fixed, source, target, faces = surfaces(tmp_path)
    plan = read_plan(cfg)
    objects = [o for o in plan["objects"] if o["kind"] == "SurfaceMesh"]
    assert [o["region_index"] for o in objects] == [0, 1, 2]
    assert len({o["source"]["sha256"] for o in objects}) == 3
    assert len({o["target"]["sha256"] for o in objects}) == 3
    assert [o["target_area"] / o["noise_std"] for o in objects] == pytest.approx(
        [objects[0]["target_area"] / objects[0]["noise_std"]] * 3)
    assert min(o["kernel_width"] for o in objects) > 1.0
    model = ET.fromstring('<model><template><object id="surface"/></template></model>')
    data = ET.fromstring('<data-set><subject><visit/></subject></data-set>')
    apply_xml(cfg, model, data)
    assert [x.attrib["id"] for x in model.findall("template/object")] == [
        "surface", "focus", "focus2", "focus3", "protect", "fixed"]
    assert len(data.findall("subject/visit/filename")) == 5
    errors = joint.measure(SimpleNamespace(vertices=target, triangles=faces),
                           SimpleNamespace(vertices=source, triangles=faces), [*red, fixed])
    baseline = _red_baseline(dict(regions=[*red, fixed], baseline=errors))
    assert set(baseline) == {"R0", "R1", "R2"} and min(baseline.values()) > 1


def test_middle_alone_does_not_count_as_all_improved_and_fixed_motion_fails(tmp_path):
    cfg, _, _, source, target, faces = surfaces(tmp_path)
    middle = source.copy()
    middle[8:16] = target[8:16]
    _save(tmp_path / "middle.vtk", middle, faces)
    middle_q = measure(cfg, tmp_path / "middle.vtk")
    assert middle_q["joint_marks_improved_or_within_tolerance"] == [False, True, False]
    assert not middle_q["local_improved"]
    complete = measure(cfg, tmp_path / "target.vtk")
    assert complete["local_improved"] and complete["explicit_fixed_preserved"]
    moved = target.copy()
    moved[24:32, 0] += .02
    _save(tmp_path / "moved.vtk", moved, faces)
    bad = measure(cfg, tmp_path / "moved.vtk")
    assert not bad["numerical_selection_suitable"] and not bad["explicit_fixed_preserved"]


def test_nested_control_contrast_covers_only_the_two_unresolved_patches(tmp_path):
    _, red, fixed, source, target, faces = surfaces(tmp_path)
    middle = source.copy()
    middle[8:16] = target[8:16]
    initial = np.array([[0., 0., -4.], [0., 0., 4.]])
    additions, spacing, report = joint.control_additions(
        middle, faces, target, faces, [*red, fixed], [red[0], red[2]], initial, .5, 2000)
    assert spacing == .25 and report["marked_patches"] == 2
    assert (additions[:, 0] < -3).any() and (additions[:, 0] > 3).any()
    assert (abs(additions[:, 0]) > 3).all() and np.array_equal(initial[:, 2], [-4, 4])
