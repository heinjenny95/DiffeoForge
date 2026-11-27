"""Prepare a separate, short fixed-basis check for specimens outside a saved pilot."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

import yaml

from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_atlas_handoff import (
    METHOD,
    _direct_joint_configuration,
    direct_joint_source_path,
    initialization,
)
from diffeoforge.reference_calibration import select_representative_pilot_subjects
from diffeoforge.reference_calibration_study import (
    STUDY_MANIFEST,
    _verify_manifest,
    calibration_verification_scope,
)
from diffeoforge.reference_recommendation import recommend_reference_parameters
from diffeoforge.runs import _prepare_run

SUBJECT_LIMIT = 3
ITERATION_LIMIT = 120
RUN_ID = "pre-atlas-heldout-check"


@dataclass(frozen=True)
class PreparedPilotHoldout:
    run_directory: Path
    specimens: tuple[str, ...]
    maximum_iterations: int


def _pilot_history(study: Path) -> tuple[set[str], set[str]]:
    """Exclude selected subjects and exact duplicate geometry from verified ancestors."""
    names, digests = set(), set()
    while True:
        manifest = _verify_manifest(study)
        for record in manifest["plan"]["selected_pilot_subjects"]:
            names.add(record["filename"].casefold())
            digests.add(record["sha256"])
        source = manifest.get("search_extension_source")
        if source is None:
            return names, digests
        study = Path(source["study_directory"]).resolve()


def _copy_bound(source: Path, target: Path, digest: str) -> None:
    shutil.copy2(source, target)
    if sha256_file(target) != digest:
        raise ConfigurationError("A selected held-out input changed during staging.")


def prepare_pilot_holdout(
    config_path: Path | str,
    *,
    destination: Path | str | None = None,
    cancelled: Event | None = None,
) -> PreparedPilotHoldout:
    """Create a verified, explicitly executable run. Never start a process."""
    source = Path(config_path).expanduser().resolve()
    config = load_config(source)
    plan = initialization(config)
    if plan is None or plan["method"] != METHOD:
        raise ConfigurationError(
            "This check requires an approved saved pilot with exact specimen provenance. "
            "Open a completed preserved-pilot setup."
        )
    if plan.get("direct_joint_start"):
        source = direct_joint_source_path(source, plan["direct_joint_start"])
        config = load_config(source)
        plan = initialization(config)

    def require_active() -> None:
        if cancelled is not None and cancelled.is_set():
            raise ConfigurationError("Held-out check preparation was cancelled.")

    # Validate the same approved decision, native result, and bound full-cohort
    # input bytes as Direct start. This synthetic variant is never written.
    study = source.parent.parent
    with calibration_verification_scope():
        direct = _direct_joint_configuration(config, source)
        inputs = validate_input_paths(direct, source.with_name(f".probe-{uuid4().hex}.yaml"))
        seen_names, seen_hashes = _pilot_history(study)
    require_active()

    expected = plan["subject_sha256"]
    recommendation = config["project"]["parameter_provenance"]["recommendation"]
    seen_names.update(name.casefold() for name in plan["pilot_subject_labels"])
    seen_hashes.update(expected[name] for name in plan["pilot_subject_labels"])
    seen_hashes.update((plan["template_sha256"], recommendation["calibration_plan"][
        "template_sha256"
    ]))
    eligible = []
    for path in inputs.subjects:
        digest = expected[path.name]
        if path.name.casefold() not in seen_names and digest not in seen_hashes:
            eligible.append(path)
        seen_hashes.add(digest)
    if len(eligible) < 2:
        raise ConfigurationError(
            "The current cohort has fewer than two distinct surfaces outside this pilot history."
        )
    geometry = recommend_reference_parameters(
        (inputs.template, *eligible), alignment_basis="declared_gpa",
        surface_detail_intent=recommendation["surface_detail_intent"],
        deformation_scale_intent=recommendation["deformation_scale_intent"],
    )
    if any(expected[row.filename] != row.sha256 for row in geometry.observations[1:]):
        raise ConfigurationError("A held-out candidate changed after pilot verification.")
    by_name = {path.name: path for path in eligible}
    chosen = select_representative_pilot_subjects(
        geometry, requested_count=min(SUBJECT_LIMIT, len(eligible)),
    )
    selected = {row.filename: expected[row.filename] for row in chosen}
    require_active()

    probe = deepcopy(config)
    probe["project"] = {"name": config["project"]["name"] + " held-out check"}
    probe["input"].update(directory="./subjects", template="./starting-template.vtk",
                          subject_pattern="*.vtk")
    deformation = probe["model"]["deformation"]
    deformation["initial_control_points"] = "./starting-control-points.txt"
    for key in ("initial_momenta", "initial_momenta_subjects"):
        deformation.pop(key, None)
    optimization = probe["optimization"]
    cap = min(ITERATION_LIMIT, optimization["max_iterations"])
    optimization.update(freeze_template=True, freeze_control_points=True, max_iterations=cap)
    # Preserve the numerical configuration and use the normal protected final export.
    probe["output"].update(directory="./runs", checkpoint_mode="compact_final_export")
    provenance = {
        "source_setup_sha256": initialization(direct)["direct_joint_start"]["source_config_sha256"],
        "pilot_study_manifest_sha256": sha256_file(study / STUDY_MANIFEST),
        "pilot_run_manifest_sha256": plan["source_run_manifest_sha256"],
        "excluded_pilot_names": sorted(seen_names),
        "selected_specimens": selected,
        "selection": "deterministic surface-shape medoid and farthest-first",
        "maximum_iterations": cap,
        "scope": "Fixed template and controls. Only momenta estimated. "
                 "Descriptive geometric screening outside the recorded pilot history.",
    }
    # Sibling output keeps the preparation and its results away from the full atlas.
    requested = (
        study.with_name(f"{study.name}-heldout-{uuid4().hex[:10]}")
        if destination is None else Path(destination).expanduser()
    )
    if requested.exists() or requested.is_symlink():
        raise ConfigurationError("Choose a new held-out run destination.")
    destination = requested.resolve()
    if (
        not destination.parent.is_dir()
        or destination.is_relative_to(study)
        or destination.is_relative_to(inputs.input_directory)
    ):
        raise ConfigurationError("Choose a private destination outside the pilot and its inputs.")

    def verify_staging(run, manifest):
        require_active()
        subjects = {Path(row["staged_path"]).name: row["geometry"]["sha256"]
                    for row in manifest["inputs"] if row["role"] == "subject"}
        if subjects != selected:
            raise ConfigurationError("The prepared run does not contain the exact held-out cohort.")
        template = next(row for row in manifest["inputs"] if row["role"] == "template")
        controls = run / "input" / "control-points" / "starting-control-points.txt"
        if (
            template["geometry"]["sha256"] != plan["template_sha256"]
            or sha256_file(controls) != plan["control_points_sha256"]
        ):
            raise ConfigurationError("The prepared held-out check differs from the pilot basis.")

    with TemporaryDirectory(prefix=".preparing-heldout-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        cohort = staging / "subjects"
        cohort.mkdir()
        _copy_bound(inputs.template, staging / "starting-template.vtk", plan["template_sha256"])
        _copy_bound(inputs.initial_control_points, staging / "starting-control-points.txt",
                    plan["control_points_sha256"])
        for name, digest in selected.items():
            require_active()
            _copy_bound(by_name[name], cohort / name, digest)
        spec = staging / "atlas.yaml"
        provenance_comments = "".join(
            f"# {line}\n" for line in json.dumps(provenance, indent=2, sort_keys=True).splitlines()
        )
        spec.write_text(
            provenance_comments + yaml.safe_dump(probe, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        require_active()
        destination.mkdir(exist_ok=False)
        try:
            result = _prepare_run(
                spec, run_id=RUN_ID, output_directory=destination, before_publish=verify_staging,
            )
        except Exception:
            if not any(destination.iterdir()):
                destination.rmdir()
            raise
    return PreparedPilotHoldout(result, tuple(selected), cap)
