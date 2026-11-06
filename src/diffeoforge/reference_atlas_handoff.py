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
from diffeoforge.reference_checkpoint_schedule import needs_adapter, new_run_config
from diffeoforge.reference_initial_fit_screen import NATIVE_SCREEN, REVIEW_PRIORITY
from diffeoforge.reference_initial_fit_screen import RECEIPT as INITIAL_SCREEN
from diffeoforge.reference_initial_fit_screen import VERSION as INITIAL_SCREEN_VERSION
from diffeoforge.strict_json import load_strict_json_object

METHOD = "preserved_pilot_momenta_fixed_basis_initialization"
REFINEMENT_METHOD = "preserved_atlas_momenta_fixed_basis_refinement"
PROGRESS = "atlas-initialization.json"
EARLY_CHECK = "early-atlas-check.json"
REVIEW = "early-atlas-review.json"
REVIEW_CHOICE = "early-atlas-review-choice.json"


def early_review_enabled(plan):
    """Old protected contracts retain their explicit review stop until changed."""
    enabled = plan.get("early_review_enabled", True)
    if type(enabled) is not bool:
        raise ConfigurationError("Early atlas review must be an explicit boolean choice.")
    return enabled


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

    if not needs_adapter(new_run_config(config)):
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
        "early_review_enabled": False,
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


def choose_early_review(config_path, *, enabled):
    """Save a linked launch choice without rewriting the completed pilot config."""
    if type(enabled) is not bool:
        raise ConfigurationError("Early atlas review must be an explicit boolean choice.")
    path = Path(config_path).resolve()
    config = load_config(path)
    plan = initialization(config)
    if not plan:
        raise ConfigurationError("This configuration has no preserved-pilot atlas handoff.")
    if early_review_enabled(plan) == enabled:
        return path
    plan["early_review_enabled"] = enabled
    plan["early_review_choice"] = {"source_config_sha256": sha256_file(path)}
    target = path.with_name(f"{path.stem}-early-review-{'on' if enabled else 'off'}.yaml")
    return _write_linked_atlas_config(config, target)


def choose_initial_fit_screen(config_path, *, enabled):
    """Record the starting-fit review choice for a new atlas in a linked configuration."""
    if type(enabled) is not bool:
        raise ConfigurationError("Starting-fit review must be an explicit boolean choice.")
    path = Path(config_path).resolve()
    config = load_config(path)
    plan = initialization(config)
    if not plan or plan["method"] != METHOD:
        if enabled:
            raise ConfigurationError("Starting-fit review requires a saved pilot atlas setup.")
        return path
    if bool(plan.get("initial_fit_screen")) == enabled:
        return path
    if plan.get("initial_fit_screen_binding"):
        raise ConfigurationError("The starting-fit review choice is already bound to a run.")
    if enabled:
        plan["initial_fit_screen"] = INITIAL_SCREEN_VERSION
    else:
        plan.pop("initial_fit_screen")
    suffix = "fit-screen" if enabled else "no-fit-screen"
    return _write_linked_atlas_config(config, path.with_name(f"{path.stem}-{suffix}.yaml"))


def _write_linked_atlas_config(config, target):
    from diffeoforge.initialization import _CONFIG_MARKER

    rendered = _CONFIG_MARKER + "\n" + yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    if target.exists():
        if target.read_text(encoding="utf-8") != rendered:
            raise ConfigurationError("Existing linked atlas configuration differs.")
    else:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    validate_input_paths(config, target)
    return target


def read_early_check(run_directory, *, verified_report=None):
    """Verify terminal inventory, exact checkpoint and both sets of pilot meshes."""
    from diffeoforge.result_report import collect_run_report

    run = Path(run_directory).resolve()
    report = verified_report if verified_report is not None else collect_run_report(run)
    if any(c.status != "pass" for c in report.checks):
        raise ConfigurationError("Early atlas evidence failed verification.")
    return verify_early_check_files(run, report.manifest["effective_config"])


def is_initial_fit_review(run_directory):
    """Identify the review wording only; continuation verifies the full receipt."""
    path = Path(run_directory) / "output" / EARLY_CHECK
    try:
        return load_strict_json_object(path.read_bytes(), path, label="Early atlas check").get(
            "phase"
        ) == "initialization"
    except (OSError, ValueError):
        return False


def verify_early_check_files(run_directory, config):
    """Check the checkpoint receipt, including before terminal inventory is sealed."""
    run = Path(run_directory).resolve()
    plan = initialization(config)
    if not plan:
        raise ConfigurationError("This run has no preserved-pilot initialization contract.")
    path = run / "output" / EARLY_CHECK
    value = load_strict_json_object(path.read_bytes(), path, label="Early atlas check")
    if value.get("phase") == "initialization":
        if (value.get("checkpoint_sha256") != sha256_file(run / "output/deformetrica-state.p")
                or not value.get("pilot_indices")):
            raise ConfigurationError("Flagged initial fits differ from the review checkpoint.")
        _verify_initial_screen(run, plan, value)
        return value
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


