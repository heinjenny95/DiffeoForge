"""Synthetic finite native-guard evidence; no optimizer, replay or scientific input."""

import copy
import hashlib
import json
import pickle
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_reference_ordinary_guard import ordinary as ordinary_config
from test_regional_continuation import case as case  # Reuse the real finite-guard observer fixture.

from diffeoforge import guided_feedback, regional_continuation, regional_evaluation, regional_search
from diffeoforge import pilot_adaptive_native as native
from diffeoforge import reference_calibration_study as study
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_adaptive_fit import VERSION, create_contract, digest
from diffeoforge.reference_guard_assets import C5_SOURCE
from diffeoforge.reference_ordinary_guard import DECLARATION as ORDINARY
from diffeoforge.reference_ordinary_guard import mark as mark_ordinary


@pytest.fixture
def finite(case, monkeypatch):
    # The continuation fixture's retained parent had only a manifest because its
    # old cap-only tests never read inherited coefficients. Supply a distinct,
    # explicitly finite parent field here so complete-prefix seals are exercised.
    parent = case.tmp / "prefix-4"
    config = copy.deepcopy(case.config)
    config["project"]["parameter_provenance"].pop("regional_fit")
    cp, momenta = case.cp + 0.125, case.m * 0.5
    np.savetxt(parent / "controls.txt", cp, fmt="%.17g")
    np.savetxt(parent / "momenta.txt", momenta.reshape(-1, 3), fmt="%.17g")
    parent_inputs = SimpleNamespace(
        control_points=cp,
        momenta=momenta,
        control_points_path=parent / "controls.txt",
        momenta_path=parent / "momenta.txt",
        subject_labels=("target.vtk",),
        source_hashes={
            name: sha256_file(parent / name)
            for name in ("manifest.json", "controls.txt", "momenta.txt")
        },
        run_report=SimpleNamespace(manifest=dict(effective_config=config)),
    )
    case.parent, case.parent_inputs = parent, parent_inputs

    def field_inputs(run, _):
        if Path(run).resolve() == case.run.resolve():
            return case.inputs
        if Path(run).resolve() == parent.resolve():
            return parent_inputs
        raise AssertionError("An unexpected inherited field was accessed")

    monkeypatch.setattr(regional_evaluation, "field_inputs", field_inputs)
    case.snapshot.study_directory = case.tmp / "study"
    case.snapshot.study_directory.mkdir()
    (case.snapshot.study_directory / study.STUDY_MANIFEST).write_text("{}")
    case.snapshot.plan.selected_pilot_subjects = [SimpleNamespace(filename="target.vtk")]
    case.snapshot.current_stage = SimpleNamespace(
        candidates=[SimpleNamespace(candidate_id=case.identifier, values=case.ref["values"])]
    )
    case.snapshot.attachment_comparison = dict(methods={case.identifier: "varifold"})
    case.snapshot.visual_reviews = {}
    case.candidate.run_directory = case.run
    case.candidate.metrics["subject_reconstruction_count"] = 1
    case.candidate.metrics["runtime_seconds"] = 2.5
    case.info["target"] = "target.vtk"
    case.ref = guided_feedback.reference(case.snapshot, case.identifier)
    return case


def contract_for(field, marks, *, total=600):
    return create_contract(
        action_id="synthetic-action",
        seed_sha256=field["field_sha256"],
        objective_sha256=digest("same-physical-objective"),
        marks_sha256=digest(marks),
        evaluation_sha256=digest("same-full-resolution-roi-protocol"),
        red_tolerances={
            f"R{i}": 0.01 for i, r in enumerate(marks) if r.get("purpose", "problem") == "problem"
        },
        green_limits={f"G{i}": 0.001 for i, r in enumerate(marks) if r.get("purpose") == "fixed"},
        outside_limit=0.001,
        wall_seconds=120,
        total_iterations=total,
        now=1000,
    )


