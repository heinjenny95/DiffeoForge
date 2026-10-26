"""Private synthetic protocol tests; actual preparation/XML, no native solver."""

import copy
import hashlib
import json
import pickle
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_regional_fit import fixture as objective_fixture

from diffeoforge import guided_feedback, guided_search, regional_evaluation, regional_pilot
from diffeoforge import reference_attachment_comparison as comparison
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge import regional_continuation as continuation
from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_guard_assets import C5_SOURCE
from diffeoforge.reference_pca_deformations import _write_momenta
from diffeoforge.regional_fit import assets, read_plan


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    config, *_ = objective_fixture(tmp_path)
    config["optimization"].update(
        method="lbfgs", max_iterations=4, convergence_tolerance=1e-6, max_line_search_iterations=27
    )
    config["model"]["deformation"].update(timepoints=getattr(request, "param", 37), use_rk2=True)
    config["project"]["parameter_provenance"]["finite_accepted_guard"] = copy.deepcopy(
        continuation.GUARD
    )
    keys = (
        "attachment_kernel_width",
        "deformation_kernel_width",
        "initial_control_point_spacing",
        "noise_std",
    )
    config["project"]["parameter_provenance"].update(
        profile="advanced",
        scale_reference="template_bounding_box_diagonal",
        ratios={key: 1.0 for key in keys},
        sources={key: "absolute_override" for key in keys},
    )
    run = tmp_path / "run"
    (run / "engine").mkdir(parents=True)
    (run / "input/regional").mkdir(parents=True)
    (run / "output").mkdir()
    (run / "logs").mkdir()
    (run / "logs/deformetrica.log").write_text(
        "Iteration: 4\n>> STOP: TOTAL NO. of ITERATIONS EXCEEDS LIMIT\n"
    )
    for source, staged, _ in assets(config):
        shutil.copyfile(source, run / staged)
    declaration = config["project"]["parameter_provenance"]["regional_fit"]
    declaration["manifest"] = str(run / "input/regional/plan.json")
    # Four distinct frozen prefix bindings, retained without replay or replacement.
    parent = None
    for index in range(4):
        parent = tmp_path / f"prefix-{index + 1}"
        parent.mkdir()
        write_json(parent / "manifest.json", dict(prefix=index + 1))
    plan_path = Path(declaration["manifest"])
    plan = read_plan(config)
    for name in ("residual-source.vtk", "original-source-grid.vtk"):
        shutil.copyfile(tmp_path / "source.vtk", plan_path.parent / name)
    plan["residual"] = dict(
        parent_run=str(parent),
        parent_manifest_sha256=sha256_file(parent / "manifest.json"),
        prefix_count=4,
        original_template_sha256=sha256_file(tmp_path / "source.vtk"),
        **{
            key: dict(
                copy=name,
                sha256=sha256_file(plan_path.parent / name),
                bytes=(plan_path.parent / name).stat().st_size,
            )
            for key, name in [
                ("source", "residual-source.vtk"),
                ("original_source_grid", "original-source-grid.vtk"),
            ]
        },
    )
    write_json(plan_path, plan)
    declaration["sha256"] = sha256_file(plan_path)
    cp = np.array(
        [[0.1234567890123456, -0.0, 0.3], [0.7, 0.8123456789012345, 0.4]], dtype=np.float64
    )
    cp_path = run / "input/initial-controls.txt"
    np.savetxt(cp_path, cp, fmt="%.17g")
    rounded = run / "output/rounded-controls.txt"
    np.savetxt(rounded, cp, fmt="%.6f")
    x = np.array([0.0123456789012345, -0.02, 0.03, -0.04, 0.05, 0.06], dtype=np.float64)
    m = x.reshape(1, 2, 3)
    mp = run / "output/momenta.txt"
    _write_momenta(mp, m)
    config["model"]["deformation"].update(initial_control_points=str(cp_path))
    marker = config["project"]["parameter_provenance"]
    marker["attachment_selection"] = dict(
        version="attachment-comparison-v1",
        mode="auto",
        state="selected",
        selected_method="varifold",
    )
    config["model"]["attachment"]["type"] = "varifold"
    # Real rendering is exercised on both sides of the numerical successor.
    rendered = render_engine_file_bytes(
        config,
        Path("../input/template.vtk"),
        [Path("../input/target.vtk")],
        Path("../input/initial-controls.txt"),
    )
    for name in ("model.xml", "optimization_parameters.xml", "data_set.xml"):
        (run / "engine" / name).write_bytes(rendered[name])
    for name, data in [
        ("manifest.json", dict(effective_config=config)),
        ("result.json", dict(status="completed", return_code=0, execution_error=None)),
        ("output-inventory.json", {}),
    ]:
        write_json(run / name, data)
    namespace = {}
    exec(compile(C5_SOURCE, "qualified-finite-guard", "exec"), namespace)

    def snapshot(path, parameters, iteration):
        with path.open("wb") as handle:
            pickle.dump(
                dict(
                    parameters=parameters,
                    current_iteration=iteration,
                    parameters_shape=dict(momenta=(1, 2, 3)),
                    parameters_order=["momenta"],
                ),
                handle,
                protocol=4,
            )

    guard = namespace["FiniteAcceptedGuard"](
        np.zeros(6),
        run / "output/numerical-guard",
        snapshot,
        provenance=dict(
            scope=copy.deepcopy(continuation.GUARD),
            objective_fingerprint="fixed-objective-test",
            actual_control_basis=dict(
                shape=list(cp.shape),
                dtype=cp.dtype.str,
                sha256=hashlib.sha256(cp.tobytes()).hexdigest(),
                basis="staged_control_points",
            ),
        ),
    )
    guard.observe_fg(np.zeros(6), np.float64(3), np.ones(6), 1)
    accepted = guard.observe_fg(x, np.float64(2), np.ones(6) * 0.5, 4)
    guard.commit(accepted, 4)
    guard.validate_final_result(x, np.float64(2), np.ones(6) * 0.5)
    guard.export_allowed(x)
    final_checkpoint = run / "output/deformetrica-state.p"
    snapshot(final_checkpoint, x, 4)
    write_json(
        run / "result.json",
        dict(
            status="completed",
            return_code=0,
            execution_error=None,
            checkpoint=dict(
                available=True,
                path="output/deformetrica-state.p",
                bytes=final_checkpoint.stat().st_size,
                sha256=sha256_file(final_checkpoint),
            ),
        ),
    )
    inputs = SimpleNamespace(
        control_points=cp,
        control_points_path=cp_path,
        momenta=m,
        momenta_path=mp,
        subject_labels=("target.vtk",),
        run_report=SimpleNamespace(manifest=dict(effective_config=config)),
    )
    monkeypatch.setattr(regional_evaluation, "field_inputs", lambda *_: inputs)
    ref = dict(
        directory=str(tmp_path / "parent-study"),
        candidate_id="guided-varifold",
        target="target.vtk",
        method="varifold",
        manifest_sha256="synthetic-parent-binding",
        values=dict(
            attachment_kernel_width=config["model"]["attachment"]["kernel_width"],
            noise_std=config["model"]["noise_std"],
            deformation_kernel_width=config["model"]["deformation"]["kernel_width"],
            initial_control_point_spacing=config["model"]["deformation"][
                "initial_control_point_spacing"
            ],
        ),
    )
    marks = copy.deepcopy(plan["regions"])
    recipe = dict(
        symptom="gap",
        residual=True,
        focus_noise=0.02,
        focus_width=0.1,
        protection_noise=0.001,
        protection_halo=0.2,
        guide_noise=0.001,
        guide_points=16,
    )
    cap_metrics = dict(
        completed=True,
        converged=False,
        optimizer_stop_signal="maximum_iterations",
        final_iteration=4,
        maximum_iterations=4,
        invalid_face_count=0,
        attachment_comparison=dict(
            subjects={
                "target.vtk": dict(
                    refinement_guard=dict(severe=False),
                    regional_quality=dict(
                        marked_regions=marks,
                        outside_preserved=True,
                        shape_preserved=True,
                        numerical_selection_suitable=False,
                    ),
                )
            }
        ),
    )
    candidate = SimpleNamespace(
        status="completed",
        candidate_id=ref["candidate_id"],
        config_path=tmp_path / "old.yaml",
        metrics=cap_metrics,
    )
    study._write_yaml(candidate.config_path, config, overwrite=False)
    info = dict(
        goal="regional",
        pilot_order=["target.vtk", "other.vtk"],
        feedback=dict(regions=marks),
        strategy=dict(regional_recipe=recipe),
    )
    snapshot = SimpleNamespace(plan=SimpleNamespace(pilot_subject_count=1), candidates=[candidate])
    monkeypatch.setattr(guided, "record", lambda _: info)
    monkeypatch.setattr(guided_feedback, "verify_reference", lambda _: snapshot)
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _: run)
    data = dict(
        current=candidate,
        current_reference=ref,
        anchor=ref,
        regions=marks,
        severe=True,
        context=dict(
            feedback={ref["candidate_id"]: dict(feedback=dict(outcome="same"))},
            cases=[dict(goal="optimize", reference=ref)],
        ),
    )
    return SimpleNamespace(
        config=config,
        run=run,
        inputs=inputs,
        ref=ref,
        info=info,
        snapshot=snapshot,
        data=data,
        candidate=candidate,
        cp=cp,
        m=m,
        rounded=rounded,
        identifier=ref["candidate_id"],
        recipe=recipe,
        marks=marks,
        tmp=tmp_path,
    )


