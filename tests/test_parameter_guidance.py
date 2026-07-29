from __future__ import annotations

from html import escape

import pytest

from diffeoforge.desktop.parameter_guidance import (
    DEFORMETRICA_PARAMETER_GUIDANCE,
)

EXPECTED_GUIDANCE_KEYS = {
    "recommendation_mode",
    "surface_detail",
    "deformation_scale",
    "attachment_ratio",
    "deformation_ratio",
    "control_spacing_ratio",
    "noise_ratio",
    "maximum_iterations",
    "initial_step_size",
    "convergence_tolerance",
    "attachment_type",
    "time_points",
    "integration",
    "line_search_limit",
    "save_interval",
    "log_interval",
    "step_size_scaling",
    "sobolev_gradient",
    "sobolev_width_ratio",
    "template_update",
    "control_point_update",
    "compute_acceleration",
    "cpu_threads",
    "random_seed",
}


def test_all_deformetrica_guidance_has_explanation_and_example() -> None:
    assert set(DEFORMETRICA_PARAMETER_GUIDANCE) == EXPECTED_GUIDANCE_KEYS
    for key, guidance in DEFORMETRICA_PARAMETER_GUIDANCE.items():
        assert len(guidance.summary) >= 40, key
        assert len(guidance.sections) >= 3, key
        headings = {heading for heading, _text in guidance.sections}
        assert "Example" in headings, key
        assert all(text.strip() for _heading, text in guidance.sections), key
        rendered = guidance.to_html()
        assert escape(guidance.summary) in rendered
        assert "<b>Example:</b>" in rendered


def test_each_deformetrica_control_has_an_expandable_english_guide(
    monkeypatch,
) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.project_setup import DesktopEngine
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-parameter-guide-test"]
    )
    window = DiffeoForgeWindow()
    window.engine_combo.setCurrentIndex(
        window.engine_combo.findData(DesktopEngine.DEFORMETRICA_REFERENCE)
    )
    window.page_stack.setCurrentIndex(1)
    window.show()
    window.resize(900, 650)
    application.processEvents()

    assert set(window.reference_parameter_help_panels) == EXPECTED_GUIDANCE_KEYS
    assert window.reference_acceleration_combo.currentData() == "auto"
    for key, help_panel in window.reference_parameter_help_panels.items():
        assert help_panel.panel.isHidden() is True, key
        assert help_panel.toggle_button.text() == "+ Parameter guide", key
        assert help_panel.toggle_button.accessibleName().startswith("Explain "), key
        assert "Example:" in help_panel.text_browser.toPlainText(), key

    attachment_help = window.reference_parameter_help_panels["surface_detail"]
    attachment_help.toggle_button.click()
    application.processEvents()
    assert attachment_help.panel.isHidden() is False
    assert attachment_help.toggle_button.text() == "- Hide parameter guide"
    assert "Fine matching:" in attachment_help.text_browser.toPlainText()
    assert "Coarse matching:" in attachment_help.text_browser.toPlainText()
    assert "does not control how far a deformation spreads" in (
        attachment_help.text_browser.toPlainText()
    )
    assert (
        attachment_help.text_browser.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    attachment_help.text_browser.setFixedHeight(60)
    attachment_help.text_browser.resize(320, 60)
    application.processEvents()
    assert attachment_help.text_browser.verticalScrollBar().maximum() > 0

    attachment_help.toggle_button.click()
    application.processEvents()
    assert attachment_help.panel.isHidden() is True

    distinction = window.reference_scale_difference_label
    assert distinction.objectName() == "conceptDifference"
    assert "two independent questions" in distinction.text()
    assert "What should DiffeoForge notice?" in distinction.text()
    assert "How far should one adjustment spread?" in distinction.text()
    assert "They do not have to match." in distinction.text()
    assert window.reference_surface_detail_combo.itemText(0) == (
        "Notice small ridges, pits, and edges (fine)"
    )
    assert window.reference_deformation_scale_combo.itemText(0) == (
        "Keep changes confined to small regions (local)"
    )

    deformation_help = window.reference_parameter_help_panels["deformation_scale"]
    deformation_help.toggle_button.click()
    application.processEvents()
    assert "does not control which surface details are noticed" in (
        deformation_help.text_browser.toPlainText()
    )

    window.close()
    application.processEvents()
