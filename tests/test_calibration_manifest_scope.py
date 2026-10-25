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
