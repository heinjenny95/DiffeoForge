"""Identity, immutability and review gates for the pilot-to-atlas handoff."""

import hashlib
import json
import pickle
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import yaml
from test_pilot_cohort_handoff import handoff  # noqa: F401
from test_reference_checkpoint_schedule import _adapter
from test_runs import _execute_cap_fixture, abandon_prepared_run, write_tetrahedron

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_handoff import (
    ADAPTER,
    EARLY_CHECK,
    INITIAL_SCREEN_VERSION,
    METHOD,
    PROGRESS,
    REFINEMENT_METHOD,
    REVIEW,
    REVIEW_CHOICE,
    adapter_source,
    choose_direct_joint_start,
    choose_early_review,
    choose_initial_fit_screen,
    configure_preserved_pilot,
    configure_resume,
    direct_joint_start_enabled,
    early_review_enabled,
    initialization,
    is_initial_fit_review,
    record_early_review,
    record_early_review_choice,
    verify_early_check_files,
)
from diffeoforge.reference_checkpoint_schedule import new_run_config, render_adapter
from diffeoforge.reference_pca import read_deformetrica_momenta
from diffeoforge.reference_pca_deformations import _write_momenta
from diffeoforge.reference_preparation_plan import plan_reference_preparation
from diffeoforge.runs import (
    prepare_resume_run,
    prepare_run,
    prepare_run_against_plan,
    recover_run,
    verify_prepared_run,
)


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


