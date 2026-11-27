from pathlib import Path

import pytest
from test_reference_calibration_study import _review_ready_stage
from test_reference_progressive_fit import mock_singleton
from test_reference_sequential_fit import _measured, _reject

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_fit_preferences as preferences
from diffeoforge import reference_fit_search as search
from diffeoforge import reference_sequential_fit as sequence
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def prepared_pair(tmp_path, monkeypatch):
    from diffeoforge import reference_pca

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    first_inputs = mock_singleton(monkeypatch, first)
    cid = _reject(first)
    second = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    second_inputs = mock_singleton(monkeypatch, second)
    inputs = {
        study.calibration_candidate_run_directory(s.candidates[0]): field
        for s, field in [(first, first_inputs), (second, second_inputs)]
    }
    monkeypatch.setattr(
        reference_pca, "load_reference_momenta", lambda run, **kw: inputs[Path(run)]
    )
    root = Path(sequence.sequence_info(second.study_directory)["root"])
    return runner, root, first, second, inputs


@pytest.mark.parametrize("outcome", ["worse", "same"])
def test_worse_or_same_preserves_best_field_without_approval(tmp_path, monkeypatch, outcome):
    runner, root, first, second, inputs = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    good = preferences.fit_record(first, cid)
    comparison = dict(current=preferences.fit_record(second, cid), reference=good, best=None)
    before = {
        p: sha256_file(p)
        for s in (first, second)
        for p in s.study_directory.rglob("*")
        if p.is_file()
    }
    successor = sequence.run_specimen_sequence(runner, action=(outcome, cid, comparison))
    state = sequence._read(root)
    assert state["best_fits"]["0"] == good
    assert state["approved"] == []
    assert state["fit_preferences"][-1]["anatomical_approval"] is False
    assert not successor.visual_reviews
    settings = study._verify_manifest(successor.study_directory)["fit_search"]
    assert settings["warm_seed"]["source_study"] == str(first.study_directory)
    assert settings["progressive"]["best_study_sha256"] == good["study_sha256"]
    copied = successor.study_directory / settings["warm_seed"]["copy"]
    assert (
        copied.read_bytes()
        == inputs[
            study.calibration_candidate_run_directory(first.candidates[0])
        ].momenta_path.read_bytes()
    )
    assert all(sha256_file(p) == digest for p, digest in before.items())
    assert sequence._basis(sequence._values(successor, cid)) == good["basis"]
    # Reopen the sequence and request another attempt: the last (worse) trial is not the seed.
    reopened = study.ReferenceCalibrationStudyRunner(successor.study_directory)
    again = sequence.run_specimen_sequence(reopened, action=("improve", cid, 0))
    assert study._verify_manifest(again.study_directory)["fit_search"]["warm_seed"][
        "source_study"
    ] == str(first.study_directory)
    assert preferences.comparison_choices(again.study_directory)["best"] == good


def test_better_promotes_current_and_resets_local_proposals(tmp_path, monkeypatch):
    runner, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    current = preferences.fit_record(second, cid)
    comparison = dict(current=current, reference=preferences.fit_record(first, cid), best=None)
    successor = sequence.run_specimen_sequence(runner, action=("better", cid, comparison))
    assert sequence._read(root)["best_fits"]["0"] == current
    seed = study._verify_manifest(successor.study_directory)["fit_search"]["warm_seed"]
    assert seed["source_study"] == str(second.study_directory)
    assert not successor.visual_reviews
    assert load_config(successor.candidates[0].config_path)["optimization"]["freeze_template"]


@pytest.mark.parametrize("change", ["reference", "current", "best"])
def test_stale_or_foreign_comparison_cannot_change_starting_point(tmp_path, monkeypatch, change):
    runner, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    data = dict(
        current=preferences.fit_record(second, cid),
        reference=preferences.fit_record(first, cid),
        best=None,
    )
    if change == "reference":
        data["reference"] = dict(data["reference"], study="../outside")
    elif change == "current":
        data["current"] = dict(data["current"], run_sha256="0" * 64)
    else:
        data["best"] = data["reference"]
    before = (root / sequence.STATE).read_bytes()
    with pytest.raises(ValueError):
        sequence.run_specimen_sequence(runner, action=("better", cid, data))
    assert (root / sequence.STATE).read_bytes() == before


