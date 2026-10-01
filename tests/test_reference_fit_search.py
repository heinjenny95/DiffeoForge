import numpy as np
import pytest
from test_reference_adaptive_calibration import seed_stub
from test_reference_calibration_study import _review_ready_stage

import diffeoforge.reference_adaptive_calibration as adaptive
import diffeoforge.reference_calibration_study as study
import diffeoforge.reference_fit_search as search
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import TriangleMesh, sha256_file


def test_point_to_triangle_distance_ignores_vertex_density():
    vertices = [[0, 0, 0], [10, 0, 0], [0, 10, 0]]
    points = [[2, 2, 0], [2, 2, 1]]
    distances = search.distances_to_surface(points, vertices, [[0, 1, 2]])
    np.testing.assert_allclose(distances, [0, 1], atol=1e-6)


def test_area_sampling_covers_large_faces_not_many_tiny_vertices():
    surface = TriangleMesh(((0, 0, 0), (10, 0, 0), (0, 10, 0)), ((0, 1, 2),))
    fit = search.surface_fit(surface, surface)
    assert fit["p99"] < 1e-6
    points = search.surface_samples(surface.vertices, surface.triangles)
    np.testing.assert_array_equal(
        points, search.surface_samples(surface.vertices, surface.triangles)
    )
    assert points[:, 0].mean() == pytest.approx(10 / 3, abs=0.15)


@pytest.mark.parametrize("bounds", [(0, 4, 0, 4, 0, 4), (0, 4, 0, 0.1, 0, 2)])
def test_grid_capacity_is_bounded_and_covers_template(bounds):
    controls, spacing = search.control_grid(bounds)
    assert 64 <= len(controls) <= 200
    assert spacing > 0
    np.testing.assert_allclose(controls.min(axis=0), np.array(bounds)[::2])
    np.testing.assert_allclose(controls.max(axis=0), np.array(bounds)[1::2])


def test_search_preserves_originals_binds_working_targets_and_rejects_tampering(
    tmp_path, monkeypatch
):
    _, original = _review_ready_stage(tmp_path, monkeypatch)
    before = sha256_file(original.study_directory / "events.jsonl")
    created = search.create_search(original.study_directory, 60)
    manifest = study._verify_manifest(created.study_directory)
    assert len(created.candidates) == 4
    assert sha256_file(original.study_directory / "events.jsonl") == before
    for candidate in created.candidates:
        config = load_config(candidate.config_path)
        inputs = validate_input_paths(config, candidate.config_path)
        assert len(inputs.subjects) == original.plan.pilot_subject_count
        assert "working-targets" in str(inputs.input_directory)
        assert config["optimization"]["max_iterations"] == 40
        assert config["optimization"]["freeze_template"] is True
        assert config["optimization"]["freeze_control_points"] is True
        assert (
            inputs.template.read_bytes()
            == (
                original.study_directory
                / study._verify_manifest(original.study_directory)["inputs"]["template"]["copy"]
            ).read_bytes()
        )
    target = created.study_directory / manifest["fit_search"]["working_targets"][0]["copy"]
    target.write_text("changed")
    with pytest.raises(ValueError, match="working geometry"):
        study.load_reference_calibration_study(created.study_directory)


