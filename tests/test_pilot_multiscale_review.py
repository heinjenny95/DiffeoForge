"""The fixed actions name the exact stage/result instead of an earlier repair fit."""

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "mode,action",
    [
        ("broad_detail", "adaptive_common_continue"),
        ("detail_pending", "adaptive_multiscale_detail"),
    ],
)
def test_prepare_action_is_visible_without_scrolling_and_never_opens_an_old_fit(
    tmp_path, monkeypatch, mode, action
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from diffeoforge.desktop.pilot_common_model import pin_recovery

    app = QApplication.instance() or QApplication([])
    button = QPushButton()
    button.hide()
    window = SimpleNamespace(next_step_button=button, _guided_footer_action=None)
    snapshot = SimpleNamespace(
        study_directory=tmp_path, candidates=[SimpleNamespace(candidate_id="guided-varifold")]
    )
    choice = dict(mode=mode, available=True, label="Prepare this declared stage")
    pin_recovery(window, snapshot, choice)
    assert button.isEnabled() and not button.isHidden()
    assert button.text() == choice["label"]
    assert window._guided_footer_action == (tmp_path, action, "guided-varifold")
    button.deleteLater()
    app.processEvents()


def test_current_detail_review_does_not_point_to_the_accepted_individual_or_capture(tmp_path):
    from diffeoforge.desktop.pilot_review_target import choose

    ref = dict(directory=str(tmp_path / "detail"), candidate_id="guided-varifold", target="one.vtk")
    snapshot = SimpleNamespace(study_directory=tmp_path)
    guidance = dict(
        common_recovery=dict(
            mode="review", reference=ref, review_reference=ref, target="one.vtk", test_number=9
        )
    )
    target = choose(snapshot, guidance, {})
    assert target["kind"] == "common" and target["pending"]
    assert target["reference"] == ref
    assert "common-model" in target["label"] and "one.vtk" in target["label"]