def test_new_handoff_defaults_off_and_linked_opt_in_preserves_source(preserved):
    config, path, _, _, _ = preserved
    assert early_review_enabled(initialization(config)) is False
    assert "initial_fit_screen" not in initialization(config)
    assert "_DF_INITIAL_SCREEN_VERSION =" not in adapter_source(new_run_config(config))
    target = path.with_name("optional.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = target.read_bytes()
    chosen = choose_early_review(target, enabled=True)
    assert early_review_enabled(initialization(load_config(chosen))) is True
    assert target.read_bytes() == original
    assert choose_early_review(target, enabled=True) == chosen
    legacy = dict(initialization(config))
    legacy.pop("early_review_enabled")
    assert early_review_enabled(legacy) is True
    with pytest.raises(ConfigurationError, match="boolean"):
        choose_early_review(target, enabled=0)


def test_starting_fit_review_opt_in_and_legacy_opt_out_are_linked(preserved):
    config, path, _, _, _ = preserved
    target = path.with_name("saved-pilot.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = target.read_bytes()
    assert choose_initial_fit_screen(target, enabled=False) == target
    linked = choose_initial_fit_screen(target, enabled=True)
    assert linked != target and target.read_bytes() == original
    opted_in = load_config(linked)
    assert initialization(opted_in)["initial_fit_screen"] == INITIAL_SCREEN_VERSION
    assert "_DF_INITIAL_SCREEN_VERSION =" in adapter_source(new_run_config(opted_in))
    assert choose_initial_fit_screen(linked, enabled=True) == linked
    screened = linked.read_bytes()
    off = choose_initial_fit_screen(linked, enabled=False)
    assert off != linked and linked.read_bytes() == screened
    assert load_config(off) == config
    assert choose_initial_fit_screen(linked, enabled=False) == off
    with pytest.raises(ConfigurationError, match="boolean"):
        choose_initial_fit_screen(target, enabled=1)


@pytest.fixture
def completed_joint_pilot(tmp_path, monkeypatch):
    from test_pilot_completion import _approve_preview, _checked

    from diffeoforge import reference_adaptive_calibration as adaptive
    from diffeoforge.reference_pilot_completion import finish

    _, checked, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    _approve_preview(checked, identifier)
    bind = adaptive.bind_learned_seed
    source = {}

    def bind_fields(snapshot, center_id, destination):
        seed = bind(snapshot, center_id, destination)
        record = seed["files"]["momenta"]
        path = destination / record["copy"]
        fields = read_deformetrica_momenta(path)
        fields[:] = np.arange(fields.size).reshape(fields.shape) / 128
        path.unlink()
        _write_momenta(path, fields)
        record["sha256"] = sha256_file(path)
        source[seed["source_run_directory"]] = SimpleNamespace(
            source_hashes={"manifest.json": seed["source_manifest_sha256"]},
            momenta_record={"sha256": record["sha256"]},
            control_points_record={"sha256": seed["files"]["control_points"]["sha256"]},
            subject_labels=tuple(seed["subject_labels"]),
            momenta=fields,
            run_report=SimpleNamespace(inventory=({
                "path": "DeterministicAtlas__EstimatedParameters__Template_surface.vtk",
                "sha256": seed["files"]["template"]["sha256"],
            },)),
        )
        return seed

    # Only the synthetic pilot runner lacks a native inventory. Preserve the real
    # review ledger and exercise ordinary atlas preparation and sealed execution below.
    monkeypatch.setattr(adaptive, "bind_learned_seed", bind_fields)
    monkeypatch.setattr("diffeoforge.reference_pca.load_reference_momenta", source.__getitem__)
    completed, _ = finish(checked.study_directory, identifier)
    return completed


def test_direct_joint_handoff_preserves_pilot_and_prepares_native_run(
    completed_joint_pilot, monkeypatch
):
    source = completed_joint_pilot.final_config_path
    before = {p: p.read_bytes() for p in completed_joint_pilot.study_directory.rglob("*")
              if p.is_file()}
    assert choose_direct_joint_start(source, enabled=False) == source
    direct = choose_direct_joint_start(source, enabled=True)
    assert direct != source
    assert all(p.read_bytes() == data for p, data in before.items())
    assert choose_direct_joint_start(source, enabled=True) == direct
    assert choose_direct_joint_start(direct, enabled=True) == direct
    assert choose_direct_joint_start(direct, enabled=False) == source

    config = load_config(direct)
    plan = initialization(config)
    assert direct_joint_start_enabled(plan) and not early_review_enabled(plan)
    assert not direct_joint_start_enabled(initialization(load_config(source)))
    assert adapter_source(new_run_config(config)) == ""
    for choice in (choose_early_review, choose_initial_fit_screen):
        assert choice(direct, enabled=False) == direct
        with pytest.raises(ConfigurationError, match="unavailable"):
            choice(direct, enabled=True)

    serial = prepare_run(source, run_id="serial-pilot-handoff")
    preparation = plan_reference_preparation(direct, run_id="direct-pilot-handoff")
    run = prepare_run_against_plan(direct, preparation)
    manifest = verify_prepared_run(run)
    assert initialization(manifest["effective_config"]) == plan
    for name in ("model.xml", "data_set.xml", "optimization_parameters.xml"):
        assert (run / "engine" / name).read_bytes() == (serial / "engine" / name).read_bytes()
    for directory in ("template", "control-points", "momenta"):
        assert [p.read_bytes() for p in (run / "input" / directory).iterdir()] == [
            p.read_bytes() for p in (serial / "input" / directory).iterdir()
        ]
    native = (run / "engine/sitecustomize.py").read_text(encoding="utf-8")
    assert "_df_atlas_update" not in native
    assert "_df_flow" in native  # Compact native checkpoint/final export remains present.
    compile(native, "sitecustomize.py", "exec")
    # Also restore an interrupted direct-joint run via normal stopped-worker recovery.
    interrupted = prepare_run(direct, run_id="direct-interrupted")
    abandon_prepared_run(interrupted, checkpoint=b"opaque interrupted state")
    recover_run(interrupted, reason="Synthetic interruption", confirm_process_stopped=True)
    resumed = prepare_resume_run(interrupted, run_id="direct-resume")
    assert initialization(verify_prepared_run(resumed)["effective_config"]) == plan
    assert "_df_atlas_update" not in (resumed / "engine/sitecustomize.py").read_text()

    # A prepared run and its capped successor are self-contained even after archiving the
    # project-level source. Check the copied binding through ordinary prepare/execute/resume.
    original = before[source]
    source.unlink()
    try:
        assert verify_prepared_run(run) == manifest
        _execute_cap_fixture(run, monkeypatch)
        successor = prepare_resume_run(run, run_id="direct-plus-300", additional_iterations=300)
        extended = verify_prepared_run(successor)
        assert initialization(extended["effective_config"]) == plan
        assert extended["effective_config"]["optimization"]["max_iterations"] == (
            config["optimization"]["max_iterations"] + 300
        )
        assert "_df_atlas_update" not in (successor / "engine/sitecustomize.py").read_text()
    finally:
        source.write_bytes(original)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_direct_joint_rejects_edited_link_or_missing_recorded_review(completed_joint_pilot):
    from diffeoforge import reference_calibration_study as study

    source = completed_joint_pilot.final_config_path
    direct = choose_direct_joint_start(source, enabled=True)
    edited = load_config(direct)
    edited["optimization"]["max_iterations"] += 1
    edited_path = direct.with_name("direct-with-edited-budget.yaml")
    edited_path.write_text(yaml.safe_dump(edited), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="differs from its saved pilot"):
        prepare_run(edited_path, run_id="changed-direct")

    root, _ = study._search_extension_series(completed_joint_pilot.study_directory)
    journal = root / "visual-reviews.json"
    saved = journal.read_bytes()
    journal.unlink()
    try:
        with pytest.raises(ConfigurationError, match="Review"):
            validate_input_paths(load_config(direct), direct)
    finally:
        journal.write_bytes(saved)


def test_flagged_initial_fit_requires_its_own_review_and_keeps_pilot_gate(early):
    config, run, old = early
    output = run / "output"
    plan = initialization(config)
    plan["initial_fit_screen"] = INITIAL_SCREEN_VERSION
    plan["early_review_enabled"] = True
    (output / "atlas-initialized-state.p").write_bytes(
        (output / "deformetrica-state.p").read_bytes()
    )
    indices = sorted(set(range(len(plan["subject_labels"]))) - set(plan["pilot_indices"]))
    flagged = indices[0]
    fit = output / "initial-fit-review" / f"fit-{flagged:04d}.vtk"
    fit.parent.mkdir()
    fit.write_bytes((output / old["meshes"][0]["after"]["path"]).read_bytes())
    value = {
        "version": INITIAL_SCREEN_VERSION,
        "phase": "initialization",
        "pilot_indices": [flagged],
        "subject_labels": plan["subject_labels"],
        "iteration": 0,
        "checkpoint_sha256": old["checkpoint_sha256"],
        "screened": [{"index": index, "distance_threshold": .1,
                      "priority": 2 * .05**.5 if index == flagged else 0.,
                      "patches": [{"direction": "missing_surface", "peak_point": [1, 2, 3],
                                   "peak_distance": .2, "area_fraction": .05}]
                      if index == flagged else []} for index in indices],
        "meshes": [{"index": flagged, "after": {"index": flagged,
                    "path": fit.relative_to(output).as_posix(), "sha256": sha256_file(fit)}}],
    }
    (output / EARLY_CHECK).write_text(json.dumps(value), encoding="utf-8")
    assert is_initial_fit_review(run)
    with pytest.raises(ConfigurationError, match="Review the flagged"):
        configure_resume(config, run)
    with pytest.raises(ConfigurationError, match="require a recorded visual review"):
        record_early_review_choice(run, enabled=False)
    label = plan["subject_labels"][flagged]
    record_early_review(run, approved=True, inspected_subjects=[label])
    configure_resume(config, run)
    assert plan["initial_fit_screen_binding"]["review_sha256"] == sha256_file(
        run / "analysis" / REVIEW
    )
    assert not plan["early_review_approved"] and plan["early_review_enabled"]
    fit.write_bytes(fit.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError, match="mesh changed"):
        configure_resume(config, run)


def test_optional_review_choice_is_bound_and_never_anatomical_approval(early):
    config, run, _ = early
    original = {p: p.read_bytes() for p in (run / "output").iterdir()}
    record_early_review_choice(run, enabled=False)
    configure_resume(config, run)
    plan = initialization(config)
    assert plan["early_review_enabled"] is False
    assert plan["early_review_approved"] is False
    assert plan["completed_initialization_indices"] == list(range(len(plan["subject_labels"])))
    assert not (run / "analysis" / REVIEW).exists()
    assert all(p.read_bytes() == data for p, data in original.items())
    choice_path = run / "analysis" / REVIEW_CHOICE
    choice = json.loads(choice_path.read_text())
    choice["checkpoint_sha256"] = "a" * 64
    choice_path.write_text(json.dumps(choice), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid or stale"):
        configure_resume(config, run)


def test_explicit_anatomical_rejection_cannot_be_bypassed_by_optional_choice(early):
    config, run, _ = early
    record_early_review(run, approved=False, inspected_subjects=[])
    before = (run / "analysis" / REVIEW).read_bytes()
    with pytest.raises(ConfigurationError, match="rejected"):
        record_early_review_choice(run, enabled=False)
    assert (run / "analysis" / REVIEW).read_bytes() == before
    with pytest.raises(ConfigurationError, match="rejected, incomplete or stale"):
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


@pytest.mark.parametrize("mode", ["compact_final_export", "compact_convergence_export"])
def test_saved_atlas_refinement_rejects_moving_basis_before_preparation(preserved, mode):
    config, path, _, _, _ = preserved
    initialization(config)["method"] = REFINEMENT_METHOD
    initialization(config)["source_momenta_sha256"] = "d" * 64
    config["optimization"].update(freeze_template=True, freeze_control_points=True)
    config["output"]["checkpoint_mode"] = mode
    target = path.with_name("refinement.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepare_run(target, run_id="fixed-refinement")
    assert REFINEMENT_METHOD in (run / "engine/sitecustomize.py").read_text()
    for setting in ("freeze_template", "freeze_control_points"):
        config["optimization"][setting] = False
        with pytest.raises(ConfigurationError, match="frozen template and controls"):
            adapter_source(new_run_config(config))
        config["optimization"][setting] = True


@pytest.mark.parametrize("mode", ["compact_final_export", "compact_convergence_export"])
def test_saved_atlas_refinement_keeps_checkpoint_bound_review_gate(early, mode):
    config, run, _ = early
    config["output"]["checkpoint_mode"] = mode
    initialization(config)["method"] = REFINEMENT_METHOD
    with pytest.raises(ConfigurationError, match="Review.*before resuming"):
        configure_resume(config, run)
    record_early_review(
        run, approved=True, inspected_subjects=initialization(config)["pilot_subject_labels"]
    )
    configure_resume(config, run)
    assert initialization(config)["early_review_approved"] is True


@pytest.mark.parametrize("method", [METHOD, REFINEMENT_METHOD])
@pytest.mark.parametrize("decision", ["approve", "skip_optional"])
def test_preserved_atlas_capped_resume_accepts_convergence_export_mode(
    preserved, monkeypatch, method, decision
):
    config, path, _, _, _ = preserved
    plan = initialization(config)
    plan["method"] = method
    if method == REFINEMENT_METHOD:
        plan["source_momenta_sha256"] = "d" * 64
    config["optimization"].update(
        max_iterations=10, freeze_template=True, freeze_control_points=True
    )
    target = path.with_name("reviewed-atlas.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    early_run = prepare_run(target, run_id="early-atlas")
    output_files = {}
    rows = []
    mesh_bytes = write_tetrahedron(path.with_name("early-shape.vtk")).read_bytes()
    for index in plan["pilot_indices"]:
        row = {"index": index}
        for phase in ("before", "after"):
            name = f"{phase}-{index}.vtk"
            output_files[f"output/{name}"] = mesh_bytes
            row[phase] = {
                "index": index, "path": name, "sha256": hashlib.sha256(mesh_bytes).hexdigest(),
            }
        rows.append(row)
    output_files[f"output/{EARLY_CHECK}"] = json.dumps({
        "version": "0.1", "iteration": 10, "pilot_indices": plan["pilot_indices"],
        "subject_labels": plan["subject_labels"], "pilot_momenta_preserved_exactly": True,
        "checkpoint_sha256": hashlib.sha256(b"opaque-native-state").hexdigest(), "meshes": rows,
    }).encode("utf-8")
    _execute_cap_fixture(early_run, monkeypatch, output_files=output_files)
    if decision == "approve":
        record_early_review(
            early_run, approved=True, inspected_subjects=plan["pilot_subject_labels"]
        )
    else:
        record_early_review_choice(early_run, enabled=False)
    source = prepare_resume_run(
        early_run, run_id="capped-reviewed-atlas", additional_iterations=300
    )
    _execute_cap_fixture(source, monkeypatch)
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    successor = prepare_resume_run(
        source, run_id="convergence-reviewed-atlas", additional_iterations=300,
        checkpoint_mode="compact_convergence_export",
    )
    effective = verify_prepared_run(successor)["effective_config"]
    assert initialization(effective)["method"] == method
    assert initialization(effective)["early_review_approved"] is (decision == "approve")
    if decision == "skip_optional":
        assert initialization(effective)["early_review_enabled"] is False
        assert (successor / "resume" / REVIEW_CHOICE).is_file()
    assert effective["optimization"]["max_iterations"] == 610
    adapter = (successor / "engine/sitecustomize.py").read_text()
    assert "_df_export_on_convergence = True" in adapter
    assert "_df_ga.update = _df_atlas_update" in adapter
    compile(adapter, "sitecustomize.py", "exec")
    _execute_cap_fixture(successor, monkeypatch)
    following = prepare_resume_run(successor, run_id="following-atlas", additional_iterations=300)
    assert verify_prepared_run(following)["effective_config"]["output"]["checkpoint_mode"] == (
        "compact_convergence_export"
    )
    retained = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert retained == before


def test_preserved_pilot_policy_guard_accepts_only_compact_schedules(preserved):
    config, path, root, seed, _ = preserved
    config["output"]["checkpoint_mode"] = "compact_convergence_export"
    configure_preserved_pilot(config, root=root, seed=seed, config_directory=path.parent)
    assert adapter_source(config)
    config["output"]["checkpoint_mode"] = "native_full_outputs"
    with pytest.raises(ConfigurationError, match="compact checkpoints"):
        configure_preserved_pilot(config, root=root, seed=seed, config_directory=path.parent)
    with pytest.raises(ConfigurationError, match="compact checkpoints"):
        adapter_source(config)


@pytest.mark.parametrize("stop,flows", [
    (None, 0),
    ("Tolerance threshold met. Stopping the optimization process.", 2),
])
def test_reviewed_atlas_adapter_composition_keeps_convergence_export_gate(
    preserved, monkeypatch, tmp_path, stop, flows
):
    config, _, _, _, _ = preserved
    initialization(config).update(method=REFINEMENT_METHOD, early_review_approved=True)
    config["optimization"].update(freeze_template=True, freeze_control_points=True)
    config["output"]["checkpoint_mode"] = "compact_convergence_export"
    support = ModuleType("deformetrica.support")
    support.utilities = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "deformetrica.support", support)
    estimator = _adapter(
        monkeypatch, tmp_path, convergence_only=True, stop=stop,
        atlas_source=adapter_source(config),
    )[0]()
    estimator.update()
    assert estimator.statistical_model.exponential.flows == 0
    estimator.write()
    assert estimator.statistical_model.exponential.flows == flows
    assert pickle.loads(Path(estimator.state_file).read_bytes())[0] == 3


@pytest.mark.parametrize("already_initialized", [False, True])
def test_disabled_early_check_runs_native_optimizer_without_review_exports(
    preserved, monkeypatch, tmp_path, already_initialized
):
    config, _, _, _, _ = preserved
    plan = initialization(config)
    plan.update(subject_labels=["a", "b"], pilot_indices=[0, 1],
                completed_initialization_indices=[0, 1] if already_initialized else [],
                early_review_enabled=False, early_review_approved=False)
    support = ModuleType("deformetrica.support")
    support.utilities = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "deformetrica.support", support)
    gradient = _adapter(
        monkeypatch, tmp_path, atlas_source=adapter_source(new_run_config(config))
    )[0]
    estimator = gradient()
    estimator.output_dir = str(tmp_path)
    estimator.callback = None
    estimator._get_parameters = lambda: estimator.current_parameters
    momenta = np.arange(12, dtype=float).reshape(2, 2, 3)
    estimator.statistical_model.get_momenta = lambda: momenta
    estimator.update()
    assert estimator.current_iteration == 3
    assert not (tmp_path / EARLY_CHECK).exists()
    assert not (tmp_path / "early-atlas-before").exists()
    assert not (tmp_path / "early-atlas-after").exists()
    np.testing.assert_array_equal(momenta, np.arange(12).reshape(2, 2, 3))
    assert estimator.statistical_model.exponential.flows == 0
    estimator.write()
    assert estimator.statistical_model.exponential.flows == 2


def test_default_off_joint_checkpoint_resumes_after_completed_initialization(
    preserved, monkeypatch
):
    config, path, _, _, _ = preserved
    config["optimization"]["max_iterations"] = 10
    plan = initialization(config)
    target = path.with_name("no-early-check.yaml")
    target.write_text(yaml.safe_dump(config), encoding="utf-8")
    source = prepare_run(target, run_id="joint-no-early-check")
    initialized = b"verified initialized state before later joint iterations"
    _execute_cap_fixture(source, monkeypatch, output_files={
        "output/atlas-initialized-state.p": initialized,
        f"output/{PROGRESS}": json.dumps({
            "version": "0.1", "subject_labels": plan["subject_labels"],
            "completed_indices": list(range(len(plan["subject_labels"]))),
            "checkpoint_sha256": hashlib.sha256(initialized).hexdigest(),
        }).encode(),
    })
    successor = prepare_resume_run(source, run_id="joint-resumed", additional_iterations=300)
    resumed = initialization(verify_prepared_run(successor)["effective_config"])
    assert resumed["early_review_enabled"] is False
    assert resumed["early_review_approved"] is False
    assert resumed["completed_initialization_indices"] == list(range(len(plan["subject_labels"])))
    assert not (source / "analysis" / REVIEW).exists()
    _execute_cap_fixture(successor, monkeypatch)
    following = prepare_resume_run(successor, run_id="joint-following", additional_iterations=300)
    assert initialization(verify_prepared_run(following)["effective_config"]) == resumed
