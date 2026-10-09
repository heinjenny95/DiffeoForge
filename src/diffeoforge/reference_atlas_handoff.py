"""Preserved pilot fields and a supervised early full-cohort checkpoint.

All fields initialize one subsequent joint atlas on the same learned basis.
They are never substituted into an existing PCA or treated as final atlas results.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import numpy as np
import yaml

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import inspect_vtk, sha256_file
from diffeoforge.strict_json import load_strict_json_object

METHOD = "preserved_pilot_momenta_fixed_basis_initialization"
REFINEMENT_METHOD = "preserved_atlas_momenta_fixed_basis_refinement"
PROGRESS = "atlas-initialization.json"
EARLY_CHECK = "early-atlas-check.json"
REVIEW = "early-atlas-review.json"


def initialization(config):
    value = (
        config.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
        .get("calibration_result", {})
        .get("full_cohort_initialization", {})
    )
    return value if value.get("method") in {METHOD, REFINEMENT_METHOD} else None


def configure_preserved_pilot(config, *, root, seed, config_directory):
    """Bind exactly ordered pilot rows to a new full-cohort initial field."""
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.reference_pca_deformations import _write_momenta

    if config.get("output", {}).get("checkpoint_mode", "compact_final_export") != (
        "compact_final_export"
    ):
        raise ConfigurationError("Preserved pilot initialization requires compact checkpoints.")

    basis = root / seed["files"]["momenta"]["copy"]
    if sha256_file(basis) != seed["files"]["momenta"]["sha256"]:
        raise ConfigurationError("Pilot momentum seed changed.")
    fields = read_deformetrica_momenta(basis)
    for role in ("template", "control_points"):
        if sha256_file(root / seed["files"][role]["copy"]) != seed["files"][role]["sha256"]:
            raise ConfigurationError("Pilot template or control-point seed changed.")
    labels = seed["subject_labels"]
    if len(labels) != len(set(labels)) or fields.shape[0] != len(labels):
        raise ConfigurationError("Pilot momentum identities are inconsistent.")
    directory = Path(config["input"]["directory"])
    if not directory.is_absolute():
        directory = (config_directory / directory).resolve()
    original = config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"][
        "template_filename"
    ]
    subjects = sorted(
        p.resolve()
        for p in directory.glob(config["input"]["subject_pattern"])
        if p.is_file() and p.suffix.lower() == ".vtk" and p.name != original
    )
    names = [p.name for p in subjects]
    if not set(labels) <= set(names) or len(names) != len(set(names)):
        raise ConfigurationError("Full-cohort names do not contain the exact pilot subjects.")
    values = np.zeros((len(names), *fields.shape[1:]), dtype=np.float64)
    indices = []
    for row, name in enumerate(labels):
        index = names.index(name)
        values[index] = fields[row]
        indices.append(index)
    target = root / "full-cohort-momenta.txt"
    if target.exists():
        if not np.array_equal(read_deformetrica_momenta(target), values):
            raise ConfigurationError("Existing full-cohort momentum seed differs.")
    else:
        _write_momenta(target, values)
    deformation = config["model"]["deformation"]
    deformation.update(
        initial_momenta=os.path.relpath(target, config_directory).replace("\\", "/"),
        initial_momenta_subjects=names,
    )
    result = config["project"]["parameter_provenance"]["recommendation"]["calibration_result"]
    result["full_cohort_initialization"] = {
        "method": METHOD,
        "source_run_directory": seed["source_run_directory"],
        "source_run_manifest_sha256": seed["source_manifest_sha256"],
        "template_sha256": seed["files"]["template"]["sha256"],
        "control_points_sha256": seed["files"]["control_points"]["sha256"],
        "pilot_momenta_sha256": seed["files"]["momenta"]["sha256"],
        "initial_momenta_sha256": sha256_file(target),
        "subject_labels": names,
        "subject_sha256": {p.name: sha256_file(p) for p in subjects},
        "pilot_indices": indices,
        "pilot_subject_labels": labels,
        "individual_max_iterations": int(config["optimization"]["max_iterations"]),
        "early_review_iteration": 10,
        "completed_initialization_indices": [],
        "early_review_approved": False,
        "limitation": "Pilot rows initialize the common joint model; each other specimen "
        "is fitted against that fixed template/control basis first. Initializer completion "
        "and early pilot review do not establish full-cohort anatomical acceptance.",
    }


def upgrade_saved_pilot_config(config_path):
    """Create a linked configuration; never rewrite a completed pilot or run."""
    from diffeoforge.reference_calibration_study import (
        STUDY_EVENTS,
        STUDY_MANIFEST,
        load_reference_calibration_study,
    )
    from diffeoforge.reference_pca import load_reference_momenta

    path = Path(config_path).resolve()
    config = load_config(path)
    if initialization(config):
        validate_input_paths(config, path)
        return path
    study = path.parent.parent
    snapshot = load_reference_calibration_study(study)
    if snapshot.final_config_path != path:
        raise ConfigurationError("Choose the completed pilot's bound atlas configuration.")
    old = config["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
        "full_cohort_initialization"
    ]
    source = None
    for line in (study / STUDY_EVENTS).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == "candidate_completed":
            atlas = event.get("metrics", {}).get("atlas_path")
            if atlas:
                candidate = Path(atlas).parent.parent
                if (candidate / "manifest.json").is_file() and sha256_file(
                    candidate / "manifest.json"
                ) == old["source_run_manifest_sha256"]:
                    source = candidate
    if source is None:
        raise ConfigurationError("Cannot locate the exact selected pilot momentum source.")
    inputs = load_reference_momenta(source)
    root = study / "selected-seed"
    seed = {
        "files": {
            role: {"copy": f"adaptive-seed/{role}{suffix}", "sha256": digest}
            for role, suffix, digest in (
                ("template", ".vtk", old["template_sha256"]),
                ("control_points", ".txt", old["control_points_sha256"]),
                ("momenta", ".txt", sha256_file(inputs.momenta_path)),
            )
        },
        "subject_labels": list(inputs.subject_labels),
        "source_run_directory": str(source),
        "source_manifest_sha256": old["source_run_manifest_sha256"],
    }
    upgraded = copy.deepcopy(config)
    configure_preserved_pilot(upgraded, root=root, seed=seed, config_directory=path.parent)
    upgraded["project"]["parameter_provenance"]["recommendation"]["calibration_result"][
        "handoff_upgrade"
    ] = {
        "source_config_sha256": sha256_file(path),
        "source_study_manifest_sha256": sha256_file(study / STUDY_MANIFEST),
    }
    target = path.with_name("atlas-pilot-preserved.yaml")
    from diffeoforge.initialization import _CONFIG_MARKER

    rendered = _CONFIG_MARKER + "\n" + yaml.safe_dump(upgraded, sort_keys=False, allow_unicode=True)
    if target.exists():
        if target.read_text(encoding="utf-8") != rendered:
            raise ConfigurationError("Existing upgraded pilot configuration differs.")
    else:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    validate_input_paths(upgraded, target)
    return target


def read_early_check(run_directory, *, verified_report=None):
    """Verify terminal inventory, exact checkpoint and both sets of pilot meshes."""
    from diffeoforge.result_report import collect_run_report

    run = Path(run_directory).resolve()
    report = verified_report if verified_report is not None else collect_run_report(run)
    if any(c.status != "pass" for c in report.checks):
        raise ConfigurationError("Early atlas evidence failed verification.")
    return verify_early_check_files(run, report.manifest["effective_config"])


def verify_early_check_files(run_directory, config):
    """Check the checkpoint receipt, including before terminal inventory is sealed."""
    run = Path(run_directory).resolve()
    plan = initialization(config)
    if not plan:
        raise ConfigurationError("This run has no preserved-pilot initialization contract.")
    path = run / "output" / EARLY_CHECK
    value = load_strict_json_object(path.read_bytes(), path, label="Early atlas check")
    if (
        value.get("version") != "0.1"
        or value.get("pilot_indices") != plan["pilot_indices"]
        or value.get("checkpoint_sha256") != sha256_file(run / "output/deformetrica-state.p")
        or value.get("subject_labels") != plan["subject_labels"]
        or value.get("pilot_momenta_preserved_exactly") is not True
        or type(value.get("iteration")) is not int
        or not 0 <= value["iteration"] <= plan["early_review_iteration"]
    ):
        raise ConfigurationError(
            "Early atlas check differs from its checkpoint or subject binding."
        )
    for item in value["meshes"]:
        for kind in ("before", "after"):
            if item[kind].get("index") != item["index"]:
                raise ConfigurationError("Early atlas mesh index differs from its pilot record.")
            relative = Path(item[kind]["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ConfigurationError("Unsafe early atlas mesh path.")
            mesh = run / "output" / relative
            if mesh.is_symlink() or sha256_file(mesh) != item[kind]["sha256"]:
                raise ConfigurationError("Early atlas mesh changed.")
            inspect_vtk(mesh)
    if [r["index"] for r in value["meshes"]] != plan["pilot_indices"]:
        raise ConfigurationError("Early atlas mesh identities do not match the pilot.")
    return value


def record_early_review(run_directory, *, approved, inspected_subjects, notes=""):
    from diffeoforge.atomic_io import write_text_safely

    run = Path(run_directory).resolve()
    if type(approved) is not bool:
        raise ConfigurationError("Early atlas approval must be an explicit boolean decision.")
    check = read_early_check(run)
    expected = {check["subject_labels"][i] for i in check["pilot_indices"]}
    if approved and set(inspected_subjects) != expected:
        raise ConfigurationError("Inspect all pilot specimens before continuing the joint atlas.")
    record = {
        "version": "0.1",
        "approved": bool(approved),
        "checkpoint_sha256": check["checkpoint_sha256"],
        "check_sha256": sha256_file(run / "output" / EARLY_CHECK),
        "inspected_subjects": sorted(inspected_subjects),
        "notes": str(notes),
    }
    target = run / "analysis" / REVIEW
    target.parent.mkdir(exist_ok=True)
    write_text_safely(target, json.dumps(record, indent=2) + "\n", overwrite=True)


def configure_resume(config, source_run):
    """Bind phase continuation to inventoried initialization and explicit review."""
    plan = initialization(config)
    if not plan:
        return
    source_run = Path(source_run)
    guard = source_run / "output" / EARLY_CHECK
    if guard.exists():
        check = read_early_check(source_run)
        review_path = source_run / "analysis" / REVIEW
        if not review_path.is_file():
            raise ConfigurationError("Review the early atlas check before resuming.")
        review = load_strict_json_object(
            review_path.read_bytes(), review_path, label="Early atlas review"
        )
        required = sorted(check["subject_labels"][i] for i in check["pilot_indices"])
        if (
            review.get("approved") is not True
            or review.get("checkpoint_sha256") != check["checkpoint_sha256"]
            or review.get("check_sha256") != sha256_file(guard)
            or review.get("inspected_subjects") != required
        ):
            raise ConfigurationError("Early atlas review is rejected, incomplete or stale.")
        plan["early_review_approved"] = True
        plan["completed_initialization_indices"] = list(range(len(plan["subject_labels"])))
        plan["early_review_binding"] = {
            "review_sha256": sha256_file(review_path),
            "check_sha256": sha256_file(guard),
            "checkpoint_sha256": check["checkpoint_sha256"],
        }
    elif (source_run / "output" / PROGRESS).exists():
        progress_path = source_run / "output" / PROGRESS
        progress = load_strict_json_object(
            progress_path.read_bytes(), progress_path, label="Atlas initialization progress"
        )
        if progress.get("subject_labels") != plan["subject_labels"] or progress.get(
            "checkpoint_sha256"
        ) != sha256_file(source_run / "output/deformetrica-state.p"):
            raise ConfigurationError("Initializer progress is not bound to the saved checkpoint.")
        indices = progress["completed_indices"]
        if len(indices) != len(set(indices)) or any(
            type(i) is not int or i not in range(len(plan["subject_labels"])) for i in indices
        ):
            raise ConfigurationError("Initializer progress contains invalid subject indices.")
        plan["completed_initialization_indices"] = indices


def adapter_source(config):
    plan = initialization(config)
    if not plan:
        return ""
    if config["optimization"]["method"] != "gradient_ascent":
        raise ConfigurationError("Preserved-pilot initialization requires GradientAscent.")
    if config["output"].get("checkpoint_mode") != "compact_final_export":
        raise ConfigurationError("Preserved-pilot initialization requires compact checkpoints.")
    if plan["method"] == REFINEMENT_METHOD and not (
        config["optimization"]["freeze_template"]
        and config["optimization"]["freeze_control_points"]
    ):
        raise ConfigurationError("Saved-atlas refinement requires a frozen template and controls.")
    return "\n_DF_ATLAS_PLAN = " + repr(plan) + "\n" + ADAPTER


# Runs in the pinned reference interpreter. Native likelihood, gradient,
# integration and optimizer update equations are reused unchanged.
ADAPTER = """
import copy as _df_copy
import hashlib as _df_hashlib
import json as _df_json
import numpy as _df_np
from deformetrica.support import utilities as _df_utilities