def declare(case, contract, field, purpose="warm"):
    marker = dict(
        version=VERSION,
        contract=contract,
        plan=dict(
            purpose=purpose,
            iterations=4,
            seed=field,
            optimizer_history="new",
            anatomical_approval=False,
        ),
        seed_reference=field["reference"],
        basis_source=dict(
            path=field["control_points_path"],
            sha256=sha256_file(Path(field["control_points_path"])),
            basis_sha256=field["basis_sha256"],
            count=field["control_count"],
            spacing=0.4,
        ),
        parent_basis_sha256=sha256_file(Path(field["control_points_path"])),
        basis_relation="nested" if purpose == "cp_probe" else "unchanged",
    )
    case.info["strategy"]["adaptive_fit"] = marker
    return marker


@pytest.fixture
def ordinary(finite, monkeypatch):
    """New synthetic ordinary scope, using the unchanged real C5 observer."""
    from diffeoforge.backends.deformetrica_reference import render_engine_file_bytes

    root = finite.tmp / "ordinary-config"
    root.mkdir()
    config = ordinary_config(root, warm=False)
    run = finite.tmp / "ordinary-run"
    shutil.copytree(finite.run, run, ignore=shutil.ignore_patterns("numerical-guard"))
    cp = run / "input/initial-controls.txt"
    np.savetxt(cp, finite.cp, fmt="%.17g")
    shutil.copyfile(config["input"]["template"], run / "input/template.vtk")
    target = Path(config["input"]["directory"]) / config["input"]["subject_pattern"]
    shutil.copyfile(target, run / "input/target.vtk")
    config["optimization"].update(
        method="lbfgs", max_iterations=4, freeze_template=True, freeze_control_points=True
    )
    config["model"]["deformation"]["initial_control_points"] = str(cp)
    mark_ordinary(config)
    rendered = render_engine_file_bytes(
        config,
        Path("../input/template.vtk"),
        [Path("../input/target.vtk")],
        Path("../input/initial-controls.txt"),
    )
    for name, raw in rendered.items():
        (run / "engine" / name).write_bytes(raw)
    files = [run / "engine" / name for name in rendered]
    files += [
        run / "input" / name for name in ("initial-controls.txt", "template.vtk", "target.vtk")
    ]
    manifest = dict(
        effective_config=config,
        protected_artifacts=[
            dict(path=p.relative_to(run).as_posix(), bytes=p.stat().st_size, sha256=sha256_file(p))
            for p in files
        ],
    )
    (run / "manifest.json").write_text(json.dumps(manifest))
    namespace = {}
    exec(compile(C5_SOURCE, "qualified-ordinary-observer", "exec"), namespace)

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

    x = finite.m.ravel().copy()
    guard = namespace["FiniteAcceptedGuard"](
        np.zeros(6),
        run / "output/numerical-guard",
        snapshot,
        provenance=dict(
            scope=copy.deepcopy(ORDINARY),
            objective_fingerprint="ordinary-objective",
            actual_control_basis=dict(
                shape=list(finite.cp.shape),
                dtype=finite.cp.dtype.str,
                sha256=hashlib.sha256(finite.cp.tobytes()).hexdigest(),
                basis="staged_control_points",
            ),
        ),
    )
    guard.observe_fg(np.zeros(6), np.float64(3), np.ones(6), 1)
    guard.commit(guard.observe_fg(x, np.float64(2), np.ones(6) * 0.5, 4), 4)
    guard.validate_final_result(x, np.float64(2), np.ones(6) * 0.5)
    guard.export_allowed(x)
    checkpoint = run / "output/deformetrica-state.p"
    snapshot(checkpoint, x, 4)
    (run / "result.json").write_text(
        json.dumps(
            dict(
                status="completed",
                return_code=0,
                execution_error=None,
                duration_seconds=2.0,
                checkpoint=dict(
                    available=True,
                    path="output/deformetrica-state.p",
                    bytes=checkpoint.stat().st_size,
                    sha256=sha256_file(checkpoint),
                ),
            )
        )
    )
    inputs = SimpleNamespace(
        control_points=finite.cp,
        control_points_path=cp,
        momenta=finite.m,
        momenta_path=run / "output/momenta.txt",
        subject_labels=("target.vtk",),
        run_report=SimpleNamespace(manifest=manifest),
        source_hashes={
            name: sha256_file(run / name)
            for name in ("manifest.json", "result.json", "output-inventory.json")
        },
    )
    monkeypatch.setattr(regional_evaluation, "field_inputs", lambda *_a, **_k: inputs)
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda _: run)
    finite.run, finite.config, finite.inputs = run, config, inputs
    finite.candidate.run_directory = run
    finite.candidate.config_path = root / "ordinary.yaml"
    study._write_yaml(finite.candidate.config_path, config, overwrite=False)
    values = dict(
        attachment_kernel_width=config["model"]["attachment"]["kernel_width"],
        deformation_kernel_width=config["model"]["deformation"]["kernel_width"],
        initial_control_point_spacing=config["model"]["deformation"][
            "initial_control_point_spacing"
        ],
        noise_std=config["model"]["noise_std"],
    )
    finite.snapshot.current_stage.candidates[0].values = values
    finite.ref = guided_feedback.reference(finite.snapshot, finite.identifier)
    return finite