def test_best_and_feedback_survive_failed_preparation(tmp_path, monkeypatch):
    runner, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    record = preferences.fit_record(first, cid)
    data = dict(current=preferences.fit_record(second, cid), reference=record, best=None)
    monkeypatch.setattr(
        sequence, "_make_child", lambda *a, **k: (_ for _ in ()).throw(ValueError("prepare failed"))
    )
    with pytest.raises(ValueError, match="prepare failed"):
        sequence.run_specimen_sequence(runner, action=("worse", cid, data))
    state = sequence._read(root)
    assert state["best_fits"]["0"] == record and len(state["fit_preferences"]) == 1
    assert state["current"] == second.study_directory.name
    assert state["approved"] == []


def test_feedback_chain_corruption_and_nonbest_reference_are_rejected(tmp_path, monkeypatch):
    runner, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    state = sequence._read(root)
    cid = second.candidates[0].candidate_id
    good = preferences.fit_record(first, cid)
    current = preferences.fit_record(second, cid)
    preferences.record_preference(
        root, state, second, cid, "worse", dict(current=current, reference=good, best=None)
    )
    preferences.verify_preferences(root, state)
    # Knowing the state checksum does not make an altered historical rating valid.
    state["fit_preferences"][0]["outcome"] = "better"
    sequence._save(root, state)
    with pytest.raises(ValueError, match="history changed"):
        sequence._read(root)


def test_first_fit_can_be_a_provisional_start_without_becoming_approved(tmp_path, monkeypatch):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    mock_singleton(monkeypatch, first)
    choices = preferences.comparison_choices(first.study_directory)
    assert choices["choices"] == [] and choices["best"] is None
    cid = first.candidates[0].candidate_id
    successor = sequence.run_specimen_sequence(runner, action=("starting_point", cid, 0))
    root = Path(sequence.sequence_info(successor.study_directory)["root"])
    assert sequence._read(root)["approved"] == []
    assert sequence._read(root)["best_fits"]["0"]["study"] == first.study_directory.name
    assert not successor.visual_reviews


@pytest.mark.parametrize("outcome", ["better", "worse", "same"])
def test_final_inspection_saves_ranking_without_launching_and_rejection_uses_it(
    tmp_path, monkeypatch, outcome
):
    runner, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    previous = preferences.fit_record(first, cid)
    current = preferences.fit_record(second, cid)
    comparison = dict(current=current, reference=previous, best=None)
    trials = tuple(sequence._read(root)["trials"])
    preferred = preferences.save_inspection_preference(
        second.study_directory, (outcome, cid, comparison)
    )
    state = sequence._read(root)
    assert tuple(state["trials"]) == trials and state["current"] == second.study_directory.name
    assert state["approved"] == []
    assert study.load_reference_calibration_study(second.study_directory).visual_reviews == {}
    assert preferred == (current if outcome == "better" else previous)
    _reject(second)
    successor = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    assert study._verify_manifest(successor.study_directory)["fit_search"]["warm_seed"][
        "source_study"
    ] == str(root / preferred["study"])


def test_inspection_preference_rejects_a_stale_fit_without_writing(tmp_path, monkeypatch):
    _, root, first, second, _ = prepared_pair(tmp_path, monkeypatch)
    cid = second.candidates[0].candidate_id
    comparison = dict(current=preferences.fit_record(first, cid), reference=None, best=None)
    before = (root / sequence.STATE).read_bytes()
    with pytest.raises(ValueError, match="no longer current"):
        preferences.save_inspection_preference(
            first.study_directory, ("starting_point", cid, comparison)
        )
    assert (root / sequence.STATE).read_bytes() == before