def _verify_initial_screen(run, plan, value):
    """Bind every screened initializer row and any displayed meshes to the saved state."""
    screened = [i for i in range(len(plan["subject_labels"])) if i not in plan["pilot_indices"]]
    if (
        plan.get("initial_fit_screen") != INITIAL_SCREEN_VERSION
        or value.get("version") != INITIAL_SCREEN_VERSION
        or value.get("phase") != "initialization" or value.get("iteration") != 0
        or value.get("subject_labels") != plan["subject_labels"]
        or value.get("checkpoint_sha256") != sha256_file(run / "output/atlas-initialized-state.p")
        or [row["index"] for row in value["screened"]] != screened
    ):
        raise ConfigurationError("Initial fit screen differs from its saved cohort or state.")
    flagged, required = [], []
    for row in value["screened"]:
        threshold = row["distance_threshold"]
        if not np.isfinite(threshold) or threshold <= 0:
            raise ConfigurationError("An initial-fit screen threshold is invalid.")
        for patch in row["patches"]:
            point = np.asarray(patch["peak_point"], dtype=float)
            if (patch["direction"] not in {"missing_surface", "extra_surface"}
                    or point.shape != (3,) or not np.isfinite(point).all()
                    or not np.isfinite(patch["peak_distance"])
                    or patch["peak_distance"] < threshold
                    or not 0 < patch["area_fraction"] <= 1):
                raise ConfigurationError("An initial-fit inspection marker is invalid.")
        priority = max((p["peak_distance"] / threshold * p["area_fraction"]**0.5
                        for p in row["patches"]), default=0.)
        if not np.isclose(priority, row["priority"], rtol=1e-12, atol=1e-15):
            raise ConfigurationError("An initial-fit review priority is inconsistent.")
        if row["patches"]:
            flagged.append(row["index"])
        if priority >= REVIEW_PRIORITY:
            required.append(row["index"])
    if (value["pilot_indices"] != required
            or [row["index"] for row in value["meshes"]] != flagged):
        raise ConfigurationError("Flagged initial fit review is incomplete or inconsistent.")
    for row in value["meshes"]:
        relative = Path(row["after"]["path"])
        mesh = run / "output" / relative
        if (relative != Path(f'initial-fit-review/fit-{row["index"]:04d}.vtk') or mesh.is_symlink()
                or row["after"]["index"] != row["index"]
                or sha256_file(mesh) != row["after"]["sha256"]):
            raise ConfigurationError("An initial-fit review mesh changed.")
        inspect_vtk(mesh)


def record_early_review(run_directory, *, approved, inspected_subjects, notes=""):
    from diffeoforge.atomic_io import write_text_safely

    run = Path(run_directory).resolve()
    if type(approved) is not bool:
        raise ConfigurationError("Early atlas approval must be an explicit boolean decision.")
    check = read_early_check(run)
    expected = {check["subject_labels"][i] for i in check["pilot_indices"]}
    if approved and set(inspected_subjects) != expected:
        raise ConfigurationError(
            "Inspect all required specimens before continuing the joint atlas."
        )
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