def test_new_ordinary_scope_is_a_verified_seed_but_not_a_regional_continuation(ordinary):
    field = native.inspect_field(ordinary.snapshot, ordinary.identifier)
    assert field["prefix_sha256"] is None and field["bundle"]["plan"] is None
    assert field["normal_terminal"] and field["reference"] == ordinary.ref
    assert native.eligible_seed(ordinary.snapshot, ordinary.identifier)
    assert field["basis_sha256"] == native.basis_sha256(ordinary.cp)
    with pytest.raises(ValueError, match="newly guarded frozen singleton"):
        regional_continuation.bundle(ordinary.run)
    contract = contract_for(field, ordinary.marks)
    receipt = native.baseline_receipt(
        ordinary.snapshot,
        ordinary.identifier,
        contract,
        red_errors={"R0": 0.02},
        regions=ordinary.marks,
    )
    assert receipt["accepted"] and receipt["native_accepted"] and not receipt["anatomical_approval"]


@pytest.mark.parametrize("change", ["scope", "target", "observer", "cp", "momenta", "checkpoint"])
def test_ordinary_seed_rejects_scope_confusion_and_altered_native_evidence(ordinary, change):
    if change == "scope":
        (ordinary.run / "engine/ordinary-scope.json").write_text("{}")
    elif change == "target":
        path = ordinary.run / "input/target.vtk"
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "observer":
        path = ordinary.run / "engine/finite_accepted_guard.py"
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "cp":
        ordinary.inputs.control_points[0, 0] += 0.01
    elif change == "momenta":
        ordinary.inputs.momenta[0, 0, 0] += 0.01
    else:
        (ordinary.run / "output/deformetrica-state.p").write_bytes(b"changed")
    with pytest.raises(ValueError):
        native.inspect_field(ordinary.snapshot, ordinary.identifier)


def test_new_regional_scope_does_not_become_ordinary_or_change_its_old_objective_digest(finite):
    frozen = regional_continuation.bundle(finite.run)
    session = json.loads((finite.run / "output/numerical-guard/session.json").read_text())
    expected = dict(
        physics=regional_continuation.physics(finite.config),
        staged_plan_sha256=sha256_file(finite.run / "input/regional/plan.json"),
        actual_control_basis=session["provenance"]["actual_control_basis"],
    )
    assert frozen["objective_sha256"] == digest(expected)
    with pytest.raises(ValueError, match="newly guarded frozen singleton"):
        regional_continuation.ordinary_bundle(finite.run)


def test_ordinary_bundle_itself_rejects_unknown_or_line_search_stop(ordinary):
    (ordinary.run / "logs/deformetrica.log").write_text(
        "Iteration: 4\nNumber of line search loops exceeded\n"
    )
    with pytest.raises(ValueError, match="line-search"):
        regional_continuation.ordinary_bundle(ordinary.run)


def test_inspection_binds_guard_coefficients_full_prefix_and_exact_order_without_approval(finite):
    before = copy.deepcopy(finite.snapshot.visual_reviews)
    field = native.inspect_field(finite.snapshot, finite.identifier)
    assert field["normal_terminal"] and field["finite"] and field["accepted"]
    assert field["iterations"] == 4 and field["evaluations"] == 2
    assert field["stop"] == "maximum_iterations" and field["reference"] == finite.ref
    assert field["control_count"] == 2
    assert field["basis_sha256"] == hashlib.sha256(finite.cp.tobytes()).hexdigest()
    assert field["prefix_sha256"] == native._field_identity(finite.parent)["field_sha256"]
    assert finite.snapshot.visual_reviews == before == {}
    assert not native.basis_sha256(finite.cp[::-1]) == field["basis_sha256"]


