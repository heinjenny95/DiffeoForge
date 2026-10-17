from pathlib import Path

import pytest
import yaml
from test_runs import write_run_config

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.reference_preparation_plan import plan_reference_preparation
from diffeoforge.runs import prepare_run, verify_prepared_run


def warm_config(root: Path) -> Path:
    path = write_run_config(root)
    (root / "controls.txt").write_text("0 0 0\n1 1 1\n", encoding="ascii")
    (root / "momenta.txt").write_text("2 2 3\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n", encoding="ascii")
    config = yaml.safe_load(path.read_text())
    config["model"]["deformation"].update(
        initial_control_points="./controls.txt",
        initial_momenta="./momenta.txt",
        initial_momenta_subjects=["subject-a.vtk", "subject-b.vtk"],
    )
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_momenta_are_bound_and_preparation_plan_matches_actual_bytes(tmp_path):
    config = warm_config(tmp_path)
    plan = plan_reference_preparation(config, run_id="warm")
    run = prepare_run(config, run_id="warm")
    manifest = verify_prepared_run(run)
    assert manifest["protected_artifacts"] == [
        {k: item[k] for k in ["path", "bytes", "sha256"]} for item in plan["protected_files"]
    ]
    assert (
        "<initial-momenta>../input/momenta/momenta.txt</initial-momenta>"
        in (run / "engine/model.xml").read_text()
    )
    staged = run / "input/momenta/momenta.txt"
    staged.write_text("2 2 3\n0 0 0\n0 0 0\n0 0 0\n0 0 0\n")
    with pytest.raises(ConfigurationError):
        verify_prepared_run(run)


def test_same_sized_but_swapped_cohort_is_rejected(tmp_path):
    path = warm_config(tmp_path)
    config = load_config(path)
    config["model"]["deformation"]["initial_momenta_subjects"].reverse()
    with pytest.raises(ConfigurationError, match="subject order"):
        validate_input_paths(config, path)


@pytest.mark.parametrize(
    "text", ["1 2 3\n0 0 0\n0 0 0\n", "2 2 3\n0 0 0\n0 0 nan\n0 0 0\n0 0 0\n", "2 3 3\n0 0 0\n", ""]
)
def test_malformed_or_wrong_sized_momenta_are_rejected(tmp_path, text):
    path = warm_config(tmp_path)
    (tmp_path / "momenta.txt").write_text(text)
    with pytest.raises(ConfigurationError, match="Invalid initial momenta"):
        validate_input_paths(load_config(path), path)
