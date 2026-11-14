"""Explicit full-target singleton scope; old regional bytes remain unchanged."""

import json
import types
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_reference_calibration_study import _project
from test_reference_finite_accepted_guard import config_fixture, render

from diffeoforge.config import ConfigurationError, load_config, validate_schema
from diffeoforge.reference_finite_accepted_guard import mark_new_configuration
from diffeoforge.reference_ordinary_guard import DECLARATION, mark, runtime_source


def ordinary(tmp_path, *, warm=True):
    config = config_fixture(tmp_path, warm=warm)
    provenance = config["project"]["parameter_provenance"]
    provenance.pop("regional_fit")
    planned = load_config(_project(tmp_path / "plan"))["project"]["parameter_provenance"]
    plan = deepcopy(planned["recommendation"]["calibration_plan"])
    plan.update(
        execution_scope="single_specimen_probe",
        requested_pilot_subject_count=1,
        pilot_subject_count=1,
        selected_pilot_subjects=plan["selected_pilot_subjects"][:1],
    )
    provenance["recommendation"] = deepcopy(planned["recommendation"])
    provenance["recommendation"]["calibration_plan"] = plan
    config["runtime"]["precision"] = "float32"
    config["model"]["attachment"]["type"] = "varifold"
    return config


@pytest.mark.parametrize("warm", [False, True])
def test_explicit_ordinary_guard_keeps_full_target_xml_and_native_c5(tmp_path, warm):
    from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_SOURCE

    config = ordinary(tmp_path, warm=warm)
    # Rendering an old unguarded configuration is still byte identical.
    legacy = render(config)
    mark(config)
    mark_new_configuration(config)
    validate_schema(config)
    assert config["project"]["parameter_provenance"]["finite_accepted_guard"] == DECLARATION
    generated = render(config)
    for name in ("model.xml", "data_set.xml", "optimization_parameters.xml"):
        assert generated[name] == legacy[name]
    assert generated["finite_accepted_guard.py"] == C5_SOURCE
    assert generated["ordinary_guard_runtime.py"] == runtime_source()
    assert generated["ordinary_guard_runtime.py"] != RUNTIME_SOURCE
    assert "regional_guard_runtime.py" not in generated
    assert b"pilot_review" not in generated["sitecustomize.py"]
    assert json.loads(generated["guard-policy.json"])["initializer"] == (
        "staged_momenta" if warm else "native_zero"
    )
    compile(generated["sitecustomize.py"], "sitecustomize.py", "exec")


@pytest.mark.parametrize(
    "bad",
    [
        "regional",
        "review",
        "gather",
        "conditioning",
        "float64",
        "current",
        "free_template",
        "free_controls",
        "implicit",
        "cohort",
        "gradient",
        "compact",
    ],
)
def test_ordinary_scope_rejects_unsupported_combinations(tmp_path, bad):
    config = ordinary(tmp_path)
    p = config["project"]["parameter_provenance"]
    if bad in {"regional", "review", "gather", "conditioning"}:
        p[
            {
                "regional": "regional_fit",
                "review": "pilot_review",
                "gather": "surface_gather",
                "conditioning": "regional_conditioning",
            }[bad]
        ] = {"version": "unexpected"}
    elif bad == "float64":
        config["runtime"]["precision"] = "float64"
    elif bad == "current":
        config["model"]["attachment"]["type"] = "current"
    elif bad == "implicit":
        config["model"]["deformation"].pop("initial_control_points")
    elif bad == "cohort":
        p["recommendation"]["calibration_plan"]["execution_scope"] = "joint_fit_confirmation"
    elif bad == "gradient":
        config["optimization"]["method"] = "gradient_ascent"
    elif bad == "compact":
        config["output"]["checkpoint_mode"] = "compact_convergence_export"
    else:
        config["optimization"][
            "freeze_template" if bad == "free_template" else "freeze_control_points"
        ] = False
    with pytest.raises(ConfigurationError):
        mark(config)


def test_ordinary_preparation_protects_scope_and_rejects_modified_native_input(tmp_path):
    from diffeoforge.reference_preparation_plan import plan_reference_preparation
    from diffeoforge.runs import inspect_resume_source, prepare_run, verify_prepared_run

    config = ordinary(tmp_path)
    mark(config)
    path = tmp_path / "ordinary.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    plan = plan_reference_preparation(path, run_id="ordinary")
    run = prepare_run(path, run_id="ordinary")
    manifest = verify_prepared_run(run)
    assert manifest["protected_artifacts"] == [
        {k: r[k] for k in ("path", "bytes", "sha256")} for r in plan["protected_files"]
    ]
    required = {
        "engine/ordinary-scope.json",
        "engine/ordinary_guard_runtime.py",
        "engine/finite_accepted_guard.py",
        "engine/guard-policy.json",
    }
    assert required <= {r["path"] for r in manifest["protected_artifacts"]}
    runtime = types.ModuleType("ordinary_test")
    exec(compile(runtime_source(), "ordinary_guard_runtime.py", "exec"), runtime.__dict__)
    runtime.ManifestContext(run / "engine").verify_content()
    with pytest.raises(ConfigurationError, match="no automatic restore/resume"):
        inspect_resume_source(run)
    target = next(run / r["staged_path"] for r in manifest["inputs"] if r["role"] == "subject")
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Protected bytes differ"):
        runtime.ManifestContext(run / "engine")


def test_ordinary_render_cannot_change_into_joint_scope(tmp_path):
    from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes

    config = ordinary(tmp_path)
    mark(config)
    with pytest.raises(ConfigurationError):
        render_engine_file_bytes(
            config,
            Path("../input/template/source.vtk"),
            [Path("../input/subjects/a.vtk"), Path("../input/subjects/b.vtk")],
            Path("../input/control-points/controls.txt"),
            Path("../input/momenta/momenta.txt"),
        )
