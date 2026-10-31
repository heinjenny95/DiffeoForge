"""Extra owner-requested end-to-end dead-end checks. Public synthetic receipts only."""

import pytest
from pilot_view_helpers import wait_pilot_view
from test_guided_feedback import attempted
from test_guided_pilot import approve, run_batch
from test_pilot_form_progress import local_fit
from test_pilot_region_feedback import reject

from diffeoforge import guided_strategy as strategy
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


def dialog_for(snapshot, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    dialog = ReferenceCalibrationDialog(snapshot.study_directory)
    dialog.show()
    wait_pilot_view(dialog, timeout=40)
    return app, dialog


def test_real_next_button_survives_reopen_and_double_click_prepares_once(tmp_path, monkeypatch):
    _, snapshot = local_fit(tmp_path, monkeypatch)
    expected = strategy.state(snapshot)["next_forms"]["guided-varifold"]["target"]
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Navigation started an optimizer"),
    )
    app, dialog = dialog_for(snapshot, monkeypatch)
    try:
        assert dialog.next_step_button.isEnabled() and not dialog.next_step_button.isHidden()
        assert dialog.review_next_button.isEnabled() and not dialog.review_next_button.isHidden()
        queued = []
        monkeypatch.setattr(dialog._thread_pool, "start", queued.append)
        for _ in range(20):
            dialog.next_step_button.click()
        assert len(queued) == 1
        queued[0].run()
        wait_pilot_view(dialog, timeout=40)
        child = dialog.snapshot
        assert guided.record(child)["target"] == expected
        assert child.study_directory != snapshot.study_directory
        assert not child.visual_reviews and not child.candidates[0].attempts
        assert dialog.start_button.isEnabled() and not dialog.start_button.isHidden()
        assert dialog.next_step_button.isHidden() and dialog.review_next_button.isHidden()
    finally:
        dialog._worker = None
        dialog.close()
        app.processEvents()
    app, reopened = dialog_for(
        study.load_reference_calibration_study(child.study_directory), monkeypatch
    )
    try:
        assert reopened.start_button.isEnabled() and not reopened.start_button.isHidden()
        assert guided.record(reopened.snapshot)["target"] == expected
        assert reopened.snapshot.candidates[0].attempts == 0
    finally:
        reopened.close()
        app.processEvents()


@pytest.mark.parametrize("decision", [None, False])
def test_unreviewed_and_rejected_result_offer_review_not_false_advance(
    tmp_path, monkeypatch, decision
):
    if decision is False:
        _, snapshot = attempted(tmp_path, monkeypatch)
        snapshot = reject(snapshot, "guided-varifold")
    else:
        _, snapshot = attempted(tmp_path, monkeypatch)
    app, dialog = dialog_for(snapshot, monkeypatch)
    try:
        assert dialog.review_next_button.isEnabled() and not dialog.review_next_button.isHidden()
        assert dialog.next_step_button.isHidden()
        assert dialog.start_button.isHidden()
        if decision is False:
            from PySide6.QtWidgets import QPushButton

            work = next(
                (
                    b
                    for b in dialog.content.findChildren(QPushButton)
                    if b.text().startswith("Work from this starting fit")
                ),
                None,
            )
            assert work and work.isEnabled() and not work.isHidden()
            opened = []
            monkeypatch.setattr(
                dialog, "_open_guided_working_fit", lambda *args: opened.append(args)
            )
            work.click()
            assert len(opened) == 1 and opened[0][0] == "guided-varifold"
            assert opened[0][1]["directory"] != str(snapshot.study_directory)
            assert not dialog.snapshot.visual_reviews["guided-varifold"]
    finally:
        dialog.close()
        app.processEvents()


def test_new_individual_ledger_reaches_joint_and_final_completion_without_new_fit(
    tmp_path, monkeypatch
):
    import shutil

    from test_reference_adaptive_calibration import seed_stub

    from diffeoforge import reference_pilot_completion as completion
    from diffeoforge.mesh import sha256_file

    _, local = local_fit(tmp_path, monkeypatch)
    current = guided.next_action(local.study_directory, "adaptive_next_form", "guided-varifold")
    for _ in range(12):
        if not current.visual_reviews:
            current = approve(run_batch(current, monkeypatch), "guided-varifold")
        proposed = strategy.state(current)["next_forms"]["guided-varifold"]
        current = guided.next_action(
            current.study_directory, "adaptive_" + proposed["action"], "guided-varifold"
        )
        if guided.record(current)["phase"] == "joint":
            break
    else:
        pytest.fail("Individual/common checks did not reach joint within the finite fixture path")
    joint = approve(run_batch(current, monkeypatch), "guided-varifold")
    fourth = guided.next_action(joint.study_directory, "finish_joint", "guided-varifold")
    assert fourth.current_stage.order == 4
    names = [s.filename for s in fourth.plan.selected_pilot_subjects]
    template = next((fourth.study_directory / "inputs/template").glob("*.vtk"))

    def bind(snapshot, identifier, destination):
        seed = seed_stub(snapshot, identifier, destination)
        candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
        seed["source_manifest_sha256"] = sha256_file(
            study.calibration_candidate_run_directory(candidate) / "manifest.json"
        )
        return seed

    def shoot(config, folder, seed, destination, count, **kwargs):
        destination.mkdir(parents=True)
        paths = {n: destination / n for n in names}
        for path in paths.values():
            shutil.copyfile(template, path)
        return paths, {}

    monkeypatch.setattr("diffeoforge.reference_adaptive_calibration.bind_learned_seed", bind)
    monkeypatch.setattr(completion, "shoot", shoot)
    monkeypatch.setattr(
        completion.legacy, "_reconstructions", lambda *a: (None, {n: template for n in names})
    )
    monkeypatch.setattr(
        study.ReferenceCalibrationStudyRunner,
        "run_current_stage",
        lambda *a, **k: pytest.fail("Final check must not dispatch optimization"),
    )
    runner = study.ReferenceCalibrationStudyRunner(fourth.study_directory)
    checked = completion.run(runner)
    identifier = next(iter(completion.evidence(checked)))
    assert checked.visual_reviews[identifier] is True
    app, dialog = dialog_for(checked, monkeypatch)
    try:
        assert dialog._final_next_step.action == "finish"
        assert dialog.next_step_button.isEnabled() and not dialog.next_step_button.isHidden()
    finally:
        dialog.close()
        app.processEvents()
    final, _ = completion.finish(checked.study_directory, identifier)
    assert final.status == "completed"
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"
    app, dialog = dialog_for(final, monkeypatch)
    try:
        assert dialog.advance_button.isEnabled()
        assert dialog.advance_button.text() == "Return to full atlas setup"
    finally:
        dialog.close()
        app.processEvents()
