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
    from PySide6.QtWidgets import QApplication

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(
        ["diffeoforge-parameter-guide-test"]
    )
    window = DiffeoForgeWindow()

    assert set(window.reference_parameter_help_panels) == EXPECTED_GUIDANCE_KEYS
    for key, help_panel in window.reference_parameter_help_panels.items():
        assert help_panel.panel.isHidden() is True, key
        assert help_panel.toggle_button.text() == "+ Parameter guide", key
        assert help_panel.toggle_button.accessibleName().startswith("Explain "), key
        assert "Example:" in help_panel.text_label.text(), key

    attachment_help = window.reference_parameter_help_panels["attachment_ratio"]
    attachment_help.toggle_button.click()
    application.processEvents()
    assert attachment_help.panel.isHidden() is False
    assert attachment_help.toggle_button.text() == "- Hide parameter guide"
    assert "Increase:" in attachment_help.text_label.text()
    assert "Decrease:" in attachment_help.text_label.text()

    attachment_help.toggle_button.click()
    application.processEvents()
    assert attachment_help.panel.isHidden() is True

    window.close()
    application.processEvents()
