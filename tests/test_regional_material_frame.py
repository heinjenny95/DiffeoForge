"""A fine retained field must not be forced onto an older coarse vertex array."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import regional_frame, regional_residual
from diffeoforge import regional_material_frame as frame
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save
from diffeoforge.source_refinement import subdivide


def receipt(folder, vertices, faces, *, shift=0.):
    folder.mkdir()
    for name in ['manifest.json', 'q.txt', 'p.txt']:
        (folder/name).write_text(name)
    _save(folder/'original.vtk', vertices, faces)
    _save(folder/'endpoint.vtk', vertices+shift, faces)
    return dict(source_run=str(folder),
        source_manifest_sha256=sha256_file(folder/'manifest.json'),
        controls_sha256=sha256_file(folder/'q.txt'),
        momenta_sha256=sha256_file(folder/'p.txt'),
        field_paths=dict(control_points=str(folder/'q.txt'), momenta=str(folder/'p.txt')),
        reference_source=dict(path=str(folder/'original.vtk'),
                              sha256=sha256_file(folder/'original.vtk')),
        endpoint=dict(path=str(folder/'endpoint.vtk'),sha256=sha256_file(folder/'endpoint.vtk')),
        integrator='rk2',precision='float64',timepoints=577,
        starting_frame_qualification=dict(temporal_stable=True),optimizer_updates=0)


@pytest.fixture
def materials(tmp_path):
    vertices, faces = map(np.asarray, cube())
    selected = np.zeros(len(faces), bool)
    selected[0] = True
    fine, triangles, _ = subdivide(vertices, faces, selected)
    coarse = receipt(tmp_path/'coarse', vertices, faces)
    saved = receipt(tmp_path/'fine', fine, triangles, shift=.05)
    return SimpleNamespace(coarse=coarse,fine=saved,vertices=vertices,faces=faces,
                           points=fine,triangles=triangles)


def test_existing_fine_grid_is_selected_without_replacing_old_points(materials):
    selected = frame.common_grid(materials.coarse['reference_source']['path'],
                                 [materials.coarse,materials.fine])
    assert selected == materials.fine['reference_source']


@pytest.mark.parametrize('changed', ['endpoint.vtk','p.txt','original.vtk'])
def test_changed_saved_evidence_cannot_be_reinterpreted_as_a_new_frame(materials,changed):
    path = Path(materials.fine['source_run'])/changed
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='changed'):
        frame.common_grid(materials.coarse['reference_source']['path'],[materials.fine])


def test_non_nested_material_points_are_rejected_even_when_receipt_hashes_match(
    tmp_path,materials,
):
    incompatible = materials.points.copy()
    incompatible[0,0] += .01
    other = receipt(tmp_path/'different',incompatible,materials.triangles)
    with pytest.raises(ValueError,match='unchanged original material'):
        frame.common_grid(materials.coarse['reference_source']['path'],[other])


def test_same_vertex_count_with_changed_faces_is_not_a_valid_warm_refinement(tmp_path,materials):
    other = receipt(tmp_path/'different',materials.vertices,materials.faces[::-1])
    with pytest.raises(ValueError,match='conflicting original material connectivity'):
        frame.common_grid(materials.coarse['reference_source']['path'],[other])


def test_matching_warm_material_keeps_existing_field_and_recipe(tmp_path,materials,monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('Matching material must not create a residual')

    monkeypatch.setattr(regional_residual,'bind',forbidden)
    record=dict(refinement=dict(initialization='learned'))
    recipe=dict(residual=False)
    source=materials.coarse['reference_source']['path']
    result=frame.align(tmp_path,{},record,recipe,None,source,
                       materials.coarse,materials.coarse,materials.coarse['source_run'])
    assert result[:3] == (record,recipe,None) and result[-1] is None


def test_fine_saved_fit_uses_zero_residual_and_preserves_all_old_receipts(
    tmp_path,materials,monkeypatch,
):
    source=materials.coarse['reference_source']['path']
    manifest=dict(inputs=dict(template=dict(sha256=sha256_file(Path(source)))))
    record=dict(refinement=dict(initialization='learned'),guided=dict(strategy={}))
    recipe=dict(residual=False,phase='initial_warm',focus_width=.1,focus_noise=.02)
    initial=deepcopy((record,recipe))
    seals={p:sha256_file(p) for p in tmp_path.rglob('*') if p.is_file()}
    calls=[]

    def bind(root,manifest,updated,policy,*,source_grid):
        calls.append(source_grid)
        grid=root/'original-source-grid.vtk'
        grid.write_bytes(Path(source_grid['path']).read_bytes())
        incoming=root/'residual-source.vtk'
        incoming.write_bytes(Path(materials.fine['endpoint']['path']).read_bytes())
        residual=dict(source=dict(copy=incoming.name,sha256=sha256_file(incoming)),
            original_source_grid=dict(copy=grid.name,sha256=sha256_file(grid)))
        return dict(updated,refinement=dict(initialization='residual',residual=residual,
                                            parent_evaluation=materials.fine))

    monkeypatch.setattr(regional_residual,'bind',bind)
    result=frame.align(tmp_path,manifest,record,recipe,None,source,
                       materials.fine,materials.fine,materials.fine['source_run'])
    updated,policy,residual,incoming,automatic,anchor,response=result
    assert calls == [materials.fine['reference_source']]
    assert updated['refinement']['initialization']=='residual'
    assert response['existing_field_parameters_changed'] is False
    assert policy['focus_width']==recipe['focus_width']
    assert policy['focus_noise']==recipe['focus_noise']
    assert automatic is anchor is materials.fine and residual and incoming.is_file()
    assert (record,recipe)==initial and all(sha256_file(p)==digest for p,digest in seals.items())


def test_distinct_retained_field_is_evaluated_on_the_same_fine_grid(
    tmp_path,materials,monkeypatch,
):
    grid=tmp_path/'original-source-grid.vtk'
    grid.write_bytes(Path(materials.fine['reference_source']['path']).read_bytes())
    residual=dict(source=dict(copy='source.vtk'),original_source_grid=dict(
        copy=grid.name,sha256=sha256_file(grid)))
    calls=[]

    def qualify(run,destination,*,source):
        calls.append((run,source))
        return receipt(destination,materials.points,materials.triangles)

    monkeypatch.setattr(regional_frame,'qualify',qualify)
    result=frame.align(tmp_path,{},dict(refinement=dict(initialization='residual')),{},residual,
        materials.fine['endpoint']['path'],materials.fine,materials.coarse,
        materials.coarse['source_run'])
    assert calls==[(materials.coarse['source_run'],grid)]
    assert result[4] is materials.fine
    assert result[5]['reference_source']['sha256']==sha256_file(grid)
    assert result[5]['optimizer_updates']==0


def test_residual_binding_qualifies_requested_fine_grid_instead_of_using_old_coarse_cache(
    tmp_path,materials,monkeypatch,
):
    from diffeoforge import (
        guided_feedback,
        reference_calibration_study,
        regional_evaluation,
        result_report,
    )
    from diffeoforge.surface_io import load_surface_mesh

    candidate=SimpleNamespace(candidate_id='saved',metrics=dict(attachment_comparison=dict(
        subjects={'target.vtk':dict(regional_quality=dict(evaluation=materials.coarse))})))
    parent=SimpleNamespace(candidates=[candidate])
    monkeypatch.setattr(guided_feedback,'verify_reference',lambda _:parent)
    monkeypatch.setattr(reference_calibration_study,'calibration_candidate_run_directory',
                        lambda _:Path(materials.coarse['source_run']))
    monkeypatch.setattr(result_report,'collect_run_report',lambda _:SimpleNamespace())
    monkeypatch.setattr(regional_evaluation,'endpoint',lambda _:materials.coarse['endpoint'])
    calls=[]

    def qualify(run,directory,*,source):
        calls.append((run,Path(source)))
        return dict(materials.coarse,
                    endpoint=materials.fine['endpoint'],
                    reference_source=materials.fine['reference_source'])

    monkeypatch.setattr(regional_frame,'qualify',qualify)
    root=tmp_path/'new'
    root.mkdir()
    record=dict(refinement=dict(reference=dict(candidate_id='saved',target='target.vtk')))
    manifest=dict(inputs=dict(template=dict(sha256='original-template')))
    result=regional_residual.bind(root,manifest,record,{},
                                 source_grid=materials.fine['reference_source'])
    assert calls==[(Path(materials.coarse['source_run']),
                    Path(materials.fine['reference_source']['path']))]
    bound=result['refinement']['residual']
    assert bound['original_source_grid']['sha256']==materials.fine['reference_source']['sha256']
    saved=load_surface_mesh(root/bound['source']['copy']).geometry
    expected=load_surface_mesh(materials.fine['endpoint']['path']).geometry
    assert np.array_equal(saved.vertices,expected.vertices)
    assert np.array_equal(saved.triangles,expected.triangles)
    assert result['refinement']['initialization']=='residual'
