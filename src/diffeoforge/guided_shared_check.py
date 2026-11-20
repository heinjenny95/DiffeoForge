"""Explicit common-objective check initialized by an approved local field.

Local suitability is retained as local evidence. No common-model approval is
created by preparing the check, copying coefficients or retaining the time grid.
"""

from diffeoforge.config import load_config

VERSION = "local-field-shared-check-v1"


def declaration(snapshot, identifier):
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_strategy import _reference
    from diffeoforge.regional_fit import read_plan

    if not snapshot.attachment_comparison.get("regional_objective"):
        raise ValueError("Choose an approved local fit for this explicit model check")
    guided._approved_record(snapshot, identifier)
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    config = load_config(candidate.config_path)
    regional = read_plan(config)
    if not regional or regional.get("residual"):
        raise ValueError("This composed residual cannot initialize the standard model alone. "
                         "Keep this fit and inspect its retained original-basis starting fit.")
    if not all(config["optimization"][key]
               for key in ("freeze_template", "freeze_control_points")):
        raise ValueError("This check requires a saved field on the original fixed basis")
    return dict(version=VERSION, reference=_reference(snapshot, identifier),
                integration={k: config["model"]["deformation"][k]
                             for k in ("timepoints", "use_rk2")},
                precision=config["runtime"]["precision"], initialization_only=True,
                regional_approval_transferred=False)


def preview(snapshot, identifier):
    try:
        marker = declaration(snapshot, identifier)
        return dict(available=True, integration=marker["integration"])
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return dict(available=False, reason=str(error))


def configure(config, marker, cohort_method):
    """Retain the declared numerical model; use the ordinary cohort objective."""
    from diffeoforge.reference_finite_accepted_guard import clear_runtime_markers

    config["project"]["parameter_provenance"].pop("regional_fit", None)
    clear_runtime_markers(config)
    config["optimization"]["method"] = cohort_method
    config["model"]["deformation"].update(marker["integration"])
    config["runtime"]["precision"] = marker["precision"]


def compatible(marker, candidate):
    config = load_config(candidate.config_path)
    return (all(config["model"]["deformation"][k] == v
                for k, v in marker["integration"].items())
            and config["runtime"]["precision"] == marker["precision"])


def verify(info, record, manifest, root):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.guided_feedback import verify_reference

    marker = info["strategy"]["shared_model_check"]
    ref = marker["reference"]
    parent = verify_reference(ref)
    if marker != declaration(parent, ref["candidate_id"]):
        raise ValueError("The approved local field or shared-check numerical settings changed")
    if guided.record(parent)["origin"] != info["origin"]:
        raise ValueError("Shared-model initialization belongs to another pilot cohort")
    if record.get("regional_objective") and info.get("goal") != "shared_check":
        return  # A later explicit local trial retains its own verified numerical protocol.
    config = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    if (any(config["model"]["deformation"][k] != v
            for k, v in marker["integration"].items())
            or config["runtime"]["precision"] != marker["precision"]):
        raise ValueError("Shared check must preserve the saved field's numerical model")
    if info.get("goal") == "shared_check":
        from diffeoforge.reference_attachment_comparison import ITERATIONS

        refinement = record.get("refinement", {})
        if (info["phase"] != "refine" or info["target"] != ref["target"]
                or record.get("regional_objective")
                or refinement.get("reference") != ref
                or refinement.get("initialization") != "learned"
                or record["iterations"] != ITERATIONS
                or info["strategy"].get("baseline") != ref):
            raise ValueError("Shared check requires the complete retained field, not a fresh start")

