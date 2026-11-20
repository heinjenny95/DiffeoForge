"""NEW-action helper environment isolation; no native optimizer or owner data."""

import copy
import hashlib
import json
import os
import subprocess
import sys

import pytest
from test_reference_finite_accepted_guard import config_fixture, render
from test_reference_ordinary_guard import ordinary

from diffeoforge import reference_finite_accepted_guard as guard
from diffeoforge import reference_fixed_shooting as shooting
from diffeoforge import reference_python_child_isolation as isolation
from diffeoforge.config import ConfigurationError, load_config, validate_schema
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_adaptive_fit import VERSION as BOUNDED_VERSION

# Exact old rendered bytes, recorded from qualified source 946249e before this fix.
LEGACY_HASHES = {
    "regional": {
        "cpu_surface_gather.py": "f083c6d12a3dbff5d1cbdaf4f96cf6968fdb8825a6da8670bc6d2c61e7009362",
        "data_set.xml": "38d7a851035eeb741706f25f93adfd009d57578083cb4936f985980463946b1d",
        "finite_accepted_guard.py": (
            "c5acaa4fa961d2f413978dd798d8576c9c89ec49e793d4700acd1e597196b58e"
        ),
        "guard-policy.json": "ac85da5ed015ed0e19bcdf875b43c08af4639f875448d72a1456a66d07fcb9df",
        "model.xml": "dd3a6b4f6cac4a5349b90684c40d6543cc253b298174480dba821aa8e74c5719",
        "optimization_parameters.xml": (
            "2c42ea2cbbce1655ac4b829f7a2b9729c7a8aca2f3973de589c0c387451f9e47"
        ),
        "regional_guard_runtime.py": (
            "7d6b1b5f1f2f3766622332bbe7462eb6e703ae06afc42ffd0e45ab58a4aa600e"
        ),
        "sitecustomize.py": "825976b1f01dd3a3ae6f3cd4522f666e5b076cef91c0385c0560249302f81eb8",
    },
    "ordinary": {
        "data_set.xml": "5e3a5d887b3a66dc318557977fa1ad47dcab833b260d3d58a3782f270c8fea14",
        "finite_accepted_guard.py": (
            "c5acaa4fa961d2f413978dd798d8576c9c89ec49e793d4700acd1e597196b58e"
        ),
        "guard-policy.json": "0b79a5f546cc3095674e40e07bb41ed7e0e3c28a8cd6d31bfb98bb6e655fc6b4",
        "model.xml": "374704ad76a220fec59539b29c7b08d1f50fe0e07c782bd4728baeacb79c0f50",
        "optimization_parameters.xml": (
            "2c42ea2cbbce1655ac4b829f7a2b9729c7a8aca2f3973de589c0c387451f9e47"
        ),
        "ordinary-scope.json": "c774833671c668b1cdd5cf34c7ccf86445f956345484dd836b2310daec8502f3",
        "ordinary_guard_runtime.py": (
            "cb4d1a8f53932c3c46b96147a0b3a3d5f991d508235f82d36bcce2fb0e6f4eda"
        ),
        "sitecustomize.py": "7eab324642b358ced455f8733e39f5185ea49ade46cd43724d8e23de3722a197",
    },
}


def bounded_record():
    return dict(guided=dict(strategy=dict(adaptive_fit=dict(version=BOUNDED_VERSION))))


@pytest.mark.parametrize("kind", ["regional", "ordinary"])
def test_absent_marker_keeps_all_legacy_render_bytes(kind, tmp_path):
    config = config_fixture(tmp_path) if kind == "regional" else ordinary(tmp_path)
    if kind == "ordinary":
        from diffeoforge.reference_ordinary_guard import mark

        mark(config)
    guard.mark_new_configuration(config)
    assert isolation.declaration(config) is None
    actual = {name: hashlib.sha256(raw).hexdigest() for name, raw in render(config).items()}
    assert actual == LEGACY_HASHES[kind]


def test_only_new_bounded_regional_creation_adds_marker_and_only_parent_tail_changes(tmp_path):
    config = config_fixture(tmp_path)
    guard.mark_new_configuration(config)
    legacy = render(config)
    assert isolation.mark(config, {}) is False
    assert isolation.KEY not in config["project"]["parameter_provenance"]
    assert isolation.mark(config, bounded_record()) is True
    validate_schema(config)
    generated = render(config)
    assert set(generated) == set(legacy)
    assert {key: value for key, value in generated.items() if key != "sitecustomize.py"} == {
        key: value for key, value in legacy.items() if key != "sitecustomize.py"
    }
    assert generated["sitecustomize.py"] != legacy["sitecustomize.py"]
    text = generated["sitecustomize.py"].decode()
    assert text.index("_df_guard_context = _df_guard_install") < text.index("_df_child_environment")
    assert text.index("_df_gather_install(_df_guard_context)") < text.index("_df_child_environment")
    assert "_df_child_environment.environ.pop('PYTHONPATH', None)" in text
    assert isolation.mark(config, {}) is False
    assert render(config) == legacy


@pytest.mark.parametrize(
    "bad",
    [None, {}, True, "enabled", {"version": "unknown"}, dict(isolation.DECLARATION, extra=True)],
)
def test_unknown_marker_fails_closed_in_render_mark_and_central_clear(tmp_path, bad):
    config = config_fixture(tmp_path)
    guard.mark_new_configuration(config)
    config["project"]["parameter_provenance"][isolation.KEY] = bad
    original = copy.deepcopy(config)
    for operation in (
        lambda: render(config),
        lambda: isolation.mark(config, {}),
        lambda: guard.clear_runtime_markers(config),
    ):
        with pytest.raises(ConfigurationError, match="child-environment"):
            operation()
        assert config == original