@pytest.mark.parametrize("outcome", ["same", "better"])
def test_same_or_better_capped_field_preserves_objective_despite_prior_extension(case, outcome):
    case.data["context"]["feedback"][case.identifier]["feedback"]["outcome"] = outcome
    proposal = continuation.proposal(case.snapshot, case.identifier, case.data)
    assert proposal["numerical_extension"] and proposal["optimization_iterations"] == 8
    assert proposal["regional_recipe"] == case.recipe
    assert proposal["initialization_reference"] == case.ref
    assert not proposal["regional_continuation"]["anatomical_approval"]
    assert proposal["available"]  # Prior optimize family does not block a new accepted field.


@pytest.mark.parametrize(
    "change",
    [
        "worse",
        "unsure",
        "no_feedback",
        "marks",
        "basis",
        "objective",
        "false_stop",
        "unknown_stop",
        "failed",
        "nonfinite",
        "preservation",
        "uninspected",
        "unguarded",
        "short_accepted",
        "suitable",
    ],
)
def test_ineligible_states_never_auto_continue(case, change):
    if change in {"worse", "unsure"}:
        case.data["context"]["feedback"][case.identifier]["feedback"]["outcome"] = change
    elif change == "no_feedback":
        case.data["context"]["feedback"] = {}
    elif change == "marks":
        case.data["regions"] = [dict(case.marks[0], radius=999)]
    elif change == "basis":
        case.inputs.control_points = np.round(case.cp, 6)
    elif change == "objective":
        (case.run / "input/regional/plan.json").write_text("{}")
    elif change == "false_stop":
        case.candidate.metrics["converged"] = True
    elif change == "unknown_stop":
        case.candidate.metrics["optimizer_stop_signal"] = "unknown"
    elif change == "failed":
        case.candidate.status = "failed"
    elif change == "nonfinite":
        write_json(case.run / "output/numerical-guard/violation.json", dict(reason="nonfinite"))
    elif change == "preservation":
        case.candidate.metrics["attachment_comparison"]["subjects"]["target.vtk"][
            "regional_quality"
        ]["outside_preserved"] = False
    elif change == "uninspected":
        case.data["current_reference"] = None
    elif change == "unguarded":
        case.config["project"]["parameter_provenance"].pop("finite_accepted_guard")
        study._write_yaml(case.candidate.config_path, case.config, overwrite=True)
    elif change == "short_accepted":
        case.candidate.metrics.update(maximum_iterations=5, final_iteration=5)
    elif change == "suitable":
        case.snapshot.visual_reviews = {case.identifier: True}
    assert continuation.proposal(case.snapshot, case.identifier, case.data) is None


