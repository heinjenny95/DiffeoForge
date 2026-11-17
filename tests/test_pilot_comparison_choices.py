"""A numerical trade-off must not imply a method choice through button styling."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QBoxLayout, QWidget
from test_desktop_guided_fit_direction import _direction

from diffeoforge.desktop import guided_fit_direction as viewer
from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair
from diffeoforge.mesh import sha256_file


@pytest.mark.parametrize("tradeoff,preference,emphasized", [
    (True, None, False), (False, None, False),
    (True, "alternative", False), (False, "alternative", True),
])
@pytest.mark.parametrize("same_method", [False, True])
def test_both_named_choices_stay_visible_and_resize_without_clipping(
    tmp_path, monkeypatch, tradeoff, preference, emphasized, same_method,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    example = Path(__file__).resolve().parents[1] / "examples/synthetic/meshes"
    original, left, right = (example / name for name in (
        "subject-01.vtk", "template.vtk", "subject-02.vtk"))
    pairs = tuple(CalibrationQcPair(name, name, original, fit, True,
        sha256_file(original), sha256_file(fit))
        for name, fit in (("left", left), ("right", right)))
    direction = _direction(original.name, tmp_path, tmp_path / "alternative")
    direction.update(tradeoff=tradeoff, metric_preference=preference)
    method = "Current" if same_method else "Varifold"
    labels = ("Current · Test 6 · 405 CP", f"{method} · Test 4 · 270 CP")
    dialog = viewer._ComparisonDialog(window, tmp_path, direction, (pairs, labels))
    dialog.show()
    try:
        for width in (1024, 680, 1180):
            dialog.resize(width, 760)
            for _ in range(8):
                app.processEvents()
            assert dialog.keep_left.isVisible() and dialog.work.isVisible()
            assert dialog.keep_left.text() == f"Work from {labels[0]}…"
            assert dialog.work.text() == f"Work from {labels[1]}…"
            assert dialog.keep_left.objectName() != "primary"
            assert (dialog.work.objectName() == "primary") is emphasized
            for button in (dialog.keep_left, dialog.work):
                assert button.width() >= button.sizeHint().width()
                assert button.x() >= 0 and button.geometry().right() < dialog.width()
            if width == 680:
                assert dialog.fit_actions.direction() == QBoxLayout.Direction.TopToBottom
                assert dialog.keep_left.geometry().bottom() < dialog.work.geometry().top()
    finally:
        dialog.close()
        app.processEvents()


def test_lower_whole_shape_distances_do_not_hide_a_local_regression(tmp_path, monkeypatch):
    from test_guided_fit_direction import _complete
    from test_pilot_control_capacity import origin
    from test_pilot_region_feedback import reject

    from diffeoforge import guided_fit_direction as direction
    from diffeoforge import guided_strategy
    from diffeoforge import reference_guided_pilot as guided

    snapshot = guided.prepare(origin(tmp_path, "extreme").study_directory)
    snapshot = _complete(snapshot, monkeypatch, {"guided-current": .27, "guided-varifold": .23})
    snapshot = reject(reject(snapshot, "guided-current"), "guided-varifold")
    mixed = [dict(cell=[0, 0, 1], change="improved", current_p95=6.4, alternative_p95=1.6),
             dict(cell=[0, 0, 3], change="regressed", current_p95=1.1, alternative_p95=2.9)]
    monkeypatch.setattr(direction, "_regions", lambda *_: mixed)
    monkeypatch.setattr(direction, "_has_local_regression", lambda *_: True)
    result = direction.preview(snapshot, guided_strategy.state(snapshot))
    assert result["alternative_p95"] < result["current_p95"]
    assert result["tradeoff"] is True and result["metric_preference"] is None
    assert "local area is farther away" in result["reason"]


def test_local_loss_veto_covers_bins_omitted_from_the_two_display_markers():
    from diffeoforge import guided_fit_direction as direction

    current = dict(diagonal=1., repeats=[dict(regions={
        "0:1": dict(count=12, tail=.2), "1:1": dict(count=12, tail=.1),
    })] * 2)
    alternative = dict(repeats=[dict(regions={
        "0:1": dict(count=12, tail=.1), "1:1": dict(count=12, tail=.2),
    })] * 2)
    # Both directions occupy the same display cell, which has only one marker.
    assert not any(row["change"] == "regressed"
                   for row in direction._regions(current, alternative))
    assert direction._has_local_regression(current, alternative)
