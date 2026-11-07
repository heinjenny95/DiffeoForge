"""The accepted-field contrast is bounded and keeps review separate."""

from types import SimpleNamespace

import pytest

from diffeoforge import guided_feedback, pilot_common_diagnosis
from diffeoforge import pilot_common_warm_start as warm


@pytest.mark.parametrize(("history_kind", "review", "losses", "warnings", "mode", "kind"), [
    (None, None, [], [], "accepted_warm", "warm"),
    ("warm", None, [], [], "review", "warm"),
    ("warm", True, [], [], "approved", "warm"),
    ("warm", False, [{"region": "mark:0"}], [], "accepted_warm", "detail"),
    ("warm", False, [], [], "stalled", "warm"),
    ("warm", False, [{"region": "mark:0"}], ["invalid"], "stalled", "warm"),
    ("detail", False, [{"region": "mark:0"}], [], "stalled", "warm"),
    ("detail", True, [], [], "adopt", "warm"),
])
def test_choose_once_from_the_saved_accepted_field(
        monkeypatch, history_kind, review, losses, warnings, mode, kind):
    candidate = SimpleNamespace(candidate_id="varifold", status="completed")
    prior = SimpleNamespace(candidates=[candidate],
                            visual_reviews={} if review is None else {"varifold": review})
    monkeypatch.setattr(warm, "trials", lambda *_: [(prior, history_kind)] if history_kind else [])
    monkeypatch.setattr(warm, "review_event", lambda *_: {
        "approved": review, "event_hash": "bound-rejection"})
    monkeypatch.setattr(guided_feedback, "reference", lambda *_: {"directory": "common"})
    monkeypatch.setattr(pilot_common_diagnosis, "diagnose", lambda *_: {
        "local_losses": losses, "warnings": warnings})
    seed = {"directory": "accepted"}
    shared = {"attachment_kernel_width": .1, "deformation_kernel_width": .4,
              "initial_control_point_spacing": .4, "noise_std": .025}
    protocol = {"reference": {"values": shared}}
    choice = warm.preview(None, {"protocol": protocol}, "target.vtk", seed)
    assert (choice["mode"], choice["kind"]) == (mode, kind)
    if mode == "accepted_warm":
        plan = warm.apply({"strategy": {}}, choice, protocol)
        marker = plan["strategy"]["common_basis_step"]
        assert marker["reference"] is seed
        assert marker["additional_iterations"] == 120
        assert marker["approval_transferred"] is False
        expected = dict(shared)
        if kind == "detail":
            expected["attachment_kernel_width"] *= .9
            assert marker["review_hash"] == "bound-rejection"
        assert plan["values"] == expected
        assert shared["attachment_kernel_width"] == .1
