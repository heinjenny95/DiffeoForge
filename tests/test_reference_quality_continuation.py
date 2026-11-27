import hashlib
import json
import pickle
import sys
from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree

import pytest
import yaml
from test_reference_atlas_handoff import completed_joint_pilot  # noqa: F401
from test_reference_morphospace_stopping import _retained_report
from test_reference_tolerance_continuation import (
    NATIVE_TOLERANCE_STOP,
    _execute_tolerance_fixture,
    _finish_source,
    _run_hashes,
)
from test_runs import _execute_cap_fixture, _finish_at_cap, abandon_prepared_run, write_run_config

import diffeoforge.runs as runs
from diffeoforge.backends import CommandSpec
from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.reference_prelaunch import (
    DesktopReferenceLaunchRequest,
    DesktopReferencePrelaunchError,
    bind_reference_resume_launch_request,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_handoff import choose_direct_joint_start
from diffeoforge.reference_atlas_stop import (
    MORPHOSPACE_STABILITY,
    MORPHOSPACE_STABILITY_UNLIMITED,
    atlas_iteration_limit,
    stop_policy,
)
from diffeoforge.reference_morphospace_native import LIVE_PREFIX, REPORT_NAME
from diffeoforge.runs import (
    prepare_resume_run,
    prepare_run,
    quality_continuation_preview,
    recover_run,
    verify_prepared_run,
)


@pytest.mark.parametrize(
    "mode,budget", [(MORPHOSPACE_STABILITY, 457), (MORPHOSPACE_STABILITY_UNLIMITED, None)]
)
def test_reopen_native_stop_and_bind_quality_successor(tmp_path, monkeypatch, mode, budget):
    source = _finish_source(tmp_path, monkeypatch)
    hashes = _run_hashes(source)
    request, evidence = bind_reference_resume_launch_request(
        source,
        request_id="choose-quality",
        run_id="quality",
        quality_stop=mode,
        quality_iterations=budget,
    )
    preview = quality_continuation_preview(source, quality_stop=mode, quality_iterations=budget)
    assert request.quality_continuation == evidence.quality_continuation == preview
    assert preview.checkpoint_iteration == 211 and preview.source_reason == "native_tolerance"
    assert DesktopReferenceLaunchRequest.from_dict(request.as_dict()) == request
    request.verify_launch_inputs()
    other = replace(preview, source_log_sha256="a" * 64)
    with pytest.raises(DesktopReferencePrelaunchError, match="changed after review"):
        replace(request, quality_continuation=other).verify_launch_inputs()
    assert not request.destination.exists()
    successor = prepare_resume_run(
        source,
        run_id=request.run_id,
        quality_stop=mode,
        quality_iterations=budget,
        expected_quality_continuation=preview,
    )
    config = verify_prepared_run(successor)["effective_config"]
    assert config["project"]["atlas_stop"] == preview.policy
    assert atlas_iteration_limit(config) == (211 + budget if budget else None)
    assert config["optimization"]["convergence_tolerance"] == preview.source_tolerance
    assert sha256_file(successor / "resume/source-checkpoint.p") == preview.checkpoint_sha256
    xml = ElementTree.parse(successor / "engine/optimization_parameters.xml").getroot()
    assert xml.findtext("state-file") == "../output/deformetrica-state.p"
    assert int(xml.findtext("max-iterations")) == config["optimization"]["max_iterations"]
    assert "morphospace_stability" in (successor / "engine/sitecustomize.py").read_text()
    receipt = json.loads((successor / "resume/resume.json").read_text())
    assert receipt["quality_continuation"] == request.as_dict()["quality_continuation"]
    assert _run_hashes(source) == hashes


def test_quality_continuation_from_capped_direct_pilot_and_then_interruption(request, monkeypatch):
    pilot = request.getfixturevalue("completed_joint_pilot")
    setup = choose_direct_joint_start(pilot.final_config_path, enabled=True)
    source = prepare_run(setup, run_id="direct")
    maximum = verify_prepared_run(source)["effective_config"]["optimization"]["max_iterations"]
    checkpoint = pickle.dumps({"current_iteration": maximum})
    _execute_cap_fixture(source, monkeypatch, checkpoint=checkpoint)
    quality = prepare_resume_run(source, run_id="quality", quality_stop=MORPHOSPACE_STABILITY)
    config = verify_prepared_run(quality)["effective_config"]
    assert config["optimization"]["max_iterations"] == maximum + 300
    assert "_df_atlas_update" not in (quality / "engine/sitecustomize.py").read_text()
    abandon_prepared_run(quality, checkpoint=pickle.dumps({"current_iteration": maximum + 10}))
    recover_run(quality, reason="Synthetic interruption", confirm_process_stopped=True)
    resumed = prepare_resume_run(quality, run_id="interrupted-quality")
    assert verify_prepared_run(resumed)["effective_config"] == config
    assert "_df_atlas_update" not in (resumed / "engine/sitecustomize.py").read_text()


def test_refuse_unverified_stop_and_change_after_binding(tmp_path, monkeypatch):
    source = _finish_source(tmp_path, monkeypatch, stop="Number of line search loops exceeded.")
    with pytest.raises(ConfigurationError, match="must confirm"):
        prepare_resume_run(source, run_id="refused", quality_stop=MORPHOSPACE_STABILITY)
    assert not (source.parent / "refused").exists()


@pytest.mark.parametrize("iteration,valid", [(211, True), (210, False)])
def test_legacy_full_outputs_require_terminal_accepted_state(
    tmp_path, monkeypatch, iteration, valid
):
    source = _finish_source(
        tmp_path, monkeypatch, iteration=iteration, checkpoint_mode="native_full_outputs"
    )
    if not valid:
        with pytest.raises(ConfigurationError, match="must confirm"):
            quality_continuation_preview(source)
        return
    before = _run_hashes(source)
    successor = prepare_resume_run(source, run_id="quality", quality_stop=MORPHOSPACE_STABILITY)
    config = verify_prepared_run(successor)["effective_config"]
    assert config["output"]["checkpoint_mode"] == "compact_final_export"
    receipt = json.loads((successor / "resume/resume.json").read_text())
    assert receipt["output_schedule_change"] == {
        "source_mode": "native_full_outputs",
        "successor_mode": "compact_final_export",
    }
    assert receipt["quality_continuation"]["checkpoint_iteration"] == iteration
    assert _run_hashes(source) == before


@pytest.mark.parametrize("iteration,eligible", [(5, True), (4, False)])
def test_deferred_final_export_requires_exact_cap_checkpoint(
    tmp_path, monkeypatch, iteration, eligible
):
    path = write_run_config(tmp_path)
    config = yaml.safe_load(path.read_text())
    config["output"]["checkpoint_mode"] = "compact_convergence_export"
    config["optimization"].update(max_iterations=5, print_every_n_iterations=2)
    path.write_text(yaml.safe_dump(config))
    source = prepare_run(path, run_id="deferred")
    _execute_tolerance_fixture(
        source,
        monkeypatch,
        "DiffeoForge final mesh export deferred: native stop "
        "maximum_iterations; checkpoint retained",
        iteration,
        logged=4,
    )
    if not eligible:
        with pytest.raises(ConfigurationError, match="must confirm"):
            quality_continuation_preview(source)
        return
    successor = prepare_resume_run(source, run_id="quality", quality_stop=MORPHOSPACE_STABILITY)
    assert (
        verify_prepared_run(successor)["effective_config"]["output"]["checkpoint_mode"]
        == "compact_final_export"
    )
    assert quality_continuation_preview(source).checkpoint_iteration == 5


def test_legacy_convergence_export_reuses_own_reference_in_new_stage(tmp_path, monkeypatch):
    initial = _finish_at_cap(tmp_path, monkeypatch)
    config = json.loads((initial / "manifest.json").read_text())["effective_config"]
    context = dict(
        version=1,
        initial_log_likelihood=-111.0,
        origin_iteration=0,
        origin_checkpoint_sha256="a" * 64,
        convergence_tolerance=config["optimization"]["convergence_tolerance"],
    )
    source = prepare_resume_run(
        initial,
        run_id="convergence",
        additional_iterations=300,
        checkpoint_mode="compact_convergence_export",
        convergence_reference=context,
    )
    _execute_tolerance_fixture(
        source, monkeypatch, NATIVE_TOLERANCE_STOP, 531, logged=530, context=context
    )
    successor = prepare_resume_run(
        source, run_id="strict", optimizer_tolerance=1e-6, iteration_limit=731
    )
    config = verify_prepared_run(successor)["effective_config"]
    assert config["output"]["checkpoint_mode"] == "compact_final_export"
    receipt = json.loads((successor / "resume/resume.json").read_text())
    assert receipt["convergence_reference"] == dict(context, convergence_tolerance=1e-6)
    assert receipt["output_schedule_change"]["source_mode"] == "compact_convergence_export"
    quality = prepare_resume_run(source, run_id="quality", quality_stop=MORPHOSPACE_STABILITY)
    assert (
        verify_prepared_run(quality)["effective_config"]["output"]["checkpoint_mode"]
        == "compact_final_export"
    )


@pytest.mark.parametrize("native", [True, False])
def test_continue_verified_joint_cap_until_quality_stop(tmp_path, monkeypatch, native):
    sample, report = _retained_report(tmp_path, reason="iteration_limit")
    setup = tmp_path / "atlas.yaml"
    if not native:
        config = yaml.safe_load(setup.read_text())
        config["project"]["atlas_stop"] = report["policy"] = stop_policy(MORPHOSPACE_STABILITY)
        setup.write_text(yaml.safe_dump(config))
    source = prepare_run(setup, run_id="capped")
    fields = [row["checkpoint"]["path"] for row in report["observations"]]
    files = {"output/" + field: (sample / "output" / field).read_bytes() for field in fields}
    checkpoint = pickle.dumps({"current_iteration": 2})
    report["terminal"]["checkpoint_sha256"] = hashlib.sha256(checkpoint).hexdigest()
    files["output/" + REPORT_NAME] = json.dumps(report).encode()
    _execute_cap_fixture(source, monkeypatch, output_files=files, checkpoint=checkpoint)
    before = _run_hashes(source)
    successor = prepare_resume_run(
        source, run_id="open", quality_stop=MORPHOSPACE_STABILITY_UNLIMITED
    )
    effective = verify_prepared_run(successor)["effective_config"]
    assert atlas_iteration_limit(effective) is None
    assert (successor / "resume/source-checkpoint.p").read_bytes() == checkpoint
    assert _run_hashes(source) == before
    report_path = source / "output" / REPORT_NAME
    report_path.write_bytes(report_path.read_bytes() + b" ")
    with pytest.raises(ConfigurationError, match="terminal output inventory"):
        prepare_resume_run(source, run_id="stale", quality_stop=MORPHOSPACE_STABILITY)
    assert not (source.parent / "stale").exists()


def _finish_two_joint_steps(
    run,
    origin,
    sample,
    sample_report,
    monkeypatch,
    *,
    reason="iteration_limit",
    export="complete",
    stale_log=False,
):
    config = verify_prepared_run(run)["effective_config"]
    report = deepcopy(sample_report)
    report["joint_origin_iteration"] = origin
    report["policy"] = config["project"]["atlas_stop"]
    snapshots = {}
    files = {}
    for row in report["observations"]:
        previous = row["previous_iteration"]
        if previous is not None:
            for window in (row, row["long_window"]):
                window["previous_iteration"] = previous + origin
                window["previous_checkpoint"] = snapshots[previous]
        offset = row["iteration"]
        row["iteration"] = origin + offset
        old = row["checkpoint"]
        name = f"morphospace-checkpoints/iteration-{row['iteration']}.npz"
        snapshots[offset] = row["checkpoint"] = {**old, "path": name}
        files["output/" + name] = (sample / "output" / old["path"]).read_bytes()
    checkpoint = pickle.dumps({"current_iteration": origin + 2})
    report["terminal"].update(
        iteration=origin + 2,
        checkpoint_sha256=hashlib.sha256(checkpoint).hexdigest(),
        reason=reason,
        export=export,
    )
    files["output/" + REPORT_NAME] = json.dumps(report).encode()
    observed = report["observations"][0 if stale_log else -1]
    log = LIVE_PREFIX + json.dumps(observed)
    if reason == "line_search_exhausted":
        log = "Number of line search loops exceeded. Stopping.\n" + log
    _execute_cap_fixture(
        run,
        monkeypatch,
        output_files=files,
        checkpoint=checkpoint,
        stop=log,
        last_logged_iteration=origin + 2,
    )


@pytest.mark.parametrize(
    "reason,export,stale",
    [
        ("line_search_exhausted", "complete", False),
        ("optimizer_callback", "complete", False),
        ("line_search_exhausted", "complete", True),
        ("optimizer_callback", "failed", False),
        ("cancelled", "complete", False),
        ("backend_failure", "complete", False),
    ],
)
def test_continue_only_from_verified_accepted_terminal_export(
    tmp_path, monkeypatch, reason, export, stale
):
    sample, report = _retained_report(tmp_path)
    setup = tmp_path / "atlas.yaml"
    config = yaml.safe_load(setup.read_text())
    config["optimization"]["max_iterations"] = 30
    setup.write_text(yaml.safe_dump(config))
    source = prepare_run(setup, run_id="joint-stop")
    _finish_two_joint_steps(
        source, 0, sample, report, monkeypatch, reason=reason, export=export, stale_log=stale
    )
    for name, settings in (
        ("numeric", {"optimizer_tolerance": 1e-6, "iteration_limit": 302}),
        ("target", {"iteration_limit": 302}),
        ("quality", {"quality_stop": MORPHOSPACE_STABILITY}),
    ):
        if stale or export != "complete" or reason in ("cancelled", "backend_failure"):
            with pytest.raises(ConfigurationError):
                prepare_resume_run(source, run_id=name, **settings)
            assert not (source.parent / name).exists()
            continue
        request, evidence = bind_reference_resume_launch_request(
            source, request_id=name, run_id=name, **settings
        )
        assert DesktopReferenceLaunchRequest.from_dict(request.as_dict()) == request
        preview = evidence.quality_continuation or evidence.tolerance_continuation
        assert preview.source_reason == reason and preview.checkpoint_iteration == 2
        run = prepare_resume_run(source, run_id=name, **settings)
        assert atlas_iteration_limit(verify_prepared_run(run)["effective_config"]) == 302


def test_cross_rule_chain_preserves_original_objective_and_all_source_runs(tmp_path, monkeypatch):
    sample, report = _retained_report(tmp_path, reason="iteration_limit")
    source = prepare_run(tmp_path / "atlas.yaml", run_id="native")
    _finish_two_joint_steps(source, 0, sample, report, monkeypatch)
    hashes = _run_hashes(source)
    quality = prepare_resume_run(
        source, run_id="quality", quality_stop=MORPHOSPACE_STABILITY, quality_iterations=2
    )
    _finish_two_joint_steps(quality, 2, sample, report, monkeypatch)
    quality_hashes = _run_hashes(quality)
    fixed = prepare_resume_run(quality, run_id="target", iteration_limit=6)
    _finish_two_joint_steps(fixed, 4, sample, report, monkeypatch)
    strict = prepare_resume_run(fixed, run_id="strict", iteration_limit=8, optimizer_tolerance=1e-6)
    receipt = json.loads((strict / "resume/resume.json").read_text())
    reference = receipt["convergence_reference"]
    assert reference["origin_iteration"] == 0 and reference["convergence_tolerance"] == 1e-6
    assert (
        reference["origin_checkpoint_sha256"] == report["observations"][0]["checkpoint"]["sha256"]
    )
    _finish_two_joint_steps(strict, 6, sample, report, monkeypatch)
    final = prepare_resume_run(
        strict, run_id="quality-again", quality_stop=MORPHOSPACE_STABILITY, quality_iterations=413
    )
    assert atlas_iteration_limit(verify_prepared_run(final)["effective_config"]) == 421
    assert sha256_file(final / "resume/source-checkpoint.p") == sha256_file(
        strict / "output/deformetrica-state.p"
    )
    assert _run_hashes(source) == hashes and _run_hashes(quality) == quality_hashes


def test_completed_uncapped_stability_run_accepts_a_later_target(tmp_path, monkeypatch):
    sample, report = _retained_report(
        tmp_path, full_window=True, reason="morphospace_stable", unlimited=True
    )
    source = prepare_run(tmp_path / "atlas.yaml", run_id="stable-at-400")
    checkpoint = pickle.dumps({"current_iteration": 400})
    report["terminal"]["checkpoint_sha256"] = hashlib.sha256(checkpoint).hexdigest()
    saved_report = tmp_path / "stable-report.json"
    saved_report.write_text(json.dumps(report))
    program = (
        "import shutil; from pathlib import Path; "
        f"shutil.copytree({str(sample / 'output')!r}, {str(source / 'output')!r}, "
        "dirs_exist_ok=True); "
        f"shutil.copyfile({str(saved_report)!r}, {str(source / 'output' / REPORT_NAME)!r}); "
        f"Path({str(source / 'output/deformetrica-state.p')!r}).write_bytes({checkpoint!r}); "
        "print('------ Iteration: 400 ------'); "
        "print('Log-likelihood = -10 ; attachment = -8 ; regularity = -2')"
    )
    monkeypatch.setattr(runs, "ensure_launcher_available", lambda _: None)
    monkeypatch.setattr(
        runs,
        "_probe_backend_environment",
        lambda _: {
            "probe_status": "verified",
            "packages": {"deformetrica": "4.3.0"},
        },
    )
    monkeypatch.setattr(
        runs,
        "build_command",
        lambda _, directory: CommandSpec(
            argv=(sys.executable, "-c", program),
            working_directory=str(directory),
            environment={"MKL_CBWR": "COMPATIBLE"},
        ),
    )
    assert runs.execute_run(source) == 0
    request, evidence = bind_reference_resume_launch_request(
        source,
        request_id="review-stable",
        run_id="additional",
        quality_stop=MORPHOSPACE_STABILITY,
        quality_iterations=37,
    )
    assert evidence.quality_continuation.source_reason == "morphospace_stable"
    assert evidence.quality_continuation.source_maximum_iterations is None
    assert DesktopReferenceLaunchRequest.from_dict(request.as_dict()) == request
    for name, settings in (
        ("fixed", {"iteration_limit": 417}),
        ("native", {"iteration_limit": 417, "optimizer_tolerance": 1e-7}),
        ("quality", {"quality_stop": MORPHOSPACE_STABILITY, "quality_iterations": 17}),
    ):
        successor = prepare_resume_run(source, run_id=name, **settings)
        assert atlas_iteration_limit(verify_prepared_run(successor)["effective_config"]) == 417
