from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_reference_calibration_study import _approve_for_test, _review_ready_stage
from test_reference_sequential_fit import _measured, _reject

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_fit_search as search
from diffeoforge import reference_progressive_fit as progressive
from diffeoforge import reference_sequential_fit as sequence
from diffeoforge.config import load_config


def mock_singleton(monkeypatch, snapshot):
    """Public synthetic field fixture; no production evidence gate is disabled."""
    from diffeoforge import reference_pca
    from diffeoforge.reference_pca_deformations import _write_momenta

    candidate = snapshot.candidates[0]
    run = study.calibration_candidate_run_directory(candidate)
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text('{"synthetic_fixture":true}', encoding="utf-8")
    info = sequence.sequence_info(snapshot.study_directory)
    parent = Path(info["root"])
    bound = study._verify_manifest(parent)
    controls = np.loadtxt(parent / bound["fit_search"]["controls"]["copy"])
    manifest = study._verify_manifest(snapshot.study_directory)
    file = run / "synthetic-field.txt"
    values = np.ones((1, len(controls), 3)) * 0.01
    _write_momenta(file, values)
    inputs = SimpleNamespace(
        subject_labels=(info["filename"],),
        momenta=values,
        control_points=np.round(controls, 6),
        momenta_path=file,
        run_report=SimpleNamespace(
            manifest=dict(
                effective_config=load_config(candidate.config_path),
                inputs=[
                    dict(
                        role="subject", staged_path=r["filename"], geometry=dict(sha256=r["sha256"])
                    )
                    for r in manifest["fit_search"]["working_targets"]
                ]
                + [
                    dict(
                        role="template", geometry=dict(sha256=bound["inputs"]["template"]["sha256"])
                    )
                ],
            )
        ),
    )
    monkeypatch.setattr(reference_pca, "load_reference_momenta", lambda *a, **k: inputs)
    return inputs


def test_progression_uses_fields_without_transferring_qc_and_is_bounded():
    center = dict(
        deformation_kernel_width=1,
        attachment_kernel_width=0.001,
        initial_control_point_spacing=0.3,
        noise_std=0.2,
    )
    observations = []
    for branch in range(progressive.BRANCHES):
        for step in range(progressive.STEPS):
            attempt = progressive.next_attempt(center, observations, 4)
            assert attempt["progressive"]["branch"] == branch
            assert attempt["progressive"]["step"] == step
            assert sequence._basis(attempt["values"]) == sequence._basis(center)
            assert attempt["seed"] == ("verified field" if step else None)
            if step:
                assert (
                    attempt["values"]["attachment_kernel_width"]
                    <= observations[-1]["values"]["attachment_kernel_width"]
                )
            observations.append(dict(attempt, seed="verified field", p95=0.3))
    with pytest.raises(ValueError, match="All approvals are saved"):
        progressive.next_attempt(center, observations, 4)
    # Corrupt/missing fields cannot start a warm refinement.
    observations = [dict(observations[0], seed=None)]
    assert progressive.next_attempt(center, observations, 4)["seed"] is None


def test_warm_continuation_copies_exact_field_and_checks_basis(tmp_path, monkeypatch):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    inputs = mock_singleton(monkeypatch, first)
    candidate = first.candidates[0]
    root = Path(sequence.sequence_info(first.study_directory)["root"])
    values = sequence._values(first, candidate.candidate_id)
    seed = progressive.seed_request(first, candidate.candidate_id, root, values)
    cid = _reject(first)
    successor = sequence.run_specimen_sequence(runner, action=("retry", cid, 80))
    manifest = study._verify_manifest(successor.study_directory)
    config = load_config(successor.candidates[0].config_path)
    path = (
        successor.candidates[0].config_path.parent
        / config["model"]["deformation"]["initial_momenta"]
    ).resolve()
    assert path.read_bytes() == inputs.momenta_path.read_bytes()
    assert path.is_relative_to(successor.study_directory)
    assert config["optimization"]["max_iterations"] == 80
    assert manifest["fit_search"]["warm_seed"]["source_run_sha256"] == seed["source_run_sha256"]
    assert not successor.visual_reviews
    from diffeoforge.backends.deformetrica_reference import build_command, render_engine_file_bytes
    from diffeoforge.config import ConfigurationError, validate_input_paths, validate_schema

    command = build_command(config, successor.study_directory / "test-run")
    assert command.environment["PYTHONPATH"].replace("\\", "/").endswith("test-run/engine")
    rendered = render_engine_file_bytes(
        config,
        Path("template.vtk"),
        [Path("subject.vtk")],
        Path("controls.txt"),
        Path("momenta.txt"),
    )
    assert "sitecustomize.py" in rendered
    validate_input_paths(config, successor.candidates[0].config_path)
    config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"][
        "execution_scope"
    ] = "pilot"
    with pytest.raises(ConfigurationError):
        validate_schema(config)
    inputs.control_points[0, 0] += 1
    with pytest.raises(ValueError, match="control basis"):
        progressive.seed_request(first, cid, root, values)
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError):
        study.load_reference_calibration_study(successor.study_directory)


@pytest.mark.parametrize("change", ["subject", "kernel", "template", "nonfinite", "freeze"])
def test_singleton_seed_rejects_incompatible_evidence(tmp_path, monkeypatch, change):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    inputs = mock_singleton(monkeypatch, first)
    if change == "subject":
        inputs.subject_labels = ("wrong.vtk",)
    elif change == "kernel":
        inputs.run_report.manifest["effective_config"]["model"]["deformation"]["kernel_width"] *= 2
    elif change == "template":
        inputs.run_report.manifest["inputs"][-1]["geometry"]["sha256"] = "0" * 64
    elif change == "freeze":
        inputs.run_report.manifest["effective_config"]["optimization"]["freeze_control_points"] = (
            False
        )
    else:
        inputs.momenta[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="control basis"):
        progressive.seed_request(
            first,
            first.candidates[0].candidate_id,
            Path(sequence.sequence_info(first.study_directory)["root"]),
            sequence._values(first, first.candidates[0].candidate_id),
        )


