"""Later working-history annotations must survive reopening an older common field."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import pilot_common_diagnosis as diagnosis


@pytest.mark.parametrize(
    "state",
    [
        "later",
        "clear",
        "absent",
        "other_target",
        "other_origin",
        "changed_history",
        "ancestor",
        "other_id",
        "current_newer",
        "current_clear",
    ],
)
def test_working_context_marks_are_compared_on_every_saved_field(tmp_path, monkeypatch, state):
    from diffeoforge import guided_feedback, mesh
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided

    target = "shape.vtk"
    identifier = "fit"
    accepted_ref = dict(
        directory=str(tmp_path / "accepted"),
        candidate_id=identifier,
        target=target,
        manifest_sha256="accepted-hash",
        method="varifold",
    )
    current_ref = dict(
        accepted_ref, directory=str(tmp_path / "current"), manifest_sha256="current-hash"
    )
    previous_ref = dict(current_ref, directory=str(tmp_path / "previous"))
    old = [dict(old="earlier-mark")]
    newer = [dict(new="missing-projection"), dict(new="preserve-good-tooth")]
    later_id = "different-fit" if state == "other_id" else identifier

    def snap(name, *, target_name=target, origin="cohort", history=(), candidate_id=identifier):
        info = dict(
            target=target_name,
            origin=str(tmp_path / origin),
            history=list(history),
            screen_trials_spent=1,
        )
        return SimpleNamespace(
            study_directory=tmp_path / name,
            info=info,
            candidates=[SimpleNamespace(candidate_id=candidate_id)],
            visual_reviews={candidate_id: False},
            region_edits={},
            problem_regions={},
            attachment_comparison=dict(guided=info, methods={candidate_id: "varifold"}),
        )

    accepted = snap("accepted")
    current = snap("current")
    later = snap(
        "later",
        target_name="other.vtk" if state == "other_target" else target,
        origin="elsewhere" if state == "other_origin" else "cohort",
        candidate_id=later_id,
    )
    history = [
        dict(directory=str(current.study_directory), manifest_sha256="current-hash"),
        dict(
            directory=str(later.study_directory),
            manifest_sha256="wrong-hash" if state == "changed_history" else "later-hash",
        ),
    ]
    working = snap("working", history=[] if state == "ancestor" else history)
    current.region_edits = {
        identifier: dict(
            recorded_at=300 if state in {"current_newer", "current_clear"} else 100,
            cleared=[target] if state == "current_clear" else [],
        )
    }
    current.problem_regions = {
        identifier: {target: [] if state == "current_clear" else deepcopy(old)}
    }
    if state != "absent":
        later.region_edits = {
            later_id: dict(recorded_at=200, cleared=[target] if state == "clear" else [])
        }
        later.problem_regions = {later_id: {target: [] if state == "clear" else deepcopy(newer)}}
    # A different current form must not hide later same-original annotation history.
    working.info["target"] = "another-current-form.vtk"
    catalogue = {str(s.study_directory): s for s in (accepted, current, later, working)}
    monkeypatch.setattr(guided, "record", lambda s: s.info)
    monkeypatch.setattr(
        study, "load_reference_calibration_study", lambda p: catalogue[str(Path(p))]
    )
    monkeypatch.setattr(study, "_load_events", lambda p: ())
    digests = {current.study_directory: "current-hash", later.study_directory: "later-hash"}
    monkeypatch.setattr(mesh, "sha256_file", lambda p: digests[Path(p).parent])
    monkeypatch.setattr(
        guided_feedback, "verify_reference", lambda ref: catalogue[ref["directory"]]
    )
    monkeypatch.setattr(guided_feedback, "reference", lambda *a: accepted_ref)

    def region_state(parent, candidate, target_name, **kwargs):
        assert target_name == target
        if parent is current:
            return ([], True) if state == "current_clear" else (deepcopy(old), False)
        if parent is later:
            assert candidate == later_id
            assert kwargs.get("_search_history") is False
            return (
                ([], True)
                if state == "clear"
                else ([], False)
                if state == "absent"
                else (deepcopy(newer), False)
            )
        return [], False

    monkeypatch.setattr(guided_feedback, "region_state", region_state)
    calls = []

    def compare(first, second, *, regions=None):
        calls.append((second, deepcopy(regions)))
        row = dict(mean=0.01, p95=0.01, p99=0.01, regional_tail=0.01, regions={})
        surface = dict(diagonal=1.0, repeats=[dict(row), dict(row)], warnings=[])
        return dict(
            accepted=surface,
            current=surface,
            agreement=surface,
            accepted_local=False,
            accepted_controls=10,
            current_controls=10,
            objective_tail=[],
            original_sha256="same",
            template_sha256="same",
        )

    monkeypatch.setattr(diagnosis, "_compare", compare)
    value = dict(
        reviews=[
            dict(filename=target, directory=accepted_ref["directory"], candidate_id=identifier)
        ]
    )
    if state in {"other_origin", "changed_history"}:
        with pytest.raises(ValueError, match="annotation|history|cohort"):
            diagnosis.diagnose(working, value, current_ref, previous_ref)
        assert not calls
    else:
        diagnosis.diagnose(working, value, current_ref, previous_ref)
        expected = (
            []
            if state in {"clear", "current_clear"}
            else old
            if state in {"absent", "other_target", "ancestor", "current_newer"}
            else newer
        )
        assert calls == [(current_ref, expected), (previous_ref, expected)]
