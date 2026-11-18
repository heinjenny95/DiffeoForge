"""Real durable policy plus isolated normal-runner seams; no native worker jobs."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import pilot_adaptive_fit as policy
from diffeoforge import pilot_adaptive_native as native
from diffeoforge import pilot_adaptive_run as orchestration
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


def h(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


@pytest.fixture
def action(tmp_path, monkeypatch):
    states, fields, args_seen, launches = {}, {}, [], []
    marks = [
        dict(purpose="problem", symptom="detail", center=[0, 0, 0], radius=1),
        dict(purpose="fixed", symptom="unsure", center=[4, 0, 0], radius=1),
    ]
    values = dict(
        deformation_kernel_width=1.0,
        initial_control_point_spacing=0.5,
        attachment_kernel_width=0.2,
        noise_std=0.1,
    )

    def ref(snapshot, identifier):
        return dict(
            directory=str(snapshot.study_directory),
            candidate_id=identifier,
            target="target.vtk",
            method="varifold",
            values=copy.deepcopy(snapshot.plan.effective_values),
            manifest_sha256=sha256_file(snapshot.study_directory / "study.json"),
            binding=dict(metrics_sha256=h(snapshot.study_directory.name + "metrics")),
        )

    def field(snapshot, identifier):
        if snapshot.study_directory in fields:
            return fields[snapshot.study_directory]
        record = snapshot.attachment_comparison
        mark = orchestration.marker(record)
        basis = orchestration._basis(
            snapshot.study_directory / record["controls"]["copy"], record["controls"]["spacing"]
        )
        seed = mark["plan"]["seed"] if mark else {}
        config = dict(
            optimization=dict(
                max_iterations=mark["plan"]["iterations"] if mark else 600,
                freeze_template=True,
                freeze_control_points=True,
            )
        )
        result = dict(
            reference=ref(snapshot, identifier),
            field_sha256=h(snapshot.study_directory),
            basis_sha256=basis["basis_sha256"],
            control_count=basis["count"],
            control_points_path=basis["path"],
            movement_width=snapshot.plan.effective_values["deformation_kernel_width"],
            prefix_sha256=(
                seed["field_sha256"]
                if mark and mark["plan"]["purpose"] in orchestration._PROBES
                else seed.get("prefix_sha256")
            ),
            native_receipt_sha256=h(str(snapshot.study_directory) + "native"),
            finite=True,
            accepted=True,
            normal_terminal=True,
            config=config,
            bundle=dict(
                objective_sha256=h("nativeobjective"),
                seals={},
                accepted_parameter_sha256=h("accepted"),
                guard_objective_fingerprint=h("guard"),
            ),
        )
        return result

    def batch(**args):
        args_seen.append(
            copy.deepcopy({k: v for k, v in args.items() if k not in {"source", "previous"}})
        )
        mark = args["strategy"]["adaptive_fit"]
        root = Path(args["destination_parent"]) / ("guided-pilot-" + str(len(args_seen)))
        root.mkdir()
        cp = np.loadtxt(mark["basis_source"]["path"]).reshape(-1, 3)
        if mark["plan"]["purpose"] == "cp_probe":
            cp = np.vstack((cp, [[2.0, 2, 2]]))
        np.savetxt(root / "controls.txt", cp, fmt="%.17g")
        record = dict(
            iterations=mark["plan"]["iterations"],
            methods={"guided-varifold": "varifold"},
            controls=dict(
                copy="controls.txt",
                sha256=sha256_file(root / "controls.txt"),
                count=len(cp),
                spacing=mark["basis_source"]["spacing"],
            ),
            guided=dict(version=guided.ADAPTIVE_VERSION, strategy=args["strategy"],
                        feedback=args["feedback"], target="target.vtk",
                        history=args["history"], screen_trials_spent=args["spent"] + 1),
        )
        manifest = dict(
            attachment_comparison=record, plan=dict(execution_scope="single_specimen_probe")
        )
        (root / "study.json").write_text(json.dumps(manifest))
        study._append_event(root, "study_created", {"fixture": True})
        config = dict(
            optimization=dict(
                max_iterations=mark["plan"]["iterations"],
                freeze_template=True,
                freeze_control_points=True,
            )
        )
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config))
        snapshot = SimpleNamespace(
            study_directory=root,
            attachment_comparison=record,
            candidates=[
                SimpleNamespace(
                    candidate_id="guided-varifold",
                    status="pending",
                    attempts=0,
                    config_path=config_path,
                    metrics={},
                )
            ],
            plan=SimpleNamespace(effective_values=copy.deepcopy(args["values"])),
            visual_reviews={},
            current_stage=SimpleNamespace(order=1),
            region_edits={},
            problem_regions={},
        )
        states[root] = snapshot
        orchestration.verify_declaration(root, manifest, record)
        guided._pointer(args["previous"].study_directory, root)
        return snapshot

    original = tmp_path / "original"
    original.mkdir()
    (original / "study.json").write_text("{}")
    np.savetxt(original / "controls.txt", [[0.0, 0, 0], [1.0, 0, 0]], fmt="%.17g")
    base = SimpleNamespace(
        study_directory=original,
        attachment_comparison=dict(controls=dict(copy="controls.txt", spacing=0.5)),
        candidates=[
            SimpleNamespace(candidate_id="guided-varifold", status="completed", attempts=1)
        ],
        plan=SimpleNamespace(effective_values=values),
        visual_reviews={"guided-varifold": False},
    )
    states[original] = base
    seed = ref(base, "guided-varifold")
    feedback = dict(
        **{
            k: seed[k]
            for k in ("directory", "candidate_id", "manifest_sha256", "binding", "target")
        },
        regions=marks,
        baseline=[
            dict(region=marks[0], repeats=[dict(original_to_fit_p95=10.0, fit_to_original_p95=8.0)])
        ],
    )
    recipe = dict(
        phase="capture",
        residual=True,
        guide_noise=None,
        protection_tolerance=1.0,
        focus_width=0.2,
        focus_noise=0.1,
        protection_noise=0.01,
    )
    arguments = dict(
        source=base,
        previous=base,
        phase="refine",
        goal="regional",
        target="target.vtk",
        methods=("varifold",),
        values=values,
        approved=[],
        history=[],
        spent=2,
        feedback=feedback,
        strategy=dict(regional_recipe=recipe, baseline=seed, anchor=seed, control_basis=seed),
    )
    monkeypatch.setattr(orchestration, "_reference", ref)
    monkeypatch.setattr(native, "inspect_field", field)
    monkeypatch.setattr(study, "load_reference_calibration_study", lambda path: states[Path(path)])
    monkeypatch.setattr(
        study, "_verify_manifest", lambda path: json.loads((Path(path) / "study.json").read_text())
    )
    monkeypatch.setattr(guided, "_batch", batch)
    from diffeoforge import config, guided_feedback, pilot_iteration_accounting

    monkeypatch.setattr(
        guided_feedback, "verify_reference", lambda reference: states[Path(reference["directory"])]
    )
    monkeypatch.setattr(config, "load_config", lambda path: json.loads(Path(path).read_text()))
    monkeypatch.setattr(pilot_iteration_accounting, "branch_total", lambda *_: 100)

    def baseline(snapshot, identifier, contract, *, red_errors, regions):
        assert regions == marks
        f = field(snapshot, identifier)
        return dict(
            {
                k: f[k]
                for k in (
                    "reference",
                    "field_sha256",
                    "basis_sha256",
                    "control_count",
                    "movement_width",
                    "prefix_sha256",
                    "native_receipt_sha256",
                )
            },
            **{k: contract[k] for k in ("objective_sha256", "marks_sha256", "evaluation_sha256")},
            finite=True,
            accepted=True,
            normal_terminal=True,
            stop="seed",
            iterations=0,
            evaluations=0,
            duration_seconds=0.0,
            red_errors=red_errors,
            green_errors={"G1": 0.0},
            outside_error=0.0,
        )

    monkeypatch.setattr(native, "baseline_receipt", baseline)
    red_by_stage = [9.99, 9.98, 8.0, 7.5, 6.0, 5.0, 4.0, 3.0]

    def scalar(snapshot, identifier, contract):
        f = field(snapshot, identifier)
        mark = orchestration.marker(snapshot.attachment_comparison)
        index = int(mark["plan"]["stage_id"].split("-")[-1]) - 1
        red_error = 2.0 if contract.get("extension_of") else red_by_stage[index]
        return dict(
            {
                k: f[k]
                for k in (
                    "reference",
                    "field_sha256",
                    "basis_sha256",
                    "control_count",
                    "movement_width",
                    "prefix_sha256",
                    "native_receipt_sha256",
                )
            },
            **{k: contract[k] for k in ("objective_sha256", "marks_sha256", "evaluation_sha256")},
            finite=True,
            accepted=True,
            normal_terminal=True,
            stop="maximum_iterations",
            iterations=mark["plan"]["iterations"],
            evaluations=2,
            duration_seconds=0.1,
            red_errors={"R0": red_error},
            green_errors={"G1": 0.0},
            outside_error=0.0,
            child_manifest_sha256=sha256_file(snapshot.study_directory / "study.json"),
            native_accepted=True,
            quality_warnings=[],
        )

    monkeypatch.setattr(native, "stage_receipt", scalar)

    class Runner:
        def __init__(self, path):
            self.study_directory = path
            self._cancel_requested = False

        def request_cancel(self):
            self._cancel_requested = True

        def run_current_stage(self, *, event_callback, candidate_ids):
            current = states[self.study_directory]
            mark = orchestration.marker(current.attachment_comparison)
            ledger = policy.load_ledger(mark["ledger"])
            assert ledger.active and ledger.held == mark["plan"]["iterations"]
            assert self._bounded_adaptive_dispatch
            launches.append(mark["plan"]["iterations"])
            current.candidates[0].status = "completed"
            current.candidates[0].attempts = 1
            return current

    return SimpleNamespace(
        arguments=arguments,
        states=states,
        base=base,
        seed=seed,
        args_seen=args_seen,
        launches=launches,
        Runner=Runner,
        field=field,
        marks=marks,
    )


def test_preparation_creates_only_new_action_and_normalizes_warm_field(action):
    original = {p: sha256_file(p) for p in action.base.study_directory.rglob("*") if p.is_file()}
    result = orchestration.prepare(action.arguments)
    mark = orchestration.marker(result.attachment_comparison)
    assert mark["plan"]["iterations"] == 100 and not action.launches
    assert (
        result.attachment_comparison["guided"]["strategy"]["regional_recipe"]["phase"]
        == "initial_warm"
    )
    assert (
        result.attachment_comparison["guided"]["strategy"]["regional_recipe"]["residual"] is False
    )
    assert result.plan.effective_values == action.seed["values"]
    assert all(sha256_file(p) == v for p, v in original.items())
    assert result.visual_reviews == {}


@pytest.mark.parametrize(
    "change",
    [
        dict(regions=[]),
        dict(goal="density"),
        dict(regions=[dict(purpose="preserve", symptom="detail")]),
        dict(regions=[dict(purpose="problem", symptom="gap")]),
        dict(method="current"),
        dict(regional_recipe=dict(guide_noise=0.1)),
    ],
)
def test_ineligible_requests_cannot_get_an_implicit_bounded_run(action, change):
    request = dict(
        goal="regional",
        regions=action.marks,
        reference=action.seed,
        regional_recipe={"guide_noise": None},
        method="varifold",
    )
    assert not orchestration.eligible(request | change)


def test_full_policy_run_reserves_every_arm_and_stays_within600(action):
    first = orchestration.prepare(action.arguments)
    runner = action.Runner(first.study_directory)
    events = []
    result = orchestration.run(runner, events.append)
    assert action.launches == [100, 40, 40, 40, 100, 100, 100, 80]
    assert sum(action.launches) == 600 and not result.visual_reviews
    mark = orchestration.marker(result.attachment_comparison)
    state = policy.load_ledger(mark["ledger"])
    assert state.spent == 600 and state.held == 0 and state.remaining == 0
    assert all(row["status"] == "completed" for row in state.stages)
    probes = action.args_seen[1:4]
    assert len({policy.digest(p["strategy"]["baseline"]) for p in probes}) == 1
    assert all(p["strategy"]["anchor"] == action.seed for p in action.args_seen)
    assert probes[1]["strategy"]["adaptive_fit"]["basis_relation"] == "nested"
    assert probes[2]["strategy"]["adaptive_fit"]["basis_relation"] == "unchanged"
    assert probes[2]["values"]["deformation_kernel_width"] == 0.7
    assert probes[2]["strategy"]["adaptive_fit"]["basis_source"]["count"] == 3
    finish = [e for e in events if e["event"] == "adaptive_fit_finished"][-1]
    assert (
        finish["spent"] == 600 and finish["requires_review"] and not finish["anatomical_approval"]
    )
    assert orchestration.finished_reference(result) == state.best_feasible["reference"]
    assert [args["spent"] for args in action.args_seen] == list(range(2, 10))
    assert [len(args["history"]) for args in action.args_seen] == list(range(8))


def test_finished_adaptive_can_prepare_exact_single300_with_normal_saved_pointer(action):
    from diffeoforge.reference_sequential_fit import resume_directory

    original = orchestration.prepare(action.arguments)
    finished = orchestration.run(action.Runner(original.study_directory))
    origin = finished.study_directory.parent
    prior = {p: sha256_file(p) for p in origin.rglob("*") if p.is_file()}
    offer = orchestration.presentation(finished)["extension"]
    assert offer["iterations"] == 300
    assert offer["remaining_regions"] == [
        dict(label="A", before=4.0, after=3.0, improvement_percent=25.0)
    ]
    assert all(sha256_file(path) == digest for path, digest in prior.items())
    assert sum(action.launches) == 600
    result = guided.next_action(finished.study_directory, "adaptive_extend_bounded",
                                "guided-varifold", goal=offer)
    assert sum(action.launches) == 600
    assert all(sha256_file(path) == digest for path, digest in prior.items())
    assert resume_directory(original.study_directory) == result.study_directory
    assert not orchestration.presentation(finished)["extension"]
    assert orchestration.presentation(result)["extension_from"] == 600
    assert not result.visual_reviews and result.candidates[0].attempts == 0
    stage = orchestration.marker(result.attachment_comparison)
    original_strategy = finished.attachment_comparison["guided"]["strategy"]
    strategy = result.attachment_comparison["guided"]["strategy"]
    assert stage["plan"]["iterations"] == 300 and stage["plan"]["purpose"] == "continue"
    assert stage["contract"]["extension_of"] == offer["state_head"]
    assert stage["plan"]["seed"]["reference"] == strategy["baseline"] == offer["reference"]
    assert strategy["regional_recipe"] == original_strategy["regional_recipe"]
    assert strategy["regional_continuation"]["marks"] == action.marks
    assert result.plan.effective_values == finished.plan.effective_values
    with pytest.raises(ValueError, match="newer prepared batch"):
        guided.next_action(finished.study_directory, "adaptive_extend_bounded",
                           "guided-varifold", goal=offer)
    final = orchestration.run(action.Runner(result.study_directory))
    assert sum(action.launches) == 900 and action.launches[-1:] == [300]
    assert not orchestration.presentation(final)["extension"] and not final.visual_reviews
    ledger = policy.load_ledger(stage["ledger"])
    assert ledger.spent == 300 and len(ledger.stages) == 1


def test_extension_stale_marks_or_protection_recheck_fail_without_reservation(action, monkeypatch):
    from diffeoforge import guided_feedback

    first = orchestration.prepare(action.arguments)
    original = orchestration.run(action.Runner(first.study_directory))
    identifier = "guided-varifold"
    offer = orchestration.presentation(original)["extension"]
    with monkeypatch.context() as altered:
        altered.setattr(guided_feedback, "region_state", lambda *_: ([], True))
        assert not orchestration.presentation(original)["extension"]
        with pytest.raises(ValueError, match="recommendation changed"):
            guided.next_action(original.study_directory, "adaptive_extend_bounded",
                               identifier, goal=offer)
    with monkeypatch.context() as altered:
        altered.setitem(original.visual_reviews, identifier, True)
        assert not orchestration.presentation(original)["extension"]

    fresh = native.stage_receipt
    child = guided.next_action(original.study_directory, "adaptive_extend_bounded",
                               identifier, goal=offer)

    def failed_protection(*args):
        return fresh(*args) | {"accepted": False, "quality_warnings": ["outside_preserved"]}

    monkeypatch.setattr(native, "stage_receipt", failed_protection)
    manifest = study._verify_manifest(child.study_directory)
    with pytest.raises(ValueError, match="changed before continuation"):
        orchestration.authorize_launch(child.study_directory, manifest, identifier)
    state = policy.load_ledger(orchestration.marker(child.attachment_comparison)["ledger"])
    assert state.spent == state.held == 0 and sum(action.launches) == 600


def test_extension_tolerance_stop_releases_unused_effort_without_another_child(action, monkeypatch):
    first = orchestration.prepare(action.arguments)
    original = orchestration.run(action.Runner(first.study_directory))
    offer = orchestration.presentation(original)["extension"]
    child = orchestration.prepare_extension(original, offer)
    original_receipt = native.stage_receipt

    def stopped_normally(*args):
        row = original_receipt(*args)
        return row | {"stop": "tolerance", "iterations": 41}

    # Only the new child stopped early. The older native evidence stays the same.
    monkeypatch.setattr(native, "stage_receipt", lambda *args: (
        stopped_normally(*args) if args[2].get("extension_of") else original_receipt(*args)))
    result = orchestration.run(action.Runner(child.study_directory))
    state = policy.load_ledger(orchestration.marker(result.attachment_comparison)["ledger"])
    assert state.spent == 41 and state.held == 0 and len(state.stages) == 1
    assert not orchestration.presentation(result)["extension"] and action.launches[-1:] == [300]


def test_interrupted_extension_pointer_recovers_only_its_verified_preparation(action, monkeypatch):
    first = orchestration.prepare(action.arguments)
    original = orchestration.run(action.Runner(first.study_directory))
    offer = orchestration.presentation(original)["extension"]
    with monkeypatch.context() as blocked:
        def incomplete_pointer(*_):
            raise OSError("Interrupted before publishing latest-search pointer")

        blocked.setattr(guided, "_pointer", incomplete_pointer)
        with pytest.raises(OSError, match="Interrupted before publishing"):
            orchestration.prepare_extension(original, offer)
    created = len(action.args_seen)
    assert orchestration.presentation(original)["extension"] == offer
    child = orchestration.prepare_extension(original, offer)
    assert len(action.args_seen) == created and child.candidates[0].attempts == 0
    assert not orchestration.presentation(original)["extension"] and sum(action.launches) == 600


def test_incomplete_extension_preparation_does_not_keep_suggesting_unusable_action(
    action, monkeypatch,
):
    first = orchestration.prepare(action.arguments)
    original = orchestration.run(action.Runner(first.study_directory))
    offer = orchestration.presentation(original)["extension"]

    def incomplete(*_):
        raise OSError("The extra stage could not be prepared")

    monkeypatch.setattr(orchestration, "_next_child", incomplete)
    with pytest.raises(OSError, match="could not be prepared"):
        orchestration.prepare_extension(original, offer)
    presentation = orchestration.presentation(original)
    assert presentation["extension"] is None
    assert "cannot be safely reopened" in presentation["reason"]
    assert presentation["recommendation"] == offer["reference"] and sum(action.launches) == 600


@pytest.mark.parametrize("terminal_change", [
    {"red_errors": {"R0": 3.99}},  # Less than the existing two-percent improvement floor.
    {"red_errors": {"R0": 1.0}},  # All declared targets reached.
    {"outside_error": 2.0},
    {"green_errors": {"G1": 2.0}},
    {"accepted": False, "quality_warnings": ["spatial_resolution_sufficient"]},
    {"native_accepted": False},
    {"stop": "tolerance"},
])
def test_budget_exhaustion_alone_does_not_offer_a_continuation(
    action, monkeypatch, terminal_change,
):
    first = orchestration.prepare(action.arguments)
    scalar = native.stage_receipt

    def final_check(snapshot, identifier, contract):
        row = scalar(snapshot, identifier, contract)
        stage = orchestration.marker(snapshot.attachment_comparison)["plan"]["stage_id"]
        return row | terminal_change if stage == "stage-0008" else row

    monkeypatch.setattr(native, "stage_receipt", final_check)
    finished = orchestration.run(action.Runner(first.study_directory))
    observed = orchestration.presentation(finished)
    assert observed["closed"] and observed["spent"] == 600
    assert observed["extension"] is None and observed["recommendation"]


def test_changed_native_cap_is_rejected_before_any_reservation(action):
    result = orchestration.prepare(action.arguments)
    candidate = result.candidates[0]
    config = json.loads(candidate.config_path.read_text())
    config["optimization"]["max_iterations"] = 601
    candidate.config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="native child cap"):
        orchestration.authorize_launch(
            result.study_directory,
            json.loads((result.study_directory / "study.json").read_text()),
            candidate.candidate_id,
        )
    state = policy.load_ledger(orchestration.marker(result.attachment_comparison)["ledger"])
    assert not state.active and not action.launches


def test_unfinished_child_holds_full_reservation_and_never_retries(action, monkeypatch):
    first = orchestration.prepare(action.arguments)
    runner = action.Runner(first.study_directory)

    def failed(**kwargs):
        first.candidates[0].status = "failed"
        first.candidates[0].attempts = 1
        return first

    monkeypatch.setattr(runner, "run_current_stage", failed)
    result = orchestration.run(runner)
    state = policy.load_ledger(orchestration.marker(result.attachment_comparison)["ledger"])
    assert state.held == 100 and state.spent == 0 and state.active
    # The held budget remains unresolved, but the independent old seed is viewable.
    assert orchestration.finished_reference(result) == action.seed
    assert len(action.args_seen) == 1
    with pytest.raises(ValueError, match="action has finished|cannot restart"):
        orchestration.authorize_launch(
            result.study_directory,
            json.loads((result.study_directory / "study.json").read_text()),
            "guided-varifold",
        )


def test_action_or_marks_tampering_cannot_authorize_any_native_work(action):
    result = orchestration.prepare(action.arguments)
    mark = orchestration.marker(result.attachment_comparison)
    context = Path(mark["ledger"]).parent / "action.json"
    payload = json.loads(context.read_text())
    payload["feedback"]["regions"][0]["radius"] = 2
    context.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="preparation or contract changed"):
        orchestration.authorize_launch(
            result.study_directory,
            json.loads((result.study_directory / "study.json").read_text()),
            "guided-varifold",
        )
    assert not action.launches


def test_internal_reference_needs_completed_ledger_receipt_and_current_hashes(action):
    result = orchestration.prepare(action.arguments)
    ref = orchestration._reference(result, "guided-varifold")
    assert not orchestration.trusted_reference(result, ref)
    result = orchestration.run(action.Runner(result.study_directory))
    ref = orchestration._reference(result, "guided-varifold")
    assert orchestration.trusted_reference(result, ref)
    action.states[result.study_directory].plan.effective_values["noise_std"] = 0.2
    assert not orchestration.trusted_reference(result, ref)


def test_real_batch_prepares_declared100_without_dispatch_or_source_rewrites(tmp_path, monkeypatch):
    """Real study/batch persistence; finite numerical guard has separate bridge tests."""
    from test_guided_direction_flow import _marked_fit

    from diffeoforge import guided_feedback, guided_strategy
    from diffeoforge.config import load_config

    base, identifier = _marked_fit(tmp_path, monkeypatch)
    arguments = guided_strategy._plan_transition(
        base, "recover", identifier, goal="regional:detail"
    )
    source = guided_feedback.reference(base, identifier)
    record = base.attachment_comparison
    controls = record["controls"]
    basis = orchestration._basis(base.study_directory / controls["copy"], controls["spacing"])
    field = dict(
        reference=source,
        field_sha256=h("synthetic-finite-source"),
        control_points_path=basis["path"],
        basis_sha256=basis["basis_sha256"],
        control_count=basis["count"],
        movement_width=source["values"]["deformation_kernel_width"],
        prefix_sha256=None,
        native_receipt_sha256=h("separately-tested-guard"),
    )
    monkeypatch.setattr(native, "inspect_field", lambda *_: field)

    def baseline(_snapshot, _identifier, contract, *, red_errors, regions):
        return dict(
            field,
            **{k: contract[k] for k in ("objective_sha256", "marks_sha256", "evaluation_sha256")},
            finite=True,
            accepted=True,
            normal_terminal=True,
            stop="seed",
            iterations=0,
            evaluations=0,
            duration_seconds=0.0,
            red_errors=red_errors,
            green_errors={},
            outside_error=0.0,
        )

    monkeypatch.setattr(native, "baseline_receipt", baseline)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("Preparation dispatched a numerical job"),
    )
    preserved = {p: sha256_file(p) for p in base.study_directory.rglob("*") if p.is_file()}
    result = orchestration.prepare(arguments)
    reopened = study.load_reference_calibration_study(result.study_directory)
    assert reopened.attachment_comparison["iterations"] == 100
    assert load_config(reopened.candidates[0].config_path)["optimization"]["max_iterations"] == 100
    assert reopened.candidates[0].attempts == 0 and not reopened.visual_reviews
    assert all(sha256_file(p) == v for p, v in preserved.items())


def test_cancel_before_dispatch_is_terminal_and_does_not_spend_or_resume(action):
    first = orchestration.prepare(action.arguments)
    runner = action.Runner(first.study_directory)
    runner.request_cancel()
    result = orchestration.run(runner)
    state = policy.load_ledger(orchestration.marker(result.attachment_comparison)["ledger"])
    assert state.spent == 0 and state.held == 0 and not action.launches
    assert orchestration.run(action.Runner(first.study_directory)) is result
    with pytest.raises(ValueError, match="action has finished"):
        orchestration.authorize_launch(
            result.study_directory,
            json.loads((result.study_directory / "study.json").read_text()),
            "guided-varifold",
        )


def test_expired_action_cannot_launch_even_an_already_reserved_pending_child(action, monkeypatch):
    from dataclasses import replace

    first = orchestration.prepare(action.arguments)
    manifest = json.loads((first.study_directory / "study.json").read_text())
    orchestration.authorize_launch(first.study_directory, manifest, "guided-varifold")
    original = orchestration._context

    def expired(marker):
        ledger, state, context = original(marker)
        return ledger, replace(state, now=state.deadline), context

    monkeypatch.setattr(orchestration, "_context", expired)
    with pytest.raises(ValueError, match="deadline ended"):
        orchestration.authorize_launch(first.study_directory, manifest, "guided-varifold")
    assert not action.launches


def test_expiry_does_not_invalidate_prepared_declaration_or_display(action, monkeypatch):
    from dataclasses import replace

    first = orchestration.prepare(action.arguments)
    manifest = json.loads((first.study_directory / "study.json").read_text())
    original = orchestration._context

    def expired(mark):
        ledger, state, context = original(mark)
        return ledger, replace(state, now=state.deadline + 100), context

    monkeypatch.setattr(orchestration, "_context", expired)
    orchestration.verify_declaration(first.study_directory, manifest, first.attachment_comparison)
    with pytest.raises(ValueError, match="deadline ended"):
        orchestration.authorize_launch(first.study_directory, manifest, "guided-varifold")


def test_historical_stage_cannot_restart_a_finished_advanced_action(action):
    first = orchestration.prepare(action.arguments)
    orchestration.run(action.Runner(first.study_directory))
    launched = len(action.launches)
    with pytest.raises(ValueError, match="stage is historical"):
        orchestration.run(action.Runner(first.study_directory))
    assert len(action.launches) == launched


def test_completed_warm_with_failed_qc_is_not_a_trusted_seed_for_any_probe(action, monkeypatch):
    original = native.stage_receipt

    def failed_warm(snapshot, identifier, contract):
        row = original(snapshot, identifier, contract)
        if orchestration.marker(snapshot.attachment_comparison)["plan"]["purpose"] == "warm":
            row.update(
                accepted=False,
                native_accepted=True,
                quality_warnings=["spatial_resolution_sufficient"],
            )
        return row

    monkeypatch.setattr(native, "stage_receipt", failed_warm)
    first = orchestration.prepare(action.arguments)
    final = orchestration.run(action.Runner(first.study_directory))
    assert not orchestration.trusted_reference(
        first, orchestration._reference(first, "guided-varifold")
    )
    assert all(p["strategy"]["baseline"] == action.seed for p in action.args_seen[1:4])
    state = policy.load_ledger(orchestration.marker(final.attachment_comparison)["ledger"])
    assert state.spent <= 600 and state.stages[0]["receipt"]["accepted"] is False
    assert state.best_feasible["reference"] != orchestration._reference(first, "guided-varifold")


def test_different_comparison_red_errors_are_recaptured_from_exact_seed(action, monkeypatch):
    from diffeoforge import pilot_recovery

    incoming = action.arguments["feedback"]
    incoming["directory"] = "old-comparison"
    incoming["baseline"][0]["repeats"][0]["original_to_fit_p95"] = 999.0
    incoming["regions_cleared"] = False
    preserved = {p: sha256_file(p) for p in action.base.study_directory.rglob("*") if p.is_file()}
    called = []

    def capture(snapshot, identifier, target, *, regions):
        called.append((snapshot, identifier, target, regions))
        result = copy.deepcopy(incoming)
        result.update(
            {
                k: action.seed[k]
                for k in ("directory", "candidate_id", "manifest_sha256", "binding", "target")
            }
        )
        result["baseline"][0]["repeats"][0].update(original_to_fit_p95=4.0, fit_to_original_p95=3.0)
        return result

    monkeypatch.setattr(pilot_recovery, "capture", capture)
    first = orchestration.prepare(action.arguments)
    state = policy.load_ledger(orchestration.marker(first.attachment_comparison)["ledger"])
    assert state.baseline["red_errors"] == {"R0": 4.0}
    assert action.args_seen[0]["feedback"]["directory"] == action.seed["directory"]
    assert action.args_seen[0]["feedback"]["regions_cleared"] is False
    assert len(called) == 1 and called[0][0] is action.base
    assert all(sha256_file(p) == v for p, v in preserved.items()) and not action.launches


def test_fresh_capture_cost_counts_from_action_entry_not_after_measurement(action, monkeypatch):
    from diffeoforge import pilot_recovery

    clock = [1000.0]
    monkeypatch.setattr(orchestration.time, "time", lambda: clock[0])
    action.arguments["feedback"]["directory"] = "old-comparison"

    def capture(_snapshot, _identifier, _target, *, regions):
        clock[0] += 12.0
        result = copy.deepcopy(action.arguments["feedback"])
        result.update(
            {
                k: action.seed[k]
                for k in ("directory", "candidate_id", "manifest_sha256", "binding", "target")
            }
        )
        return result

    monkeypatch.setattr(pilot_recovery, "capture", capture)
    first = orchestration.prepare(action.arguments)
    state = policy.load_ledger(orchestration.marker(first.attachment_comparison)["ledger"])
    assert state.contract["created_at"] == 1000.0
    assert state.deadline == 8200.0 and state.now == 1012.0
    assert not action.launches


def test_capture_failure_preserves_old_files_and_creates_no_action(action, monkeypatch):
    from diffeoforge import pilot_recovery

    action.arguments["feedback"]["directory"] = "old-comparison"
    preserved = {p: sha256_file(p) for p in action.base.study_directory.rglob("*") if p.is_file()}

    def fail(*_a, **_k):
        raise ValueError("The chosen field cannot be measured")

    monkeypatch.setattr(pilot_recovery, "capture", fail)
    with pytest.raises(ValueError, match="cannot be measured"):
        orchestration.prepare(action.arguments)
    assert not list(action.base.study_directory.parent.glob("adaptive-fit-*"))
    assert all(sha256_file(p) == v for p, v in preserved.items()) and not action.launches


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Complete nested support exceeds 2000 controls"),
        InterruptedError("Preparation cancelled"),
    ],
)
def test_refused_or_cancelled_contrast_preserves140_budget_and_closes_with_retained_field(
    action,
    monkeypatch,
    error,
):
    original = orchestration._next_child
    partial = []

    def prepare(current, ledger, state, context, decision):
        if decision["purpose"] == "cp_probe":
            path = Path(ledger).parent / "partial-cp-preparation.json"
            path.write_text(json.dumps({"attempted": decision["stage_id"], "launched": False}))
            partial.append((path, sha256_file(path)))
            if isinstance(error, ValueError):
                # Trigger the actual native bridge's complete-support ceiling,
                # rather than replacing it with a fabricated short basis.
                from diffeoforge import regional_search

                seed = orchestration._snapshot(decision["seed"]["reference"])
                field = action.field(seed, "guided-varifold")
                basis = orchestration._basis(field["control_points_path"], 0.5)
                mark = orchestration._marker(ledger, state, decision, action.seed, basis, "nested")
                monkeypatch.setattr(
                    regional_search,
                    "controls",
                    lambda *_a, **_k: (
                        np.arange(6000, dtype=float).reshape(-1, 3),
                        0.1,
                        dict(limit=2000),
                    ),
                )
                native.residual_basis(
                    Path(ledger).parent,
                    dict(plan=dict(baseline_effective_values=dict(deformation_kernel_width=1.0))),
                    dict(
                        guided=dict(
                            strategy=dict(adaptive_fit=mark), feedback=dict(regions=action.marks)
                        )
                    ),
                    [],
                    [],
                )
                pytest.fail("The full nested support should exceed the declared ceiling")
            raise error
        return original(current, ledger, state, context, decision)

    monkeypatch.setattr(orchestration, "_next_child", prepare)
    first = orchestration.prepare(action.arguments)
    events = []
    result = orchestration.run(action.Runner(first.study_directory), events.append)
    state = policy.load_ledger(orchestration.marker(result.attachment_comparison)["ledger"])
    assert action.launches == [100, 40]
    assert state.spent == 140 and state.remaining == 460 and state.held == 0
    assert len(state.stages) == 2 and all(row["status"] == "completed" for row in state.stages)
    assert all(path.is_file() and sha256_file(path) == digest for path, digest in partial)
    finish = [row for row in events if row["event"] == "adaptive_fit_finished"][-1]
    assert "could not be prepared" in finish["reason"] and "no fallback ran" in finish["reason"]
    assert finish["best_reference"] == state.best_feasible["reference"]
    assert orchestration.finished_reference(result) == state.best_feasible["reference"]
    assert not result.visual_reviews
