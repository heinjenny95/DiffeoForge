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
