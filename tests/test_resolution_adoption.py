import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from test_pilot_completion import _approve_preview
from test_reference_integration_check import _fourth

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_completion as completion
from diffeoforge import reference_resolution_adoption as adoption
from diffeoforge.config import load_config


def _setup(tmp_path, monkeypatch, *, coarse_mismatch=False):
    runner, _ = _fourth(tmp_path, monkeypatch)
    collect = study.collect_reference_calibration_run_metrics
    monkeypatch.setattr(
        study,
        "collect_reference_calibration_run_metrics",
        lambda run: replace(
            collect(run),
            converged=False,
            optimizer_stop_signal="maximum_iterations",
            final_iteration=50,
            maximum_iterations=50,
        ),
    )
    done = runner.run_current_stage()
    identifier = done.candidates[0].candidate_id
    base_count = int(
        load_config(done.candidates[0].config_path)["model"]["deformation"]["timepoints"]
    )
    template = next((done.study_directory / "inputs/template").glob("*.vtk"))
    labels = sorted(s.filename for s in done.plan.selected_pilot_subjects)
    monkeypatch.setattr(
        completion.legacy, "_reconstructions", lambda *a: (None, {n: template for n in labels})
    )
    calls = []

    def shoot(config, root, seed, destination, count, **kwargs):
        calls.append(count)
        output = destination / "output"
        output.mkdir(parents=True)
        paths = {}
        for index, label in enumerate(seed["subject_labels"]):
            prefix = "Shooting" if len(labels) == 1 else f"Shooting_{index}"
            path = output / (prefix + "__endpoint.vtk")
            if coarse_mismatch and count != base_count:
                from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata

                mesh = read_vtk_polydata(template)
                write_vtk_polydata(
                    path, [(x + 0.1, y, z) for x, y, z in mesh.vertices], mesh.triangles
                )
            else:
                shutil.copyfile(template, path)
            (output / (prefix + "__grid.json")).write_text(
                json.dumps(
                    dict(
                        root=prefix,
                        timepoints=count,
                        tmin=0,
                        tmax=1,
                    )
                )
            )
            paths[label] = path
        return paths, {}

    monkeypatch.setattr(completion, "shoot", shoot)
    monkeypatch.setattr(adoption, "shoot", shoot)
    monkeypatch.setattr(
        runner, "run_current_stage", lambda **k: pytest.fail("Adoption must never run an optimizer")
    )
    return runner, completion.run(runner, candidate_id=identifier), identifier, calls


def test_adoption_reuses_two_grids_binds_new_qc_and_finishes_only_provisionally(
    tmp_path, monkeypatch
):
    runner, checked, source_id, calls = _setup(tmp_path, monkeypatch, coarse_mismatch=True)
    n = calls[0]
    assert calls == [n, 2 * n - 1, 4 * n - 3]
    _approve_preview(checked, source_id)
    original = {p: p.read_bytes() for p in checked.study_directory.rglob("*") if p.is_file()}
    adopted = adoption.run(runner, candidate_id=source_id)
    assert calls == [n, 2 * n - 1, 4 * n - 3, 8 * n - 7]
    candidate = adopted.candidates[-1]
    assert candidate.candidate_id.startswith("resolution-")
    assert candidate.candidate_id not in adopted.visual_reviews
    assert load_config(candidate.config_path)["model"]["deformation"]["timepoints"] == 2 * n - 1
    assert candidate.metrics["final_iteration"] is None
    assert candidate.metrics["source_optimizer"]["optimizer_stop_signal"] == "maximum_iterations"
    assert completion.provisional_available(adopted, candidate.candidate_id)
    assert completion.evidence(adopted)[candidate.candidate_id]["failures"] == []
    for path, value in original.items():
        if path.name == study.STUDY_EVENTS:
            assert path.read_bytes().startswith(value)
        else:
            assert path.read_bytes() == value
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs

    pairs = collect_calibration_qc_pairs(adopted.study_directory, candidate)
    assert sum(p.required for p in pairs) == adopted.plan.pilot_subject_count
    assert all(p.reconstruction_path.is_relative_to(candidate.run_directory) for p in pairs)
    with pytest.raises(ValueError, match="Review"):
        completion.finish(adopted.study_directory, candidate.candidate_id)
    # Mock native seed extraction only for synthetic fixtures; production resolves
    # the actual source optimizer run and verifies its fields, not the evaluation.
    from test_reference_adaptive_calibration import seed_stub

    from diffeoforge import reference_adaptive_calibration as adaptive

    monkeypatch.setattr(adaptive, "bind_learned_seed", seed_stub)
    _approve_preview(adopted, candidate.candidate_id)
    final, _ = completion.finish(adopted.study_directory, candidate.candidate_id)
    decision = study.load_reference_calibration_report(final.study_directory)[
        "final_pilot_completion"
    ]
    assert decision["provisional"] and not decision["converged"]
    assert decision["fixed_state_resolution"]["optimizer_executed"] is False
    assert load_config(final.final_config_path)["model"]["deformation"]["timepoints"] == 2 * n - 1
    assert study.load_reference_calibration_study(final.study_directory).status == "completed"