def prepared(case):
    proposal = continuation.proposal(case.snapshot, case.identifier, case.data)
    marker = proposal["regional_continuation"]
    root = case.tmp / "new-study"
    root.mkdir()
    record = dict(
        iterations=8,
        methods={case.identifier: "varifold"},
        refinement=dict(version="guided-refinement-v1", reference=case.ref),
        guided=dict(
            goal="optimize",
            feedback=dict(target="target.vtk", regions=case.marks),
            strategy=dict(regional_recipe=case.recipe, regional_continuation=marker),
        ),
    )
    manifest = dict(
        plan=dict(baseline_effective_values=case.ref["values"]),
        inputs=dict(
            template=dict(sha256=sha256_file(case.tmp / "source.vtk")),
            subjects=[dict(filename="target.vtk", sha256=sha256_file(case.tmp / "target.vtk"))],
        ),
    )
    old_seals = dict(marker["source_seals"])
    record = comparison.prepare_controls(root, manifest, record)
    continuation.verify(root, manifest, record)
    regional_pilot.verify(root, manifest, record)
    return root, manifest, record, old_seals


def test_real_prepare_and_render_keep_all_geometry_prefix_basis_and_physics(case, monkeypatch):
    # Any regeneration, prefix replay, refinement qualification or fitting is a failure.
    import diffeoforge.regional_fit as fit
    import diffeoforge.regional_frame as frame
    import diffeoforge.regional_residual as residual

    for module, name in [(residual, "bind"), (fit, "prepare"), (frame, "qualify")]:
        monkeypatch.setattr(
            module,
            name,
            lambda *_a, **_k: pytest.fail("Unchanged objective was regenerated/replayed"),
        )
    root, manifest, record, seals = prepared(case)
    new = copy.deepcopy(case.config)
    # Pretend the ordinary configure hook tried its usual numerical defaults;
    # the final same-objective hook must keep the actual old 37-grid and L-BFGS.
    new["model"]["deformation"].update(
        timepoints=19,
        initial_control_points=str(root / record["controls"]["copy"]),
        initial_momenta=str(root / record["refinement"]["momenta"]["copy"]),
        initial_momenta_subjects=["target.vtk"],
    )
    new["optimization"]["max_line_search_iterations"] = 30
    regional_pilot.configure(new, record)
    assert continuation.physics(new) == continuation.physics(case.config)
    assert new["optimization"]["max_iterations"] == 8
    assert new["model"]["deformation"]["timepoints"] == 37
    assert new["optimization"]["max_line_search_iterations"] == 27
    assert sha256_file(root / "continuation-controls.txt") == sha256_file(
        case.inputs.control_points_path
    )
    assert sha256_file(root / "continuation-controls.txt") != sha256_file(case.rounded)
    assert read_plan(new)["residual"]["parent_run"] == str(case.tmp / "prefix-4")
    for old, staged, digest in assets(case.config):
        new_file = Path(record["regional_objective"]["manifest"]).parent / staged.name
        assert sha256_file(new_file) == digest == sha256_file(old)
    old_xml = render_engine_file_bytes(
        case.config,
        Path("../input/template.vtk"),
        [Path("../input/target.vtk")],
        Path("../input/controls.txt"),
        Path("../input/momenta.txt"),
    )
    new_xml = render_engine_file_bytes(
        new,
        Path("../input/template.vtk"),
        [Path("../input/target.vtk")],
        Path("../input/controls.txt"),
        Path("../input/momenta.txt"),
    )
    assert new_xml["model.xml"] == old_xml["model.xml"]
    assert new_xml["data_set.xml"] == old_xml["data_set.xml"]
    # Compare to the actual old cold-start XML as well: the NEW accepted-field
    # warm initializer is an explicit difference, not restored optimizer memory.
    actual_old_model = ET.parse(case.run / "engine/model.xml").getroot()
    actual_new_model = ET.fromstring(new_xml["model.xml"])
    assert actual_old_model.find("initial-momenta") is None
    assert actual_new_model.find("initial-momenta") is not None
    for tag in ("template", "deformation-parameters"):
        assert ET.tostring(actual_old_model.find(tag)) == ET.tostring(actual_new_model.find(tag))
    old_opt, new_opt = [
        ET.fromstring(rows["optimization_parameters.xml"]) for rows in (old_xml, new_xml)
    ]
    assert old_opt.find("max-iterations").text == "4"
    assert new_opt.find("max-iterations").text == "8"
    new_opt.find("max-iterations").text = "4"
    assert ET.tostring(old_opt) == ET.tostring(new_opt)
    assert all(sha256_file(Path(path)) == digest for path, digest in seals.items())
    write_json(
        root / "actual-prepare-render-evidence.json",
        dict(
            model_xml_identical_with_canonical_seed_paths=True,
            dataset_xml_identical=True,
            actual_prior_template_and_deformation_xml_identical=True,
            new_accepted_field_warm_initializer_explicit=True,
            optimization_only_cap_changed=True,
            exact_native_cp_copied=True,
            rounded_export_not_used=True,
            staged_objective_assets_identical=True,
            four_prefix_binding_unchanged=True,
            solver_dispatched=False,
            anatomical_approval=False,
            all_source_seals_unchanged=True,
        ),
    )


