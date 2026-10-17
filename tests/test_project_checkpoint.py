from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import pytest

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.desktop.setup_checkpoint import (
    restore_setup_checkpoint,
    save_setup_checkpoint,
)
from diffeoforge.input_preflight import inspect_mesh_input_cohort
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.mesh_scaling_contract import DEFAULT_MESH_SCALING_MODE
from diffeoforge.preprocessing import preview_landmark_alignment
from diffeoforge.project_checkpoint import (
    CheckpointUnavailable,
    checkpoint_directory,
    load_checkpoint,
    save_checkpoint,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture
def cohort(tmp_path):
    meshes = tmp_path / "meshes"
    meshes.mkdir()
    source = ROOT / "examples/synthetic/meshes"
    subject_names = [item.name for item in sorted(source.glob("subject-*.vtk"))[:2]]
    paths = tuple(meshes / name for name in ("template.vtk", *subject_names))
    for path in paths:
        shutil.copyfile(ROOT / "examples/synthetic/meshes" / path.name, path)
    landmarks = tmp_path / "landmarks.csv"
    with landmarks.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(LANDMARK_COLUMNS)
        for path in paths:
            vertices = read_vtk_polydata(path).vertices
            for label, index in zip(("a", "b", "c"), (0, 40, 80), strict=True):
                writer.writerow((path.name, label, *vertices[index]))
    return tmp_path / "project", paths, landmarks


def forbid(*_args, **_kwargs):
    raise AssertionError("An unchanged cached input must not be recomputed")


def _form(project, paths, landmarks, preview):
    return {
        "meshes": str(paths[0].parent), "project": str(project),
        "template": str(paths[0]), "landmarks": str(landmarks),
        "pattern": "subject-*.vtk", "engine": "deformetrica_reference", "unit": "millimeter",
        "apply_alignment": True, "remove_size": preview.scale_to_unit_centroid_size,
        "scaling_mode": preview.scaling_mode.value, "target_size": preview.target_size,
        "allow_reflection": preview.allow_reflection, "tolerance": preview.tolerance,
        "max_iterations": preview.max_iterations,
    }


def _prepared(cohort):
    project, paths, landmarks = cohort
    report = inspect_mesh_input_cohort(
        paths, landmark_csv=landmarks, cache_project=project,
        scaling_mode=DEFAULT_MESH_SCALING_MODE,
    )
    preview = preview_landmark_alignment(
        paths[0].parent, template=paths[0], subject_pattern="subject-*.vtk",
        landmarks_file=landmarks, source_metadata=report.metadata,
        source_scale_metrics=report.mesh_scale_metrics,
    )
    return report, preview, _form(project, paths, landmarks, preview)


def test_saved_mesh_checks_are_reused_without_parsing_or_topology(cohort, monkeypatch):
    project, paths, landmarks = cohort
    before = tuple(sha256_file(path) for path in paths)
    first = inspect_mesh_input_cohort(paths, landmark_csv=landmarks, cache_project=project)
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    monkeypatch.setattr("diffeoforge.input_preflight.assess_normalized_triangle_mesh", forbid)
    second = inspect_mesh_input_cohort(
        paths, landmark_csv=landmarks, cache_project=project, cache_only=True,
    )
    assert first == second
    assert tuple(sha256_file(path) for path in paths) == before
    assert len(list(checkpoint_directory(project).glob("surface-*.json"))) == 3


def test_same_size_same_mtime_changed_file_alone_is_rechecked(cohort, monkeypatch):
    from diffeoforge import input_preflight

    project, paths, _landmarks = cohort
    inspect_mesh_input_cohort(paths, cache_project=project)
    original = paths[1].read_bytes()
    lines = original.splitlines(keepends=True)
    lines[1] = bytes([lines[1][0] ^ 32]) + lines[1][1:]
    modified = b"".join(lines)
    assert len(modified) == len(original) and modified != original
    stat = paths[1].stat()
    paths[1].write_bytes(modified)
    os.utime(paths[1], ns=(stat.st_atime_ns, stat.st_mtime_ns))
    calls = []
    loader = input_preflight.load_surface_mesh

    def record(path):
        calls.append(path)
        return loader(path)

    monkeypatch.setattr(input_preflight, "load_surface_mesh", record)
    with pytest.raises(CheckpointUnavailable):
        inspect_mesh_input_cohort(paths, cache_project=project, cache_only=True)
    assert calls == []
    inspect_mesh_input_cohort(paths, cache_project=project)
    assert calls == [paths[1]]


def test_corrupt_cache_is_not_accepted_and_explicit_check_repairs_owned_record(cohort):
    project, paths, _landmarks = cohort
    inspect_mesh_input_cohort(paths, cache_project=project)
    target = next(checkpoint_directory(project).glob("surface-*.json"))
    payload = json.loads(target.read_text())
    payload["sha256"] = "0" * 64
    target.write_text(json.dumps(payload))
    with pytest.raises(CheckpointUnavailable):
        inspect_mesh_input_cohort(paths, cache_project=project, cache_only=True)
    inspect_mesh_input_cohort(paths, cache_project=project)
    inspect_mesh_input_cohort(paths, cache_project=project, cache_only=True)


def test_approved_gpa_survives_restart_and_app_version_change(cohort, monkeypatch):
    project, paths, landmarks = cohort
    report, preview, form = _prepared(cohort)
    save_setup_checkpoint(project, form, report, preview, preview.fingerprint, True)
    monkeypatch.setattr("diffeoforge.__version__", "0.0.0.dev999")
    monkeypatch.setattr("diffeoforge.preprocessing.fit_landmark_guided_alignment", forbid)
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    restored = restore_setup_checkpoint(project, form, paths, landmarks)
    assert restored.preflight == report
    assert restored.preview.fingerprint == preview.fingerprint
    assert restored.reviewed_fingerprint == preview.fingerprint and restored.approved
    assert not restored.preview.alignment.mean_shape.flags.writeable


@pytest.mark.parametrize("change", ["landmarks", "settings"])
def test_changed_landmarks_or_settings_remove_gpa_approval_without_deep_scan(
    cohort, monkeypatch, change,
):
    project, paths, landmarks = cohort
    report, preview, form = _prepared(cohort)
    save_setup_checkpoint(project, form, report, preview, preview.fingerprint, True)
    if change == "landmarks":
        landmarks.write_bytes(landmarks.read_bytes() + b"\n")
    else:
        form = {**form, "target_size": preview.target_size * 2}
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    monkeypatch.setattr("diffeoforge.preprocessing.fit_landmark_guided_alignment", forbid)
    restored = restore_setup_checkpoint(project, form, paths, landmarks)
    assert restored.preflight is not None
    assert restored.preview is None and not restored.approved
    assert restored.reviewed_fingerprint is None


def test_numerical_preview_does_not_manufacture_visual_acceptance(cohort):
    project, paths, landmarks = cohort
    report, preview, form = _prepared(cohort)
    save_setup_checkpoint(project, form, report, preview, None, True)
    restored = restore_setup_checkpoint(project, form, paths, landmarks)
    assert restored.preview is not None
    assert not restored.approved and restored.reviewed_fingerprint is None


def test_old_checkpoint_contract_is_not_silently_accepted(cohort, monkeypatch):
    project, paths, landmarks = cohort
    report, preview, form = _prepared(cohort)
    save_setup_checkpoint(project, form, report, preview, preview.fingerprint, True)
    monkeypatch.setattr("diffeoforge.project_checkpoint.CHECKPOINT_VERSION", "new-rules")
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    restored = restore_setup_checkpoint(project, form, paths, landmarks)
    assert restored.preflight is None and restored.preview is None and not restored.approved


def test_restored_setup_reapplies_current_mesh_quality_policy(cohort, monkeypatch):
    from diffeoforge.mesh_quality import MeshQualitySettings

    project, paths, landmarks = cohort
    report, preview, form = _prepared(cohort)
    save_setup_checkpoint(project, form, report, preview, preview.fingerprint, True)
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    monkeypatch.setattr("diffeoforge.input_preflight.ATLAS_INPUT_MESH_QUALITY_SETTINGS",
                        MeshQualitySettings(minimum_triangle_angle_degrees=60))
    restored = restore_setup_checkpoint(project, form, paths, landmarks)
    assert restored.preflight.blockers


def test_unrecognized_file_is_preserved_and_bad_names_rejected(tmp_path):
    folder = checkpoint_directory(tmp_path)
    folder.mkdir(parents=True)
    (folder / "setup.json").write_text("private unrelated content")
    with pytest.raises(CheckpointUnavailable):
        save_checkpoint(tmp_path, "setup", {"value": 1})
    assert (folder / "setup.json").read_text() == "private unrelated content"
    with pytest.raises(ValueError):
        save_checkpoint(tmp_path, "../escape", {})
    with pytest.raises(CheckpointUnavailable):
        load_checkpoint(tmp_path, "setup")


def test_reference_review_reuses_geometry_but_rechecks_current_quality_gates(cohort, monkeypatch):
    from diffeoforge.config import ConfigurationError
    from diffeoforge.initialization import initialize_project
    from diffeoforge.mesh_quality import MeshQualitySettings
    from diffeoforge.report import collect_preflight

    project, paths, _landmarks = cohort
    result = initialize_project(
        paths[0].parent, config_path=project / "atlas.yaml", units="millimeter",
        template=paths[0], subject_pattern="subject-*.vtk",
    )
    first = collect_preflight(result.config_path, cache_project=project)
    monkeypatch.setattr("diffeoforge.report._structural_quality", forbid)
    monkeypatch.setattr("diffeoforge.mesh.inspect_vtk", forbid)
    second = collect_preflight(result.config_path, cache_project=project)
    assert second.mesh_quality == first.mesh_quality
    monkeypatch.setattr("diffeoforge.report.ATLAS_INPUT_MESH_QUALITY_SETTINGS",
                        MeshQualitySettings(minimum_triangle_angle_degrees=60))
    with pytest.raises(ConfigurationError):
        collect_preflight(result.config_path, cache_project=project)


@pytest.mark.parametrize("invalidate", ["bytes", "corrupt", "definitions"])
def test_reference_preflight_rechecks_only_invalidated_mesh_checks(cohort, monkeypatch, invalidate):
    import diffeoforge.report as report_module
    from diffeoforge.initialization import initialize_project
    from diffeoforge.report import collect_preflight

    project, paths, _landmarks = cohort
    config = initialize_project(
        paths[0].parent, config_path=project / "atlas.yaml", units="millimeter",
        template=paths[0], subject_pattern="subject-*.vtk",
    ).config_path
    events = []
    collect_preflight(config, cache_project=project, progress_callback=events.append)
    assert [e.state for e in events] == ["hashing", "checking", "checked"] * 3
    if invalidate == "bytes":
        paths[0].write_bytes(paths[0].read_bytes() + b"\n")
    elif invalidate == "corrupt":
        next(checkpoint_directory(project).glob("vtk-1-*.json")).write_text("broken")
    else:
        monkeypatch.setattr("diffeoforge.mesh_quality.QUALITY_DEFINITIONS_VERSION", "next")
    original = report_module._structural_quality
    calls = []

    def checked(metadata, subjects):
        calls.append(metadata.path)
        return original(metadata, subjects)

    monkeypatch.setattr(report_module, "_structural_quality", checked)
    events.clear()
    result = collect_preflight(config, cache_project=project, progress_callback=events.append)
    assert len(calls) == (3 if invalidate == "definitions" else 1)
    finished = [e for e in events if e.state in {"checked", "reused"}]
    assert [e.completed for e in finished] == [1, 2, 3]
    assert all(e.total == 3 for e in events)
    assert len(result.mesh_quality) == 3


class QueuedPool:
    def __init__(self):
        self.workers = []

    def start(self, worker):
        self.workers.append(worker)


@pytest.mark.parametrize("change_during_load", [False, True])
def test_desktop_last_project_restores_checks_and_gpa_without_recalculation(
    cohort, monkeypatch, tmp_path, change_during_load,
):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.recent_projects import (
        recent_project_from_inputs,
        record_recent_project,
    )
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    project, paths, landmarks = cohort
    report, preview, _form_values = _prepared(cohort)
    (project / "atlas.yaml").write_text("placeholder for history availability only")
    entry = recent_project_from_inputs(
        engine="deformetrica_reference", project_directory=project,
        mesh_directory=paths[0].parent, template=paths[0], landmarks=landmarks,
        subject_pattern="subject-*.vtk", coordinate_unit="millimeter",
    )
    app = QApplication.instance() or QApplication(["checkpoint-restart-test"])
    first = DiffeoForgeWindow()
    first.mesh_edit.setText(str(paths[0].parent))
    first.template_edit.setText(str(paths[0]))
    first.landmarks_edit.setText(str(landmarks))
    first.pattern_edit.setText("subject-*.vtk")
    first.project_edit.setText(str(project))
    first.units_combo.setCurrentIndex(first.units_combo.findData("millimeter"))
    first.procrustes_scaling_combo.setCurrentIndex(
        first.procrustes_scaling_combo.findData(preview.scaling_mode.value)
    )
    first._input_preflight = report
    first._input_preflight_signature = first._current_input_preflight_signature()
    first._procrustes_preview = preview
    first._procrustes_visual_reviewed_fingerprint = preview.fingerprint
    first._update_procrustes_controls()
    first.approve_procrustes_check.setChecked(True)
    assert first._approved_procrustes_fingerprint() == preview.fingerprint
    first._save_setup_checkpoint()
    first.close()
    record_recent_project(entry)
    monkeypatch.setattr("diffeoforge.input_preflight.load_surface_mesh", forbid)
    monkeypatch.setattr("diffeoforge.preprocessing.fit_landmark_guided_alignment", forbid)
    second = DiffeoForgeWindow()
    assert not second.mesh_edit.text()
    pool = QueuedPool()
    second._thread_pool = pool
    second.load_last_project_button.click()
    assert len(pool.workers) == 1
    assert second._input_preflight_worker is None
    if change_during_load:
        second.procrustes_target_size_spin.setValue(preview.target_size * 2)
    pool.workers[0].run()
    app.processEvents()
    assert second._worker is None
    if change_during_load:
        assert second._input_preflight is None
        assert second._approved_procrustes_fingerprint() is None
    else:
        assert second._data_inputs_ready()
        assert second._approved_procrustes_fingerprint() == preview.fingerprint
        assert second.approve_procrustes_check.isChecked()
        assert "No deep mesh validation or GPA was repeated" in second.data_status_label.text()
        # Re-loading identical fields must clear an old in-memory approval before
        # checking bytes again, and must not overwrite the saved approval en route.
        saved_before = (checkpoint_directory(project) / "setup.json").read_bytes()
        second.load_last_project_button.click()
        assert second._approved_procrustes_fingerprint() is None
        assert (checkpoint_directory(project) / "setup.json").read_bytes() == saved_before
        paths[1].write_bytes(paths[1].read_bytes() + b"\n")
        pool.workers[-1].run()
        app.processEvents()
        assert second._input_preflight is None
        assert second._procrustes_preview is None
        assert second._approved_procrustes_fingerprint() is None
    second.close()


def test_failed_project_write_remains_visible_after_state_refresh(cohort, monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    project, paths, landmarks = cohort
    report, _preview, _form_values = _prepared(cohort)
    app = QApplication.instance() or QApplication(["checkpoint-write-failure-test"])
    window = DiffeoForgeWindow()
    window.mesh_edit.setText(str(paths[0].parent))
    window.project_edit.setText(str(project))
    window.template_edit.setText(str(paths[0]))
    window.landmarks_edit.setText(str(landmarks))
    window.pattern_edit.setText("subject-*.vtk")
    window._input_preflight = report
    window._input_preflight_signature = window._current_input_preflight_signature()

    def cannot_write(*_args, **_kwargs):
        raise PermissionError("project is read-only")

    monkeypatch.setattr("diffeoforge.desktop.widgets.save_setup_checkpoint", cannot_write)
    window._save_setup_checkpoint()
    window._sync_ready_state()
    app.processEvents()
    assert "Checks could not be saved" in window.data_status_label.text()
    assert "project is read-only" in window.data_status_label.text()
    window.close()


def test_existing_project_resume_does_not_require_raw_setup_again(cohort, monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "state"))
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_setup import DesktopEngine, ProjectSetupResult
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    project, paths, _landmarks = cohort
    project.mkdir()
    config = project / "atlas.yaml"
    config.write_text("immutable existing project")
    app = QApplication.instance() or QApplication(["legacy-resume-checkpoint-test"])
    window = DiffeoForgeWindow()
    window.project_edit.setText(str(project))
    result = ProjectSetupResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE, config_path=config,
        template_path=paths[0], subject_count=2, report_path=None, notices=(),
    )
    monkeypatch.setattr(
        "diffeoforge.desktop.widgets.load_existing_reference_project", lambda _: result,
    )
    reviews = []
    monkeypatch.setattr(window, "_review_project", lambda: reviews.append(True))
    monkeypatch.setattr(window, "_preview_procrustes", forbid)
    monkeypatch.setattr(window, "_start_input_preflight", forbid)
    window._sync_ready_state()
    assert not window._data_inputs_ready()
    assert window.continue_parameter_button.isEnabled()
    window.continue_parameter_button.click()
    app.processEvents()
    assert window._result == result and reviews == [True]
    assert config.read_text() == "immutable existing project"
    window.close()
