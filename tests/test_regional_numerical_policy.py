"""Preparation/rendering-only minimum-grid qualification; no native estimator."""

import copy
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_regional_continuation import case as _case_fixture
from test_regional_continuation import prepared

from diffeoforge import regional_continuation, regional_evaluation, regional_pilot
from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import read_plan


@pytest.fixture(name="case")
def continuation_case(tmp_path, monkeypatch, request):
    return _case_fixture.__wrapped__(tmp_path, monkeypatch, request)


def render(config, *, warm=False):
    return render_engine_file_bytes(
        config,
        Path("../input/template.vtk"),
        [Path("../input/target.vtk")],
        Path("../input/controls.txt"),
        Path("../input/momenta.txt") if warm else None,
    )


@pytest.mark.parametrize("case", [19], indirect=True)
@pytest.mark.parametrize("requested", [10, 19, 37, 73])
@pytest.mark.parametrize("warm", [False, True])
def test_new_minimum_is_37_preserves_higher_grids_and_zero_or_warm_initializer(
    case, requested, warm
):
    before = render(case.config)
    source_bytes = {path: path.read_bytes() for path in case.run.rglob("*") if path.is_file()}
    new = copy.deepcopy(case.config)
    new["model"]["deformation"].update(timepoints=requested, use_rk2=False)
    if warm:
        new["model"]["deformation"].update(
            initial_momenta=str(case.inputs.momenta_path), initial_momenta_subjects=["target.vtk"]
        )
    regional_pilot.configure_numerics(new)
    rendered = render(new, warm=warm)
    model = ET.fromstring(rendered["model.xml"])
    optimizer = ET.fromstring(rendered["optimization_parameters.xml"])
    assert int(model.find("./deformation-parameters/number-of-timepoints").text) == max(
        37, requested
    )
    assert optimizer.find("use-rk2").text.lower() == "on"
    guard_policy = json.loads(rendered["guard-policy.json"])
    assert guard_policy["initializer"] == ("staged_momenta" if warm else "native_zero")
    assert new["model"]["deformation"]["use_rk2"] is True
    assert render(case.config) == before  # Old prepared 19-grid renders are unchanged.
    assert (
        int(
            ET.fromstring(before["model.xml"])
            .find("./deformation-parameters/number-of-timepoints")
            .text
        )
        == 19
    )
    assert all(path.read_bytes() == content for path, content in source_bytes.items())


@pytest.mark.parametrize("case", [19, 37, 73], indirect=True)
def test_same_objective_successor_retains_exact_prior_grid_even_below_new_minimum(case):
    root, _, record, _ = prepared(case)
    new = copy.deepcopy(case.config)
    new["model"]["deformation"].update(
        initial_control_points=str(root / record["controls"]["copy"]),
        initial_momenta=str(root / record["refinement"]["momenta"]["copy"]),
        initial_momenta_subjects=["target.vtk"],
    )
    regional_pilot.configure(new, record)
    assert regional_continuation.physics(new) == regional_continuation.physics(case.config)
    assert (
        new["model"]["deformation"]["timepoints"]
        == case.config["model"]["deformation"]["timepoints"]
    )
    assert new["optimization"]["max_iterations"] == 8
    assert (
        int(
            ET.fromstring(render(new, warm=True)["model.xml"])
            .find("./deformation-parameters/number-of-timepoints")
            .text
        )
        == case.config["model"]["deformation"]["timepoints"]
    )


