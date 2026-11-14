"""Each reviewed joint form uses its own exact checked endpoint and hash."""

from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import cohort_field_quality, guided_feedback, regional_evaluation, result_report
from diffeoforge import reference_attachment_comparison as methods
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save


@pytest.mark.parametrize("passed", [True, False])
def test_joint_measurement_retains_each_checked_form_and_its_failed_quality_flag(
    tmp_path, monkeypatch, passed
):
    from diffeoforge import guided_refinement

    v, f = cube()
    run = tmp_path / "run"
    output = run / "output"
    output.mkdir(parents=True)
    inventory, subjects, qualities = [], [], {}
    for index, name in enumerate(("a.vtk", "b.vtk")):
        target, dense = tmp_path / name, tmp_path / ("dense-" + name)
        _save(target, np.asarray(v) + index * 3, f)
        _save(dense, np.asarray(v) + index * 3, f)
        native = output / ("D__Reconstruction__surface__subject_" + name + ".vtk")
        _save(native, np.asarray(v) + index * 3 + [1, 0, 0], f)
        subjects.append(dict(filename=name, copy=name, sha256=sha256_file(target)))
        inventory.append(dict(path=native.name))
        qualities[name] = dict(
            version=cohort_field_quality.VERSION,
            passed=passed,
            numerical_selection_suitable=passed,
            evaluation=dict(endpoint=dict(path=str(dense), sha256=sha256_file(dense))),
        )
    report = SimpleNamespace(manifest=dict(effective_config=dict(project={})), inventory=inventory)
    monkeypatch.setattr(result_report, "collect_run_report", lambda run: report)
    received = []
    monkeypatch.setattr(
        cohort_field_quality,
        "evaluate_and_measure",
        lambda *args, **kwargs: received.append(kwargs) or dict(subjects=qualities),
    )

    def parent(ref):
        baseline = dict(attachment_comparison=dict(subjects={ref["target"]: {}}))
        return SimpleNamespace(
            candidates=[SimpleNamespace(candidate_id="accepted", metrics=baseline)]
        )

    monkeypatch.setattr(guided_feedback, "verify_reference", parent)
    monkeypatch.setattr(guided_refinement, "geometry_guard", lambda a, b: dict(severe=False))
    manifest = dict(
        inputs=dict(subjects=subjects),
        attachment_comparison=dict(
            joint_initialization=dict(
                field_quality=cohort_field_quality.VERSION,
                references=[dict(target=s["filename"], candidate_id="accepted") for s in subjects],
            )
        ),
    )
    result = methods.measure(
        tmp_path,
        manifest,
        SimpleNamespace(candidate_id="joint"),
        run,
        cancelled=lambda: False,
        event_callback=None,
    )
    rows = result["attachment_comparison"]["subjects"]
    assert all(max(r["p95"] for r in row["repeats"]) < 1e-8 for row in rows.values())
    assert all(row["cohort_quality"] is qualities[name] for name, row in rows.items())
    candidate = SimpleNamespace(candidate_id="joint", metrics=result)
    assert regional_evaluation.endpoints(candidate) == {
        name: row["evaluation"]["endpoint"] for name, row in qualities.items()
    }
    assert guided_feedback.severe_regression(SimpleNamespace(candidates=[candidate]), "joint") is (
        not passed
    )
    assert callable(received[0]["cancelled"])


def test_unnamed_cohort_endpoint_cannot_substitute_an_arbitrary_form(tmp_path):
    files = [tmp_path / "a.vtk", tmp_path / "b.vtk"]
    for p in files:
        p.write_text(p.name)
    candidate = SimpleNamespace(
        metrics=dict(
            attachment_comparison=dict(
                subjects={
                    p.name: dict(
                        cohort_quality=dict(
                            evaluation=dict(endpoint=dict(path=str(p), sha256=sha256_file(p)))
                        )
                    )
                    for p in files
                }
            )
        )
    )
    with pytest.raises(ValueError, match="ambiguous"):
        regional_evaluation.endpoint(candidate)
    assert regional_evaluation.endpoint(candidate, subject="b.vtk")["path"] == str(files[1])
    files[0].write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        regional_evaluation.endpoints(candidate)


@pytest.mark.parametrize("complete", [True, False])
def test_viewer_requires_exact_checked_cohort_and_keeps_each_endpoint_hash(
    tmp_path, monkeypatch, complete
):
    from diffeoforge import config, reference_calibration_study
    from diffeoforge.desktop import reference_calibration_dialog as ui

    run = tmp_path / "run"
    output = run / "output"
    output.mkdir(parents=True)
    subjects = tmp_path / "inputs/subjects"
    subjects.mkdir(parents=True)
    template = tmp_path / "inputs/template"
    template.mkdir()
    (template / "template.vtk").write_text("original source")
    inventory, rows, inputs = [], {}, []
    for name in ("a.vtk", "b.vtk"):
        original = subjects / name
        original.write_text(name)
        inputs.append(dict(filename=name, sha256=sha256_file(original)))
        native = output / ("D__Reconstruction__surface__subject_" + name + ".vtk")
        native.write_text("native " + name)
        inventory.append(dict(path=native.name, sha256=sha256_file(native)))
        dense = tmp_path / ("checked-" + name)
        dense.write_text("checked " + name)
        if complete or name == "a.vtk":
            rows[name] = dict(
                cohort_quality=dict(
                    evaluation=dict(endpoint=dict(path=str(dense), sha256=sha256_file(dense)))
                )
            )
    atlas = output / "D__EstimatedParameters__Template_surface.vtk"
    atlas.write_text("estimated source")
    inventory.append(dict(path=atlas.name, sha256=sha256_file(atlas)))
    monkeypatch.setattr(ui, "calibration_candidate_run_directory", lambda _: run)
    monkeypatch.setattr(ui, "collect_run_report", lambda _: SimpleNamespace(inventory=inventory))
    monkeypatch.setattr(config, "load_config", lambda _: dict(model=dict(object_id="surface")))
    monkeypatch.setattr(
        reference_calibration_study,
        "_verify_manifest",
        lambda _: dict(inputs=dict(subjects=inputs, template=dict(sha256="0" * 64))),
    )
    candidate = SimpleNamespace(
        run_directory=str(run),
        config_path=tmp_path / "unused",
        metrics=dict(attachment_comparison=dict(subjects=rows)),
    )
    if not complete:
        with pytest.raises(ValueError, match="exact pilot cohort"):
            ui.collect_calibration_qc_pairs(tmp_path, candidate)
        return
    pairs = ui.collect_calibration_qc_pairs(tmp_path, candidate)
    assert len(pairs) == 3 and not pairs[0].required
    for pair in pairs[1:]:
        expected = rows[pair.original_path.name]["cohort_quality"]["evaluation"]["endpoint"]
        assert str(pair.reconstruction_path) == expected["path"]
        assert pair.reconstruction_sha256 == expected["sha256"]


def test_joint_confirmation_rejects_capture_only_and_keeps_legacy_scope():
    from diffeoforge.guided_joint_initialization import _new_shared_field

    assert not _new_shared_field(SimpleNamespace(attachment_comparison={}))

    def parent(stage):
        return SimpleNamespace(
            attachment_comparison=dict(
                guided=dict(strategy=dict(common_multiscale=dict(stage=stage)))
            )
        )

    assert _new_shared_field(parent("detail"))
    with pytest.raises(ValueError, match="declared detail"):
        _new_shared_field(parent("capture"))