def test_seed_eligibility_is_metadata_only_and_does_not_promote_an_ordinary_fit(
    finite, monkeypatch
):
    def forbidden(*_a, **_k):
        raise AssertionError("Metadata eligibility must not import a field or checkpoint")

    monkeypatch.setattr(regional_continuation, "bundle", forbidden)
    monkeypatch.setattr(regional_evaluation, "field_inputs", forbidden)
    assert native.eligible_seed(finite.snapshot, finite.identifier)
    finite.config["project"]["parameter_provenance"].pop("regional_fit")
    study._write_yaml(finite.candidate.config_path, finite.config, overwrite=True)
    assert not native.eligible_seed(finite.snapshot, finite.identifier)
    finite.candidate.status = "failed"
    assert not native.eligible_seed(finite.snapshot, finite.identifier)


@pytest.mark.parametrize("change", ["prefix", "guard", "native_export", "nonfinite"])
def test_modified_or_nonfinite_native_evidence_never_becomes_a_seed(finite, change):
    if change == "prefix":
        (finite.parent / "momenta.txt").write_text("changed")
    elif change == "guard":
        (finite.run / "output/numerical-guard/violation.json").write_text("{}")
    elif change == "native_export":
        finite.inputs.momenta[0, 0, 0] += 0.001
    else:
        finite.inputs.control_points[0, 0] = float("nan")
    with pytest.raises(ValueError):
        native.inspect_field(finite.snapshot, finite.identifier)


@pytest.mark.parametrize("stop", ["unknown", "line_search", "conflicting"])
def test_a_normal_exit_without_a_known_native_stop_does_not_restart(finite, stop):
    log = finite.run / "logs/deformetrica.log"
    log.write_text(
        "Iteration: 4\n"
        + {
            "unknown": "Normal process exit\n",
            "line_search": "Number of line search loops exceeded\n",
            "conflicting": (
                "Tolerance threshold met\n>> STOP: TOTAL NO. of ITERATIONS EXCEEDS LIMIT\n"
            ),
        }[stop]
    )
    with pytest.raises(ValueError):
        native.inspect_field(finite.snapshot, finite.identifier)


def test_adaptive_tolerance_reuse_is_explicit_and_legacy_cap_semantics_are_unchanged(finite):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    contract = contract_for(field, finite.marks)
    log = finite.run / "logs/deformetrica.log"
    log.write_text("Iteration: 4\nTolerance threshold met\n")
    with pytest.raises(ValueError, match="maximum-iteration"):
        regional_continuation._bundle_for_record({}, finite.run)
    record = dict(guided=dict(strategy=dict(adaptive_fit=dict(version=VERSION, contract=contract))))
    assert (
        regional_continuation._bundle_for_record(record, finite.run)["objective_evaluations"] == 2
    )
    assert native.inspect_field(finite.snapshot, finite.identifier)["stop"] == "tolerance"
    record["guided"]["strategy"]["adaptive_fit"]["contract"]["total_iterations"] = 601
    with pytest.raises(ValueError):
        regional_continuation._bundle_for_record(record, finite.run)


def test_baseline_uses_explicit_new_marks_and_capture_units_without_creating_approval(finite):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    marks = [dict(finite.marks[0], center=[1, 0, 0]), dict(finite.marks[0], purpose="fixed")]
    contract = contract_for(field, marks)
    receipt = native.baseline_receipt(
        finite.snapshot, finite.identifier, contract, red_errors={"R0": 0.024}, regions=marks
    )
    assert receipt["red_errors"] == {"R0": 0.024}
    assert receipt["green_errors"] == {"G1": 0.0} and receipt["outside_error"] == 0
    assert receipt["iterations"] == 0 and receipt["stop"] == "seed"
    assert receipt["reference"] == finite.ref
    assert receipt["anatomical_approval"] is False
    assert finite.info["feedback"]["regions"] == finite.marks
    with pytest.raises(ValueError, match="exact ordered"):
        native.baseline_receipt(
            finite.snapshot, finite.identifier, contract, red_errors={"R0": 1.0}
        )