@pytest.mark.parametrize("change", ["seed", "cp", "marker", "marks", "source"])
def test_prepared_successor_rejects_tampering(case, change):
    root, manifest, record, _ = prepared(case)
    if change == "seed":
        (root / record["refinement"]["momenta"]["copy"]).write_text("1 2 3\n0 0 0\n0 0 0\n")
    elif change == "cp":
        shutil.copyfile(case.rounded, root / record["controls"]["copy"])
    elif change == "marker":
        record["guided"]["strategy"]["regional_continuation"]["objective_sha256"] = "0" * 64
    elif change == "marks":
        record["guided"]["feedback"]["regions"] = []
    elif change == "source":
        with (case.run / "engine/model.xml").open("ab") as out:
            out.write(b" ")
    with pytest.raises((ValueError, KeyError)):
        continuation.verify(root, manifest, record)


def test_guided_search_and_regional_direct_route_use_same_continuation(case):
    # Normal search resolves the current/ref comparison; this fixture gives a
    # valid inspected binding, and retains all old cases including optimize.
    case.data["references"] = {case.ref["directory"]: case.snapshot}
    case.info["strategy"]["baseline"] = case.ref
    case.data["current_reference"] = case.ref
    case.data["target"] = "target.vtk"
    for request in ["detail", "regional:gap", "goal:optimize"]:
        row = guided_search.propose(case.snapshot, case.identifier, request, case.data)
        assert row["goal"] == "optimize" and row["regional_continuation"]


