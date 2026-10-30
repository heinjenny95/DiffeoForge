"""Bound ancestor verification is reused only inside an immutable read action."""
import json
import os

import pytest
from test_interactive_pilot import initial

from diffeoforge import reference_calibration_study as study


def test_manifest_is_verified_once_and_cached_values_are_independent(tmp_path, monkeypatch):
    snapshot = initial(tmp_path)
    original = study._verify_manifest_uncached
    calls = []
    def observed(root):
        calls.append(root)
        return original(root)
    monkeypatch.setattr(study, "_verify_manifest_uncached", observed)
    with study.calibration_verification_scope():
        first = study._verify_manifest(snapshot.study_directory)
        first["scientific_boundary"] = "caller mutation"
        second = study._verify_manifest(snapshot.study_directory)
        assert second["scientific_boundary"] != "caller mutation"
        assert calls.count(snapshot.study_directory) == 1
        assert len(calls) == len(set(calls))
    study._verify_manifest(snapshot.study_directory)
    assert calls.count(snapshot.study_directory) == 2


def test_input_changes_inside_action_and_between_actions_fail(tmp_path):
    snapshot = initial(tmp_path)
    root = snapshot.study_directory
    manifest = json.loads((root / study.STUDY_MANIFEST).read_text())
    asset = root / manifest["inputs"]["template"]["copy"]
    before = asset.read_bytes()
    old_stat = asset.stat()
    with study.calibration_verification_scope():
        study._verify_manifest(root)
        asset.write_bytes(before + b"changed")
        with pytest.raises(ValueError, match="changed during"):
            study._verify_manifest(root)
    # Restoring timestamps cannot reuse any prior action's hash result.
    asset.write_bytes(bytes([before[0] ^ 1]) + before[1:])
    os.utime(asset, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    with pytest.raises(ValueError, match="input changed"):
        study._verify_manifest(root)


def test_cyclic_manifest_recursion_fails_without_poisoning_later_reads(tmp_path, monkeypatch):
    snapshot = initial(tmp_path)
    original = study._verify_manifest_uncached
    monkeypatch.setattr(study, "_verify_manifest_uncached", study._verify_manifest)
    with pytest.raises(ValueError, match="Cyclic calibration manifest"):
        study._verify_manifest(snapshot.study_directory)
    monkeypatch.setattr(study, "_verify_manifest_uncached", original)
    study._verify_manifest(snapshot.study_directory)


def test_ancestor_asset_changes_are_checked_on_cached_descendant(tmp_path):
    from pathlib import Path

    snapshot = initial(tmp_path)
    root = snapshot.study_directory
    origin = Path(snapshot.attachment_comparison["guided"]["origin"])
    ancestor = json.loads((origin / study.STUDY_MANIFEST).read_text())
    asset = origin / ancestor["source_config"]["copy"]
    with study.calibration_verification_scope():
        study._verify_manifest(root)
        asset.write_text(asset.read_text() + "\n# changed in ancestor\n")
        with pytest.raises(ValueError, match="changed during"):
            study._verify_manifest(root)


def test_complete_pilot_state_shares_ancestor_work_but_next_action_verifies_again(
    tmp_path, monkeypatch,
):
    from collections import Counter

    from test_pilot_form_progress import local_fit

    from diffeoforge import guided_strategy

    _, snapshot = local_fit(tmp_path, monkeypatch)
    original = study._verify_manifest_uncached
    calls = Counter()
    def observed(root):
        calls[root] += 1
        return original(root)
    monkeypatch.setattr(study, '_verify_manifest_uncached', observed)
    first = guided_strategy.state(snapshot)
    assert first['next_forms']['guided-varifold']['available']
    assert calls and set(calls.values()) == {1}
    assert not hasattr(study._LOAD_CONTEXT, 'manifests')
    before = calls.copy()
    assert guided_strategy.state(snapshot)['next_forms'] == first['next_forms']
    assert calls == Counter({root: count*2 for root, count in before.items()})


def test_retained_run_resolution_checks_each_ancestor_once_and_rechecks_next_call(
    tmp_path, monkeypatch,
):
    from collections import Counter

    from test_reference_stage_retention import _second_stage

    from diffeoforge.reference_stage_retention import keep_previous_fit

    _, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    third = keep_previous_fit(second.study_directory)
    candidate = third.candidates[-1]
    original = study._verify_manifest_uncached
    calls = Counter()
    def observed(root):
        calls[root] += 1
        return original(root)
    monkeypatch.setattr(study, '_verify_manifest_uncached', observed)
    assert study.calibration_candidate_run_directory(candidate) == accepted.run_directory
    assert calls and set(calls.values()) == {1}
    before = calls.copy()
    assert study.calibration_candidate_run_directory(candidate) == accepted.run_directory
    assert calls == Counter({root: count*2 for root, count in before.items()})


@pytest.mark.parametrize('changed', ['events', 'review_created', 'config', 'result'])
def test_retained_reference_cache_checks_journals_config_and_outputs(
    tmp_path, monkeypatch, changed,
):
    from test_reference_stage_retention import _second_stage

    from diffeoforge.reference_stage_retention import verify_reference

    _, _, accepted, second = _second_stage(tmp_path, monkeypatch)
    root = second.study_directory
    record = next(e for e in study._load_events(root) if e['event'] == 'stage_retained')
    path = dict(events=root/study.STUDY_EVENTS, review_created=root/'visual-reviews.json',
                config=accepted.config_path, result=accepted.run_directory/'result.json')[changed]
    with study.calibration_verification_scope():
        verified = verify_reference(root, record)
        # Returned metrics are caller-owned; mutation cannot poison the scoped record.
        verified.metrics['caller_mutation'] = True
        assert 'caller_mutation' not in verify_reference(root, record).metrics
        path.write_bytes((path.read_bytes() if path.exists() else b'') + b'changed')
        with pytest.raises(ValueError, match='changed during'):
            verify_reference(root, record)


def test_cyclic_retained_reference_does_not_poison_a_later_action(tmp_path, monkeypatch):
    from diffeoforge import reference_stage_retention as retained

    record = dict(retained_source=dict(study_directory=str(tmp_path)))
    with monkeypatch.context() as patch:
        patch.setattr(retained, '_verify_reference', retained.verify_reference)
        with pytest.raises(ValueError, match='Cyclic retained-fit'):
            retained.verify_reference(tmp_path, record)
    assert not hasattr(study._LOAD_CONTEXT, 'retained_references')
