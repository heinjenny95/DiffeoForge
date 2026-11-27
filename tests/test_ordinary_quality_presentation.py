"""The qualified ordinary endpoint is measured and displayed without relabelling."""

from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import guided_feedback, ordinary_field_quality, regional_evaluation, result_report
from diffeoforge import reference_attachment_comparison as methods
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_ordinary_guard import DECLARATION
from diffeoforge.regional_fit import _save


@pytest.mark.parametrize("passed", [False, True])
def test_comparison_uses_qualified_full_field_and_keeps_failed_checks_visible(
    tmp_path, monkeypatch, passed
):
    v, f = cube()
    original, raw, dense = (tmp_path / p for p in ("target.vtk", "raw.vtk", "dense.vtk"))
    _save(original, v, f)
    _save(raw, np.asarray(v) + [1, 0, 0], f)
    _save(dense, v, f)
    run = tmp_path / "run"
    output = run / "output"
    output.mkdir(parents=True)
    native = output / "D__Reconstruction__surface__subject_target.vtk.vtk"
    native.write_bytes(raw.read_bytes())
    report = SimpleNamespace(
        manifest={
            "effective_config": {
                "project": {"parameter_provenance": {"finite_accepted_guard": DECLARATION}}
            }
        },
        inventory=[dict(path=native.name)],
    )
    monkeypatch.setattr(result_report, "collect_run_report", lambda _: report)
    quality = dict(
        version=ordinary_field_quality.VERSION,
        passed=passed,
        numerical_selection_suitable=passed,
        evaluation={"endpoint": {"path": str(dense), "sha256": sha256_file(dense)}},
    )
    received = []
    monkeypatch.setattr(
        ordinary_field_quality,
        "evaluate_and_measure",
        lambda *a, **k: received.append(k) or quality,
    )
    manifest = dict(
        attachment_comparison={},
        inputs={
            "subjects": [
                dict(filename=original.name, copy=original.name, sha256=sha256_file(original))
            ]
        },
    )
    result = methods.measure(
        tmp_path,
        manifest,
        SimpleNamespace(candidate_id="one"),
        run,
        cancelled=lambda: False,
        event_callback=None,
    )
    row = result["attachment_comparison"]["subjects"][original.name]
    assert row["ordinary_quality"] is quality and "regional_quality" not in row
    assert max(r["p95"] for r in row["repeats"]) < 1e-8
    candidate = SimpleNamespace(candidate_id="one", metrics=result)
    assert regional_evaluation.endpoint(candidate) == quality["evaluation"]["endpoint"]
    snapshot = SimpleNamespace(candidates=[candidate])
    assert guided_feedback.severe_regression(snapshot, "one") is (not passed)
    assert any("qualification did not pass" in w for w in row["warnings"]) is (not passed)
    assert received and callable(received[0]["cancelled"])


def test_changed_or_ambiguous_ordinary_endpoint_is_not_silently_replaced(tmp_path):
    p = tmp_path / "endpoint.vtk"
    p.write_text("original")
    record = dict(evaluation={"endpoint": dict(path=str(p), sha256=sha256_file(p))})
    candidate = SimpleNamespace(
        metrics={"attachment_comparison": {"subjects": {"one": {"ordinary_quality": record}}}}
    )
    assert regional_evaluation.endpoint(candidate)["path"] == str(p)
    p.write_text("changed")
    with pytest.raises(ValueError, match="changed or is ambiguous"):
        regional_evaluation.endpoint(candidate)
    p.write_text("original")
    candidate.metrics["attachment_comparison"]["subjects"]["one"]["regional_quality"] = record
    with pytest.raises(ValueError, match="ambiguous"):
        regional_evaluation.endpoint(candidate)
