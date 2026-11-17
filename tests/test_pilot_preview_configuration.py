"""Stage a display tap without changing the scientific model or optimizer."""

from copy import deepcopy

import pytest
from test_pilot_control_capacity import origin

from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.pilot_preview_configuration import ASSET, DECLARATION, mark
from diffeoforge.runs import prepare_run, verify_prepared_run


def test_guided_reference_run_stages_only_a_display_adapter(tmp_path):
    snapshot = guided.prepare(origin(tmp_path, "moderate").study_directory)
    candidate = snapshot.candidates[0]
    config = load_config(candidate.config_path)
    assert config["project"]["parameter_provenance"]["pilot_live_preview"] == DECLARATION
    run = prepare_run(candidate.config_path, output_directory=tmp_path / "runs", run_id="preview")
    current = verify_prepared_run(run)
    assert "engine/" + ASSET in {p["path"] for p in current["protected_artifacts"]}
    assert not list((run / "output").iterdir())

    from diffeoforge.reference_calibration_study import _write_yaml

    legacy = deepcopy(config)
    legacy["project"]["parameter_provenance"].pop("pilot_live_preview")
    legacy_config = candidate.config_path.with_name("legacy.yaml")
    _write_yaml(legacy_config, legacy, overwrite=False)
    baseline = prepare_run(legacy_config, output_directory=tmp_path / "runs", run_id="legacy")
    prior = verify_prepared_run(baseline)
    assert not (baseline / "engine" / ASSET).exists()
    for name in ("model.xml", "data_set.xml", "optimization_parameters.xml"):
        assert (run / "engine" / name).read_bytes() == (baseline / "engine" / name).read_bytes()
    for key in ("model", "optimization", "runtime"):
        assert current["effective_config"][key] == prior["effective_config"][key]


@pytest.mark.parametrize("case", ["joint", "workers", "open_controls"])
def test_preview_declaration_is_removed_outside_supported_scope(tmp_path, case):
    candidate = guided.prepare(origin(tmp_path, "moderate").study_directory).candidates[0]
    config = load_config(candidate.config_path)
    manifest = {"attachment_comparison": {"guided": {"phase": "refine"}},
                "inputs": {"subjects": ["one"]}}
    if case == "joint":
        manifest["attachment_comparison"]["guided"]["phase"] = "joint"
    elif case == "workers":
        config["runtime"]["processes"] = 2
    else:
        config["optimization"]["freeze_control_points"] = False
    mark(config, manifest)
    assert "pilot_live_preview" not in config["project"]["parameter_provenance"]
