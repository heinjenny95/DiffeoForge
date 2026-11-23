"""Verify projected frozen coefficients and build a fresh original-target pilot singleton."""

from copy import deepcopy
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_feedback import verify_reference
from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_common_projection import BUDGET, VERSION


def mark(record):
    return (record.get("guided", {}).get("strategy") or {}).get("approved_projection")


def bind(root, manifest, record):
    from diffeoforge.pilot_common_projection import verified_endpoint

    request = mark(record)
    if not request:
        return record
    point = verified_endpoint(request["directory"], "projection")
    if point["retention"]["status"] != "comparable" or not point["numerical_checks"]["passed"]:
        raise ValueError("A projected start requires complete retained-anatomy measurements")
    if (
        len(manifest["inputs"]["subjects"]) != 1
        or manifest["inputs"]["subjects"][0]["sha256"] != point["original_sha256"]
        or manifest["inputs"]["subjects"][0]["filename"] != point["target"]
        or manifest["inputs"]["template"]["sha256"] != point["template_sha256"]
        or record["controls"]["sha256"] != point["control_points_sha256"]
    ):
        raise ValueError("The projection cannot initialize another original or grid")
    source = Path(point["momenta_path"])
    path = root / "projected-initial-momenta.txt"
    study._copy_bound(source, path, point["momenta_sha256"])
    return dict(
        record, projected_initial_momenta=dict(copy=path.name, sha256=point["momenta_sha256"])
    )


def configure(config, root, record):
    request = mark(record)
    if request:
        row = record["projected_initial_momenta"]
        config["model"]["deformation"].update(
            initial_momenta=str(root / row["copy"]),
            initial_momenta_subjects=[record["guided"]["target"]],
        )


def verify(info, record, manifest, root):
    from diffeoforge.pilot_common_model import physics
    from diffeoforge.pilot_common_projection import contract, verified_endpoint

    request = mark(record)
    if not request:
        return
    transfer = Path(request["directory"])
    point = verified_endpoint(transfer, "projection")
    d = contract(transfer)
    choice = d["choice"]
    vals = manifest["plan"]["baseline_effective_values"]
    ref = point["basis_reference"]
    parent = verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    source = load_config(study._safe_study_path(root, manifest["source_config"]["copy"]))
    row = record["projected_initial_momenta"]
    previous = info["strategy"]["previous"]
    if (
        request
        != {
            "version": VERSION,
            "directory": str(transfer),
            "contract_sha256": sha256_file(transfer / "transfer.json"),
            "receipt_sha256": sha256_file(transfer / "projection-receipt.json"),
        }
        or point["retention"]["status"] != "comparable"
        or not point["numerical_checks"]["passed"]
        or previous
        != {
            "directory": choice["context_directory"],
            "manifest_sha256": choice["context_manifest_sha256"],
        }
        or info["goal"] != "form_model_check"
        or info["phase"] != "validate"
        or vals != ref["values"]
        or info["target"] != point["target"]
        or len(manifest["inputs"]["subjects"]) != 1
        or manifest["inputs"]["subjects"][0]["sha256"] != point["original_sha256"]
        or manifest["inputs"]["template"]["sha256"] != point["template_sha256"]
        or record["controls"]["sha256"] != point["control_points_sha256"]
        or set(record["methods"].values()) != {ref["method"]}
        or record.get("regional_objective")
        or record.get("refinement")
        or record["iterations"] != BUDGET
        or physics(source) != physics(load_config(candidate.config_path))
        or sha256_file(study._safe_study_path(root, row["copy"])) != point["momenta_sha256"]
        or row["sha256"] != point["momenta_sha256"]
    ):
        raise ValueError(
            "The new original-target check differs from its verified shared projection"
        )


def prepare_original(directory):
    from diffeoforge.pilot_common_projection import contract, original_directory, verified_endpoint
    from diffeoforge.pilot_form_progress import transfer_marker

    root = Path(directory).resolve()
    ready = original_directory(root)
    if ready:
        return ready
    with study.calibration_verification_scope():
        endpoint = verified_endpoint(root, "projection")
        if (
            endpoint["retention"]["status"] != "comparable"
            or not endpoint["numerical_checks"]["passed"]
        ):
            raise ValueError("The projected fit did not preserve the measured anatomy")
        d = contract(root)
        parent = study.load_reference_calibration_study(Path(d["choice"]["context_directory"]))
        info = guided.record(parent)
        progress = transfer_marker(parent, endpoint["target"], endpoint["approved_reference"])
        if not progress:
            raise ValueError("The common-model plan is no longer available")
        previous = dict(
            directory=str(parent.study_directory),
            manifest_sha256=sha256_file(parent.study_directory / study.STUDY_MANIFEST),
        )
        decl = dict(
            directory=str(root),
            version=VERSION,
            contract_sha256=sha256_file(root / "transfer.json"),
            receipt_sha256=sha256_file(root / "projection-receipt.json"),
        )
        ref = endpoint["basis_reference"]
        strategy = dict(
            previous=previous,
            form_progress=deepcopy(progress),
            control_basis=ref,
            approved_projection=decl,
            preference=None,
        )
        if (info.get("strategy") or {}).get("correction_policy"):
            strategy["correction_policy"] = info["strategy"]["correction_policy"]
        source, _ = guided._origin(parent.study_directory)
        # Prepare in the new experiment; the owner's active project pointer has not changed.
        result = guided._batch(
            source,
            None,
            phase="validate",
            target=endpoint["target"],
            methods=(ref["method"],),
            values=ref["values"],
            approved=info["approved"],
            history=[*info["history"], dict(previous, outcome="adaptive_approved_projection")],
            spent=info["screen_trials_spent"],
            goal="form_model_check",
            strategy=strategy,
            destination_parent=root,
        )
        path = result.study_directory
        study._write_json(
            root / "original-study.json",
            dict(directory=path.name, manifest_sha256=sha256_file(path / study.STUDY_MANIFEST)),
            overwrite=False,
        )
        return path
