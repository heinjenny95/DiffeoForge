"""Qualified starting geometry stays bound to the actual retained field."""
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
