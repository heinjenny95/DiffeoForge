"""Time refinement must requalify space and compare both fields on the final grid."""

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from test_regional_fit import fixture

from diffeoforge import (
    reference_fixed_shooting,
    regional_evaluation,
    regional_quality,
    source_refinement,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_frame import TEMPORAL_COUNTS


def test_finer_time_rechecks_material_and_separately_evaluates_both_references(
    tmp_path, monkeypatch,
):
    config, *_ = fixture(tmp_path, guides=False)
    keys = ('attachment_kernel_width', 'deformation_kernel_width',
            'initial_control_point_spacing', 'noise_std')
    config['project']['parameter_provenance'].update(profile='advanced',
        scale_reference='template_bounding_box_diagonal',
        ratios={k: 1. for k in keys}, sources={k: 'absolute_override' for k in keys})
    config_path = tmp_path / 'atlas.yaml'
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    plan = regional_quality.read_plan(config)
    for key in ('retained_run', 'automatic_reference_run'):
        folder = tmp_path / key
        folder.mkdir()
        (folder / 'manifest.json').write_text('{}')
        plan[key] = dict(path=str(folder), manifest_sha256=sha256_file(folder/'manifest.json'))
    monkeypatch.setattr(regional_quality, 'read_plan', lambda _: plan)
    original = tmp_path / 'source.vtk'
    grids = {0: original}
    for count in TEMPORAL_COUNTS:
        path = tmp_path / f'grid-{count}.vtk'
        path.write_bytes(original.read_bytes()+b'\n'*count)
        grids[count] = path
    metadata, refinements, evaluated, measured = {}, [], [], []

    def evaluate(run, destination, *, count=73, _source=None, **kwargs):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        grid = Path(_source) if _source else grids[0]
        endpoint = destination / 'endpoint.vtk'
        endpoint.write_bytes(original.read_bytes())
        receipt = dict(source_run=str(run), timepoints=count, prefix=None,
            reference_source=dict(path=str(grid), sha256=sha256_file(grid)),
            endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)))
        metadata[str(endpoint)] = receipt
        evaluated.append(receipt)
        return receipt

    def refine(run, receipt, destination, plan, **kwargs):
        count = receipt['timepoints']
        refinements.append(count)
        result = evaluate(run, destination, count=count, _source=grids[count])
        result['source_refinement'] = dict(checked_at_timepoints=count, resource_limit=False)
        return result

    def movement(coarse, fine, diagonal):
        a, b = metadata[str(coarse)], metadata[str(fine)]
        assert a['reference_source']['sha256'] == b['reference_source']['sha256']
        on_original = b['reference_source']['path'] == str(grids[0])
        return dict(maximum=0. if on_original else 3e-5 if b['timepoints'] == 1153 else 1e-3)

    def measure(config, fitted, **kwargs):
        measured.append(kwargs)
        return dict(numerical_selection_suitable=True)

    monkeypatch.setattr(regional_evaluation, 'evaluate', evaluate)
    monkeypatch.setattr(source_refinement, 'refine_evaluation', refine)
    monkeypatch.setattr(reference_fixed_shooting, 'movement', movement)
    monkeypatch.setattr(regional_quality, 'measure', measure)
    result = regional_quality.evaluate_and_measure(tmp_path/'qc',
        dict(attachment_comparison=dict(regional_objective=True)),
        SimpleNamespace(candidate_id='test', config_path=config_path), tmp_path/'candidate')
    assert refinements == list(TEMPORAL_COUNTS) == [73, 145, 289, 577, 1153]
    assert result['numerical_selection_suitable'] and result['temporal_grid_stable']
    assert result['evaluation']['source_refinement']['checked_at_timepoints'] == 1153
    assert result['baseline_evaluation']['source_run'] == plan['retained_run']['path']
    assert (result['automatic_baseline_evaluation']['source_run']
            == plan['automatic_reference_run']['path'])
    assert measured[0]['baseline_path'] != measured[0]['automatic_baseline_path']
    for row in (result['baseline_evaluation'], result['automatic_baseline_evaluation']):
        assert row['timepoints'] == 1153 and row['reference_source']['path'] == str(grids[1153])
    assert any(r['timepoints'] == 577 and r['reference_source']['path'] == str(grids[1153])
               for r in evaluated)
    saved = json.loads(next((tmp_path/'qc').rglob('quality.json')).read_text())
    assert saved['temporal_grid_stable']
