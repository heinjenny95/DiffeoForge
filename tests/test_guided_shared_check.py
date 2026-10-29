"""Common-objective staging from a saved field; synthetic controllers, no solver."""

from dataclasses import replace

import numpy as np
import pytest
from test_guided_pilot import approve, run_batch
from test_guided_suitable_dialog import panel as panel
from test_interactive_pilot import initial

from diffeoforge import guided_shared_check as shared
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import read_deformetrica_momenta


@pytest.mark.parametrize("timepoints,identifier", [(10, "guided-varifold"), (37, "guided-current")])
def test_shared_check_prepares_saved_field_without_transferring_approval(
        tmp_path, monkeypatch, timepoints, identifier):
    from diffeoforge import reference_attachment_comparison as comparison

    configure = comparison.configure

    def numerical_local_fixture(config, *args, **kwargs):
        configure(config, *args, **kwargs)
        config["model"]["deformation"].update(timepoints=timepoints, use_rk2=timepoints == 37)

    # Only the local candidate grid differs from the original cohort source.
    with monkeypatch.context() as fixture:
        fixture.setattr(comparison, "configure", numerical_local_fixture)
        first = initial(tmp_path)
    base = approve(run_batch(first, monkeypatch), identifier)
    original_declaration = shared.declaration

    # The receipt-only controller supplies an ordinary finite synthetic field.
    # Mock local-objective eligibility only; all staging/field/journal checks run.
    def local_declaration(snapshot, identifier):
        if snapshot.study_directory != base.study_directory:
            return original_declaration(snapshot, identifier)
        config = load_config(next(c.config_path for c in snapshot.candidates
                                  if c.candidate_id == identifier))
        return dict(version=shared.VERSION, reference=strategy._reference(snapshot, identifier),
                    integration={k: config["model"]["deformation"][k]
                                 for k in ("timepoints", "use_rk2")},
                    precision=config["runtime"]["precision"], initialization_only=True,
                    regional_approval_transferred=False)

    monkeypatch.setattr(shared, "declaration", local_declaration)
    candidate = next(c for c in base.candidates if c.candidate_id == identifier)
    before = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    child = guided.next_action(
        base.study_directory, "adaptive_shared_check", candidate.candidate_id
    )
    info = guided.record(child)
    config = load_config(child.candidates[0].config_path)
    inputs = validate_input_paths(config, child.candidates[0].config_path)
    assert info["goal"] == "shared_check" and info["target"] == guided.record(base)["target"]
    assert child.attachment_comparison["refinement"]["initialization"] == "learned"
    assert not child.attachment_comparison.get("regional_objective")
    assert not config["project"]["parameter_provenance"].get("regional_fit")
    assert not config["project"]["parameter_provenance"].get("finite_accepted_guard")
    assert config["optimization"]["max_iterations"] == 120
    assert np.any(read_deformetrica_momenta(inputs.initial_momenta, allow_singleton=True) != 0)
    assert np.array_equal(
        read_deformetrica_momenta(inputs.initial_momenta, allow_singleton=True),
        read_deformetrica_momenta(candidate.run_directory / "synthetic-final-momenta.txt",
                                 allow_singleton=True))
    assert config["model"]["deformation"]["timepoints"] == timepoints
    assert not child.visual_reviews and all(c.attempts == 0 for c in child.candidates)
    assert not info["approved"]
    assert all(sha256_file(p) == digest for p, digest in before.items()
               if p.name not in {study.STUDY_EVENTS, "fit-search-latest.json"})
    with pytest.raises(ValueError):
        guided.next_action(child.study_directory, "adaptive_confirm", identifier)
    checked = approve(run_batch(child, monkeypatch), identifier)
    next_form = guided.next_action(checked.study_directory, "adaptive_confirm", identifier)
    assert guided.record(next_form)["target"] != info["target"]
    assert len(guided.record(next_form)["approved"]) == 1
    next_config = load_config(next_form.candidates[0].config_path)
    assert all(next_config["model"]["deformation"][k] == v
               for k, v in info["strategy"]["shared_model_check"]["integration"].items())
    assert study.load_reference_calibration_study(child.study_directory).visual_reviews
    if timepoints == 37:
        current = next_form
        while guided.record(current)["phase"] != "joint":
            current = approve(run_batch(current, monkeypatch), identifier)
            current = guided.next_action(current.study_directory, "adaptive_confirm", identifier)
        assert current.attachment_comparison["joint_initialization"]["version"]
        assert not current.visual_reviews and all(c.attempts == 0 for c in current.candidates)
        joint_config = load_config(current.candidates[0].config_path)
        assert joint_config["model"]["deformation"]["timepoints"] == 37
        assert joint_config["model"]["deformation"]["use_rk2"] is True


def test_local_declaration_requires_suitability_and_rejects_residual(tmp_path, monkeypatch):
    from diffeoforge import regional_fit

    base = run_batch(initial(tmp_path), monkeypatch)
    local = replace(base, attachment_comparison=dict(base.attachment_comparison,
                                                    regional_objective={"version": "fixture"}))
    with pytest.raises(ValueError, match="approve"):
        shared.declaration(local, "guided-varifold")
    accepted = approve(base, "guided-varifold")
    local = replace(accepted, attachment_comparison=local.attachment_comparison)
    monkeypatch.setattr(regional_fit, "read_plan", lambda _: dict(residual={"prefix": True}))
    assert not shared.preview(local, "guided-varifold")["available"]
    monkeypatch.setattr(regional_fit, "read_plan", lambda _: dict(residual=None))
    marker = shared.declaration(local, "guided-varifold")
    assert marker["initialization_only"] and not marker["regional_approval_transferred"]
    config = load_config(local.candidates[0].config_path)
    assert marker["integration"]["timepoints"] == config["model"]["deformation"]["timepoints"]


def test_suitable_local_fit_has_explicit_nonrunning_next_action(panel):
    from PySide6.QtWidgets import QPushButton

    identifier = panel.candidate.candidate_id
    panel.snapshot.visual_reviews[identifier] = True
    panel.guidance["shared_model_checks"] = {identifier: dict(available=True)}
    panel.render()
    button = next(b for b in panel.window.findChildren(QPushButton)
                  if b.text() == "Use suitable fit → prepare atlas-model check")
    assert button.isVisible() and button.isEnabled() and not panel.invoked
    button.click()
    assert panel.invoked == [((), dict(adaptive=False,
        guided_action=("adaptive_shared_check", identifier, None)))]