def _df_digest(path):
    digest = _df_hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _df_json_atomic(path, value):
    fd, temporary = _df_tempfile.mkstemp(
        prefix=".df-initialization-", dir=_df_os.path.dirname(path))
    try:
        with _df_os.fdopen(fd, "w") as stream:
            _df_json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            _df_os.fsync(stream.fileno())
        _df_os.replace(temporary, path)
    finally:
        if _df_os.path.exists(temporary):
            _df_os.unlink(temporary)

def _df_pilot_shapes(estimator, phase):
    model = estimator.statistical_model
    device, _ = _df_utilities.get_best_device(model.gpu_mode)
    data, points, controls, momenta = model._fixed_effects_to_torch_tensors(False, device=device)
    exponential = model.exponential
    exponential.set_initial_template_points(points)
    exponential.set_initial_control_points(controls)
    root = _df_os.path.join(estimator.output_dir, "early-atlas-" + phase)
    _df_os.makedirs(root, exist_ok=True)
    result = []
    for index in _DF_ATLAS_PLAN["pilot_indices"]:
        exponential.set_initial_momenta(momenta[index])
        exponential.update()
        deformed = model.template.get_deformed_data(exponential.get_template_points(), data)
        names = ["pilot-%04d" % index + ext for ext in model.objects_name_extension]
        model.template.write(
            root, names, {k: v.detach().cpu().numpy() for k, v in deformed.items()})
        path = _df_os.path.join(root, names[0])
        relative = _df_os.path.relpath(path, estimator.output_dir).replace("\\\\", "/")
        result.append({"index": index, "path": relative,
                       "sha256": _df_digest(path)})
    return result

