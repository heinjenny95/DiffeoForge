"""Pre-atlas check uses separate immutable preparations, with no native execution."""

import shutil
from threading import Event

import pytest
from test_reference_atlas_handoff import completed_joint_pilot  # noqa: F401

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.reference_atlas_handoff import initialization
from diffeoforge.reference_pilot_holdout import prepare_pilot_holdout
from diffeoforge.runs import verify_prepared_run


def test_saved_pilot_holdout_prepares_only_unseen_exact_inputs(completed_joint_pilot):  # noqa: F811
    path = completed_joint_pilot.final_config_path
    study = completed_joint_pilot.study_directory
    before = {p: p.read_bytes() for p in study.rglob("*") if p.is_file()}
    config = load_config(path)
    plan = initialization(config)
    result = prepare_pilot_holdout(path)
    manifest = verify_prepared_run(result.run_directory)

    assert result.run_directory.parent.parent == study.parent
    assert not result.run_directory.is_relative_to(study)
    assert not set(result.specimens) & set(plan["pilot_subject_labels"])
    assert len(result.specimens) == 2
    assert set(result.specimens).issubset(plan["subject_labels"])
    assert {record["staged_path"].split("/")[-1]: record["geometry"]["sha256"]
            for record in manifest["inputs"] if record["role"] == "subject"} == {
        name: plan["subject_sha256"][name] for name in result.specimens
    }
    effective = manifest["effective_config"]
    assert effective["optimization"] == {
        **config["optimization"], "freeze_template": True, "freeze_control_points": True,
        "max_iterations": min(120, config["optimization"]["max_iterations"]),
    }
    assert effective["model"]["attachment"] == config["model"]["attachment"]
    assert not initialization(effective)
    assert "initial_momenta" not in effective["model"]["deformation"]
    assert not list((result.run_directory / "output").iterdir())
    assert all(p.read_bytes() == data for p, data in before.items())
    assert set(p for p in study.rglob("*") if p.is_file()) == set(before)


def test_legacy_or_changed_pilot_input_is_refused_before_publication(
    completed_joint_pilot, tmp_path,  # noqa: F811
):
    path = completed_joint_pilot.final_config_path
    study = completed_joint_pilot.study_directory
    config = load_config(path)
    before = set(study.parent.iterdir())
    legacy = tmp_path / "legacy.yaml"
    shutil.copy2(study / "source" / "atlas.yaml", legacy)
    with pytest.raises(ConfigurationError, match="exact specimen provenance"):
        prepare_pilot_holdout(legacy)

    staged_seed = validate_input_paths(config, path).initial_momenta
    assert staged_seed.is_relative_to(study)
    staged_seed.write_bytes(b"changed")
    with pytest.raises(ConfigurationError, match="momenta"):
        prepare_pilot_holdout(path)
    assert set(study.parent.iterdir()) - {legacy} == before


def test_cancelled_holdout_does_not_stage(completed_joint_pilot):  # noqa: F811
    path = completed_joint_pilot.final_config_path
    parent = completed_joint_pilot.study_directory.parent
    before = set(parent.iterdir())
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ConfigurationError, match="cancelled"):
        prepare_pilot_holdout(path, cancelled=cancelled)
    assert set(parent.iterdir()) == before