def test_actual_batch_staging_never_presents_regional_terms_as_full_cohort(case, monkeypatch):
    from test_guided_pilot import origin

    from diffeoforge.config import load_config

    original_root = case.tmp / "origin-fixture"
    original_root.mkdir()
    source = origin(original_root)
    manifest = study._verify_manifest(source.study_directory)
    origin_config = load_config(source.study_directory / manifest["source_config"]["copy"])
    case.config["project"]["parameter_provenance"]["recommendation"] = copy.deepcopy(
        origin_config["project"]["parameter_provenance"]["recommendation"]
    )
    study._write_yaml(case.candidate.config_path, case.config, overwrite=True)
    frozen = continuation.proposal(case.snapshot, case.identifier, case.data)
    strategy = dict(
        baseline=case.ref,
        optimization=dict(reference=case.ref, iterations=8),
        regional_recipe=case.recipe,
        regional_continuation=frozen["regional_continuation"],
    )
    captured = {}

    def capture(config_path, destination, **kwargs):
        captured.update(config=load_config(config_path), kwargs=kwargs)
        return SimpleNamespace(study_directory=destination)

    monkeypatch.setattr(study, "create_reference_calibration_study", capture)
    guided._batch(
        source,
        None,
        phase="refine",
        target=source.plan.selected_pilot_subjects[0].filename,
        methods=("varifold",),
        values=case.ref["values"],
        approved=(),
        history=(),
        spent=4,
        goal="optimize",
        feedback=dict(regions=case.marks),
        strategy=strategy,
    )
    config = captured["config"]
    provenance = config["project"]["parameter_provenance"]
    assert "regional_fit" not in provenance and "finite_accepted_guard" not in provenance
    assert config["optimization"]["method"] == origin_config["optimization"]["method"]
    assert config["model"]["deformation"]["timepoints"] == 37
    assert captured["kwargs"]["pilot_max_iterations"] == 8
    assert captured["kwargs"]["plan_override"].pilot_subject_count == 1
    assert captured["kwargs"]["attachment_comparison"]["guided"]["strategy"] == strategy


