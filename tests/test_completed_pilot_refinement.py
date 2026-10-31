from test_pilot_completion import _approve_preview, _checked
from test_reference_adaptive_calibration import seed_stub

from diffeoforge import reference_adaptive_calibration as adaptive
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_completion as completion


def test_completed_pilot_refinement_keeps_source_and_needs_fresh_review(tmp_path, monkeypatch):
    _, done, _, identifier = _checked(tmp_path, monkeypatch, capped=True)
    _approve_preview(done, identifier)
    final, _ = completion.finish(done.study_directory, identifier)
    before = {p: p.read_bytes() for p in final.study_directory.rglob("*") if p.is_file()}
    view = study.completed_pilot_refinement_view(final.study_directory)
    assert view.current_stage.order == 4 and view.status == "awaiting_review"
    assert len(view.selected_candidate_ids) == 3
    monkeypatch.setattr(adaptive, "bind_learned_seed", seed_stub)
    refined = adaptive.create_selected_continuation(
        final.study_directory,
        tmp_path / "refined",
        candidate_id=identifier,
        iterations=300,
        reopen_completed=True,
    )
    assert refined.current_stage.order == 4
    fresh = [c for c in refined.candidates if c.candidate_id.startswith("continue-")]
    assert len(fresh) == 1 and fresh[0].metrics is None
    assert fresh[0].candidate_id not in refined.visual_reviews
    assert len(refined.selected_candidate_ids) == 3
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"
    assert all(p.read_bytes() == value for p, value in before.items())