def test_stage_all_red_repeats_and_original_surface_error_are_in_native_units(finite):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    contract = contract_for(field, finite.marks)
    declare(finite, contract, field)
    subject = finite.candidate.metrics["attachment_comparison"]["subjects"]["target.vtk"]
    subject["regional_quality"].update({key: True for key in native.HARD_QUALITY_FLAGS})
    subject["marked_regions"] = dict(
        measurements=[
            dict(
                region=finite.marks[0],
                repeats=[
                    dict(original_to_fit_p95=0.02, fit_to_original_p95=0.04),
                    dict(original_to_fit_p95=0.03, fit_to_original_p95=0.025),
                ],
            )
        ]
    )
    subject["regional_quality"].update(
        unmarked_preservation_basis="original_surface",
        previously_good_surface=[
            dict(points=10, before_p95=0.02, after_p95=0.021),
            dict(points=20, before_p95=0.05, after_p95=0.048),
        ],
        no_new_intersection_flags=False,
    )
    receipt = native.stage_receipt(finite.snapshot, finite.identifier, contract)
    assert receipt["red_errors"] == {"R0": 0.04}
    assert receipt["outside_error"] == pytest.approx(0.001)
    assert receipt["duration_seconds"] == 2.5
    assert "no_new_intersection_flags" in receipt["quality_warnings"]
    assert receipt["native_accepted"] is True and receipt["accepted"] is False
    assert receipt["requires_visual_review"] and not receipt["anatomical_approval"]
    subject["marked_regions"]["measurements"][0]["repeats"][1]["fit_to_original_p95"] = None
    with pytest.raises(ValueError, match="finite adaptive evidence"):
        native.stage_receipt(finite.snapshot, finite.identifier, contract)


def test_every_green_patch_needs_complete_vertex_protection_evidence(finite, monkeypatch):
    # Separate scalar extraction from actual native guard verification (above).
    field = native.inspect_field(finite.snapshot, finite.identifier)
    marks = [
        finite.marks[0],
        dict(finite.marks[0], purpose="fixed", center=[-1, 0, 0]),
        dict(finite.marks[0], purpose="fixed", center=[1, 0, 0]),
    ]
    finite.info["feedback"]["regions"] = marks
    field["bundle"]["plan"]["instruction_regions"] = marks
    contract = contract_for(field, marks)
    declare(finite, contract, field)
    monkeypatch.setattr(native, "inspect_field", lambda *_: field)
    subject = finite.candidate.metrics["attachment_comparison"]["subjects"]["target.vtk"]
    subject["marked_regions"] = dict(
        measurements=[
            dict(
                region=marks[0], repeats=[dict(original_to_fit_p95=0.02, fit_to_original_p95=0.04)]
            )
        ]
    )
    quality = subject["regional_quality"]
    quality.update({key: True for key in native.HARD_QUALITY_FLAGS})
    quality.update(
        marked_regions=marks,
        unmarked_preservation_basis="material_positions",
        outside_displacement_p95=0.0002,
        fixed_protection=dict(
            active=True,
            regions=[
                dict(region=0, vertices=12, maximum=0.0001, passed=True),
                dict(region=1, vertices=8, maximum=0.003, passed=False),
            ],
        ),
    )
    receipt = native.stage_receipt(finite.snapshot, finite.identifier, contract)
    assert receipt["green_errors"] == {"G1": 0.0001, "G2": 0.003}
    assert receipt["outside_error"] == 0.0002
    quality["fixed_protection"]["regions"].pop()
    with pytest.raises(ValueError, match="complete retained-region"):
        native.stage_receipt(finite.snapshot, finite.identifier, contract)


