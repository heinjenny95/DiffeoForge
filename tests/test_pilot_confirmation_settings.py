"""Singleton initialization must retain explicit future joint update choices."""
import pytest

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config


@pytest.mark.parametrize('template,controls', [(False, False), (True, False),
                                               (False, True), (True, True)])
def test_source_joint_choices_survive_frozen_singleton_preparation(
        tmp_path, monkeypatch, template, controls):
    from test_reference_calibration_study import _project

    path = _project(tmp_path)
    config = load_config(path)
    flags = dict(freeze_template=template, freeze_control_points=controls)
    config['optimization'].update(flags)
    config['project']['parameter_provenance']['attachment_selection'] = dict(
        version='attachment-comparison-v1', mode='auto', state='pending',
        workflow=guided.ADAPTIVE_VERSION)
    study._write_yaml(path, config, overwrite=True)
    source = study.create_reference_calibration_study(path, tmp_path / 'pilot')
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, 'run_current_stage',
                        lambda *_a, **_k: pytest.fail('Preparation launched optimization'))
    child = guided._batch(source, None, phase='screen',
        target=guided._pilot_order(source.plan)[0], methods=('current', 'varifold'),
        values=source.plan.effective_values, approved=(), history=(), spent=0, strategy={})
    assert child.attachment_comparison['confirmation_freeze_settings'] == flags
    actual = load_config(child.candidates[0].config_path)
    assert all(actual['optimization'][key] for key in flags)
    assert not child.visual_reviews and all(c.attempts == 0 for c in child.candidates)
