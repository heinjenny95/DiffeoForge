from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _prepared_window(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Real recent-project history must not replace the synthetic input defaults.
    monkeypatch.setenv("DIFFEOFORGE_STATE_HOME", str(tmp_path / "desktop-state"))
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-calibration-desktop-test"]
    )
    queued = []

    class FakePool:
        def start(self, worker) -> None:
            queued.append(worker)

    window = DiffeoForgeWindow()
    window._thread_pool = FakePool()  # type: ignore[assignment]
    window.engine_combo.setCurrentIndex(
        window.engine_combo.findData(DesktopEngine.DEFORMETRICA_REFERENCE)
    )
    window.mesh_edit.setText(str(ROOT / "examples" / "synthetic" / "meshes"))
    window.project_edit.setText(str(tmp_path / "project"))
    window.units_combo.setCurrentIndex(window.units_combo.findData("unitless"))
    window.already_gpa_check.setChecked(True)
    application.processEvents()
    return application, window, queued


def test_desktop_builds_and_binds_transparent_calibration_plan(
    monkeypatch,
    tmp_path,
) -> None:
    application, window, queued = _prepared_window(monkeypatch, tmp_path)

    assert window.build_reference_calibration_button.isEnabled() is False
    assert window.export_reference_calibration_button.isEnabled() is False
    window.analyze_reference_parameters_button.click()
    assert len(queued) == 1
    queued[0].run()
    application.processEvents()

    assert window._reference_recommendation is not None
    assert window.build_reference_calibration_button.isEnabled() is True
    assert window.measure_reference_feature_button.isEnabled() is True
    assert "No Deformetrica process starts" in (
        window.reference_calibration_status.text()
    )
    window.reference_pilot_subject_count_spin.setValue(4)
    window.reference_feature_scale_spin.setValue(
        2.0
        * window._reference_recommendation.effective_values[
            "attachment_kernel_width"
        ]
    )
    window.build_reference_calibration_button.click()
    application.processEvents()

    plan = window._reference_calibration_plan
    assert plan is not None
    assert plan.pilot_subject_count == 4
    assert plan.smallest_relevant_feature == pytest.approx(
        window.reference_feature_scale_spin.value()
    )
    assert "planned, not executed" in window.reference_calibration_status.text()
    assert "Surface-detail and deformation-scale screening" in (
        window.reference_calibration_status.text()
    )
    assert window.export_reference_calibration_button.isEnabled() is True
    recommendation = window._request().reference_parameter_recommendation
    assert recommendation is not None
    assert recommendation["calibration_plan"]["fingerprint"] == plan.fingerprint
    assert recommendation["calibration_plan"]["status"] == "planned_not_executed"
    from diffeoforge.desktop.project_setup import create_project

    result = create_project(window._request())
    config_text = result.config_path.read_text(encoding="utf-8")
    assert "calibration_plan:" in config_text
    assert plan.fingerprint in config_text
    from diffeoforge.desktop.project_review import review_project

    review = review_project(result.config_path, result.engine)
    review_values = {item.label: item.value for item in review.parameters}
    assert "predeclared · not executed" in review_values["Pilot calibration"]
    assert plan.fingerprint[:12] in review_values["Pilot calibration"]
    review_html = review.report_path.read_text(encoding="utf-8")
    assert "Dataset-specific calibration plan" in review_html
    assert plan.fingerprint in review_html

    window.reference_pilot_subject_count_spin.setValue(3)
    application.processEvents()
    assert window._reference_calibration_plan is None
    assert window.export_reference_calibration_button.isEnabled() is False
    assert "rebuild" in window.reference_calibration_status.text()
    window.close()
    application.processEvents()


def test_desktop_exports_complete_calibration_bundle(
    monkeypatch,
    tmp_path,
) -> None:
    application, window, queued = _prepared_window(monkeypatch, tmp_path)
    from PySide6.QtCore import QUrl

    from diffeoforge.desktop import widgets

    window.analyze_reference_parameters_button.click()
    queued[0].run()
    application.processEvents()
    window.build_reference_calibration_button.click()
    application.processEvents()
    assert window._reference_calibration_plan is not None

    destination = tmp_path / "calibration export"
    destination.mkdir()
    opened: list[QUrl] = []
    monkeypatch.setattr(
        widgets.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(destination),
    )
    monkeypatch.setattr(
        widgets.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )
    window.export_reference_calibration_button.click()
    application.processEvents()

    assert (destination / "parameter-calibration-plan.json").is_file()
    assert (destination / "parameter-calibration-plan.html").is_file()
    assert (destination / "parameter-calibration-plan.sha256").is_file()
    assert (destination / "aligned-mesh-recommendation.json").is_file()
    assert window._reference_calibration_export is not None
    assert "Exported JSON, HTML" in window.reference_calibration_status.text()
    assert len(opened) == 1
    window.close()
    application.processEvents()