def test_denser_model_reuses_targets_but_never_approvals_and_starts_with_current(
    tmp_path, monkeypatch
):
    from diffeoforge import mesh_filter_worker

    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    cid = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, cid)
    current = sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    info = sequence.sequence_info(current.study_directory)
    old_root = Path(info["root"])
    before = (old_root / sequence.STATE).read_bytes()
    old = study._verify_manifest(old_root)
    monkeypatch.setattr(
        mesh_filter_worker, "run_mesh_filter", lambda *a, **k: pytest.fail("Repeated reduction")
    )
    denser = sequence.run_specimen_sequence(runner, action=("denser", "", 0))
    new_info = sequence.sequence_info(denser.study_directory)
    new_root = Path(new_info["root"])
    new = study._verify_manifest(new_root)
    assert new_root != old_root
    assert new_info["index"] == 0 and new_info["filename"] == info["filename"]
    assert new["fit_search"]["controls"]["count"] > old["fit_search"]["controls"]["count"]
    assert not sequence._read(new_root)["approved"] and not denser.visual_reviews
    assert (old_root / sequence.STATE).read_bytes() == before
    assert new["fit_search"]["working_targets"] == old["fit_search"]["working_targets"]
    assert not load_config(denser.candidates[0].config_path)["model"]["deformation"].get(
        "initial_momenta"
    )
    restored = sequence.restore_saved_sequence(denser.study_directory, old_root)
    # Explicit old-series choice ignores its forward pointer to the denser model.
    assert restored.study_directory == current.study_directory
    assert len(sequence._read(old_root)["approved"]) == 1
    rows = sequence.saved_sequences(denser.study_directory)
    assert rows[0]["approved"] == 1
    assert (old_root / sequence.STATE).read_bytes() == before


def test_exhausted_legacy_settings_can_start_progressive_capture_preserving_approval(
    tmp_path, monkeypatch
):
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    cid = first.candidates[0].candidate_id
    _approve_for_test(first.study_directory, cid)
    current = sequence.run_specimen_sequence(runner, action=("advance", cid, 0))
    root = Path(sequence.sequence_info(current.study_directory)["root"])
    approval = sequence._read(root)["approved"]
    improved = sequence.run_specimen_sequence(runner, action=("improve", cid, 0))
    manifest = study._verify_manifest(improved.study_directory)
    assert manifest["fit_search"]["progressive"]["phase"] == "capture"
    assert sequence.sequence_info(improved.study_directory)["index"] == 1
    assert sequence._read(root)["approved"] == approval
    assert sequence._basis(sequence._values(improved, cid)) == sequence._basis(
        sequence._values(current, cid)
    )
    mock_singleton(monkeypatch, improved)
    _reject(improved)
    refined = sequence.run_specimen_sequence(runner, action=("reject", cid, 0))
    bound = study._verify_manifest(refined.study_directory)["fit_search"]
    assert bound["progressive"]["phase"] == "refine" and bound["warm_seed"]
    assert sequence._read(root)["approved"] == approval
    assert not refined.visual_reviews


def test_gui_improve_preserves_sequence_and_restoring_blocks_dispatch(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    runner, _ = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(search, "measure_original_fit", _measured)
    first = sequence.run_specimen_sequence(runner)
    dialog = ReferenceCalibrationDialog(first.study_directory)
    calls = []
    monkeypatch.setattr(dialog, "_start_pilot", lambda **kw: calls.append(kw))
    dialog._find_fit()
    assert calls[-1]["specimen_action"][0] == "improve"
    assert dialog.find_fit_button.text() == "Improve this specimen"
    dialog._restoring_search = True
    dialog._find_fit()
    assert len(calls) == 1
    dialog._saved_search_loaded(("restore", first.study_directory), first)
    assert not dialog._restoring_search
    dialog.close()
    app.processEvents()


def test_legacy_shape_adapter_restores_only_the_missing_subject_axis(monkeypatch):
    import sys
    from types import ModuleType

    from diffeoforge.reference_singleton_compat import SITECUSTOMIZE

    atlas = ModuleType("deterministic_atlas")
    field = np.arange(12).reshape(4, 3)
    atlas.initialize_momenta = lambda *a, **k: field
    models = ModuleType("deformetrica.core.models")
    models.deterministic_atlas = atlas
    monkeypatch.setitem(sys.modules, "deformetrica", ModuleType("deformetrica"))
    monkeypatch.setitem(sys.modules, "deformetrica.core", ModuleType("deformetrica.core"))
    monkeypatch.setitem(sys.modules, "deformetrica.core.models", models)
    exec(SITECUSTOMIZE, {})
    restored = atlas.initialize_momenta("field.txt", 4, 3, number_of_subjects=1)
    assert restored.shape == (1, 4, 3)
    np.testing.assert_array_equal(restored[0], field)
    assert atlas.initialize_momenta(None, 4, 3, number_of_subjects=1) is field
    assert atlas.initialize_momenta("field.txt", 4, 3, number_of_subjects=2) is field
    with pytest.raises(ValueError):
        atlas.initialize_momenta("field.txt", 5, 3, number_of_subjects=1)
