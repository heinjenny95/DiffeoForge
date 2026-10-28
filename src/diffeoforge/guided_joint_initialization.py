"""A new joint fit starts with compatible accepted fields on one original basis."""

from copy import deepcopy
from pathlib import Path

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file

VERSION = "accepted-singletons-v1"


def references(rows):
    result = []
    for row in sorted(rows, key=lambda r: r["filename"]):
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        result.append(ref)
    return result


def subject_order(manifest):
    """Match validate_input_paths' platform Path sorting, not pilot selection order."""
    return sorted((s["filename"] for s in manifest["inputs"]["subjects"]), key=Path)


def _basis(config, values=None, method=None):
    model = deepcopy(config["model"])
    deformation = model["deformation"]
    for key in ("initial_momenta", "initial_momenta_subjects", "initial_control_points"):
        deformation.pop(key, None)
    if values is not None:
        model["attachment"].update(type=method, kernel_width=values["attachment_kernel_width"])
        model["noise_std"] = values["noise_std"]
        deformation.update(kernel_width=values["deformation_kernel_width"],
                           initial_control_point_spacing=values["initial_control_point_spacing"])
    return model, config["runtime"]["precision"]


def bind(root, manifest, record):
    request = record.get("joint_initialization")
    if not request:
        return record
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_refinement import bind as bind_single
    from diffeoforge.guided_refinement import load_field
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.reference_pca_deformations import _write_momenta

    subjects = {r["filename"]: r for r in manifest["inputs"]["subjects"]}
    refs = request["references"]
    if (request.get("version") != VERSION
            or record.get("guided", {}).get("phase") != "joint"
            or len(refs) != len(subjects)
            or {r["target"] for r in refs} != set(subjects)
            or len(record["methods"]) != 1):
        raise ValueError("Joint initialization requires one accepted field per original form")
    values = manifest["plan"]["baseline_effective_values"]
    method = next(iter(record["methods"].values()))
    config_path = root / manifest["source_config"]["copy"]
    requested = load_config(config_path)
    points = np.loadtxt(root / record["controls"]["copy"]).reshape(-1, 3)
    parts = []
    arrays = {}
    for index, ref in enumerate(refs):
        parent = verify_reference(ref)
        approved = dict(ref)
        approved["filename"] = approved.pop("target")
        if (guided._approved_record(parent, ref["candidate_id"]) != approved
                or ref["values"] != values or ref["method"] != method
                or Path(guided.record(parent)["origin"]).resolve()
                != Path(record["guided"]["origin"]).resolve()):
            raise ValueError(
                "Joint initialization must retain the accepted cohort, settings and method")
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        if _basis(load_config(candidate.config_path)) != _basis(requested, values, method):
            raise ValueError(
                "Accepted fields use different model, precision or integration settings")
        # Reuse the complete frozen-singleton binding contract, including native
        # output inventory, original template/target, time grid and control basis.
        stage = root / "joint-start" / f"{index:03}"
        stage.mkdir(parents=True)
        study._copy_bound(config_path, stage / "atlas.yaml", sha256_file(config_path))
        subset = dict(manifest, source_config=dict(copy="atlas.yaml"),
                      inputs=dict(manifest["inputs"], subjects=[subjects[ref["target"]]]))
        single = bind_single(stage, subset, dict(methods={"joint": method},
            refinement=dict(version="guided-refinement-v1", reference=ref)))
        if (single["refinement"]["initialization"] != "learned"
                or not np.array_equal(points, np.loadtxt(stage / single["controls"]["copy"])
                                      .reshape(-1, 3))):
            raise ValueError("The accepted fields cannot share this original joint basis; "
                             "no fresh joint restart was substituted")
        field = load_field(study.calibration_candidate_run_directory(candidate))
        if field.subject_labels != (ref["target"],):
            raise ValueError("Joint initialization field labels changed")
        copied = stage / single["refinement"]["momenta"]["copy"]
        array = read_deformetrica_momenta(copied, allow_singleton=True)
        if not np.array_equal(array, field.momenta):
            raise ValueError("Copied accepted momenta differ from their native source")
        arrays[ref["target"]] = array
        parts.append(dict(reference=ref, copy=copied.relative_to(root).as_posix(),
            sha256=sha256_file(copied), source_copy=study._relative_path(
                parent.study_directory, field.momenta_path),
            source_run_sha256=single["refinement"]["source_run_sha256"],
            controls_copy=(stage / single["controls"]["copy"]).relative_to(root).as_posix(),
            controls_sha256=single["controls"]["sha256"]))
    labels = subject_order(manifest)
    path = root / "joint-initial-momenta.txt"
    combined = np.concatenate([arrays[label] for label in labels])
    _write_momenta(path, combined)
    if not np.array_equal(read_deformetrica_momenta(path), combined):
        raise ValueError("Joint momenta serialization changed accepted coefficients")
    return dict(record, joint_initialization=dict(request, parts=parts, subjects=labels,
        momenta=dict(copy=path.name, sha256=sha256_file(path)),
        optimizer_history_retained=False, anatomical_approval_created=False))


