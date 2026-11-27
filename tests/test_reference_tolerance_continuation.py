from __future__ import annotations

import json
import pickle
import sys
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml
from test_runs import write_run_config

import diffeoforge.runs as runs
from diffeoforge.backends import CommandSpec
from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.reference_prelaunch import (
    DesktopReferenceLaunchRequest,
    DesktopReferencePrelaunchError,
    build_reference_resume_launch_request,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_stop import (
    MORPHOSPACE_STABILITY,
    OPTIMIZER_CONVERGENCE,
    stop_policy,
)

NATIVE_TOLERANCE_STOP = "Tolerance threshold met. Stopping the optimization process."


def _finish_source(
    tmp_path, monkeypatch, *, stop=NATIVE_TOLERANCE_STOP, iteration=211, atlas_stop=None,
    checkpoint_mode=None,
):
    config_path = write_run_config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["optimization"]["max_iterations"] = 1600
    if checkpoint_mode:
        config["output"]["checkpoint_mode"] = checkpoint_mode
    if atlas_stop:
        config["project"]["atlas_stop"] = stop_policy(atlas_stop)
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    source = runs.prepare_run(config_path, run_id="source")
    return _execute_tolerance_fixture(source, monkeypatch, stop, iteration)


def _execute_tolerance_fixture(source, monkeypatch, stop, iteration, *, logged=210, context=None):
    checkpoint = source / "output/deformetrica-state.p"
    state_dict = {"current_iteration": iteration, "current_parameters": {"template": [0]}}
    if context:
        state_dict["diffeoforge_convergence_reference"] = context
    state = pickle.dumps(state_dict)
    program = (
        "from pathlib import Path; "
        f"Path({str(checkpoint)!r}).write_bytes({state!r}); "
        f"print('------ Iteration: {logged} ------'); "
        "print('Log-likelihood = -10 ; attachment = -8 ; regularity = -2'); "
        f"print({stop!r})"
    )
    monkeypatch.setattr(runs, "ensure_launcher_available", lambda _config: None)
    monkeypatch.setattr(runs, "_probe_backend_environment", lambda _config: {
        "probe_status": "verified", "packages": {"deformetrica": "4.3.0"},
    })
    monkeypatch.setattr(runs, "build_command", lambda _config, directory: CommandSpec(
        argv=(sys.executable, "-c", program), working_directory=str(directory),
        environment={"MKL_CBWR": "COMPATIBLE"},
    ))
    assert runs.execute_run(source) == 0
    return source


def _run_hashes(directory: Path) -> dict[Path, str]:
    return {path.relative_to(directory): sha256_file(path)
            for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("atlas_stop", [None, OPTIMIZER_CONVERGENCE])
def test_tolerance_continuation_restores_exact_checkpoint(tmp_path, monkeypatch, atlas_stop):
    source = _finish_source(tmp_path, monkeypatch, atlas_stop=atlas_stop)
    before = _run_hashes(source)
    preview = runs.tolerance_extension_preview(source)
    assert preview.checkpoint_iteration == 211
    assert preview.maximum_iterations == 511
    assert preview.source_maximum_iterations == 1600
    assert preview.source_tolerance == 0.0001
    assert preview.tolerance == 0.00001
    assert preview.checkpoint_sha256 == before[Path("output/deformetrica-state.p")]
    assert preview.source_log_sha256 == before[Path("logs/deformetrica.log")]

    with pytest.raises(ConfigurationError, match="only after the iteration limit"):
        runs.prepare_resume_run(source, run_id="old-workflow", additional_iterations=300)
    with pytest.raises(ConfigurationError, match=r"explicit \+300 budget"):
        runs.prepare_resume_run(source, run_id="implicit", after_tolerance=True)
    assert sorted(path.name for path in source.parent.iterdir()) == [source.name]

    successor = runs.prepare_resume_run(
        source, run_id="continued", additional_iterations=300,
        after_tolerance=True, expected_tolerance_continuation=preview,
    )
    effective = runs.verify_prepared_run(successor)["effective_config"]
    assert effective["optimization"]["max_iterations"] == 511
    assert effective["optimization"]["convergence_tolerance"] == 0.00001
    expected_policy = stop_policy(atlas_stop) if atlas_stop else None
    assert effective["project"].get("atlas_stop") == expected_policy
    optimization = ElementTree.parse(successor / "engine/optimization_parameters.xml")
    assert optimization.findtext("max-iterations") == "511"
    assert float(optimization.findtext("convergence-tolerance")) == 0.00001
    provenance = json.loads((successor / "resume/resume.json").read_text())
    assert provenance["tolerance_continuation"]["additional_iterations"] == 300
    assert provenance["semantics"]["restored"] == ["current_parameters", "current_iteration"]
    assert provenance["semantics"]["reinitialized"] == [
        "objective_baseline", "gradient", "line_search_step_sizes",
    ]
    assert provenance["source_run"]["terminal_status"] == "completed"
    assert runs._load_resume_provenance(successor) == provenance
    assert sha256_file(successor / "resume/source-checkpoint.p") == preview.checkpoint_sha256
    assert not list((successor / "output").iterdir())
    assert runs.run_status(successor)["status"] == "prepared"
    assert _run_hashes(source) == before


def test_staged_optimizer_uses_chosen_tolerance_and_limit(tmp_path, monkeypatch):
    source = _finish_source(tmp_path, monkeypatch)
    before = _run_hashes(source)
    settings = {"optimizer_tolerance": 1e-6, "iteration_limit": 480}
    bound = runs.inspect_resume_source(source, **settings).tolerance_continuation
    assert bound.source_reason == "native_tolerance"
    assert bound.checkpoint_iteration == 211
    assert bound.additional_iterations == 269
    successor = runs.prepare_resume_run(source, run_id="stricter", **settings,
                                        expected_tolerance_continuation=bound)
    config = runs.verify_prepared_run(successor)["effective_config"]
    assert config["optimization"]["convergence_tolerance"] == bound.tolerance
    assert config["optimization"]["max_iterations"] == bound.maximum_iterations
    native = ElementTree.parse(successor / "engine/optimization_parameters.xml")
    assert float(native.findtext("convergence-tolerance")) == 1e-6
    assert native.findtext("max-iterations") == "480"
    assert runs._load_resume_provenance(successor)["tolerance_continuation"] == bound.record()
    assert sha256_file(successor / "resume/source-checkpoint.p") == bound.checkpoint_sha256
    for invalid in (211, 0, True):
        with pytest.raises(ConfigurationError):
            runs.prepare_resume_run(source, run_id="invalid", optimizer_tolerance=1e-6,
                                    iteration_limit=invalid)
    with pytest.raises(ConfigurationError, match="changed"):
        runs.prepare_resume_run(source, run_id="changed", optimizer_tolerance=1e-4,
                                iteration_limit=480, expected_tolerance_continuation=bound)
    assert _run_hashes(source) == before


def test_morphospace_stop_never_authorizes_a_native_tolerance_successor(tmp_path, monkeypatch):
    source = _finish_source(tmp_path, monkeypatch, atlas_stop=MORPHOSPACE_STABILITY)
    with pytest.raises(ConfigurationError, match="requires the native optimizer stop mode"):
        runs.tolerance_extension_preview(source)
    with pytest.raises(ConfigurationError, match="requires the native optimizer stop mode"):
        runs.prepare_resume_run(
            source, run_id="refused", additional_iterations=300, after_tolerance=True,
        )
    assert not (source.parent / "refused").exists()


@pytest.mark.parametrize(("stop", "iteration", "rejection"), [
    ("Tolerance threshold met.", 211, "explicit native tolerance stop"),
    ("Number of line search loops exceeded.", 211, "explicit native tolerance stop"),
    (NATIVE_TOLERANCE_STOP, 204, "does not match the terminal native log"),
    (NATIVE_TOLERANCE_STOP, 214, "does not match the terminal native log"),
])
def test_tolerance_continuation_rejects_incomplete_or_stale_stop_evidence(
    tmp_path, monkeypatch, stop, iteration, rejection,
):
    source = _finish_source(tmp_path, monkeypatch, stop=stop, iteration=iteration)
    with pytest.raises(ConfigurationError, match=rejection):
        runs.tolerance_extension_preview(source)
    with pytest.raises(ConfigurationError, match=rejection):
        runs.prepare_resume_run(
            source, run_id="refused", additional_iterations=300, after_tolerance=True,
        )
    assert not (source.parent / "refused").exists()


def test_desktop_tolerance_request_rechecks_bound_evidence(tmp_path, monkeypatch):
    source = _finish_source(tmp_path, monkeypatch)
    request = build_reference_resume_launch_request(
        source, request_id="reviewed", run_id="explicit", additional_iterations=300,
        after_tolerance=True,
    )
    payload = request.as_dict()
    assert payload["reference_launch_request_version"] == "0.5"
    assert DesktopReferenceLaunchRequest.from_dict(payload) == request

    payload["tolerance_continuation"]["maximum_iterations"] += 1
    with pytest.raises(DesktopReferencePrelaunchError, match="Invalid tolerance continuation"):
        DesktopReferenceLaunchRequest.from_dict(payload)

    other_plan = replace(request.tolerance_continuation, source_log_sha256="a" * 64)
    with pytest.raises(DesktopReferencePrelaunchError, match="changed after review"):
        replace(request, tolerance_continuation=other_plan).verify_launch_inputs()
    with pytest.raises(ConfigurationError, match="reviewed continuation plan changed"):
        runs.prepare_resume_run(
            source, run_id="explicit", additional_iterations=300, after_tolerance=True,
            expected_tolerance_continuation=other_plan,
        )

    checkpoint = source / "output/deformetrica-state.p"
    contents = checkpoint.read_bytes()
    checkpoint.write_bytes(bytes([contents[0] ^ 1]) + contents[1:])
    with pytest.raises(DesktopReferencePrelaunchError, match="checksum differs"):
        request.verify_launch_inputs()
    assert not request.destination.exists()