def test_desktop_binds_optional_biological_pilot_coverage(
    monkeypatch,
    tmp_path,
) -> None:
    application, window, queued = _prepared_window(monkeypatch, tmp_path)
    from diffeoforge.desktop import widgets

    window.analyze_reference_parameters_button.click()
    queued[0].run()
    application.processEvents()
    assert window._reference_recommendation is not None
    names = [
        item.filename for item in window._reference_recommendation.observations[1:4]
    ]
    declarations = tmp_path / "pilot-declarations.csv"
    declarations.write_text(
        "filename,stratum,is_extreme\n"
        f"{names[0]},stratum-a,true\n"
        f"{names[1]},stratum-b,false\n"
        f"{names[2]},stratum-b,false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        widgets.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(declarations), "CSV files (*.csv)"),
    )

    window.reference_pilot_subject_count_spin.setValue(3)
    window.load_reference_pilot_declarations_button.click()
    application.processEvents()
    assert window.reference_pilot_declarations_edit.text() == str(declarations)
    assert len(window._reference_pilot_subject_declarations) == 3
    window.build_reference_calibration_button.click()
    application.processEvents()

    plan = window._reference_calibration_plan
    assert plan is not None
    assert plan.version == "0.5"
    assert names[0] in {item.filename for item in plan.selected_pilot_subjects}
    assert "Researcher-declared pilot coverage" in window.reference_calibration_status.text()
    window.clear_reference_pilot_declarations_button.click()
    application.processEvents()
    assert window._reference_calibration_plan is None
    assert window.reference_pilot_declarations_edit.text() == ""

    window.close()
    application.processEvents()


def test_desktop_manual_picker_builds_hash_bound_plan_without_csv(monkeypatch, tmp_path):
    application, window, queued = _prepared_window(monkeypatch, tmp_path)
    picker = window.reference_pilot_subject_picker
    assert not picker.isEnabled()
    window.analyze_reference_parameters_button.click()
    queued[0].run()
    application.processEvents()
    assert picker.isEnabled()
    names = [item.filename for item in window._reference_recommendation.observations[1:]]
    assert picker.combo.count() == len(names)
    assert window._reference_recommendation.template_filename not in [
        picker.combo.itemText(i) for i in range(picker.combo.count())
    ]
    window.reference_pilot_subject_count_spin.setValue(2)
    for name in names[:3]:
        picker.combo.setCurrentText(name)
        picker.add_button.click()
    assert picker.selected_filenames == tuple(sorted(names[:3]))
    assert window.reference_pilot_subject_count_spin.value() == 3
    assert not picker.add_button.isEnabled()  # duplicate choice
    window.build_reference_calibration_button.click()
    plan = window._reference_calibration_plan
    assert plan is not None
    assert plan.required_subject_filenames == picker.selected_filenames
    assert window._reference_calibration_plan_matches_current_inputs()
    assert len(queued) == 1  # only geometry analysis, never a pilot/atlas
    from diffeoforge.config import load_config
    from diffeoforge.desktop.project_setup import create_project
    from diffeoforge.reference_calibration import reference_calibration_plan_from_provenance

    project = create_project(window._request())
    config = load_config(project.config_path)
    stored = config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"]
    reopened = reference_calibration_plan_from_provenance(stored)
    assert reopened.required_subject_filenames == plan.required_subject_filenames
    from diffeoforge.reference_calibration_study import (
        create_reference_calibration_study,
        load_reference_calibration_study,
    )

    study = create_reference_calibration_study(project.config_path, tmp_path / "manual-study")
    assert study.plan.required_subject_filenames == plan.required_subject_filenames
    assert load_reference_calibration_study(study.study_directory).plan == study.plan
    picker.selected_list.setCurrentRow(0)
    picker.remove_button.click()
    assert window._reference_calibration_plan is None
    assert not window.export_reference_calibration_button.isEnabled()
    assert window.reference_pilot_subject_count_spin.minimum() == 2
    window.close()
    application.processEvents()


def test_manual_picker_rejects_free_text_caps_and_resets_only_changed_cohort(monkeypatch, tmp_path):
    application, window, _queued = _prepared_window(monkeypatch, tmp_path)
    from diffeoforge.desktop.pilot_subject_picker import PilotSubjectPicker

    picker = PilotSubjectPicker(maximum=2)
    names = ["first.ply", "second.stl", "third.vtk"]
    changed = []
    picker.selectionChanged.connect(lambda: changed.append(True))
    picker.set_subjects(names, cohort_key=("cohort-a",))
    picker.combo.setCurrentText("made-up.stl")
    assert not picker.add_button.isEnabled()
    picker._add()
    assert not picker.selected_filenames
    for name in names:
        picker.combo.setCurrentText(name)
        picker.add_button.click()
    assert picker.selected_filenames == tuple(names[:2])
    assert len(changed) == 2
    assert "Limit: 2" in picker.hint.text()
    picker.set_subjects(names, cohort_key=("cohort-a",))
    assert picker.selected_filenames == tuple(names[:2])
    assert len(changed) == 2
    picker.set_subjects(names, cohort_key=("cohort-b",))
    assert picker.selected_filenames == ()
    assert len(changed) == 3
    assert "cohort changed" in picker.hint.text()
    picker.close()
    window.close()
    application.processEvents()


def test_reanalysis_preserves_manual_choice_but_disables_stale_picker(monkeypatch, tmp_path):
    application, window, queued = _prepared_window(monkeypatch, tmp_path)
    window.analyze_reference_parameters_button.click()
    queued[0].run()
    application.processEvents()
    picker = window.reference_pilot_subject_picker
    name = picker.combo.itemText(0)
    picker.combo.setCurrentText(name)
    picker.add_button.click()
    window.reference_surface_detail_combo.setCurrentIndex(
        window.reference_surface_detail_combo.findData("fine")
    )
    assert not picker.isEnabled()
    assert picker.selected_filenames == (name,)
    window.analyze_reference_parameters_button.click()
    queued[-1].run()
    application.processEvents()
    assert picker.isEnabled()
    assert picker.selected_filenames == (name,)
    window.build_reference_calibration_button.click()
    assert window._reference_calibration_plan.required_subject_filenames == (name,)
    window.close()
    application.processEvents()