def record_early_review_choice(run_directory, *, enabled):
    """Record an optional-check decision, never an anatomical approval."""
    from diffeoforge.atomic_io import write_text_safely

    if enabled is not False:
        raise ConfigurationError("Use anatomical review to approve an enabled early check.")
    run = Path(run_directory).resolve()
    check = read_early_check(run)
    if check.get("phase") == "initialization":
        raise ConfigurationError("Flagged initial fits require a recorded visual review.")
    review_path = run / "analysis" / REVIEW
    if review_path.is_file():
        review = load_strict_json_object(review_path.read_bytes(), review_path,
                                        label="Early atlas review")
        if review.get("approved") is not True:
            raise ConfigurationError("A rejected early atlas review cannot be skipped.")
    target = run / "analysis" / REVIEW_CHOICE
    record = {
        "version": "0.1", "early_review_enabled": False,
        "checkpoint_sha256": check["checkpoint_sha256"],
        "check_sha256": sha256_file(run / "output" / EARLY_CHECK),
        "decision": "researcher_continues_without_optional_early_review",
        "anatomical_approval": False,
    }
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
            if check.get("phase") == "initialization":
                raise ConfigurationError("Review the flagged initial fits before the joint atlas.")
            choice_path = source_run / "analysis" / REVIEW_CHOICE
            if not choice_path.is_file():
                raise ConfigurationError("Review the early atlas check before resuming, or "
                                         "explicitly continue without the optional check.")
            choice = load_strict_json_object(choice_path.read_bytes(), choice_path,
                                            label="Optional early-review choice")
            if (choice.get("version") != "0.1"
                    or choice.get("early_review_enabled") is not False
                    or choice.get("anatomical_approval") is not False
                    or choice.get("decision") !=
                    "researcher_continues_without_optional_early_review"
                    or choice.get("checkpoint_sha256") != check["checkpoint_sha256"]
                    or choice.get("check_sha256") != sha256_file(guard)):
                raise ConfigurationError("Optional early-review choice is invalid or stale.")
            plan["early_review_enabled"] = False
            plan["completed_initialization_indices"] = list(range(len(plan["subject_labels"])))
            plan["early_review_choice_binding"] = {
                "choice_sha256": sha256_file(choice_path),
                "check_sha256": sha256_file(guard),
                "checkpoint_sha256": check["checkpoint_sha256"],
            }
            return
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
        plan["completed_initialization_indices"] = list(range(len(plan["subject_labels"])))
        binding = {
            "review_sha256": sha256_file(review_path),
            "check_sha256": sha256_file(guard),
            "checkpoint_sha256": check["checkpoint_sha256"],
        }
        if check.get("phase") == "initialization":
            plan["initial_fit_screen_binding"] = binding
        else:
            plan["early_review_approved"] = True
            plan["early_review_binding"] = binding
    elif (source_run / "output" / PROGRESS).exists():
        progress_path = source_run / "output" / PROGRESS
        progress = load_strict_json_object(
            progress_path.read_bytes(), progress_path, label="Atlas initialization progress"
        )
        if progress.get("subject_labels") != plan["subject_labels"]:
            raise ConfigurationError("Initializer progress is not bound to the saved checkpoint.")
        indices = progress["completed_indices"]
        if len(indices) != len(set(indices)) or any(
            type(i) is not int or i not in range(len(plan["subject_labels"])) for i in indices
        ):
            raise ConfigurationError("Initializer progress contains invalid subject indices.")
        if progress.get("checkpoint_sha256") != sha256_file(
            source_run / "output/deformetrica-state.p"
        ):
            initialized = source_run / "output/atlas-initialized-state.p"
            if (early_review_enabled(plan)
                    or set(indices) != set(range(len(plan["subject_labels"])))
                    or not initialized.is_file()
                    or sha256_file(initialized) != progress.get("checkpoint_sha256")):
                raise ConfigurationError(
                    "Initializer progress is not bound to the saved checkpoint."
                )
        plan["completed_initialization_indices"] = indices
        screen_path = source_run / "output" / INITIAL_SCREEN
        if screen_path.exists():
            screened = load_strict_json_object(screen_path.read_bytes(), screen_path,
                                               label="Initial fit screen")
            _verify_initial_screen(source_run, plan, screened)
            if screened["pilot_indices"]:
                raise ConfigurationError("Flagged initial fits have no sealed review checkpoint.")
            plan["initial_fit_screen_binding"] = {
                "check_sha256": sha256_file(screen_path),
                "checkpoint_sha256": screened["checkpoint_sha256"],
            }


def adapter_source(config):
    plan = initialization(config)
    if not plan:
        return ""
    early_review_enabled(plan)
    if config["optimization"]["method"] != "gradient_ascent":
        raise ConfigurationError("Preserved-pilot initialization requires GradientAscent.")
    if not needs_adapter(config):
        raise ConfigurationError("Preserved-pilot initialization requires compact checkpoints.")
    if plan["method"] == REFINEMENT_METHOD and not (
        config["optimization"]["freeze_template"]
        and config["optimization"]["freeze_control_points"]
    ):
        raise ConfigurationError("Saved-atlas refinement requires a frozen template and controls.")
    screen = ""
    if plan.get("initial_fit_screen") == INITIAL_SCREEN_VERSION:
        screen = (
            "\n_DF_INITIAL_SCREEN_VERSION = " + repr(INITIAL_SCREEN_VERSION)
            + "\n_DF_INITIAL_SCREEN_WIDTH = " + repr(config["model"]["attachment"]["kernel_width"])
            + "\n_DF_INITIAL_REVIEW_PRIORITY = " + repr(REVIEW_PRIORITY)
            + "\n" + NATIVE_SCREEN + SCREEN_ADAPTER
        )
    return "\n_DF_ATLAS_PLAN = " + repr(plan) + "\n" + screen + ADAPTER