def preview_inputs(case, monkeypatch):
    """Real inputs() assembly, with unrelated historical UI lookup fixtures."""
    from diffeoforge import guided_response, guided_strategy, regional_search

    case.snapshot.study_directory = case.tmp / "preview-study"
    context = dict(case.data["context"], allowed={case.identifier: True})
    monkeypatch.setattr(guided_feedback, "selection", lambda *_: case.ref)
    monkeypatch.setattr(guided_feedback, "regions", lambda *_: case.data["regions"])
    monkeypatch.setattr(guided_feedback, "severe_regression", lambda *_: True)
    monkeypatch.setattr(guided_strategy, "_candidate", lambda *_a, **_k: case.candidate)
    monkeypatch.setattr(guided_strategy, "_target", lambda *_: "target.vtk")
    monkeypatch.setattr(guided_strategy, "_reference", lambda *_: case.ref)
    monkeypatch.setattr(guided_response, "history", lambda *_: ([], []))
    monkeypatch.setattr(regional_search, "capture", lambda *_a, **_k: None)
    monkeypatch.setattr(study, "_verify_manifest", lambda *_: dict(template_diagonal=6.0))
    return context


def test_preview_verifies_bundle_and_loader_once_for_all_eligible_menu_options(case, monkeypatch):
    from dataclasses import FrozenInstanceError

    context = preview_inputs(case, monkeypatch)
    counts = dict(bundle=0, loader=0)
    original_bundle, original_loader = continuation.bundle, regional_evaluation.field_inputs

    def counted_bundle(*args):
        counts["bundle"] += 1
        return original_bundle(*args)

    def counted_loader(*args):
        counts["loader"] += 1
        return original_loader(*args)

    monkeypatch.setattr(continuation, "bundle", counted_bundle)
    monkeypatch.setattr(regional_evaluation, "field_inputs", counted_loader)
    data = guided_search.inputs(case.snapshot, case.identifier, context)
    assert counts == dict(bundle=1, loader=1)
    for _ in range(10):
        for request in ("detail", "regional:gap", "goal:regional", "goal:optimize"):
            row = guided_search.propose(case.snapshot, case.identifier, request, data)
            assert row["regional_continuation"]
            row["regional_recipe"]["focus_noise"] = 999  # A display edit cannot poison peers.
    assert counts == dict(bundle=1, loader=1)
    assert (
        continuation.proposal(case.snapshot, case.identifier, data)["regional_recipe"]
        == case.recipe
    )
    with pytest.raises(FrozenInstanceError):
        data["_regional_continuation_preview"].payload = "changed"
    assert continuation.proposal(case.snapshot, case.identifier, data, symptom="alignment") is None
    assert continuation.proposal(case.snapshot, case.identifier, data, symptom="topology") is None
    assert counts == dict(bundle=1, loader=1)


def test_preview_is_not_authorization_and_changed_source_rejected_on_new_operation(
    case, monkeypatch
):
    context = preview_inputs(case, monkeypatch)
    first = guided_search.inputs(case.snapshot, case.identifier, context)
    prepared = continuation.proposal(case.snapshot, case.identifier, first)
    # Read-only presentation keeps its frozen evidence, but a new inputs()
    # operation sees the corruption and cannot authorize that cached successor.
    asset = case.run / "input/regional" / read_plan(case.config)["objects"][0]["source"]["copy"]
    with asset.open("ab") as output:
        output.write(b" ")
    assert continuation.proposal(case.snapshot, case.identifier, first)
    fresh = guided_search.inputs(case.snapshot, case.identifier, context)
    assert continuation.proposal(case.snapshot, case.identifier, fresh) is None
    root = case.tmp / "forbidden-successor"
    root.mkdir()
    record = dict(
        refinement=dict(version="guided-refinement-v1", reference=case.ref),
        guided=dict(
            feedback=dict(regions=case.marks),
            strategy=dict(
                regional_recipe=case.recipe, regional_continuation=prepared["regional_continuation"]
            ),
        ),
    )
    manifest = dict(plan=dict(baseline_effective_values=case.ref["values"]))
    with pytest.raises(ValueError):
        continuation.bind(root, manifest, record)
    assert not any(root.iterdir())