def test_known_marker_cannot_be_rendered_on_ordinary_scope(tmp_path):
    from diffeoforge.reference_ordinary_guard import mark

    config = ordinary(tmp_path)
    mark(config)
    before = copy.deepcopy(config)
    with pytest.raises(ConfigurationError, match="guarded regional"):
        isolation.mark(config, bounded_record())
    assert config == before
    config["project"]["parameter_provenance"][isolation.KEY] = dict(isolation.DECLARATION)
    with pytest.raises(ConfigurationError, match="guarded regional"):
        render(config)


@pytest.mark.parametrize("new_action", [False, True])
def test_real_python_child_sysconfig_does_not_reenter_initialized_parent(tmp_path, new_action):
    # Stub only native parent setup. Real Python startup and a real non-isolated
    # child perform sysconfig queries exactly as a compiler helper does.
    engine = tmp_path / "engine"
    engine.mkdir()
    trace = tmp_path / "parent-initialized.txt"
    body = (
        "import builtins\nfrom pathlib import Path\n"
        + "_trace = Path("
        + repr(str(trace))
        + ")\n"
        + "if _trace.exists(): raise RuntimeError('Guarded probe output must start empty')\n"
        + "_trace.write_text('parent-once')\n"
        + "builtins._df_parent_hooks_intact = True\n"
    )
    config = dict(project=dict(parameter_provenance={}))
    if new_action:
        config["project"]["parameter_provenance"].update(
            finite_accepted_guard=copy.deepcopy(guard.DECLARATION),
            regional_fit={"bound": True},
            python_child_isolation=dict(isolation.DECLARATION),
        )
    text = isolation.after_parent_setup(config, body)
    wrapped = (
        "try:\n"
        + "\n".join("    " + line for line in text.splitlines())
        + "\nexcept BaseException:\n    import traceback, os\n"
        + "    traceback.print_exc()\n    os._exit(1)\n"
    )
    (engine / "sitecustomize.py").write_text(wrapped)
    child = (
        "import json,sysconfig; print(json.dumps({'prefix':sysconfig.get_config_var('prefix')}))"
    )
    parent = (
        "import builtins,json,os,subprocess,sys\n"
        + "assert builtins._df_parent_hooks_intact is True\n"
        + "result=subprocess.run([sys.executable,'-c',"
        + repr(child)
        + "],capture_output=True,text=True,timeout=15)\n"
        + "print(json.dumps({'rc':result.returncode,'stdout':result.stdout,"
        + "'stderr':result.stderr,'parent_hooks':builtins._df_parent_hooks_intact,"
        + "'pythonpath':os.environ.get('PYTHONPATH')}))\n"
    )
    environment = dict(os.environ, PYTHONPATH=str(engine), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", parent],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["parent_hooks"] and trace.read_text() == "parent-once"
    if new_action:
        assert output["rc"] == 0 and output["pythonpath"] is None
        assert output["stderr"] == "" and "prefix" in json.loads(output["stdout"])
    else:
        assert output["rc"] != 0 and output["pythonpath"] == str(engine)
        assert "Guarded probe output must start empty" in output["stderr"]


def test_fixed_shooting_drops_only_derived_runtime_markers_without_changing_parent(
    tmp_path, monkeypatch
):
    config = config_fixture(tmp_path)
    guard.mark_new_configuration(config)
    isolation.mark(config, bounded_record())
    before = copy.deepcopy(config)
    run = tmp_path / "source-run"
    (run / "engine").mkdir(parents=True)
    for name, raw in render(config).items():
        (run / "engine" / name).write_bytes(raw)
    seed = dict(source_run_directory=str(run), files={})
    for role, name in (
        ("template", "source.vtk"),
        ("control_points", "controls.txt"),
        ("momenta", "momenta.txt"),
    ):
        path = tmp_path / name
        seed["files"][role] = dict(copy=name, sha256=sha256_file(path))
    seen = []

    class ReachedCommand(Exception):
        pass

    def capture(derived, destination):
        seen.append(copy.deepcopy(derived))
        raise ReachedCommand

    monkeypatch.setattr(shooting, "build_shooting_command", capture)
    monkeypatch.setattr(
        shooting.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Started native Shooting")
    )
    with pytest.raises(ReachedCommand):
        shooting.shoot(
            config,
            tmp_path,
            seed,
            tmp_path / "fixed-evaluation",
            37,
            surface_only=config["model"]["object_id"],
        )
    assert config == before
    assert len(seen) == 1 and isolation.KEY not in seen[0]["project"]["parameter_provenance"]
    assert "finite_accepted_guard" not in seen[0]["project"]["parameter_provenance"]
    assert seen[0]["model"] == before["model"]
    assert seen[0]["optimization"] == before["optimization"]


def test_real_new_batch_binds_marker_in_valid_candidate_and_leaves_old_source(
    tmp_path, monkeypatch
):
    from test_pilot_adaptive_run import (
        test_real_batch_prepares_declared100_without_dispatch_or_source_rewrites as prepare_real,
    )

    # Existing real persistence journey supplies synthetic field receipts only;
    # its actual batch/YAML/schema/source-preservation checks remain in force.
    prepare_real(tmp_path, monkeypatch)
    candidates = [
        path
        for path in tmp_path.rglob("atlas.yaml")
        if any(part.startswith("adaptive-fit-") for part in path.parts)
        and "stages" in path.parts
    ]
    assert len(candidates) == 1
    config = load_config(candidates[0])
    validate_schema(config)
    assert isolation.declaration(config) == isolation.DECLARATION
    assert config["optimization"]["max_iterations"] == 100
    assert b"_df_child_environment" in render(config)["sitecustomize.py"]