@pytest.mark.parametrize("artifact", ["endpoint", "seed", "inventory", "config"])
def test_adopted_candidate_rejects_changed_bytes_on_reopen(tmp_path, monkeypatch, artifact):
    runner, _, source, _ = _setup(tmp_path, monkeypatch)
    done = adoption.run(runner, candidate_id=source)
    candidate = done.candidates[-1]
    path = {
        "endpoint": next((candidate.run_directory / "output").glob("*__Reconstruction__*")),
        "inventory": candidate.run_directory / "output-inventory.json",
        "config": candidate.config_path,
        "seed": candidate.config_path.parent / "adaptive-seed/template.vtk",
    }[artifact]
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(ValueError, match="changed"):
        study.load_reference_calibration_study(done.study_directory)


def test_cancel_missing_grid_keeps_original_and_does_not_register_candidate(tmp_path, monkeypatch):
    runner, checked, source, calls = _setup(tmp_path, monkeypatch)

    def cancel(*a, **k):
        raise InterruptedError("cancelled")

    monkeypatch.setattr(adoption, "shoot", cancel)
    with pytest.raises(InterruptedError):
        adoption.run(runner, candidate_id=source)
    done = study.load_reference_calibration_study(checked.study_directory)
    assert done.candidates == checked.candidates
    assert not adoption.records(study._load_events(done.study_directory))
    assert len(calls) == 3


def test_adoption_action_uses_selected_finer_evaluation_without_refit():
    from diffeoforge.desktop.reference_calibration_presentation import final_stage_next_step

    step = final_stage_next_step(
        selected=True,
        approved=True,
        reasons=("integration check differs for specimen",),
        timepoints=37,
        finer_evaluation=73,
    )
    assert step.action == "adopt"
    assert step.label == "Use 73 time steps (no refit)"
    assert (
        final_stage_next_step(selected=True, approved=False, reasons=(), finer_evaluation=73).action
        == "review"
    )


def test_one_failing_specimen_blocks_finer_pair_and_missing_grid_finish(tmp_path, monkeypatch):
    runner, checked, source, calls = _setup(tmp_path, monkeypatch)
    evidence = completion.evidence(checked)
    changed = json.loads(json.dumps(evidence))
    pair = f"{calls[1]}->{calls[2]}"
    first = next(iter(changed[source]["receipt"]["integration"][pair].values()))
    first["maximum"] = 0.1
    assert adoption.available(checked, source, checked=changed) is None
    movement = adoption.movement
    missing = 8 * calls[0] - 7
    monkeypatch.setattr(
        adoption,
        "movement",
        lambda a, b, scale: (
            dict(rms=0.1, p95=0.1, maximum=0.1)
            if f"/{missing}/" in Path(b).as_posix()
            else movement(a, b, scale)
        ),
    )
    done = adoption.run(runner, candidate_id=source)
    candidate = done.candidates[-1]
    assert completion.evidence(done)[candidate.candidate_id]["failures"]
    assert not completion.provisional_available(done, candidate.candidate_id)
    with pytest.raises(ValueError, match="integration evidence"):
        completion.finish(done.study_directory, candidate.candidate_id)