def verify(root, manifest, record):
    request = record.get("joint_initialization")
    if not request:
        return
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_pca import read_deformetrica_momenta

    labels = subject_order(manifest)
    if (request.get("version") != VERSION or request["subjects"] != labels
            or record.get("guided", {}).get("phase") != "joint"
            or len(record["methods"]) != 1
            or request.get("optimizer_history_retained") is not False
            or request.get("anatomical_approval_created") is not False
            or [p["reference"] for p in request["parts"]] != request["references"]
            or len(request["parts"]) != len(labels)
            or {r["target"] for r in request["references"]} != set(labels)):
        raise ValueError("Joint starting-field provenance changed")
    points = np.loadtxt(study._safe_study_path(root, record["controls"]["copy"])).reshape(-1, 3)
    expected = {s["filename"]: s["sha256"] for s in manifest["inputs"]["subjects"]}
    values = manifest["plan"]["baseline_effective_values"]
    method = next(iter(record["methods"].values()))
    requested = load_config(root / manifest["source_config"]["copy"])
    arrays = {}
    for part in request["parts"]:
        ref = part["reference"]
        parent = verify_reference(ref)
        row = dict(ref)
        row["filename"] = row.pop("target")
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        original = study._verify_manifest(parent.study_directory)
        run = study.calibration_candidate_run_directory(candidate)
        source = study._safe_study_path(parent.study_directory, part["source_copy"])
        path = study._safe_study_path(root, part["copy"])
        control = study._safe_study_path(root, part["controls_copy"])
        if (guided._approved_record(parent, ref["candidate_id"]) != row
                or ref["values"] != values or ref["method"] != method
                or Path(guided.record(parent)["origin"]).resolve()
                != Path(record["guided"]["origin"]).resolve()
                or {s["filename"]: s["sha256"] for s in original["inputs"]["subjects"]}
                != {ref["target"]: expected[ref["target"]]}
                or original["inputs"]["template"]["sha256"]
                != manifest["inputs"]["template"]["sha256"]
                or part["controls_sha256"] != parent.attachment_comparison["controls"]["sha256"]
                or _basis(load_config(candidate.config_path)) != _basis(requested, values, method)
                or not source.resolve().is_relative_to(run.resolve())
                or sha256_file(run / "manifest.json") != part["source_run_sha256"]
                or sha256_file(path) != part["sha256"]
                or sha256_file(source) != part["sha256"]
                or sha256_file(control) != part["controls_sha256"]
                or not np.array_equal(np.loadtxt(control).reshape(-1, 3), points)):
            raise ValueError("Accepted joint starting-field bytes or basis changed")
        arrays[ref["target"]] = read_deformetrica_momenta(path, allow_singleton=True)
    path = study._safe_study_path(root, request["momenta"]["copy"])
    if (sha256_file(path) != request["momenta"]["sha256"]
            or not np.array_equal(read_deformetrica_momenta(path),
                                  np.concatenate([arrays[label] for label in labels]))):
        raise ValueError("Joint initialization subject ordering or coefficients changed")
