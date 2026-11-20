"""Baseline capture follows inherited reconstruction marks on a qualified refined fit."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from test_reconstruction_feedback import bridge
from test_reconstruction_material_lineage import stage

from diffeoforge import pilot_recovery, result_report
from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save


def capture_fixture(tmp_path, monkeypatch, kind='regional_quality'):
    original_path, fit_path, _, fit, mark = bridge(tmp_path)
    receipt, vertices, faces, parents = stage(
        tmp_path, dict(reference_source=dict(path=str(fit_path), sha256=sha256_file(fit_path)),
                       prefix=None), fit.vertices, fit.triangles,
        mark['reconstruction']['face_ids'], 'refinement')
    evaluated = tmp_path/'qualified-endpoint.vtk'
    _save(evaluated, vertices+[0, 0, .15], faces)
    receipt['endpoint'] = dict(path=str(evaluated), sha256=sha256_file(evaluated))
    run = tmp_path/'native-run'
    (run/'output').mkdir(parents=True)
    native = run/'output'/('DeterministicAtlas__Reconstruction__surface__subject_'
                           + original_path.name + '.vtk')
    native.write_bytes(fit_path.read_bytes())
    (tmp_path/study.STUDY_MANIFEST).write_text('{"synthetic": true}')
    manifest = dict(inputs=dict(subjects=[dict(filename=original_path.name,
                    copy=original_path.name, sha256=sha256_file(original_path))]),
                    attachment_comparison=dict(regional_objective=dict(version='synthetic')))
    subject = dict(diagonal=3., **{kind: dict(evaluation=receipt)})
    candidate = SimpleNamespace(candidate_id='retained', metrics=dict(
        attachment_comparison=dict(subjects={original_path.name: subject})))
    snapshot = SimpleNamespace(study_directory=tmp_path, candidates=(candidate,),
        problem_regions=dict(retained={original_path.name: [mark]}))
    report = SimpleNamespace(inventory=[dict(path=native.name, sha256=sha256_file(native))],
        manifest=dict(effective_config=dict(model=dict(object_id='surface'))))
    monkeypatch.setattr(study, '_verify_manifest', lambda root: manifest)
    monkeypatch.setattr(study, 'calibration_candidate_run_directory', lambda c: run)
    monkeypatch.setattr(study, '_candidate_review_binding', lambda c: dict(synthetic='binding'))
    monkeypatch.setattr(result_report, 'collect_run_report', lambda root: report)
    return snapshot, candidate, mark, receipt, parents


@pytest.mark.parametrize('kind', ['regional_quality', 'ordinary_quality', 'cohort_quality'])
def test_public_capture_measures_inherited_reconstruction_material_without_rewriting_it(
        tmp_path, monkeypatch, kind):
    snapshot, candidate, mark, _, parents = capture_fixture(tmp_path, monkeypatch, kind)
    target = next(iter(snapshot.problem_regions['retained']))
    before_mark, before_metrics = deepcopy(mark), deepcopy(candidate.metrics)
    identities = {p: sha256_file(p) for p in tmp_path.rglob('*') if p.is_file()}
    captured = pilot_recovery.capture(snapshot, 'retained', target)
    measured, = captured['baseline']
    selected = np.zeros(800, bool)
    selected[mark['reconstruction']['face_ids']] = True
    descendants = int(selected[parents].sum())
    assert descendants > int(selected.sum())
    assert measured['reverse_selected_faces'] == descendants
    assert all(row['forward_count'] == 0 and row['reverse_count'] == 2048
               and row['fit_to_original_p95'] > .15 for row in measured['repeats'])
    assert captured['regions'] == [mark] == [before_mark]
    assert measured['region'] == mark and candidate.metrics == before_metrics
    assert {p: sha256_file(p) for p in tmp_path.rglob('*') if p.is_file()} == identities


def test_public_capture_rejects_changed_ancestry_instead_of_remapping_by_proximity(
        tmp_path, monkeypatch):
    snapshot, _, mark, receipt, _ = capture_fixture(tmp_path, monkeypatch)
    from pathlib import Path

    path = Path(receipt['material_lineage']['stages'][0]['parent_faces']['path'])
    values = np.load(path)
    values[0] = (int(values[0])+1) % 800
    np.save(path, values)
    saved = deepcopy(mark)
    target = next(iter(snapshot.problem_regions['retained']))
    with pytest.raises(ValueError, match='evidence changed'):
        pilot_recovery.capture(snapshot, 'retained', target)
    assert mark == saved


def test_public_capture_rejects_ambiguous_qualified_endpoint(tmp_path, monkeypatch):
    snapshot, candidate, _, receipt, _ = capture_fixture(tmp_path, monkeypatch)
    target = next(iter(snapshot.problem_regions['retained']))
    candidate.metrics['attachment_comparison']['subjects'][target]['ordinary_quality'] = dict(
        evaluation=deepcopy(receipt))
    with pytest.raises(ValueError, match='ambiguous'):
        pilot_recovery.capture(snapshot, 'retained', target)


def test_public_capture_keeps_native_same_topology_fallback(tmp_path, monkeypatch):
    snapshot, candidate, mark, _, _ = capture_fixture(tmp_path, monkeypatch)
    target = next(iter(snapshot.problem_regions['retained']))
    del candidate.metrics['attachment_comparison']['subjects'][target]['regional_quality']
    captured = pilot_recovery.capture(snapshot, 'retained', target)
    measured, = captured['baseline']
    assert measured['reverse_selected_faces'] == len(mark['reconstruction']['face_ids'])
    assert measured['region'] == mark
