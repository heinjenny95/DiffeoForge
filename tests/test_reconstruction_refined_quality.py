"""Post-fit QC follows marked material through subdivision, without editing marks."""
from copy import deepcopy
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
