from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _prepared_window(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
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
