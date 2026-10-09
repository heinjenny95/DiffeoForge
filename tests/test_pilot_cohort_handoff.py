from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.desktop.project_review import review_project
from diffeoforge.desktop.project_setup import DesktopEngine, ProjectSetupRequest, create_project
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.reference_calibration import build_reference_calibration_plan
from diffeoforge.reference_recommendation import recommend_reference_parameters

MESHES = Path(__file__).parents[1] / "examples/synthetic/meshes"


@pytest.fixture
def handoff(tmp_path):
    cohort = (MESHES / "template.vtk", *sorted(MESHES.glob("subject-*.vtk")))
    landmarks = tmp_path / "landmarks.csv"
    with landmarks.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(LANDMARK_COLUMNS)
        for mesh in cohort:
            points = read_vtk_polydata(mesh).vertices
            for label, index in zip(("a", "b", "c"), (0, 40, 80), strict=True):
                writer.writerow((mesh.name, label, *points[index]))
    recommendation = recommend_reference_parameters(
        cohort, alignment_basis="declared_gpa", surface_detail_intent="balanced",
        deformation_scale_intent="balanced",
    )
    plan = build_reference_calibration_plan(
        recommendation, coordinate_unit="unitless", requested_pilot_subject_count=3
    )
    provenance = recommendation.provenance
    provenance["calibration_plan"] = plan.provenance
    setup = create_project(ProjectSetupRequest(
        mesh_directory=MESHES, project_directory=tmp_path / "project", units="unitless",
        engine=DesktopEngine.DEFORMETRICA_REFERENCE, landmarks_file=landmarks,
        reference_parameter_profile="data_assisted",
        reference_parameter_ratios=recommendation.parameter_ratios,
        reference_parameter_recommendation=provenance,
    ))
    config = load_config(setup.config_path)
    before = validate_input_paths(config, setup.config_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    template = seed / "template.vtk"
    lines = before.template.read_text(encoding="utf-8").splitlines()
    point = [float(x) for x in lines[5].split()]
    point[0] += 0.03
    lines[5] = " ".join(str(x) for x in point)
    template.write_text("\n".join(lines) + "\n", encoding="utf-8")
    controls = seed / "controls.txt"
    controls.write_text("0 0 0\n1 1 1\n", encoding="utf-8")
    config["input"].update(template=str(template), subject_pattern="*.vtk")
    config["model"]["deformation"]["initial_control_points"] = str(controls)
    config["project"]["parameter_provenance"]["recommendation"]["calibration_result"] = {
        "version": "0.1", "status": "completed", "study_id": "synthetic-handoff",
        "plan_fingerprint": plan.fingerprint, "study_manifest_sha256": "a" * 64,
        "decision_event_hash": "b" * 64,
        "selected_candidate_ids": dict.fromkeys(
            ("attachment", "deformation", "noise", "timepoints"), "synthetic"
        ),
        "selected_values": {**plan.effective_values, "timepoints": 10},
        "full_cohort_confirmation_required": True,
        "full_cohort_initialization": {
            "method": "learned_pilot_template_and_controls_zero_full_cohort_momenta",
            "source_run_manifest_sha256": "c" * 64,
            "template_sha256": sha256_file(template),
            "control_points_sha256": sha256_file(controls),
            "limitation": "Synthetic software fixture; no scientific approval.",
        },
    }
    path = setup.config_path.parent / "atlas-calibrated.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path, before, template, controls


def test_learned_seed_preserves_gpa_subject_cohort_and_passes_parameter_review(handoff):
    path, original, template, controls = handoff
    protected = {p: p.read_bytes() for p in (path, original.template, *original.subjects)}
    inputs = validate_input_paths(load_config(path), path)
    assert inputs.template == template
    assert inputs.initial_control_points == controls
    assert inputs.cohort_template == original.template
    assert inputs.subjects == original.subjects
    review = review_project(path, DesktopEngine.DEFORMETRICA_REFERENCE)
    assert review.subject_count == original.subject_count
    values = {item.label: item.value for item in review.parameters}
    assert values["Landmark alignment"] == "generalized Procrustes · 3 landmarks · 6 meshes"
    assert values["Atlas initialization"] == "verified learned pilot template and control points"
    assert all(p.read_bytes() == data for p, data in protected.items())


@pytest.mark.parametrize("target", ("original", "seed", "controls", "subject", "landmarks"))
def test_handoff_does_not_bypass_changed_input_or_seed_evidence(handoff, target):
    path, original, template, controls = handoff
    changed = {
        "original": original.template, "seed": template, "controls": controls,
        "subject": original.subjects[0],
        "landmarks": original.input_directory.parent / "landmarks.csv",
    }[target]
    changed.write_bytes(changed.read_bytes() + b"\n ")
    with pytest.raises((ConfigurationError, RuntimeError), match="no longer matches"):
        review_project(path, DesktopEngine.DEFORMETRICA_REFERENCE)


@pytest.mark.parametrize("extra", (True, False))
def test_changed_full_cohort_is_rejected(handoff, extra):
    path, original, _, _ = handoff
    if extra:
        (original.input_directory / "extra.vtk").write_bytes(original.subjects[0].read_bytes())
    else:
        original.subjects[0].unlink()
    with pytest.raises(ConfigurationError, match="subject count differs"):
        validate_input_paths(load_config(path), path)


def test_ordinary_external_template_does_not_exclude_a_named_mesh(handoff):
    path, original, _, _ = handoff
    config = load_config(path)
    del config["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
    inputs = validate_input_paths(config, path)
    assert inputs.cohort_template is None
    assert inputs.subject_count == original.subject_count + 1
    assert original.template in inputs.subjects
