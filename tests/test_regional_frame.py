"""Qualified starting geometry stays bound to the actual retained field."""
from pathlib import Path

import pytest

from diffeoforge.mesh import sha256_file
from diffeoforge.regional_frame import compatible, verify_source


def test_qualified_frame_requires_stability_and_rejects_parameter_changes(tmp_path):
    for name in ['manifest.json', 'q.txt', 'p.txt', 'end.vtk', 'source.vtk']:
        (tmp_path / name).write_text(name)
    receipt = dict(source_run=str(tmp_path),
        source_manifest_sha256=sha256_file(tmp_path / 'manifest.json'),
        controls_sha256=sha256_file(tmp_path / 'q.txt'),
        momenta_sha256=sha256_file(tmp_path / 'p.txt'),
        field_paths=dict(control_points=str(tmp_path / 'q.txt'), momenta=str(tmp_path / 'p.txt')),
        endpoint=dict(path=str(tmp_path / 'end.vtk'), sha256=sha256_file(tmp_path / 'end.vtk')),
        reference_source=dict(path=str(tmp_path / 'source.vtk'),
                              sha256=sha256_file(tmp_path / 'source.vtk')),
        integrator='rk2', precision='float64', timepoints=73)
    assert not compatible(receipt)
    receipt['starting_frame_qualification'] = dict(temporal_stable=True)
    assert compatible(receipt)
    verify_source(receipt)
    (tmp_path / 'p.txt').write_text('changed')
    with pytest.raises(ValueError, match='parameters changed'):
        verify_source(receipt)


def test_legacy_integration_upgrade_is_explicitly_regional_only():
    from diffeoforge.guided_refinement import integration_upgrade

    old, new = dict(timepoints=10, use_rk2=False), dict(timepoints=19, use_rk2=True)
    upgrade = integration_upgrade(old, new, True)
    assert upgrade['before'] == old and upgrade['after'] == new
    assert upgrade['coefficients_unchanged']
    assert integration_upgrade(new, new, False) is None
    with pytest.raises(ValueError, match='fixed refinement basis'):
        integration_upgrade(old, new, False)
    with pytest.raises(ValueError, match='fixed refinement basis'):
        integration_upgrade(old, dict(timepoints=11, use_rk2=True), True)


@pytest.mark.parametrize('selection', [None, False, True])
def test_fixed_evaluation_selects_explicit_integrator_without_changing_seed(
    tmp_path, monkeypatch, selection
):
    import xml.etree.ElementTree as ET

    from diffeoforge import reference_fixed_shooting as shooting

    run = tmp_path / 'run'
    engine = run / 'engine'
    engine.mkdir(parents=True)
    (engine / 'model.xml').write_text(
        '<model><model-type>DeterministicAtlas</model-type><template>'
        '<object id="surface"><filename>old.vtk</filename></object></template></model>')
    parameters = ('<optimization-parameters><use-rk2>off</use-rk2>'
                  '<use-rk2-for-flow>off</use-rk2-for-flow></optimization-parameters>')
    (engine / 'optimization_parameters.xml').write_text(parameters)
    files = {}
    for name in ('template', 'control_points', 'momenta'):
        path = tmp_path / (name + '.txt')
        path.write_text('unchanged ' + name)
        files[name] = dict(copy=path.name, sha256=sha256_file(path))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    class ReachedDispatch(Exception):
        pass
    def checked_dispatch(config, directory):
        p = directory / 'engine/optimization_parameters.xml'
        if selection is None:
            assert p.read_text() == parameters
        else:
            xml = ET.parse(p).getroot()
            assert xml.find('use-rk2').text == ('on' if selection else 'off')
            assert xml.find('use-rk2-for-flow') is None
        raise ReachedDispatch
    monkeypatch.setattr(shooting, 'build_shooting_command', checked_dispatch)
    with pytest.raises(ReachedDispatch):
        shooting.shoot({}, tmp_path,
            dict(files=files, source_run_directory=str(run)), tmp_path / 'evaluation',
            73, use_rk2=selection)
    assert all(p.read_bytes() == content for p, content in before.items())


