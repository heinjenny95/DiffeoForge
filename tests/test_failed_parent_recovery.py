"""Private synthetic metadata/controller tests; no native or owner data."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from diffeoforge import guided_failed_parent as recovery
from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    from diffeoforge import runs
    from diffeoforge.reference_finite_accepted_guard import DECLARATION

    run = tmp_path / "run"
    (run / "logs").mkdir(parents=True)
    (run / "output/numerical-guard").mkdir(parents=True)

    def write(path, obj):
        path.write_text(json.dumps(obj))

    artifact = run / "guard-policy.json"
    artifact.write_text("protected synthetic C5 policy")
    manifest = dict(
        run_id="synthetic",
        effective_config=dict(
            project=dict(
                parameter_provenance=dict(
                    finite_accepted_guard=DECLARATION,
                    regional_fit={"version": "synthetic-new-regional"},
                )
            )
        ),
        protected_artifacts=[dict(path=artifact.name, sha256=sha256_file(artifact))],
    )
    write(run / "manifest.json", manifest)
    token = "synthetic-runtime-control"
    (run / "logs/backend-control-token").write_text(token)
    write(
        run / "logs/backend-control.json",
        dict(
            state="completed",
            session_empty=True,
            token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            boot_id="synthetic-boot",
            identity=dict(start_ticks=123),
            backend_return_code=1,
        ),
    )

    def rewrite(reason="accepted_cost_regression"):
        write(
            run / "output/numerical-guard/violation.json",
            dict(reason=reason, automatic_restore=False),
        )
        (run / "output/numerical-guard/events.jsonl").write_text(
            json.dumps(dict(kind="terminal_violation", reason=reason)) + "\n"
        )
        records = [
            dict(
                path=p.relative_to(run / "output").as_posix(),
                bytes=p.stat().st_size,
                sha256=sha256_file(p),
            )
            for p in (run / "output/numerical-guard").iterdir()
        ]
        write(run / "output-inventory.json", dict(files=records))
        write(
            run / "result.json",
            dict(
                run_id="synthetic",
                status="failed",
                return_code=1,
                outputs=dict(
                    inventory_path="output-inventory.json",
                    inventory_sha256=sha256_file(run / "output-inventory.json"),
                ),
            ),
        )

    rewrite()
    candidate = SimpleNamespace(candidate_id="c", status="failed", run_directory=run)
    snapshot = SimpleNamespace(candidates=[candidate], plan=SimpleNamespace(pilot_subject_count=1))
    monkeypatch.setattr(
        runs, "_read_manifest", lambda path: manifest
    )  # Full manifest schema checked separately by existing product tests.
    monkeypatch.setattr(study, "calibration_candidate_run_directory", lambda c: run)
    return SimpleNamespace(
        run=run, snapshot=snapshot, manifest=manifest, rewrite=rewrite, write=write
    )


@pytest.mark.parametrize("reason", sorted(recovery.NUMERICAL_REASONS))
def test_terminal_numerical_metadata_never_reads_failed_coefficients(terminal, reason, monkeypatch):
    from diffeoforge import regional_continuation, regional_evaluation, runs

    terminal.rewrite(reason)
    monkeypatch.setattr(
        regional_evaluation, "field_inputs", lambda *_: pytest.fail("Failed field read")
    )
    monkeypatch.setattr(
        regional_continuation, "bundle", lambda *_: pytest.fail("Failed checkpoint read")
    )
    monkeypatch.setattr(
        runs, "inspect_resume_source", lambda *_: pytest.fail("Failed optimizer resume")
    )
    result = recovery._terminal(terminal.snapshot, "c")
    assert result["reason"] == reason and set(result["metadata"]) == {
        "numerical-guard/violation.json",
        "numerical-guard/events.jsonl",
    }


@pytest.mark.parametrize(
    "bad",
    [
        "unknown",
        "nonterminal",
        "inconsistent_code",
        "changed_metadata",
        "changed_protected",
        "missing_event",
        "unguarded",
        "orphaned",
    ],
)
def test_terminal_guard_failure_is_not_permission_to_recover(terminal, bad):
    t = terminal
    if bad == "unknown":
        t.rewrite("context_changed")
    elif bad == "nonterminal":
        p = t.run / "logs/backend-control.json"
        d = json.loads(p.read_text())
        d["session_empty"] = False
        t.write(p, d)
    elif bad == "inconsistent_code":
        p = t.run / "result.json"
        d = json.loads(p.read_text())
        d["return_code"] = 0
        t.write(p, d)
    elif bad == "changed_metadata":
        (t.run / "output/numerical-guard/violation.json").write_text("{}")
    elif bad == "changed_protected":
        (t.run / "guard-policy.json").write_text("CHANGED")
    elif bad == "missing_event":
        t.rewrite()
        p = t.run / "output/numerical-guard/events.jsonl"
        p.write_text("{}")
        inv = t.run / "output-inventory.json"
        d = json.loads(inv.read_text())
        next(x for x in d["files"] if x["path"].endswith("events.jsonl")).update(
            bytes=p.stat().st_size, sha256=sha256_file(p)
        )
        t.write(inv, d)
        r = t.run / "result.json"
        d = json.loads(r.read_text())
        d["outputs"]["inventory_sha256"] = sha256_file(inv)
        t.write(r, d)
    elif bad == "unguarded":
        t.manifest["effective_config"]["project"]["parameter_provenance"].clear()
    elif bad == "orphaned":
        t.snapshot.candidates[0].status = "orphaned"
    with pytest.raises((ValueError, OSError, RuntimeError)):
        recovery._terminal(t.snapshot, "c")


@pytest.fixture
def route(tmp_path, monkeypatch):
    from test_guided_pilot import run_batch
    from test_interactive_pilot import geometry_receipt, initial
    from test_pilot_region_feedback import reject
    from test_reference_calibration_study import _FailedController

    parent = reject(run_batch(initial(tmp_path), monkeypatch), "guided-current", marked=True)
    geometry_receipt(parent, "guided-current", monkeypatch)
    from diffeoforge import regional_search

    captured = []
    monkeypatch.setattr(
        regional_search,
        "capture",
        lambda *args: (captured.append(args), dict(original_to_fit_p95=0.01))[1],
    )
    child = guided.next_action(
        parent.study_directory, "adaptive_recover", "guided-current", goal="goal:detail"
    )
    failed = run_batch(child, monkeypatch, controller=_FailedController)
    assert failed.candidates[0].status == "failed" and not failed.visual_reviews
    marker = dict(
        run="SYNTHETIC terminal-metadata seam",
        reason="accepted_cost_regression",
        manifest_sha256="a" * 64,
        result_sha256="b" * 64,
    )
    monkeypatch.setattr(recovery, "_terminal", lambda *_: marker.copy())
    captured.clear()
    return SimpleNamespace(
        parent=parent, failed=failed, identifier="guided-current", captures=captured, marker=marker
    )


def test_completed_only_candidate_unchanged_and_unknown_failure_still_inspectable(
    route, monkeypatch
):
    with pytest.raises(ValueError, match="complete, valid"):
        strategy._candidate(route.failed, route.identifier)

    def blocked(*_):
        raise ValueError("unqualified context stop")

    monkeypatch.setattr(recovery, "_terminal", blocked)
    preview = recovery.preview(route.failed, route.identifier)
    assert preview["reference"]["directory"] == str(route.parent.study_directory)
    assert not preview["available"] and "context" in preview["reason"]


def test_preserved_marks_parent_only_seed_and_one_capture_per_preview(route):
    context = strategy.state(route.failed)
    prepared = strategy.prepare_proposals(route.failed, context)
    proposals = prepared["failed_proposals"][route.identifier]
    assert len(route.captures) == 1 and proposals
    assert all(not p.get("numerical_extension") for p in proposals.values())
    assert all(
        p["failure_parent_recovery"]["marks"]
        == route.parent.problem_regions[route.identifier][guided.record(route.failed)["target"]]
        for p in proposals.values()
    )
    assert all(
        not p.get("initialization_reference")
        or p["initialization_reference"]["directory"] == str(route.parent.study_directory)
        for p in proposals.values()
    )
    assert "goal:optimize" not in proposals


def test_actual_prepare_preserves_failed_history_and_never_runs(route, monkeypatch):
    old = {p: sha256_file(p) for p in route.failed.study_directory.rglob("*") if p.is_file()}
    old_events = study._load_events(route.failed.study_directory)
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *_a, **_k: pytest.fail("Prepare ran optimizer"),
    )
    new = guided.next_action(
        route.failed.study_directory,
        "adaptive_recover_from_retained",
        route.identifier,
        goal="goal:weight",
    )
    info = guided.record(new)
    marker = info["strategy"]["failure_parent_recovery"]
    assert marker["failed_directory"] == str(route.failed.study_directory)
    assert marker["reference"]["directory"] == str(route.parent.study_directory)
    assert info["strategy"]["previous"]["directory"] == str(route.failed.study_directory)
    assert info["history"][-1]["outcome"] == "adaptive_recover_from_retained"
    assert info["feedback"]["regions"] == marker["marks"] and not new.visual_reviews
    assert all(c.status == "pending" and c.attempts == 0 for c in new.candidates)
    assert all(sha256_file(p) == v for p, v in old.items() if p.name != study.STUDY_EVENTS)
    assert study._load_events(route.failed.study_directory)[: len(old_events)] == old_events
    assert (
        study.load_reference_calibration_study(route.failed.study_directory).candidates[0].status
        == "failed"
    )


def test_preview_does_not_authorize_changed_failure_at_actual_transition(route, monkeypatch):
    context = strategy.prepare_proposals(route.failed, strategy.state(route.failed))
    assert context["failed_proposals"]
    monkeypatch.setattr(
        recovery, "_terminal", lambda *_: (_ for _ in ()).throw(ValueError("changed failure"))
    )
    with pytest.raises(ValueError, match="changed failure"):
        guided.next_action(
            route.failed.study_directory,
            "adaptive_recover_from_retained",
            route.identifier,
            goal="goal:weight",
        )


def test_identical_failed_settings_and_longer_optimizer_request_blocked(route):
    verified = recovery.inputs(route.failed, route.identifier, strategy.state(route.failed))
    proposal = recovery.propose(route.failed, route.identifier, "goal:detail", verified)
    assert not proposal["available"] and "failed objective" in proposal["blocked_reason"]
    with pytest.raises(ValueError, match="explicit different"):
        recovery.propose(route.failed, route.identifier, "goal:optimize", verified)


def test_actual_failed_card_inspects_parent_then_explicitly_prepares_without_running(
    route, monkeypatch
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QLabel,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from diffeoforge.desktop import guided_pilot as ui

    app = QApplication.instance() or QApplication([])
    window = QDialog()
    window.setLayout(QVBoxLayout())
    window.content = QWidget()
    window.content_layout = QVBoxLayout(window.content)
    window.layout().addWidget(window.content)
    window._worker = None
    window._restoring_search = False
    window.progress = QProgressBar()
    window.status = QLabel()
    window.layout().addWidget(window.progress)
    window.layout().addWidget(window.status)
    for name in (
        "find_fit_button",
        "saved_searches_button",
        "adaptive_fit_search",
        "advanced_mode",
        "afk_mode",
        "outward_mode",
        "collect_evidence_button",
        "keep_previous_button",
        "selection_combo",
        "advance_button",
        "compare_options_button",
        "use_provisional_button",
        "review_next_button",
        "denser_model_button",
        "start_button",
        "cancel_button",
    ):
        setattr(window, name, QPushButton(name, window))
    invoked = []
    inspected = []
    window._start_pilot = lambda *a, **k: invoked.append((a, k))
    window._open_candidate = lambda *_: pytest.fail("Failed field inspection")
    window._open_guided_saved_fit = lambda ref: inspected.append(ref)
    context = strategy.prepare_proposals(route.failed, strategy.state(route.failed))
    ui.render(window, SimpleNamespace(snapshot=route.failed, guidance=context))
    window.show()
    app.processEvents()
    try:
        buttons = window.content.findChildren(QPushButton)
        inspect = next(b for b in buttons if b.text() == "Inspect retained earlier fit")
        prepare = next(b for b in buttons if b.text() == "Prepare different test from retained fit")
        assert inspect.isEnabled() and not prepare.isEnabled() and not invoked
        inspect.click()
        assert inspected[0]["directory"] == str(route.parent.study_directory)
        selector = window.content.findChildren(QComboBox)[0]
        index = next(i for i in range(selector.count()) if selector.itemData(i) == "goal:weight")
        selector.setCurrentIndex(index)
        assert prepare.isEnabled() and not invoked
        prepare.click()
        assert invoked == [
            (
                (),
                dict(
                    adaptive=False,
                    guided_action=(
                        "adaptive_recover_from_retained",
                        route.identifier,
                        "goal:weight",
                    ),
                ),
            )
        ]
        assert not route.failed.visual_reviews and route.failed.candidates[0].status == "failed"
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize(
    "metadata",
    [
        {"version": "new-label", "level": 999, "symptom": "curvature", "phase": "other"},
        {"uuid": "different", "max_iterations": 600, "seed": "a-different-field"},
        {"protection_reference": {"directory": "different"}, "capture_evidence": {"tail": 99}},
        {"guide_points": 999, "control_support": "other-policy-only", "residual": True},
    ],
)
def test_display_seed_cap_policy_only_differences_do_not_make_a_different_objective(metadata):
    recipe = dict(focus_width=0.1, focus_noise=0.02, protection_noise=0.01, guide_noise=None)
    assert recovery._objective("current", {"noise_std": 0.1}, recipe) == recovery._objective(
        "current", {"noise_std": 0.1}, dict(recipe, **metadata)
    )
    assert recovery._objective("current", {}, recipe) != recovery._objective(
        "current", {}, dict(recipe, focus_width=0.05)
    )


def test_unverified_shutdown_retains_inspection_but_not_preparation(monkeypatch):
    reference = {"directory": "verified-earlier"}
    monkeypatch.setattr(recovery, "resolve", lambda *a, **k: (object(), dict(reference=reference)))

    def blocked(*_):
        raise RuntimeError("BackendShutdownUnverified")

    monkeypatch.setattr(recovery, "_terminal", blocked)
    result = recovery.preview(object(), "failed")
    assert result["reference"] == reference and not result["available"]


@pytest.mark.parametrize("blocked", ["pending", "orphaned", "worker", "restoring"])
def test_failed_selector_and_click_keep_live_idle_terminal_gates(blocked, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QVBoxLayout, QWidget

    from diffeoforge.desktop.guided_failed_parent import render

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    window._worker = None
    window._restoring_search = False
    invoked = []
    window._start_pilot = lambda **kw: invoked.append(kw)
    window._open_guided_saved_fit = lambda *_: None
    current = SimpleNamespace(candidate_id="failed", status="failed")
    other = SimpleNamespace(status="completed")
    snapshot = SimpleNamespace(candidates=[current, other])
    proposals = {
        "goal:weight": dict(
            available=True, title="Stronger surface agreement", reason="Explicit test"
        ),
        "regional:missing": dict(
            available=True, title="Improve marked areas", reason="Marked test"
        ),
    }
    guidance = dict(
        failed_parents={
            "failed": dict(
                reference={"directory": "verified"}, available=True, reason="Earlier fit retained"
            )
        },
        failed_proposals={"failed": proposals},
    )

    def action(layout, text, *args, **kwargs):
        button = QPushButton(text)
        button.clicked.connect(lambda: None)
        layout.addWidget(button)
        return button

    render(window, snapshot, current, layout, guidance, action)
    window.show()
    app.processEvents()
    try:
        selector = window.findChild(QComboBox)
        assert all(
            "goal:" not in selector.itemText(i) and "regional:" not in selector.itemText(i)
            for i in range(selector.count())
        )
        assert "Part of the surface is missed" in selector.itemText(2)
        prepare = next(
            b for b in window.findChildren(QPushButton) if b.text().startswith("Prepare different")
        )
        selector.setCurrentIndex(1)
        assert prepare.isEnabled()
        if blocked in {"pending", "orphaned"}:
            other.status = blocked
        elif blocked == "worker":
            window._worker = object()
        else:
            window._restoring_search = True
        # A stale queued click must also recheck busy/unresolved state before dispatch.
        prepare.clicked.emit()
        assert not invoked
        selector.setCurrentIndex(2)
        assert not prepare.isEnabled()
        prepare.clicked.emit()
        assert not invoked
        other.status = "completed"
        window._worker = None
        window._restoring_search = False
        selector.setCurrentIndex(1)
        assert prepare.isEnabled()
        prepare.click()
        assert len(invoked) == 1 and invoked[0]["guided_action"] == (
            "adaptive_recover_from_retained",
            "failed",
            "goal:weight",
        )
    finally:
        window.close()
        app.processEvents()


def test_failed_A_then_failed_B_does_not_offer_A_again(route, monkeypatch, tmp_path):
    from test_guided_pilot import run_batch
    from test_reference_calibration_study import _FailedController

    a = route.failed
    b = guided.next_action(
        a.study_directory, "adaptive_recover_from_retained", route.identifier, goal="goal:weight"
    )
    b = run_batch(b, monkeypatch, controller=_FailedController)
    assert b.candidates[0].status == "failed"
    context = strategy.state(b)
    verified = recovery.inputs(b, route.identifier, context)
    p = recovery.propose(b, route.identifier, "goal:detail", verified)
    av = next(c.values for c in a.current_stage.candidates if c.candidate_id == route.identifier)
    a_obj = recovery._objective(
        a.attachment_comparison["methods"][route.identifier],
        av,
        (guided.record(a).get("strategy") or {}).get("regional_recipe"),
    )
    proposed = recovery._objective(p["method"], p["values"], p.get("regional_recipe"))
    bv = next(c.values for c in b.current_stage.candidates if c.candidate_id == route.identifier)
    b_obj = recovery._objective(
        b.attachment_comparison["methods"][route.identifier],
        bv,
        (guided.record(b).get("strategy") or {}).get("regional_recipe"),
    )
    assert a_obj == proposed and a_obj != b_obj
    assert verified["evidence"]["reference"]["directory"] == str(route.parent.study_directory)
    info = guided.record(b)
    assert any(h["directory"] == str(a.study_directory) for h in info["history"])
    print(
        json.dumps(
            dict(
                failed_A=str(a.study_directory),
                failed_B=str(b.study_directory),
                same_parent=verified["evidence"]["reference"]["directory"],
                history_retains_A=True,
                context_targets=[c["target"] for c in context["cases"]],
                A_objective=a_obj,
                B_objective=b_obj,
                proposed_A_available=p["available"],
            ),
            sort_keys=True,
        )
    )
    assert not p["available"], (
        "Older terminal failed objective A is offered after terminal failed B "
        "from the same retained parent and marks"
    )


def test_changed_older_failure_rejects_fresh_preparation_and_saved_successor(route, monkeypatch):
    from test_guided_pilot import run_batch
    from test_reference_calibration_study import _FailedController

    a = route.failed
    b = guided.next_action(
        a.study_directory, "adaptive_recover_from_retained", route.identifier, goal="goal:weight"
    )
    b = run_batch(b, monkeypatch, controller=_FailedController)
    context = strategy.state(b)
    verified = recovery.inputs(b, route.identifier, context)
    novel = recovery.propose(b, route.identifier, "goal:smooth", verified)
    assert novel["available"]
    old_terminal = recovery._terminal

    def changed(snapshot, identifier):
        result = old_terminal(snapshot, identifier)
        if snapshot.study_directory == a.study_directory:
            result = dict(result, result_sha256="changed-old-terminal")
        return result

    monkeypatch.setattr(recovery, "_terminal", changed)
    with pytest.raises(ValueError, match="changed|provenance"):
        guided.next_action(
            b.study_directory,
            "adaptive_recover_from_retained",
            route.identifier,
            goal="goal:smooth",
        )
    with pytest.raises(ValueError, match="changed|provenance"):
        study.load_reference_calibration_study(b.study_directory)


@pytest.mark.parametrize("change", ["parent", "marks"])
def test_prepared_failure_scope_cannot_be_relabelled_by_later_preferences(
    route, monkeypatch, change
):
    evidence = recovery.resolve(route.failed, route.identifier)[1]
    actual = recovery.known_failures(route.failed, route.identifier, evidence)
    assert len(actual) == 1
    different = dict(evidence)
    if change == "parent":
        different["reference"] = dict(evidence["reference"], binding={"different": True})
    else:
        different["marks"] = [
            dict(evidence["marks"][0], radius=evidence["marks"][0]["radius"] * 0.9)
        ]
    # Match is against immutable prepared objective scope, not incoming display preferences.
    assert recovery.known_failures(route.failed, route.identifier, different) == []