def test_fresh_regional_objective_records_37_minimum_without_replaying_a_field(case, monkeypatch):
    from diffeoforge import regional_residual, result_report

    root = case.tmp / "new-regional-study"
    root.mkdir()
    for name in ("source.vtk", "target.vtk"):
        shutil.copyfile(case.tmp / name, root / name)
    reconstruction = case.run / "output/Fixture__Reconstruction__surface__subject_target.vtk.vtk"
    shutil.copyfile(case.tmp / "source.vtk", reconstruction)
    inventory = [dict(path=reconstruction.name, sha256=sha256_file(reconstruction))]
    monkeypatch.setattr(
        result_report,
        "collect_run_report",
        lambda *_: SimpleNamespace(
            manifest=dict(effective_config=case.config), inventory=inventory
        ),
    )
    monkeypatch.setattr(regional_evaluation, "endpoint", lambda *_: None)
    source = case.tmp / "source.vtk"
    receipt = dict(
        source_run=str(case.run),
        source_manifest_sha256=sha256_file(case.run / "manifest.json"),
        endpoint=dict(path=str(source), sha256=sha256_file(source)),
        reference_source=dict(path=str(source), sha256=sha256_file(source)),
        field_paths=dict(
            control_points=str(case.inputs.control_points_path),
            momenta=str(case.inputs.momenta_path),
        ),
        controls_sha256=sha256_file(case.inputs.control_points_path),
        momenta_sha256=sha256_file(case.inputs.momenta_path),
        integrator="rk2",
        precision="float64",
        timepoints=73,
        starting_frame_qualification=dict(temporal_stable=True),
    )
    monkeypatch.setattr(regional_residual, "retained_evaluation", lambda *_: receipt)
    recipe = dict(case.recipe, residual=False)
    record = dict(
        refinement=dict(initialization="learned", reference=case.ref),
        guided=dict(
            feedback=dict(target="target.vtk", regions=case.marks),
            strategy=dict(regional_recipe=recipe, anchor=case.ref),
        ),
    )
    manifest = dict(
        inputs=dict(
            template=dict(copy="source.vtk", sha256=sha256_file(root / "source.vtk")),
            subjects=[
                dict(
                    filename="target.vtk",
                    copy="target.vtk",
                    sha256=sha256_file(root / "target.vtk"),
                )
            ],
        )
    )
    old_plan_bytes = (case.run / "input/regional/plan.json").read_bytes()
    bound = regional_pilot.bind(root, manifest, record)
    declared = read_plan(
        dict(project=dict(parameter_provenance=dict(regional_fit=bound["regional_objective"])))
    )
    assert declared["numerical_protocol"]["minimum_native_timepoints"] == 37
    assert declared["residual"]["parent_run"] == str(case.tmp / "prefix-4")
    assert (case.run / "input/regional/plan.json").read_bytes() == old_plan_bytes


@pytest.mark.parametrize("requested", [19, 73])
def test_zero_field_endpoint_adapter_uses_effective_declared_grid_and_t0(tmp_path, requested):
    """Execute actual grid/output adapter against a synthetic zero-field Geodesic.

    No native library, watcher thread, optimizer or physical deformation runs.
    This checks scheduling/grid consistency, not integration accuracy.
    """
    import builtins
    import os

    import numpy as np

    from diffeoforge.reference_fixed_shooting import ADAPTER

    count = max(regional_pilot.MINIMUM_NEW_NATIVE_TIMEPOINTS, requested)
    original = np.array([[0.1234567890123456, -0.25, 0.75]], dtype=np.float64)

    class ZeroGeodesic:
        def __init__(self, **kwargs):
            self.intervals = kwargs["concentration_of_time_points"]

        def get_times(self):
            return [index / self.intervals for index in range(self.intervals + 1)]

        def get_template_points(self, time):
            assert time == 1
            return original.copy()

    module = SimpleNamespace(Geodesic=ZeroGeodesic)
    imports = {
        "importlib": SimpleNamespace(import_module=lambda name: module),
        "json": json,
        "os": SimpleNamespace(environ={"DF_PILOT_TIMEPOINTS": str(count)}, path=os.path),
        "threading": SimpleNamespace(Thread=lambda **kwargs: SimpleNamespace(start=lambda: None)),
    }

    def isolated_import(name, *_args, **_kwargs):
        if name not in imports:
            raise AssertionError("Unexpected runtime import: " + name)
        return imports[name]

    environment = dict(__builtins__=dict(vars(builtins), __import__=isolated_import))
    exec(compile(ADAPTER, "actual-fixed-shooting-adapter", "exec"), environment)

    class Value:
        def __init__(self, data):
            self.data = data

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.data

    observed = {}

    class Template:
        def get_deformed_data(self, points, _data):
            return dict(landmark_points=Value(points))

        def write(self, output_dir, names, data):
            observed.update(directory=output_dir, names=names, data=data)

    engine = module.Geodesic()
    engine.write("Shooting", ["surface"], [".vtk"], Template(), {}, str(tmp_path))
    receipt = json.loads((tmp_path / "Shooting__grid.json").read_text())
    assert receipt == dict(root="Shooting", timepoints=count, tmin=0, tmax=1)
    assert np.array_equal(
        observed["data"]["landmark_points"].view(np.uint64), original.view(np.uint64)
    )