def test_complete_search_refines_then_confirms_original_targets_without_qc(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    monkeypatch.setattr(adaptive, "bind_learned_seed", seed_stub)

    def measured(root, manifest, candidate, run):
        originals = {
            r["filename"]: dict(p95=0.1, p99=0.2, mean=0.05, diagonal=1)
            for r in manifest["inputs"]["subjects"]
        }
        return dict(
            original_surface_fit=originals,
            fit_scope="full_targets"
            if candidate.candidate_id in manifest["fit_search"]["confirmation_ids"]
            else "screening",
        )

    monkeypatch.setattr(search, "measure_original_fit", measured)
    result = search.run_fit_search(runner)
    assert len(result.candidates) == 6
    assert not result.visual_reviews and not result.selected_candidate_ids
    assert len([c for c in result.candidates if c.metrics["fit_scope"] == "full_targets"]) == 1
    full = result.candidates[-1]
    config = load_config(full.config_path)
    assert "working-targets" not in config["input"]["directory"]
    assert config["model"]["deformation"].get("initial_momenta")
    assert config["optimization"]["freeze_template"] is False
    assert config["optimization"]["freeze_control_points"] is False
    evidence = study._stage_evidence(result, {})
    assert not any(e.converged for e in evidence[:-1])
    attempts = [c.attempts for c in result.candidates]
    reopened = search.run_fit_search(runner)
    assert [c.attempts for c in reopened.candidates] == attempts
    assert original.study_directory != reopened.study_directory


def test_reserved_exhausted_budget_does_not_launch_an_engine(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    created = search.create_search(original.study_directory, 15)
    runner.study_directory = created.study_directory
    study._write_json(
        created.study_directory / "fit-search-budget.json",
        dict(limit_seconds=900, spent_seconds=900),
        overwrite=False,
    )
    monkeypatch.setattr(runner, "run_current_stage", lambda **k: pytest.fail("Engine launched"))
    with pytest.raises(ValueError, match="budget is exhausted"):
        search.run_fit_search(runner)


def test_time_limit_requests_cancellation_without_launching_more_work(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    created = search.create_search(original.study_directory, 15)
    runner.study_directory = created.study_directory

    class Timer:
        def __init__(self, seconds, callback):
            self.callback = callback

        def start(self):
            self.callback()

        def cancel(self):
            pass

    monkeypatch.setattr(search.threading, "Timer", Timer)
    monkeypatch.setattr(
        runner, "run_current_stage", lambda **k: pytest.fail("Started after timeout")
    )
    result = search.run_fit_search(runner)
    assert runner._cancel_requested
    assert all(c.attempts == 0 for c in result.candidates)
    assert not (created.study_directory / "fit-search-active.lock").exists()


def test_tail_ranking_cannot_hide_one_bad_specimen_in_a_pooled_mean():
    from types import SimpleNamespace

    def candidate(p99):
        return SimpleNamespace(
            metrics=dict(
                invalid_face_count=0,
                original_surface_fit={
                    n: dict(p99=value, p95=value / 2, mean=0.01, diagonal=1)
                    for n, value in enumerate(p99)
                },
            )
        )

    assert search.fit_key(candidate([0.1, 0.1])) < search.fit_key(candidate([0.01, 0.5]))


def test_preparation_exhaustion_is_saved_without_launching(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    created = search.create_search(original.study_directory, 15)
    runner.study_directory = created.study_directory
    moments = iter((0, 901))
    monkeypatch.setattr(search.time, "monotonic", lambda: next(moments, 901))
    monkeypatch.setattr(runner, "run_current_stage", lambda **k: pytest.fail("Engine launched"))
    with pytest.raises(ValueError, match="budget is exhausted"):
        search.run_fit_search(runner)
    budget = study._read_json(created.study_directory / "fit-search-budget.json", "budget")
    assert budget == dict(limit_seconds=900, spent_seconds=900)


def test_callback_failure_releases_lock_and_reports_no_full_confirmation(tmp_path, monkeypatch):
    runner, original = _review_ready_stage(tmp_path, monkeypatch)
    created = search.create_search(original.study_directory, 15)
    runner.study_directory = created.study_directory
    events = []

    def callback(event):
        events.append(event)
        if event["event"] == "fit_search_started":
            raise RuntimeError("Observer failed")

    monkeypatch.setattr(runner, "run_current_stage", lambda **k: pytest.fail("Engine launched"))
    with pytest.raises(RuntimeError, match="Observer failed"):
        search.run_fit_search(runner, event_callback=callback)
    assert not (created.study_directory / "fit-search-active.lock").exists()
    assert events[-1]["event"] == "fit_search_stopped"
    assert not events[-1]["full_target_completed"]