def _accuracy_fixture(tmp_path, monkeypatch, *, stable_at, refined=False):
    """Drive the actual qualification loops without launching an optimizer."""
    import json
    from types import SimpleNamespace

    import numpy as np

    from diffeoforge import (
        config,
        reference_fixed_shooting,
        regional_evaluation,
        source_refinement,
        surface_io,
    )

    grid = tmp_path / 'original.vtk'
    grid.write_text('unchanged original material grid')
    final_grid = tmp_path / 'refined.vtk'
    final_grid.write_text('conforming original material grid')
    calls = []

    def evaluate(run, destination, *, count=73, _source=None, **kwargs):
        source = Path(_source) if _source else grid
        destination.mkdir(parents=True)
        endpoint = destination / 'endpoint.vtk'
        endpoint.write_text(json.dumps(dict(count=count, refined=source == final_grid)))
        calls.append((count, source))
        return dict(timepoints=count, prefix=None, optimizer_updates=0,
                    reference_source=dict(path=str(source), sha256=sha256_file(source)),
                    endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)))

    def movement(coarse, fine, diagonal):
        before, after = (json.loads(path.read_text()) for path in (coarse, fine))
        assert before['count'] < after['count']
        assert diagonal > 0
        required = 577 if after['refined'] else stable_at
        error = 4e-5 if after['count'] >= required else 1.5e-4
        return dict(maximum=error, p95=error / 2, rms=error / 3)

    def refine(run, receipt, destination, plan, **kwargs):
        if not refined:
            return receipt
        result = evaluate(run, destination, count=receipt['timepoints'], _source=final_grid)
        result['source_refinement'] = dict(resource_limit=False, original_surface_unchanged=True)
        return result

    monkeypatch.setattr(regional_evaluation, 'evaluate', evaluate)
    monkeypatch.setattr(reference_fixed_shooting, 'movement', movement)
    monkeypatch.setattr(source_refinement, 'refine_evaluation', refine)
    monkeypatch.setattr(surface_io, 'load_surface_mesh', lambda p: SimpleNamespace(
        geometry=SimpleNamespace(vertices=np.array([[0., 0., 0.], [1., 1., 1.]]))))
    monkeypatch.setattr(config, 'load_config', lambda p: dict(input={}))
    monkeypatch.setattr(config, 'validate_input_paths', lambda c, p: SimpleNamespace(
        template=grid, input_directory=tmp_path))
    return grid, calls


@pytest.mark.parametrize('stable_at', [73, 145, 289, 577])
def test_saved_frame_uses_only_needed_accuracy_level(tmp_path, monkeypatch, stable_at):
    from diffeoforge import regional_frame

    grid, calls = _accuracy_fixture(tmp_path, monkeypatch, stable_at=stable_at)
    receipt = regional_frame.qualify(tmp_path / 'saved-run', tmp_path / 'check')
    assert [count for count, _source in calls] == [
        count for count in (37, 73, 145, 289, 577) if count <= stable_at]
    assert all(source == grid for _count, source in calls)
    assert receipt['timepoints'] == stable_at
    assert receipt['starting_frame_qualification']['temporal_stable']
    assert receipt['optimizer_updates'] == 0


def test_saved_frame_unresolved_at_new_bound_stays_unqualified(tmp_path, monkeypatch):
    from diffeoforge import regional_frame

    _grid, calls = _accuracy_fixture(tmp_path, monkeypatch, stable_at=1153)
    with pytest.raises(ValueError, match='numerically unresolved'):
        regional_frame.qualify(tmp_path / 'saved-run', tmp_path / 'check')
    assert [count for count, _source in calls] == [37, 73, 145, 289, 577]
    assert not (tmp_path / 'check/qualification.json').exists()


@pytest.mark.parametrize('stable_at', [73, 577, 1153])
@pytest.mark.parametrize('refined', [False, True])
def test_final_quality_checks_full_final_grid_at_unchanged_tolerance(
    tmp_path, monkeypatch, stable_at, refined
):
    from types import SimpleNamespace

    from diffeoforge import regional_quality

    _grid, calls = _accuracy_fixture(tmp_path, monkeypatch, stable_at=stable_at, refined=refined)
    monkeypatch.setattr(regional_quality, 'read_plan', lambda c: {})
    measured = []

    def measure(config, endpoint, **kwargs):
        measured.append(endpoint)
        return dict(numerical_selection_suitable=True)

    monkeypatch.setattr(regional_quality, 'measure', measure)
    quality = regional_quality.evaluate_and_measure(
        tmp_path, dict(attachment_comparison=dict(regional_objective=True)),
        SimpleNamespace(candidate_id='test', config_path=tmp_path / 'atlas.yaml'),
        tmp_path / 'saved-run')
    assert max(count for count, _source in calls) <= 577
    assert quality['temporal_grid_stable'] is (refined or stable_at <= 577)
    assert quality['numerical_selection_suitable'] == quality['temporal_grid_stable']
    expected = 577 if refined else min(stable_at, 577)
    assert quality['evaluation']['timepoints'] == expected
    assert quality['evaluation']['optimizer_updates'] == 0
    assert measured == [quality['evaluation']['endpoint']['path']]
    assert quality['temporal_grid_checks'][-1]['fine'] == expected
    if refined:
        assert quality['evaluation']['reference_source']['path'] == str(tmp_path / 'refined.vtk')
        assert quality['evaluation']['source_refinement']['original_surface_unchanged']
    assert regional_quality.TEMPORAL_TOLERANCE == 1e-4