def test_changed_preview_marks_invalidate_presentation_without_an_extra_field_import(
    case, monkeypatch
):
    context = preview_inputs(case, monkeypatch)
    data = guided_search.inputs(case.snapshot, case.identifier, context)
    monkeypatch.setattr(
        continuation, "bundle", lambda *_: pytest.fail("A preview reimported a field")
    )
    data["regions"] = [dict(case.marks[0], radius=999)]
    assert continuation.proposal(case.snapshot, case.identifier, data) is None


def test_honest_native_cap_return_is_accepted_without_an_OptimizeResult(case):
    events_path = case.run / "output/numerical-guard/events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    events = [
        event for event in events if event["kind"] != "final_result_bound_to_accepted_evaluation"
    ]
    accepted = next(event for event in reversed(events) if event["kind"] == "accepted_callback")
    terminal = dict(
        kind="native_update_returned_bound_to_accepted",
        parameter_sha256=accepted["parameter_sha256"],
        evaluation_reference=accepted["evaluation_reference"],
        native_iteration=4,
        configured_max_iterations=4,
        original_update_returned_normally=True,
    )
    events_path.write_text("\n".join(json.dumps(row) for row in [*events, terminal]) + "\n")
    assert continuation.proposal(case.snapshot, case.identifier, case.data)
    original = {
        path: path.read_bytes()
        for path in [
            events_path,
            case.run / "result.json",
            case.run / "logs/deformetrica.log",
            case.run / "output/deformetrica-state.p",
        ]
    }
    for change in (
        dict(original_update_returned_normally=False),
        dict(evaluation_reference=999),
        dict(parameter_sha256="0" * 64),
        dict(native_iteration=3),
        dict(configured_max_iterations=5),
    ):
        events_path.write_text(
            "\n".join(json.dumps(row) for row in [*events, dict(terminal, **change)]) + "\n"
        )
        with pytest.raises(ValueError):
            continuation.bundle(case.run)
    for path, content in original.items():
        path.write_bytes(content)
    for text in (
        "Iteration: 4\n",
        "Iteration: 4\nTolerance threshold met\n>> STOP: TOTAL NO. of ITERATIONS EXCEEDS LIMIT\n",
    ):
        (case.run / "logs/deformetrica.log").write_text(text)
        with pytest.raises(ValueError):
            continuation.bundle(case.run)
    for path, content in original.items():
        path.write_bytes(content)
    result = json.loads((case.run / "result.json").read_text())
    write_json(case.run / "result.json", dict(result, return_code=1))
    with pytest.raises(ValueError):
        continuation.bundle(case.run)
    for path, content in original.items():
        path.write_bytes(content)
    checkpoint = case.run / "output/deformetrica-state.p"
    with checkpoint.open("wb") as handle:
        pickle.dump(
            dict(
                parameters=case.m.ravel() + 1,
                current_iteration=4,
                parameters_shape=dict(momenta=(1, 2, 3)),
                parameters_order=["momenta"],
            ),
            handle,
            protocol=4,
        )
    result["checkpoint"].update(bytes=checkpoint.stat().st_size, sha256=sha256_file(checkpoint))
    write_json(case.run / "result.json", result)
    with pytest.raises(ValueError, match="checkpoint parameters differ"):
        continuation.bundle(case.run)


def test_native_WSL_pointer_alias_is_confined_to_the_same_guarded_folder(case):
    path = case.run / "output/numerical-guard/best-latest.json"
    pointer = json.loads(path.read_text())
    from pathlib import PureWindowsPath

    windows = PureWindowsPath(pointer["directory"])
    pointer["directory"] = "/mnt/" + windows.drive[0].lower() + "/" + "/".join(windows.parts[1:])
    write_json(path, pointer)
    assert continuation.bundle(case.run)
    pointer["directory"] = "/mnt/c/unrelated/best-0002"
    write_json(path, pointer)
    with pytest.raises(ValueError, match="leaves the guarded run"):
        continuation.bundle(case.run)
