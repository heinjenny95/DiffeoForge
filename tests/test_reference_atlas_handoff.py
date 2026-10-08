"""Identity, immutability and review gates for the pilot-to-atlas handoff."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from test_pilot_cohort_handoff import handoff  # noqa: F401

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_handoff import (
    ADAPTER,
    EARLY_CHECK,
    PROGRESS,
    REVIEW,
    configure_preserved_pilot,
    configure_resume,
    initialization,
    record_early_review,
    verify_early_check_files,
)
from diffeoforge.reference_checkpoint_schedule import new_run_config, render_adapter
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_pca_deformations import _write_momenta
from diffeoforge.runs import prepare_run


@pytest.fixture
def preserved(handoff, tmp_path):  # noqa: F811
    path, inputs, template, controls = handoff
    config = load_config(path)
    root = tmp_path / "bound-seed"
    root.mkdir()
    files = {}
    for role, source in (("template", template), ("control_points", controls)):
        target = root / source.name
        target.write_bytes(source.read_bytes())
        files[role] = {"copy": target.name, "sha256": sha256_file(target)}
    names = [inputs.subjects[-1].name, inputs.subjects[1].name]
    fields = np.arange(12, dtype=float).reshape(2, 2, 3) / 128
    _write_momenta(root / "momenta.txt", fields)
    files["momenta"] = {"copy": "momenta.txt", "sha256": sha256_file(root / "momenta.txt")}
    seed = {
        "files": files,
        "subject_labels": names,
        "source_run_directory": "synthetic-source",
        "source_manifest_sha256": "c" * 64,
    }
    configure_preserved_pilot(config, root=root, seed=seed, config_directory=path.parent)
    return config, path, root, seed, inputs


def test_exact_pilot_identity_order_preserved_other_rows_zero_and_no_old_bytes_changed(preserved):
    config, path, root, seed, inputs = preserved
    old = {p: p.read_bytes() for p in (path, inputs.template, *inputs.subjects)}
    plan = initialization(config)
    rows = read_deformetrica_momenta(root / "full-cohort-momenta.txt")
    pilot = read_deformetrica_momenta(root / "momenta.txt")
    np.testing.assert_array_equal(rows[plan["pilot_indices"]], pilot)
    assert plan["subject_labels"] == [p.name for p in inputs.subjects]
    other = sorted(set(range(len(rows))) - set(plan["pilot_indices"]))
    np.testing.assert_array_equal(rows[other], 0)
    content = (root / "full-cohort-momenta.txt").read_bytes()
    configure_preserved_pilot(config, root=root, seed=seed, config_directory=path.parent)
    assert (root / "full-cohort-momenta.txt").read_bytes() == content
    target = path.with_name("preserved.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert validate_input_paths(load_config(target), target).subjects == inputs.subjects
    run = prepare_run(target, run_id="preserved")
    assert (run / "input/control/initial-momenta.txt").is_file() or (
        list((run / "input").rglob("*momenta*"))
    )
    assert all(p.read_bytes() == data for p, data in old.items())
    compile(
        render_adapter(atlas_source="\n_DF_ATLAS_PLAN = " + repr(plan) + "\n" + ADAPTER),
        "sitecustomize.py",
        "exec",
    )


def test_changed_seed_and_full_cohort_refused_before_run_publication(preserved):
    config, path, root, seed, inputs = preserved
    (root / "momenta.txt").write_bytes(b"broken")
    with pytest.raises(ConfigurationError, match="seed changed"):
        configure_preserved_pilot(config, root=root, seed=seed, config_directory=path.parent)
    inputs.subjects[0].write_bytes(inputs.subjects[0].read_bytes() + b"\n")
    target = path.with_name("preserved.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="geometry changed"):
        prepare_run(target, run_id="changed")
    assert not (target.parent / "runs/changed").exists()


@pytest.fixture
def early(preserved, tmp_path, monkeypatch):
    config, _, _, _, inputs = preserved
    run = tmp_path / "early-run"
    output = run / "output"
    output.mkdir(parents=True)
    (output / "deformetrica-state.p").write_bytes(b"opaque native checkpoint; never unpickled")
    rows = []
    for index in initialization(config)["pilot_indices"]:
        record = {"index": index}
        for phase in ("before", "after"):
            path = output / f"{phase}-{index}.vtk"
            path.write_bytes(inputs.template.read_bytes())
            record[phase] = {"path": path.name, "sha256": sha256_file(path), "index": index}
        rows.append(record)
    receipt = {
        "version": "0.1",
        "pilot_indices": initialization(config)["pilot_indices"],
        "subject_labels": initialization(config)["subject_labels"],
        "iteration": 10,
        "checkpoint_sha256": sha256_file(output / "deformetrica-state.p"),
        "meshes": rows,
        "pilot_momenta_preserved_exactly": True,
    }
    (output / EARLY_CHECK).write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(
        "diffeoforge.result_report.collect_run_report",
        lambda _: SimpleNamespace(
            checks=(SimpleNamespace(status="pass"),),
            manifest={"effective_config": config},
        ),
    )
    return config, run, receipt


def test_missing_incomplete_rejected_or_stale_review_never_resumes(early):
    config, run, receipt = early
    with pytest.raises(ConfigurationError, match="Review.*before resuming"):
        configure_resume(config, run)
    names = initialization(config)["pilot_subject_labels"]
    with pytest.raises(ConfigurationError, match="Inspect all"):
        record_early_review(run, approved=True, inspected_subjects=names[:1])
    record_early_review(run, approved=False, inspected_subjects=names[:1])
    with pytest.raises(ConfigurationError, match="rejected, incomplete or stale"):
        configure_resume(config, run)
    record_early_review(run, approved=True, inspected_subjects=names)
    configure_resume(config, run)
    assert initialization(config)["early_review_approved"] is True
    assert initialization(config)["early_review_binding"]["review_sha256"] == sha256_file(
        run / "analysis" / REVIEW
    )
    (run / "output/deformetrica-state.p").write_bytes(b"other checkpoint")
    with pytest.raises(ConfigurationError, match="checkpoint or subject binding"):
        configure_resume(config, run)


def test_initializer_resume_restores_completed_indices_only_on_exact_checkpoint(
    preserved, tmp_path
):
    config, _, _, _, _ = preserved
    run = tmp_path / "interrupted-initializer"
    (run / "output").mkdir(parents=True)
    checkpoint = run / "output/deformetrica-state.p"
    checkpoint.write_bytes(b"checkpoint")
    progress = {
        "version": "0.1",
        "subject_labels": initialization(config)["subject_labels"],
        "completed_indices": [0, 1],
        "checkpoint_sha256": sha256_file(checkpoint),
    }
    (run / "output" / PROGRESS).write_text(json.dumps(progress), encoding="utf-8")
    configure_resume(config, run)
    assert initialization(config)["completed_initialization_indices"] == [0, 1]
    assert not initialization(config)["early_review_approved"]
    checkpoint.write_bytes(b"changed")
    with pytest.raises(ConfigurationError, match="not bound"):
        configure_resume(config, run)


def test_changed_early_mesh_blocks_review_and_legacy_configs_keep_their_meaning(early):
    config, run, receipt = early
    path = run / "output" / receipt["meshes"][0]["after"]["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError, match="mesh changed"):
        verify_early_check_files(run, config)
    legacy = {"output": {}}
    assert initialization(new_run_config(legacy)) is None
    configure_resume(legacy, Path("unused"))
    assert legacy == {"output": {}}
