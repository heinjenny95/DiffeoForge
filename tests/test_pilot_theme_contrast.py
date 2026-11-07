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