SCREEN_ADAPTER = """
def _df_screen_initial_fits(estimator, labels, pilot):
    def read_mesh(path):
        reader = vtk.vtkPolyDataReader()
        reader.SetFileName(path)
        reader.Update()
        poly = reader.GetOutput()
        if poly.GetNumberOfPolys() <= 0:
            raise ValueError("Initial fit screen could not read a staged surface")
        return poly

    indices = [i for i in range(len(labels)) if i not in pilot]
    root = _df_os.path.abspath(_df_os.path.join(estimator.output_dir, ".."))
    output = estimator.output_dir
    review_dir = _df_os.path.join(output, "initial-fit-review")
    screened, meshes = [], []
    if indices:
        import xml.etree.ElementTree as ET
        import torch
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk

        engine = _df_os.path.join(root, "engine")
        filename = ET.parse(_df_os.path.join(engine, "model.xml")).findtext(
            "template/object/filename")
        material = read_mesh(_df_os.path.normpath(_df_os.path.join(engine, filename)))
        model = estimator.statistical_model
        device, _ = _df_utilities.get_best_device(model.gpu_mode)
        data, points, controls, momenta = model._fixed_effects_to_torch_tensors(
            False, device=device)
        exponential = model.exponential
        with torch.no_grad():
            exponential.set_initial_template_points(points)
            exponential.set_initial_control_points(controls)
            for number, index in enumerate(indices, 1):
                _df_log.info("DiffeoForge initial fit screen: specimen %s of %s (%s)",
                             number, len(indices), labels[index])
                if labels[index] != _df_os.path.basename(labels[index]):
                    raise ValueError("Unsafe initial fit screen subject label")
                original = read_mesh(_df_os.path.join(root, "input", "subjects", labels[index]))
                exponential.set_initial_momenta(momenta[index])
                exponential.update()
                deformed = model.template.get_deformed_data(exponential.get_template_points(), data)
                coordinates = deformed["landmark_points"].detach().cpu().numpy()
                if coordinates.shape != (material.GetNumberOfPoints(), 3):
                    raise ValueError("Initial fit screen source connectivity differs")
                moved = vtk.vtkPoints()
                moved.SetData(numpy_to_vtk(coordinates, deep=True))
                fitted = vtk.vtkPolyData()
                fitted.ShallowCopy(material)
                fitted.SetPoints(moved)
                result = _df_initial_residuals(original, fitted, _DF_INITIAL_SCREEN_WIDTH)
                screened.append(dict(index=index, **result))
                if result["patches"]:
                    _df_os.makedirs(review_dir, exist_ok=True)
                    name = "fit-%04d.vtk" % index
                    model.template.write(review_dir, [name],
                                         {"landmark_points": coordinates})
                    relative = "initial-fit-review/" + name
                    meshes.append(dict(index=index, after=dict(index=index, path=relative,
                        sha256=_df_digest(_df_os.path.join(output, relative)))))
    required = [row["index"] for row in screened
                if row["priority"] >= _DF_INITIAL_REVIEW_PRIORITY]
    value = dict(version=_DF_INITIAL_SCREEN_VERSION, phase="initialization",
                 subject_labels=labels, pilot_indices=required,
                 iteration=int(estimator.current_iteration), screened=screened, meshes=meshes,
                 checkpoint_sha256=_df_digest(estimator.state_file))
    if required:
        _df_json_atomic(_df_os.path.join(output, "early-atlas-check.json"), value)
        _df_log.info("DiffeoForge initial fit screen: %s required reviews, %s additional "
                     "comparisons. Checkpoint saved before any joint iterations.",
                     len(required), len(meshes) - len(required))
        raise KeyboardInterrupt
    _df_json_atomic(_df_os.path.join(output, "initial-fit-screen.json"), value)
    _df_log.info("DiffeoForge initial fit screen finished: %s checked, %s advisory comparisons. "
                 "Starting the joint atlas.", len(indices), len(meshes))
"""


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
    screen_required = (_DF_ATLAS_PLAN.get("initial_fit_screen")
                       and not _DF_ATLAS_PLAN.get("initial_fit_screen_binding"))
    if (getattr(self, "_df_individual_initialization", False)
            or _DF_ATLAS_PLAN["early_review_approved"]
            or (not _DF_ATLAS_PLAN.get("early_review_enabled", True)
                and not screen_required
                and set(_DF_ATLAS_PLAN["completed_initialization_indices"])
                == set(range(len(_DF_ATLAS_PLAN["subject_labels"]))))):
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
    review_enabled = _DF_ATLAS_PLAN.get("early_review_enabled", True)
    before = _df_pilot_shapes(self, "before") if review_enabled else None
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
    if screen_required:
        if self.current_iteration != 0:
            raise RuntimeError("Initial fit screening requires the pre-joint checkpoint")
        _df_screen_initial_fits(self, labels, pilot)
    if not review_enabled:
        _df_log.info("DiffeoForge joint atlas: initialized %s of %s specimens; "
                     "optional early review disabled; continuing native optimization",
                     len(completed), len(labels))
        return _df_atlas_base_update(self, *args, **kwargs)
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
