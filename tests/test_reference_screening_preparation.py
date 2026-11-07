"""Real immutable singleton preparation; no optimizer or private input."""

import copy
import json

import pytest
import yaml
from test_reference_stage_retention import _second_stage

from diffeoforge import reference_stage_screening as screening
from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.runs import _validate_manifest_schema, prepare_run, verify_prepared_run


def test_cold_singleton_screen_prepares_seven_protected_files(tmp_path, monkeypatch):
    _, _, _, second = _second_stage(tmp_path, monkeypatch)
    queued = screening.start_screening(second, (second.plan.selected_pilot_subjects[0].filename,))
    child = screening._create_probe(queued, queued.early_screening)
    # The older study fixture always inserts synthetic learned fields. Exercise
    # the legitimate cold-grid path separately without editing its bound source.
    config = load_config(child.candidates[0].config_path)
    inputs = validate_input_paths(config, child.candidates[0].config_path)
    config["input"].update(directory=str(inputs.input_directory), template=str(inputs.template))
    for key in ("initial_control_points", "initial_momenta", "initial_momenta_subjects"):
        config["model"]["deformation"].pop(key, None)
    source = tmp_path / "cold-screen.yaml"
    source.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepare_run(source, output_directory=tmp_path / "prepared")
    verify_prepared_run(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["input_count"]["subjects"] == 1
    assert len(manifest["protected_artifacts"]) == 7
    assert manifest["effective_config"]["optimization"]["freeze_template"] is True
    assert manifest["effective_config"]["optimization"]["freeze_control_points"] is True
    missing = copy.deepcopy(manifest)
    missing["protected_artifacts"].pop()
    with pytest.raises(ConfigurationError, match="too short"):
        _validate_manifest_schema(missing)
    ordinary = copy.deepcopy(manifest)
    ordinary["input_count"]["subjects"] = 2
    ordinary["inputs"].append(copy.deepcopy(ordinary["inputs"][-1]))
    with pytest.raises(ConfigurationError, match="too short"):
        _validate_manifest_schema(ordinary)
    for key in ("freeze_template", "freeze_control_points"):
        unsafe = copy.deepcopy(manifest)
        unsafe["effective_config"]["optimization"][key] = False
        with pytest.raises(ConfigurationError):
            _validate_manifest_schema(unsafe)
    unsafe = copy.deepcopy(manifest)
    unsafe["effective_config"]["project"]["parameter_provenance"]["recommendation"][
        "calibration_plan"
    ]["execution_scope"] = "joint_pilot"
    with pytest.raises(ConfigurationError):
        _validate_manifest_schema(unsafe)
