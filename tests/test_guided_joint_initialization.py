"""Starting fields are ordered, source-bound initialization, never a new approval."""

from copy import deepcopy

import numpy as np
import pytest
from test_guided_pilot import approve, run_batch
from test_interactive_pilot import initial

from diffeoforge import guided_joint_initialization as joint
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_pca_deformations import _write_momenta


def test_new_joint_starts_from_every_distinct_accepted_field_without_changing_shared_model(
        tmp_path, monkeypatch):
    from guided_field_fixture import field_fixture

    current = approve(run_batch(initial(tmp_path), monkeypatch), "guided-varifold")
    while len({r["filename"] for r in guided.record(current)["approved"]}
               | {guided.record(current)["target"]}) < len(guided.record(current)["pilot_order"]):
        current = guided.next_action(current.study_directory, "adaptive_confirm", "guided-varifold")
        current = approve(run_batch(current, monkeypatch), "guided-varifold")

    def distinct_field(run):
        field = field_fixture(run)
        assert len(field.subject_labels) == 1
        value = sum(map(ord, field.subject_labels[0])) / 100000.
        field.momenta[:] = value
        field.momenta_path.unlink()  # Synthetic unbound controller output only.
        _write_momenta(field.momenta_path, field.momenta)
        return field

    monkeypatch.setattr("diffeoforge.guided_refinement.load_field", distinct_field)
    monkeypatch.setattr(study.ReferenceCalibrationStudyRunner, "run_current_stage",
                        lambda *_a, **_k: pytest.fail("Joint preparation dispatched optimization"))
    prepared = guided.next_action(current.study_directory, "adaptive_confirm", "guided-varifold")
    root = prepared.study_directory
    record = prepared.attachment_comparison
    manifest = study._verify_manifest(root)
    seed = record["joint_initialization"]
    config = load_config(prepared.candidates[0].config_path)
    values = read_deformetrica_momenta(root / seed["momenta"]["copy"])
    labels = seed["subjects"]
    assert len(set(float(a[0, 0]) for a in values)) == len(labels)
    for label, array in zip(labels, values, strict=True):
        assert np.all(array == sum(map(ord, label)) / 100000.)
    assert config["model"]["deformation"]["initial_momenta_subjects"] == labels
    inputs = validate_input_paths(config, prepared.candidates[0].config_path)
    assert labels == [p.name for p in inputs.subjects]
    assert config["model"]["deformation"]["initial_momenta"] == str(root / seed["momenta"]["copy"])
    assert {k: config["optimization"][k] for k in record["confirmation_freeze_settings"]} == (
        record["confirmation_freeze_settings"])
    assert not prepared.visual_reviews and not prepared.selected_candidate_ids
    assert all(c.attempts == 0 for c in prepared.candidates)
    joint.verify(root, manifest, record)
    # Even replacing the combined hash cannot make a swapped subject order valid.
    altered = deepcopy(record)
    path = root / seed["momenta"]["copy"]
    path.unlink()
    _write_momenta(path, values[::-1])
    altered["joint_initialization"]["momenta"]["sha256"] = sha256_file(path)
    with pytest.raises(ValueError, match="ordering or coefficients"):
        joint.verify(root, manifest, altered)


@pytest.mark.parametrize("change", ["precision", "timepoints", "width", "noise"])
def test_joint_basis_comparison_cannot_silently_change_model_or_accuracy(change):
    config = dict(runtime=dict(precision="float64"), model=dict(
        attachment=dict(type="current", kernel_width=.2), noise_std=.03,
        deformation=dict(kernel_width=.4, initial_control_point_spacing=.5,
                         timepoints=10, use_rk2=False)))
    other = deepcopy(config)
    if change == "precision":
        other["runtime"]["precision"] = "float32"
    elif change == "timepoints":
        other["model"]["deformation"]["timepoints"] = 20
    elif change == "width":
        other["model"]["deformation"]["kernel_width"] = .3
    else:
        other["model"]["noise_std"] = .02
    assert joint._basis(config) != joint._basis(other)
