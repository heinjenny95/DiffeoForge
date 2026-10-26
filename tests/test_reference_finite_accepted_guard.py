"""Generic preparation/packaging guards. Native qualification is separate."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from test_regional_fit import fixture

from diffeoforge.backends.deformetrica_reference import (
    generate_engine_files,
    render_engine_file_bytes,
)
from diffeoforge.config import ConfigurationError, validate_schema
from diffeoforge.reference_finite_accepted_guard import (
    C5_SHA256,
    DECLARATION,
    extend_engine_files,
    mark_new_configuration,
    reject_guarded_resume,
)
from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_PROFILE, RUNTIME_SOURCE
from diffeoforge.reference_pca_deformations import _write_momenta


def config_fixture(tmp_path, *, warm=True):
    config, *_ = fixture(tmp_path, guides=False)
    config["optimization"]["method"] = "lbfgs"
    keys = (
        "attachment_kernel_width",
        "deformation_kernel_width",
        "initial_control_point_spacing",
        "noise_std",
    )
    config["project"]["parameter_provenance"].update(
        profile="advanced",
        scale_reference="template_bounding_box_diagonal",
        ratios={k: 1.0 for k in keys},
        sources={k: "absolute_override" for k in keys},
    )
    controls = tmp_path / "controls.txt"
    controls.write_text("0 0 0\n1 1 1\n")
    config["model"]["deformation"]["initial_control_points"] = str(controls)
    if warm:
        momenta = tmp_path / "momenta.txt"
        _write_momenta(momenta, np.zeros((1, 2, 3), dtype=np.float64))
        config["model"]["deformation"].update(
            initial_momenta=str(momenta), initial_momenta_subjects=["target.vtk"]
        )
    config["output"]["directory"] = str(tmp_path / "runs")
    return config


def render(config):
    return render_engine_file_bytes(
        config,
        Path("../input/template/source.vtk"),
        [Path("../input/subjects/target.vtk")],
        Path("../input/control-points/controls.txt"),
        Path("../input/momenta/momenta.txt")
        if config["model"]["deformation"].get("initial_momenta")
        else None,
    )


@pytest.mark.parametrize("warm", [False, True])
def test_new_regionals_declare_explicit_guard_and_correct_initializer(tmp_path, warm):
    config = config_fixture(tmp_path, warm=warm)
    legacy = render(config)
    mark_new_configuration(config)
    validate_schema(config)
    assert config["project"]["parameter_provenance"]["finite_accepted_guard"] == DECLARATION
    generated = render(config)
    assert set(generated) == set(legacy) | {
        "finite_accepted_guard.py",
        "regional_guard_runtime.py",
        "guard-policy.json",
    }
    assert generated["model.xml"] == legacy["model.xml"]
    assert generated["data_set.xml"] == legacy["data_set.xml"]
    assert generated["optimization_parameters.xml"] == legacy["optimization_parameters.xml"]
    assert json.loads(generated["guard-policy.json"])["initializer"] == (
        "staged_momenta" if warm else "native_zero"
    )
    assert generated["finite_accepted_guard.py"] == C5_SOURCE
    assert generated["regional_guard_runtime.py"] == RUNTIME_SOURCE
    assert b"except BaseException" in generated["sitecustomize.py"]
    assert b"_df_message_compat" in generated["sitecustomize.py"]
    compile(generated["sitecustomize.py"], "sitecustomize.py", "exec")


def test_no_marker_is_exact_legacy_render_and_ordinary_configs_drop_marker(tmp_path):
    config = config_fixture(tmp_path)
    legacy = render(config)
    assert extend_engine_files(config, 1, legacy) is legacy
    config["project"]["parameter_provenance"]["finite_accepted_guard"] = dict(DECLARATION)
    config["project"]["parameter_provenance"].pop("regional_fit")
    mark_new_configuration(config)
    assert "finite_accepted_guard" not in config["project"]["parameter_provenance"]


def test_unsupported_scope_cannot_accidentally_receive_guard(tmp_path):
    config = config_fixture(tmp_path)
    config["optimization"]["freeze_control_points"] = False
    with pytest.raises(ConfigurationError):
        mark_new_configuration(config)
    config["optimization"]["freeze_control_points"] = True
    mark_new_configuration(config)
    with pytest.raises(ConfigurationError):
        extend_engine_files(config, 2, {})


def test_native_zero_momenta_does_not_allow_unrecoverable_implicit_control_basis(tmp_path):
    config = config_fixture(tmp_path, warm=False)
    config["model"]["deformation"].pop("initial_control_points")
    with pytest.raises(ConfigurationError, match="explicit recoverable original control points"):
        mark_new_configuration(config)


def test_all_generated_assets_are_written_and_returned_for_manifest_protection(tmp_path):
    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    engine = tmp_path / "engine"
    engine.mkdir()
    expected = render(config)
    paths = generate_engine_files(
        config,
        engine,
        Path("../input/template/source.vtk"),
        [Path("../input/subjects/target.vtk")],
        Path("../input/control-points/controls.txt"),
        Path("../input/momenta/momenta.txt"),
    )
    assert [p.name for p in paths] == list(expected)
    assert {p.name: p.read_bytes() for p in paths} == expected


def test_real_preparation_plan_and_manifest_include_assets_and_resume_rejects(tmp_path):
    from diffeoforge.reference_preparation_plan import plan_reference_preparation
    from diffeoforge.runs import inspect_resume_source, prepare_run, verify_prepared_run

    config = config_fixture(tmp_path)
    mark_new_configuration(config)
    path = tmp_path / "guarded.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    plan = plan_reference_preparation(path, run_id="guarded")
    run = prepare_run(path, run_id="guarded")
    manifest = verify_prepared_run(run)
    # Exercise the UNTOUCHED product sidecar, including its filename suffix.
    import types

    runtime = types.ModuleType("generated_guard_runtime_test")
    exec(compile(RUNTIME_SOURCE, "regional_guard_runtime.py", "exec"), runtime.__dict__)
    runtime.ManifestContext(run / "engine").verify_content()
    sidecar = run / "manifest.sha256"
    canonical_bytes = sidecar.read_bytes()
    canonical = canonical_bytes.decode("utf-8")
    assert canonical.strip().endswith("  manifest.json")
    for invalid in (
        canonical.strip() + " extra",
        canonical.replace("manifest.json", "wrong.json"),
        canonical + "\n",
        " " + canonical,
        canonical + "changed",
    ):
        sidecar.write_bytes(invalid.encode("utf-8"))
        with pytest.raises(ValueError, match="Manifest/sidecar mismatch"):
            runtime.ManifestContext(run / "engine")
    sidecar.write_bytes(canonical_bytes)
    assert sidecar.read_bytes() == canonical_bytes
    assert manifest["protected_artifacts"] == [
        {k: row[k] for k in ("path", "bytes", "sha256")} for row in plan["protected_files"]
    ]
    protected = {r["path"] for r in manifest["protected_artifacts"]}
    assert {
        "engine/finite_accepted_guard.py",
        "engine/regional_guard_runtime.py",
        "engine/guard-policy.json",
    }.issubset(protected)
    with pytest.raises(ConfigurationError, match="no automatic restore/resume"):
        inspect_resume_source(run)
    reject_guarded_resume({"project": {}})


def test_packaged_sources_and_runtime_profile_are_generic_and_byte_bound():
    assert hashlib.sha256(C5_SOURCE).hexdigest() == C5_SHA256
    assert len(RUNTIME_PROFILE["native_source_hashes"]) == 91
    assert RUNTIME_PROFILE["native_source_hashes"]["core/estimators/scipy_optimize.py"] == (
        "abfabdbd9bb08027c5149cf625ed4bbe13361329f502d27303ac68635969e7e5"
    )
    assert RUNTIME_PROFILE["versions"]["deformetrica"] == "4.3.0"
    combined = json.dumps(RUNTIME_PROFILE).encode() + C5_SOURCE + RUNTIME_SOURCE
    for token in (b"C:/Users/", b"C:\\Users\\", b"/home/", b"private_runtime_checks", b"WORK/"):
        assert token not in combined