def test_original_and_nested_probe_preserve_order_and_motion_reuses_exact_basis(
    finite, monkeypatch
):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    contract = contract_for(field, finite.marks)
    marker = declare(finite, contract, field, "baseline_probe")
    record = dict(guided=finite.info)
    width = field["movement_width"]
    manifest = dict(plan=dict(baseline_effective_values=dict(deformation_kernel_width=width)))
    points, spacing, coverage = native.residual_basis(finite.tmp, manifest, record, [], [])
    assert np.array_equal(points.view(np.uint64), finite.cp.view(np.uint64))
    assert spacing == 0.4 and coverage is None
    marker["plan"]["purpose"], marker["basis_relation"] = "cp_probe", "nested"
    additions = np.vstack((finite.cp[:1], [[5.0, 6.0, 7.0]]))
    monkeypatch.setattr(
        regional_search,
        "controls",
        lambda *_a, **_k: (additions, 0.1, dict(version="source-target-coverage-v1", limit=2000)),
    )
    points, spacing, coverage = native.residual_basis(finite.tmp, manifest, record, [], [])
    assert len(points) == 3 and coverage["added_controls"] == 1
    assert np.array_equal(points[:2].view(np.uint64), finite.cp.view(np.uint64))
    path = finite.tmp / "cp-probe-actual-controls.txt"
    np.savetxt(path, points, fmt="%.17g")
    marker["basis_source"] = dict(
        path=str(path),
        sha256=sha256_file(path),
        basis_sha256=native.basis_sha256(points),
        count=3,
        spacing=spacing,
    )
    marker["plan"]["purpose"] = "motion_probe"
    marker["parent_basis_sha256"] = sha256_file(path)
    marker["basis_relation"] = "unchanged"
    manifest["plan"]["baseline_effective_values"]["deformation_kernel_width"] *= 0.7
    moved, same_spacing, _ = native.residual_basis(finite.tmp, manifest, record, [], [])
    assert np.array_equal(moved.view(np.uint64), points.view(np.uint64)) and same_spacing == spacing


@pytest.mark.parametrize("change", ["file", "raw_hash", "count", "spacing", "width", "ceiling"])
def test_probes_reject_changed_inputs_and_never_truncate_support(finite, monkeypatch, change):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    contract = contract_for(field, finite.marks)
    marker = declare(finite, contract, field, "cp_probe")
    manifest = dict(
        plan=dict(baseline_effective_values=dict(deformation_kernel_width=field["movement_width"]))
    )
    if change == "file":
        marker["basis_source"]["sha256"] = "0" * 64
    elif change == "raw_hash":
        marker["basis_source"]["basis_sha256"] = "0" * 64
    elif change == "count":
        marker["basis_source"]["count"] = 3
    elif change == "spacing":
        marker["basis_source"].pop("spacing")
    elif change == "width":
        manifest["plan"]["baseline_effective_values"]["deformation_kernel_width"] *= 0.8
    else:
        additions = np.arange(6000, dtype=float).reshape(-1, 3)
        monkeypatch.setattr(
            regional_search, "controls", lambda *_a, **_k: (additions, 0.1, dict(limit=2000))
        )
    with pytest.raises(ValueError):
        native.residual_basis(finite.tmp, manifest, dict(guided=finite.info), [], [])


def test_unchanged_legacy_record_does_not_construct_new_probe(tmp_path):
    assert native.residual_basis(tmp_path, {}, {}, [], []) is None


def test_keep_shape_and_incomplete_or_changed_roi_evidence_are_unsupported(finite):
    field = native.inspect_field(finite.snapshot, finite.identifier)
    marks = [finite.marks[0], dict(finite.marks[0], purpose="preserve")]
    contract = contract_for(field, marks)
    with pytest.raises(ValueError, match="keep-shape"):
        native.baseline_receipt(
            finite.snapshot, finite.identifier, contract, red_errors={"R0": 0.1}, regions=marks
        )
    with pytest.raises(ValueError, match="separate error"):
        native.baseline_receipt(
            finite.snapshot, finite.identifier, contract_for(field, finite.marks), red_errors={}
        )


def test_nonfinite_json_stop_evidence_cannot_create_native_receipt(finite):
    result = json.loads((finite.run / "result.json").read_text())
    result["return_code"] = False
    (finite.run / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        native.inspect_field(finite.snapshot, finite.identifier)
