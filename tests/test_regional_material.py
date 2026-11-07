"""Public separated surfaces reproduce missing-tip/retained-neighbour conflicts."""

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge.regional_material_patch import select
from diffeoforge.regional_material_support import augment


def geometry():
    v, f = cube()
    source = np.vstack((v*.1+[-1., 0., 0.], v*.1))
    faces = np.vstack((f, f+8))
    target = v*.1+[.4, 0., 0.]
    return source, faces, target, f, [dict(center=[.4, 0., 0.], radius=.3)]


def test_absent_feature_never_uses_nearer_retained_neighbour_or_incident_faces():
    source, faces, target, tf, regions = geometry()
    chosen, proposals = select(source, faces, target, tf, regions, np.arange(8, 16))
    assert chosen[:12].all() and not chosen[12:].any()
    assert proposals[0]['source_faces'] == list(range(12))
    assert proposals[0]['source_patch_area'] == pytest.approx(proposals[0]['target_patch_area'])
    assert not proposals[0]['biological_correspondence_claim']
    other, evidence = select(source, faces, target, tf, regions, np.arange(8, 16))
    assert np.array_equal(chosen, other) and proposals == evidence


def test_insufficient_connected_material_and_no_free_material_fail_actionably():
    source, faces, target, tf, regions = geometry()
    with pytest.raises(ValueError, match='nearest free source patch is too small'):
        select(source, faces, target*2, tf,
               [dict(center=[.8, 0., 0.], radius=.6)], np.arange(8, 16))
    with pytest.raises(ValueError, match='No movable source surface'):
        select(source, faces, target, tf, regions, np.arange(16))
    with pytest.raises(ValueError, match='no movable surface'):
        select(source, faces, target, tf, regions, np.arange(8, 16), infer=False)


def test_direct_source_selection_excludes_entire_fixed_incident_triangles():
    source, faces, _, tf, _ = geometry()
    regions = [dict(center=[0., 0., 0.], radius=.3)]
    chosen, proposals = select(source, faces, source[8:], tf, regions, [8])
    assert chosen.any() and not np.isin(faces[chosen], [8]).any() and not proposals
    with pytest.raises(ValueError, match='guides overlap a Retain area'):
        select(source, faces, source[8:], tf, regions, [8], infer=False)


def test_protected_capture_grows_partial_brush_without_changing_default_or_guides():
    source, faces, target, tf, regions = geometry()
    source[8:] += [.2, 0., 0.]
    original = source.copy()
    legacy, old = select(source, faces, target, tf, regions, np.arange(8))
    assert 0 < legacy.sum() < 12 and not old
    chosen, proposals = select(source, faces, target, tf, regions, np.arange(8),
                               extend_partial=True)
    assert not chosen[:12].any() and chosen[12:].all()
    assert proposals[0]['partial_brush_extended']
    assert proposals[0]['initial_brush_area'] < proposals[0]['target_patch_area']
    assert proposals[0]['source_patch_area'] == pytest.approx(proposals[0]['target_patch_area'])
    repeated, evidence = select(source, faces, target, tf, regions, np.arange(8),
                                extend_partial=True)
    assert np.array_equal(chosen, repeated) and proposals == evidence
    guided, proof = select(source, faces, target, tf, regions, np.arange(8),
                           infer=False, extend_partial=True)
    assert np.array_equal(guided, legacy) and not proof
    assert np.array_equal(source, original)


def test_partial_growth_cannot_jump_to_another_free_component_or_consume_retain():
    source, faces, target, tf, regions = geometry()
    source[8:] += [.2, 0., 0.]
    larger = (target - [.4, 0., 0.])*1.3 + [.4, 0., 0.]
    with pytest.raises(ValueError, match='nearest free source patch is too small'):
        select(source, faces, larger, tf, regions, extend_partial=True)
    # An explicit Retain overlap keeps the existing brush scope: no inferred
    # replacement patch can quietly acquire fixed material or another component.
    legacy, _ = select(source, faces, target, tf, regions, [8])
    chosen, proof = select(source, faces, target, tf, regions, [8], extend_partial=True)
    assert np.array_equal(chosen, legacy) and not proof
    assert not np.isin(faces[chosen], [8]).any()


def test_only_new_protected_capture_preparation_extends_partial_material(tmp_path):
    from diffeoforge.regional_fit import _save, prepare, read_plan

    source, faces, target, tf, regions = geometry()
    source[8:] += [.2, 0., 0.]
    _save(tmp_path/'source.vtk', source, faces)
    _save(tmp_path/'target.vtk', target, tf)
    fixed = [dict(center=[-1., 0., 0.], radius=.3, purpose='fixed')]

    def stage(name, capture_profile):
        declaration = prepare(tmp_path/name, tmp_path/'source.vtk', tmp_path/'target.vtk',
            regions, fixed_regions=fixed, retained_path=tmp_path/'source.vtk',
            focus_width=.1, focus_noise=.02, protection_noise=.01,
            capture_profile=capture_profile)
        config = dict(project=dict(parameter_provenance=dict(regional_fit=declaration)))
        return read_plan(config)

    old = stage('legacy', False)
    old_bytes = (tmp_path/'legacy/regional-plan.json').read_bytes()
    current = stage('capture', True)
    assert len(old['material_selection']['source_faces']) < 12
    assert len(current['material_selection']['source_faces']) == 12
    assert current['material_selection']['inferred_patches'][0]['partial_brush_extended']
    assert not np.isin(faces[current['material_selection']['source_faces']], current['fixed_vertex_ids']).any()
    assert (tmp_path/'legacy/regional-plan.json').read_bytes() == old_bytes


def test_actual_material_coverage_retains_old_controls_same_spacing_and_fails_at_budget():
    old = np.array([[0., 0., 0.], [1., 1., 1.]])
    material = np.array([[3.01, 2.02, 1.03], [3.11, 2.22, 1.33]])
    q, evidence = augment(old, material, .1, [-1., -1., -1.])
    assert all(any(np.array_equal(x, y) for y in q) for x in old)
    nearest = np.linalg.norm(material[:, None]-q[None], axis=2).min(1)
    assert nearest.max() <= evidence['maximum_material_support_distance']+1e-12
    assert evidence['spacing'] == .1 and evidence['movement_scale_unchanged']
    with pytest.raises(ValueError, match='exceeds the residual control limit'):
        augment(old, material, .1, [-1., -1., -1.], limit=2)
    assert np.array_equal(old, [[0., 0., 0.], [1., 1., 1.]])
