"""Pilot headings remain readable when a real dialog changes theme."""



def test_pilot_plain_content_has_contrast_after_light_dark_switch(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    from diffeoforge.desktop.appearance import Appearance, AppearanceController, _contrast
    from diffeoforge.desktop.reference_calibration_dialog import ReferenceCalibrationDialog
    from diffeoforge.desktop.widgets import _STYLE

    app = QApplication.instance() or QApplication([])
    main = QMainWindow()
    appearance = AppearanceController(main, _STYLE,
        QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat))
    monkeypatch.setattr(ReferenceCalibrationDialog, '_render', lambda *_a, **_kw: None)
    window = ReferenceCalibrationDialog(tmp_path, parent=main)
    label = QLabel('Check the common model', window.content)
    window.content_layout.addWidget(label)
    window.resize(1000, 750)
    window.show()
    try:
        for mode in ('light', 'dark', 'light'):
            appearance.apply(Appearance(mode))
            for _ in range(3):
                app.processEvents()
            shot = window.grab().toImage()
            position = window.content.mapTo(window, QPoint(2, 2))
            background = shot.pixelColor(position)
            text = label.palette().color(label.foregroundRole())
            assert background.isValid() and text.isValid()
            assert _contrast(text, background) >= 4.5, (mode, text.name(), background.name())
            assert (background.lightness() < 100) == (mode == 'dark')
    finally:
        window.close()
        main.close()
        app.processEvents()


def test_comparison_detail_checkbox_paints_all_dark_states(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import (
        QApplication,
        QMainWindow,
        QPushButton,
        QStyle,
        QStyleOptionButton,
        QVBoxLayout,
        QWidget,
    )

    from diffeoforge.desktop.appearance import (
        Appearance,
        AppearanceController,
        _contrast,
    )
    from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
    from diffeoforge.desktop.widgets import _STYLE

    app = QApplication.instance() or QApplication([])
    main = QMainWindow()
    controls = QWidget()
    layout = QVBoxLayout(controls)
    other_control = QPushButton("Another control")
    layout.addWidget(other_control)
    canvas = CalibrationComparisonCanvas3D()
    layout.addWidget(canvas)
    main.setCentralWidget(controls)
    theme = AppearanceController(main, _STYLE, QSettings(
        str(tmp_path / "appearance.ini"), QSettings.Format.IniFormat
    ))
    theme.apply(Appearance("dark"))
    main.resize(640, 500)
    main.show()
    main.activateWindow()
    check = canvas.original_detail

    def colors():
        app.processEvents()
        option = QStyleOptionButton()
        check.initStyleOption(option)
        indicator = check.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, check
        )
        image = check.grab().toImage()
        background = image.pixelColor(QPoint(check.width() - 6, check.height() // 2))
        assert _contrast(check.palette().color(check.foregroundRole()), background) >= 4.5
        return (
            image.pixelColor(indicator.center()),
            image.pixelColor(QPoint(check.width() // 2, 0)),
            background,
        )

    try:
        check.setEnabled(True)
        other_control.setFocus()
        unchecked, border, background = colors()
        assert unchecked == background
        assert _contrast(border, background) >= 3.0
        assert check.width() < canvas.width()
        check.setChecked(True)
        checked, _, _ = colors()
        assert _contrast(checked, unchecked) >= 3.0
        check.setFocus()
        _, focus_border, _ = colors()
        assert check.hasFocus() and focus_border != border
        assert _contrast(focus_border, background) >= 3.0
        check.setEnabled(False)
        disabled_checked, _, _ = colors()
        assert _contrast(disabled_checked, unchecked) >= 3.0
        check.setChecked(False)
        disabled_unchecked, disabled_border, _ = colors()
        assert disabled_unchecked == unchecked
        assert _contrast(disabled_border, disabled_unchecked) >= 3.0
    finally:
        main.close()
        app.processEvents()
