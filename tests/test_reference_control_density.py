import json
import shutil

import numpy as np
import pytest
from pilot_view_helpers import wait_pilot_view
from test_pilot_completion import _approve_preview, _checked

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_control_density as density
from diffeoforge import reference_pilot_completion as completion
from diffeoforge.config import load_config
from diffeoforge.reference_pca import read_deformetrica_momenta


def _source(tmp_path, monkeypatch):
    runner, done, _, identifier = _checked(tmp_path, monkeypatch)
    _approve_preview(done, identifier)
    final, _ = completion.finish(done.study_directory, identifier)
    return runner, final


def _bytes(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_prepare_nested_bases_preserves_original_approvals_and_every_other_setting(
    tmp_path,
    monkeypatch,
):
    _, source = _source(tmp_path, monkeypatch)
    old = _bytes(source.study_directory)
    child = density.prepare(source.study_directory)
    manifest = study._verify_manifest(child.study_directory)
    record = manifest["control_density"]
    assert child.current_stage.stage_id == "timepoints"
    assert len(child.candidates) == 3 and not child.visual_reviews
    assert not child.early_screening and "fit_search" not in manifest
    assert all(c.status == "pending" for c in child.candidates)
    assert child.selected_candidate_ids == {
        k: v
        for k, v in source.selected_candidate_ids.items()
        if k != source.plan.stages[-1].stage_id
    }
    points, momenta = [], []
    for variant, candidate in zip(record["variants"], child.candidates, strict=True):
        config = load_config(candidate.config_path)
        points.append(np.loadtxt(child.study_directory / variant["controls"]["copy"], ndmin=2))
        momenta.append(
            read_deformetrica_momenta(
                child.study_directory / variant["momenta"]["copy"],
                allow_singleton=True,
            )
        )
        assert (
            config["model"]["deformation"]["kernel_width"]
            == load_config(child.study_directory / manifest["source_config"]["copy"])["model"][
                "deformation"
            ]["kernel_width"]
        )
    assert len(points[0]) < len(points[1]) < len(points[2])
    for p, m in zip(points, momenta, strict=True):
        assert np.array_equal(p[: len(points[0])], points[0])
        assert np.array_equal(m[:, : len(points[0])], momenta[0])
        assert not np.any(m[:, len(points[0]) :])
    before = _bytes(child.study_directory)
    assert density.prepare(source.study_directory) == child
    assert all(p.read_bytes() == b for p, b in old.items())
    assert all(p.read_bytes() == b for p, b in before.items())


def test_density_dispatch_cannot_batch_skip_or_reapprove_original(tmp_path, monkeypatch):
    _, source = _source(tmp_path, monkeypatch)
    child = density.prepare(source.study_directory)
    runner = study.ReferenceCalibrationStudyRunner(child.study_directory)
    old = _bytes(child.study_directory)
    for ids in (None, {"density-01", "density-02"}, {"density-02"}):
        with pytest.raises(ValueError, match="Density comparisons"):
            runner.run_current_stage(candidate_ids=ids)
    assert all(p.read_bytes() == b for p, b in old.items())
    assert not child.visual_reviews


@pytest.mark.parametrize("field", ["controls", "momenta"])
def test_density_reopening_rejects_changed_initialization(tmp_path, monkeypatch, field):
    _, source = _source(tmp_path, monkeypatch)
    child = density.prepare(source.study_directory)
    record = study._verify_manifest(child.study_directory)["control_density"]
    path = child.study_directory / record["variants"][1][field]["copy"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="initialization changed"):
        study.load_reference_calibration_study(child.study_directory)


def test_source_approval_withdrawal_blocks_density_reuse(tmp_path, monkeypatch):
    _, source = _source(tmp_path, monkeypatch)
    child = density.prepare(source.study_directory)
    # A real recorded withdrawal of the selected source is not overwritten by
    # child creation and must block later use of that source.
    path = source.study_directory / "visual-reviews.json"
    value = json.loads(path.read_text())
    record = value["records"][-1]
    record["approved"] = False
    record["event_hash"] = study._canonical_hash(
        {k: v for k, v in record.items() if k != "event_hash"}
    )
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Review|approval|anatom|eligible"):
        study.load_reference_calibration_study(child.study_directory)


def test_same_initial_field_and_settings_drift_rejected(tmp_path, monkeypatch):
    from diffeoforge import reference_adaptive_calibration as adaptive
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_pca_deformations import _write_momenta

    _, source = _source(tmp_path, monkeypatch)
    bind = adaptive.bind_learned_seed

    def nonzero_seed(*args):
        seed = bind(*args)
        path = args[-1] / seed["files"]["momenta"]["copy"]
        values = read_deformetrica_momenta(path, allow_singleton=True)
        values[:] = np.arange(values.size).reshape(values.shape) * 0.001
        path.unlink()  # Replace only this test-created synthetic seed.
        _write_momenta(path, values)
        seed["files"]["momenta"]["sha256"] = sha256_file(path)
        return seed

    monkeypatch.setattr(adaptive, "bind_learned_seed", nonzero_seed)
    child = density.prepare(source.study_directory)
    record = study._verify_manifest(child.study_directory)["control_density"]
    locations = np.array([[0.1, 0.2, 0.3], [1.0, 0.6, 0.5]])
    fields = []
    for variant in record["variants"]:
        cp = np.loadtxt(child.study_directory / variant["controls"]["copy"], ndmin=2)
        mp = read_deformetrica_momenta(
            child.study_directory / variant["momenta"]["copy"],
            allow_singleton=True,
        )
        kernel = np.exp(-np.sum((locations[:, None, :] - cp[None, :, :]) ** 2, axis=2))
        fields.append(np.einsum("vc,scd->svd", kernel, mp))
    assert np.any(fields[0])
    assert all(np.allclose(f, fields[0], rtol=1e-13, atol=1e-15) for f in fields)
    config = load_config(child.candidates[1].config_path)
    config["model"]["deformation"]["kernel_width"] *= 0.9
    study._write_yaml(child.candidates[1].config_path, config, overwrite=True)
    with pytest.raises(ValueError, match="Only control density"):
        study.load_reference_calibration_study(child.study_directory)


def test_each_fit_requires_fresh_review_and_selected_basis_reaches_full_cohort(
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    from diffeoforge import reference_adaptive_calibration as adaptive
    from diffeoforge.mesh import sha256_file

    _, source = _source(tmp_path, monkeypatch)
    protected = _bytes(source.study_directory)
    child = density.prepare(source.study_directory)
    with pytest.raises(ValueError, match="Complete and review"):
        completion.finish(child.study_directory, "density-01")
    binding = adaptive.bind_learned_seed

    def selected_basis(snapshot, identifier, destination):
        seed = binding(snapshot, identifier, destination)
        if "control_density" in study._read_json(
            snapshot.study_directory / study.STUDY_MANIFEST, "study"
        ):
            candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
            config = load_config(candidate.config_path)
            for role, field in (
                ("control_points", "initial_control_points"),
                ("momenta", "initial_momenta"),
            ):
                original = (
                    candidate.config_path.parent / config["model"]["deformation"][field]
                ).resolve()
                target = destination / seed["files"][role]["copy"]
                shutil.copyfile(original, target)
                seed["files"][role]["sha256"] = sha256_file(target)
        return seed

    monkeypatch.setattr(adaptive, "bind_learned_seed", selected_basis)
    original_metrics = density.source_fit(source.study_directory)[1].metrics
    calls = []

    def complete_one(*, candidate_ids, event_callback=None):
        assert len(candidate_ids) == 1
        candidate = next(c for c in child.candidates if c.candidate_id in candidate_ids)
        calls.append(candidate.candidate_id)
        run = candidate.config_path.parent / "runs" / "pilot-attempt-01"
        run.mkdir(parents=True)
        for name in ("manifest.json", "result.json", "output-inventory.json"):
            (run / name).write_text("{}", encoding="utf-8")
        study._append_event(
            child.study_directory,
            "candidate_started",
            dict(
                stage_id=density.STAGE_ID,
                candidate_id=candidate.candidate_id,
                attempt=1,
                run_directory=study._relative_path(child.study_directory, run),
            ),
        )
        study._append_event(
            child.study_directory,
            "candidate_completed",
            dict(
                stage_id=density.STAGE_ID,
                candidate_id=candidate.candidate_id,
                attempt=1,
                run_directory=study._relative_path(child.study_directory, run),
                metrics=dict(original_metrics),
            ),
        )
        return study.load_reference_calibration_study(child.study_directory)

    runner = SimpleNamespace(study_directory=child.study_directory, run_current_stage=complete_one)
    for candidate in child.candidates:
        done = density.run_next(runner)
        assert done.status == "awaiting_review"
        assert candidate.candidate_id not in done.visual_reviews
        with pytest.raises(ValueError, match="Review"):
            density.run_next(runner)
        _approve_preview(done, candidate.candidate_id)
    assert calls == ["density-01", "density-02", "density-03"]
    done = study.load_reference_calibration_study(child.study_directory)
    assert all(done.visual_reviews.values())
    checked = completion.run(
        study.ReferenceCalibrationStudyRunner(child.study_directory), candidate_id="density-02"
    )
    final, _ = completion.finish(checked.study_directory, "density-02")
    final_config = load_config(final.final_config_path)
    cp = (
        final.final_config_path.parent
        / final_config["model"]["deformation"]["initial_control_points"]
    )
    count = study._verify_manifest(child.study_directory)["control_density"]["variants"][1]["count"]
    assert len(np.loadtxt(cp, ndmin=2)) == count
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"
    report = json.loads(final.report_json_path.read_text())
    assert (
        "control_point_density" in report
        and len(report["control_point_density"]["comparisons"]) == 4
    )
    assert "Control-point density of the chosen fit" in final.report_html_path.read_text(
        encoding="utf-8"
    )
    assert all(p.read_bytes() == b for p, b in protected.items())


def test_density_ui_dispatches_one_fit_and_keeps_original_completed_action(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QTableWidget

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    app = QApplication.instance() or QApplication([])
    _, source = _source(tmp_path, monkeypatch)
    original = ReferenceCalibrationDialog(source.study_directory)
    wait_pilot_view(original)
    assert not original.density_button.isHidden()
    operations = []
    monkeypatch.setattr(
        original._saved_search_loader, "request_operation", lambda *a: operations.append(a)
    )
    original.density_button.click()
    assert operations[0][0] == ("density", source.study_directory)
    original._restoring_search = False
    original.close()
    child = density.prepare(source.study_directory)
    dialog = ReferenceCalibrationDialog(child.study_directory)
    wait_pilot_view(dialog)
    assert dialog.findChild(QTableWidget, "controlDensityComparison").rowCount() == 4
    assert "Fit next density" in dialog.start_button.text()
    assert dialog.qualification_button.isHidden()
    assert dialog.selection_combo.isHidden()
    assert dialog._candidate_option_text(child.candidates[0], 1).startswith("Matched reference")
    assert not dialog.density_return_button.isHidden()
    assert dialog.collect_evidence_button.isHidden()
    workers = []
    monkeypatch.setattr(dialog._thread_pool, "start", workers.append)
    dialog._start()
    assert len(workers) == 1 and workers[0].density_next and not workers[0].qualification
    dialog._worker = None
    dialog._saved_search_loaded(("restore", child.study_directory), source)
    wait_pilot_view(dialog)
    assert dialog.snapshot.status == "completed"
    assert not dialog.density_button.isHidden()
    assert dialog.density_return_button.isHidden()
    assert not dialog.continuation_disclosure.isHidden()
    dialog.close()
    app.processEvents()