_df_atlas_base_update = _df_ga.update

def _df_atlas_update(self, *args, **kwargs):
    if (getattr(self, "_df_individual_initialization", False)
            or _DF_ATLAS_PLAN["early_review_approved"]):
        return _df_atlas_base_update(self, *args, **kwargs)
    labels = _DF_ATLAS_PLAN["subject_labels"]
    if list(self.dataset.subject_ids) != labels:
        raise RuntimeError("Preserved pilot initialization subject order differs")
    model = self.statistical_model
    pilot = set(_DF_ATLAS_PLAN["pilot_indices"])
    preserved = model.get_momenta()[_DF_ATLAS_PLAN["pilot_indices"]].copy()
    completed = set(_DF_ATLAS_PLAN["completed_initialization_indices"]) | pilot
    if _DF_ATLAS_PLAN["method"] == "preserved_atlas_momenta_fixed_basis_refinement":
        # Every row already comes from the declared, hash-bound full-cohort seed.
        # Use it directly in the common optimizer; do not refit other rows first.
        completed.update(range(len(labels)))
    self.current_parameters = self._get_parameters()
    self._dump_state_file()
    for index, label in enumerate(labels):
        if index in completed:
            continue
        _df_log.info("DiffeoForge initialization: specimen %s of %s (%s); fixed pilot basis",
                     index + 1, len(labels), label)
        local_model = _df_copy.copy(model)
        local_model.fixed_effects = dict(model.fixed_effects)
        local_model.fixed_effects["momenta"] = model.get_momenta()[index:index + 1].copy()
        local_model.number_of_subjects = 1
        local_model.number_of_processes = 1
        local_model.freeze_template = True
        local_model.freeze_control_points = True
        local_dataset = _df_copy.copy(self.dataset)
        local_dataset.subject_ids = [label]
        local_dataset.deformable_objects = [self.dataset.deformable_objects[index]]
        local_dataset.times = [self.dataset.times[index]]
        local_dataset.number_of_subjects = 1
        optimizer = _df_ga(
            statistical_model=local_model, dataset=local_dataset,
            optimization_method_type="GradientAscent",
            max_iterations=_DF_ATLAS_PLAN["individual_max_iterations"],
            convergence_tolerance=self.convergence_tolerance,
            initial_step_size=self.initial_step_size,
            scale_initial_step_size=self.scale_initial_step_size,
            max_line_search_iterations=self.max_line_search_iterations,
            line_search_shrink=self.line_search_shrink, line_search_expand=self.line_search_expand,
            print_every_n_iters=self.print_every_n_iters,
            save_every_n_iters=self.save_every_n_iters,
            output_dir=self.output_dir, state_file=self.state_file, load_state_file=False)
        optimizer._df_individual_initialization = True
        optimizer.write = lambda: None
        optimizer._dump_state_file = lambda: None
        optimizer.print = lambda: _df_log.info(
            "DiffeoForge initialization: specimen %s of %s; optimizer iteration %s / %s",
            index + 1, len(labels), optimizer.current_iteration, optimizer.max_iterations)
        native_logger = _df_logging.getLogger("deformetrica.core.estimators.gradient_ascent")
        saved_handlers, saved_propagate = native_logger.handlers[:], native_logger.propagate
        individual_log = _df_os.path.join(self.output_dir, "initializer-%04d.log" % index)
        handler = _df_logging.FileHandler(individual_log, mode="w")
        native_logger.handlers, native_logger.propagate = [handler], False
        try:
            _df_atlas_base_update(optimizer)
        finally:
            native_logger.handlers, native_logger.propagate = saved_handlers, saved_propagate
            handler.close()
        _df_log.info("DiffeoForge initialization completed: specimen %s of %s; "
                     "%s optimizer iterations; native stop evidence in %s",
                     index + 1, len(labels), optimizer.current_iteration,
                     _df_os.path.basename(individual_log))
        field = local_model.get_momenta()[0]
        if not _df_np.isfinite(field).all():
            raise RuntimeError("Non-finite individual initialization")
        model.get_momenta()[index] = field
        completed.add(index)
        self.current_parameters = self._get_parameters()
        self._dump_state_file()
        _df_json_atomic(_df_os.path.join(self.output_dir, "atlas-initialization.json"),
                        {"version": "0.1", "subject_labels": labels,
                         "completed_indices": sorted(completed),
                         "checkpoint_sha256": _df_digest(self.state_file)})
    if not _df_np.array_equal(preserved, model.get_momenta()[_DF_ATLAS_PLAN["pilot_indices"]]):
        raise RuntimeError("Pilot momentum fields changed during individual initialization")
    before = _df_pilot_shapes(self, "before")
    self.current_parameters = self._get_parameters()
    self._dump_state_file()
    _df_json_atomic(_df_os.path.join(self.output_dir, "atlas-initialization.json"),
                    {"version": "0.1", "subject_labels": labels,
                     "completed_indices": sorted(completed),
                     "checkpoint_sha256": _df_digest(self.state_file)})
    original_state_file = self.state_file
    self.state_file = _df_os.path.join(self.output_dir, "atlas-initialized-state.p")
    try:
        self._dump_state_file()
    finally:
        self.state_file = original_state_file
    _df_log.info("DiffeoForge joint atlas: initialized %s of %s specimens; "
                 "early review at iteration %s",
                 len(completed), len(labels), _DF_ATLAS_PLAN["early_review_iteration"])
    previous_callback = self.callback
    def stop_for_review(*callback_args, **callback_kwargs):
        if self.current_iteration >= _DF_ATLAS_PLAN["early_review_iteration"]:
            return False
        if previous_callback is not None:
            return previous_callback(*callback_args, **callback_kwargs)
        return True
    self.callback = stop_for_review
    try:
        _df_atlas_base_update(self, *args, **kwargs)
    finally:
        self.callback = previous_callback
    self.current_parameters = self._get_parameters()
    self._dump_state_file()
    after = _df_pilot_shapes(self, "after")
    _df_json_atomic(_df_os.path.join(self.output_dir, "early-atlas-check.json"),
                    {"version": "0.1", "subject_labels": labels,
                     "pilot_indices": _DF_ATLAS_PLAN["pilot_indices"],
                     "pilot_momenta_preserved_exactly": True,
                     "iteration": int(self.current_iteration),
                     "checkpoint_sha256": _df_digest(self.state_file),
                     "meshes": [{"index": b["index"], "before": b, "after": a}
                                for b, a in zip(before, after)]})
    _df_log.info("DiffeoForge early atlas check ready; review all pilot fits before continuing. "
                 "No complete flow export started.")
    raise KeyboardInterrupt

_df_ga.update = _df_atlas_update
"""
