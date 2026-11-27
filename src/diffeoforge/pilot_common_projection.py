"""An explicit two-step test of an approved shape on a fixed common deformation basis."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.config import load_config
from diffeoforge.guided_density import controls_for
from diffeoforge.guided_feedback import reference, verify_reference
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import _canonical_hash

VERSION = "approved-common-surface-transfer-v1"
BUDGET = 120


def _candidate(parent, ref):
    return next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])


def _has_composed_endpoint(candidate):
    from diffeoforge.regional_fit import read_plan

    return bool((read_plan(load_config(candidate.config_path)) or {}).get("residual"))


def offer(snapshot, candidate_id=None, *, target=None, value=None, approved_reference=None):
    """Only read saved evidence. A rejected common result may still supply the basis."""
    from diffeoforge.guided_feedback import region_state
    from diffeoforge.pilot_common_diagnosis import accepted_reference
    from diffeoforge.pilot_form_progress import is_common_check, transfer_marker

    record = snapshot.attachment_comparison or {}
    info = guided.record(snapshot) if record.get("guided") else None
    if not info or info["phase"] == "joint":
        return None
    name = target or info.get("target")
    value = value or transfer_marker(snapshot, name, approved_reference=approved_reference)
    if not value:
        return None
    accepted = accepted_reference(value, name)
    if accepted is None or (approved_reference is not None and accepted != approved_reference):
        return None
    individual = verify_reference(accepted)
    cand = _candidate(individual, accepted)
    if not individual.attachment_comparison.get("regional_objective"):
        return None
    if individual.visual_reviews.get(cand.candidate_id) is not True:
        return None
    if not _has_composed_endpoint(cand):
        return None
    basis = value["protocol"]["reference"]
    if is_common_check(info) and info.get("target") == name:
        if (info.get("strategy") or {}).get("approved_projection"):
            return None
        choices = [
            c for c in snapshot.candidates if not candidate_id or c.candidate_id == candidate_id
        ]
        if len(choices) != 1 or choices[0].status != "completed":
            return None
        reviewed = choices[0]
        if snapshot.visual_reviews.get(reviewed.candidate_id) is not False:
            return None  # First inspect any existing result; an accepted fit needs no transfer.
        if record.get("regional_objective"):
            return None
        basis = reference(snapshot, reviewed.candidate_id)
    if not _eligible_basis(basis, accepted):
        return None
    marks, _ = region_state(individual, cand.candidate_id, name)
    return dict(
        mode="project_approved",
        available=True,
        target=name,
        label="Test whether the common model preserves the approved shape",
        reason="Fit the shared model to the approved reconstruction and check its "
        "saved areas against the original. Review the transfer before deciding "
        "whether to fit the original specimen.",
        approved_reference=accepted,
        approved_regions_sha256=_canonical_hash(marks),
        approved_region_count=len(marks),
        basis_reference=basis,
        context_directory=str(snapshot.study_directory),
        context_manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        projection_iterations=BUDGET,
        original_iterations=BUDGET,
    )


def _eligible_basis(basis, accepted):
    from diffeoforge.pilot_common_basis import transferable_direct_field
    from diffeoforge.regional_fit import declaration

    parent, individual = verify_reference(basis), verify_reference(accepted)
    config = load_config(_candidate(parent, basis).config_path)
    return bool(
        parent.plan.pilot_subject_count == 1
        and (not parent.attachment_comparison.get("regional_objective")
             or (parent.visual_reviews.get(basis["candidate_id"]) is True and declaration(config)))
        and guided.record(parent)["origin"] == guided.record(individual)["origin"]
        and transferable_direct_field(config)
    )


def basis_configuration(parent, reference):
    """Use this verified basis's global settings for both projection stages."""
    cfg = load_config(_candidate(parent, reference).config_path)
    if parent.attachment_comparison.get("regional_objective"):
        from diffeoforge.reference_finite_accepted_guard import clear_runtime_markers

        origin = Path(guided.record(parent)["origin"])
        saved = study._verify_manifest(origin)
        cohort = load_config(study._safe_study_path(origin, saved["source_config"]["copy"]))
        cfg["project"]["parameter_provenance"].pop("regional_fit", None)
        clear_runtime_markers(cfg)
        cfg["optimization"] = dict(cohort["optimization"], freeze_template=True,
                                   freeze_control_points=True, convergence_tolerance=
                                   cfg["optimization"]["convergence_tolerance"])
    return cfg


def default_directory(snapshot, choice):
    digest = _canonical_hash(choice)
    return snapshot.study_directory / ("common-transfer-" + digest[:20])


def _sources(choice):
    """Resolve full material endpoint, common basis and true original independently."""
    from diffeoforge.regional_evaluation import endpoint

    a, b = choice["approved_reference"], choice["basis_reference"]
    approved, basis = verify_reference(a), verify_reference(b)
    if not _eligible_basis(b, a) or approved.visual_reviews.get(a["candidate_id"]) is not True:
        raise ValueError("The approved reference or the frozen common basis is unavailable")
    endpoint_row = endpoint(_candidate(approved, a), subject=a["target"])
    if not endpoint_row:
        raise ValueError("The approved composed fit has no verified complete surface endpoint")
    ma = study._verify_manifest(approved.study_directory)
    mb = study._verify_manifest(basis.study_directory)
    if ma["inputs"]["template"]["sha256"] != mb["inputs"]["template"]["sha256"]:
        raise ValueError("The common basis and approved deformation use different templates")
    template = ma["inputs"]["template"]
    target = next(item for item in ma["inputs"]["subjects"] if item["filename"] == a["target"])
    controls = controls_for(basis.attachment_comparison, b["candidate_id"])
    paths = {
        "template": (
            study._safe_study_path(approved.study_directory, template["copy"]),
            template["sha256"],
        ),
        "original": (
            study._safe_study_path(approved.study_directory, target["copy"]),
            target["sha256"],
        ),
        "approved": (Path(endpoint_row["path"]), endpoint_row["sha256"]),
        "controls": (
            study._safe_study_path(basis.study_directory, controls["copy"]),
            controls["sha256"],
        ),
    }
    # A published set of PCA coefficients or another specimen's momentum is never a seed.
    if b["target"] == a["target"]:
        c = _candidate(basis, b)
        same_subject = next(
            (s["sha256"] for s in mb["inputs"]["subjects"] if s["filename"] == b["target"]), None
        )
        if same_subject != target["sha256"]:
            raise ValueError("The candidate common field belongs to a different original")
        m = c.metrics or {}
        s = m.get("attachment_comparison", {}).get("subjects", {}).get(a["target"], {})
        ok = (
            m.get("invalid_face_count") == 0
            and bool(s)
            and not s.get("warnings")
            and not s.get("refinement_guard", {}).get("severe")
            and all(
                q.get("numerical_selection_suitable") is True
                for key in ("ordinary_quality", "cohort_quality", "regional_quality")
                if (q := s.get(key))
            )
        )
        if ok:
            import numpy as np

            from diffeoforge.guided_refinement import load_field

            f = load_field(study.calibration_candidate_run_directory(c))
            fixed = np.loadtxt(paths["controls"][0], ndmin=2)
            if (
                f.subject_labels != (a["target"],)
                or f.control_points.shape != fixed.shape
                or not np.allclose(f.control_points, fixed, atol=5.000001e-7, rtol=0)
                or not np.isfinite(f.momenta).all()
            ):
                raise ValueError("The proposed warm start does not preserve the frozen common grid")
            paths["initial"] = f.momenta_path, sha256_file(f.momenta_path)
    return paths, basis, mb["launcher"]


def prepare(snapshot, choice, directory):
    """Stage verified copies only. A published contract belongs to exactly one experiment."""
    from diffeoforge.guided_feedback import region_state

    root = Path(directory).resolve()
    with study.calibration_verification_scope():
        expected = offer(
            snapshot,
            choice["basis_reference"]["candidate_id"],
            target=choice["target"],
            approved_reference=choice["approved_reference"],
        )
        if choice != expected:
            raise ValueError("The transfer must use this specimen's current reviewed references")
        if root.exists():
            if contract(root)["choice"] != expected:
                raise ValueError("Transfer destination already belongs to another preparation")
            return root
        paths, basis, launcher = _sources(choice)
        a, b = choice["approved_reference"], choice["basis_reference"]
        approved = verify_reference(a)
        # The test asks whether this specific approved result and its marks survive.
        # Later corrections on a rejected common fit may refer to different material.
        marks = region_state(approved, a["candidate_id"], a["target"])[0]
        if _canonical_hash(marks) != choice["approved_regions_sha256"]:
            raise ValueError("The approved fit's marks changed while preparing the transfer")
        name = choice["target"]
        files = dict(
            template="inputs/template.vtk",
            approved="approved/" + name,
            original="original/" + name,
            controls="common-controls.txt",
            initial="initial-momenta.txt",
        )
        root.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root.parent, prefix="transfer-preparation-") as temp:
            stage = Path(temp) / "new"
            stage.mkdir()
            assets = {}
            for key, (src, digest) in paths.items():
                study._copy_bound(src, stage / files[key], digest)
                assets[key] = dict(copy=files[key], sha256=digest)
            cfg = basis_configuration(basis, b)
            cfg["input"].update(
                directory=str(root / "approved"),
                template=str(root / files["template"]),
                subject_pattern="*.vtk",
            )
            cfg["output"]["directory"] = str(root / "projection-runs")
            cfg["project"]["name"] = "Approved endpoint transfer"
            prov = cfg["project"]["parameter_provenance"]
            # Screen recording and preview artifacts belong to the reviewed original run.
            prov.pop("pilot_live_preview", None)
            prov.pop("pilot_review", None)
            deform = cfg["model"]["deformation"]
            deform["initial_control_points"] = str(root / files["controls"])
            deform.pop("initial_momenta", None)
            deform.pop("initial_momenta_subjects", None)
            if "initial" in paths:
                deform.update(
                    initial_momenta=str(root / files["initial"]), initial_momenta_subjects=[name]
                )
            cfg["optimization"].update(
                max_iterations=BUDGET, freeze_template=True, freeze_control_points=True
            )
            study._write_yaml(stage / "projection.yaml", cfg, overwrite=False)
            data = dict(
                version=VERSION,
                choice=deepcopy(choice),
                assets=assets,
                regions=deepcopy(marks),
                launcher=launcher,
                config_sha256=sha256_file(stage / "projection.yaml"),
                original_is_scientific_target=True,
                approval_transferred=False,
            )
            study._write_json(
                stage / "transfer.json", dict(data, sha256=_canonical_hash(data)), overwrite=False
            )
            try:
                stage.rename(root)
            except OSError:
                if not root.is_dir() or contract(root)["choice"] != expected:
                    raise
    return root


def contract(directory):
    root = Path(directory).resolve()
    d = study._read_json(root / "transfer.json", "common transfer contract")
    digest = d.pop("sha256")
    if digest != _canonical_hash(d) or d.get("version") != VERSION:
        raise ValueError("The approved shape transfer contract changed")
    return d


@study.calibration_verification_scope()
def verified_inputs(directory):
    root = Path(directory).resolve()
    d = contract(root)
    choice = d["choice"]
    if (
        _canonical_hash(d["regions"]) != choice["approved_regions_sha256"]
        or len(d["regions"]) != choice["approved_region_count"]
    ):
        raise ValueError("The saved approved marks differ from this transfer contract")
    context = Path(choice["context_directory"])
    if sha256_file(context / study.STUDY_MANIFEST) != choice["context_manifest_sha256"]:
        raise ValueError("The saved source pilot changed")
    assets, _, launcher = _sources(choice)
    if launcher != d["launcher"] or set(assets) != set(d["assets"]):
        raise ValueError("The native transfer inputs changed")
    for k, (src, digest) in assets.items():
        row = d["assets"][k]
        if (
            row["sha256"] != digest
            or sha256_file(src) != digest
            or sha256_file(study._safe_study_path(root, row["copy"])) != digest
        ):
            raise ValueError("The approved surface or common input bytes changed")
    if sha256_file(root / "projection.yaml") != d["config_sha256"]:
        raise ValueError("The native transfer configuration changed")
    return d


def _receipt(root, stage):
    path = Path(root) / f"{stage}-receipt.json"
    saved = study._read_json(path, "transfer result")
    digest = saved.pop("sha256")
    if digest != _canonical_hash(saved) or saved["contract_sha256"] != sha256_file(
        Path(root) / "transfer.json"
    ):
        raise ValueError("The common transfer result or its originating contract changed")
    return saved


def _store_receipt(root, stage, evidence):
    data = dict(evidence, contract_sha256=sha256_file(root / "transfer.json"))
    study._write_json(
        root / f"{stage}-receipt.json", dict(data, sha256=_canonical_hash(data)), overwrite=False
    )


def original_directory(directory):
    root = Path(directory)
    if not (root / "original-study.json").is_file():
        return None
    row = study._read_json(root / "original-study.json", "original-target singleton")
    path = study._safe_study_path(root, row["directory"])
    if sha256_file(path / study.STUDY_MANIFEST) != row["manifest_sha256"]:
        raise ValueError("Original-target singleton changed")
    return path


def status(directory):
    from diffeoforge.pilot_projection_worker import active, previous_projection

    root = Path(directory)
    d = contract(root)
    child = original_directory(root)
    result = dict(
        projection="pending",
        original="pending",
        approved=None,
        original_directory=str(child) if child else None,
        target=d["choice"]["target"],
        approved_reference=d["choice"]["approved_reference"],
        basis_reference=d["choice"]["basis_reference"],
    )
    for name in ("projection", "original"):
        if (root / f"{name}-receipt.json").exists():
            receipt = _receipt(root, name)
            result[name] = "completed"
            result[name + "_retention"] = receipt["retention"]
            result[name + "_numerical"] = receipt["endpoint"].get("numerical_checks", {})
        elif active(root, name):
            result[name] = "running"
        elif (root / (name + "-last-error.json")).exists():
            result[name] = "failed"
            result["message"] = study._read_json(
                root / (name + "-last-error.json"), "transfer failure"
            )["message"]
    if result["projection"] in {"pending", "failed"}:
        run, state = previous_projection(root)
        if state in {"unfinalized", "completed", "interrupted"}:
            result["projection"] = {"unfinalized": "recovery", "completed": "verify_saved",
                                    "interrupted": "interrupted"}[state]
            result["previous_run"] = str(run)
            if state != "completed":
                result.pop("message", None)
    if child:
        snapshot = study.load_reference_calibration_study(child)
        result["approved"] = snapshot.visual_reviews.get(snapshot.candidates[0].candidate_id)
    result["can_fit_original"] = (
        result.get("projection_retention", {}).get("status") == "comparable"
        and result.get("projection_numerical", {}).get("passed") is True
    )
    result["can_attach"] = (
        result.get("original_retention", {}).get("status") == "comparable"
        and result.get("original_numerical", {}).get("passed") is True
        and result.get("approved") is True
    )
    return result


def _evidence(root, run, stage, d):
    import numpy as np

    from diffeoforge.guided_refinement import load_field
    from diffeoforge.pilot_common_model import physics
    from diffeoforge.reference_calibration_metrics import (
        _collect_reference_calibration_metrics_from_report,
    )

    force_sha = d["assets"]["approved" if stage == "projection" else "original"]["sha256"]
    field = load_field(run)
    report = field.run_report
    name = d["choice"]["target"]
    inputs = {
        r["role"]: r["geometry"]["sha256"]
        for r in report.manifest["inputs"]
        if r["role"] in {"template", "subject"}
    }
    grid = np.loadtxt(root / d["assets"]["controls"]["copy"], ndmin=2)
    if (
        inputs != {"template": d["assets"]["template"]["sha256"], "subject": force_sha}
        or field.subject_labels != (name,)
        or field.control_points.shape != grid.shape
        or not np.allclose(field.control_points, grid, atol=5.000001e-7, rtol=0)
        or field.momenta.shape != (1, len(grid), 3)
        or not np.isfinite(field.momenta).all()
        or report.max_iterations != BUDGET
    ):
        raise ValueError(
            "The native result did not preserve its declared target, controls or budget"
        )
    config = report.manifest["effective_config"]
    if physics(config) != physics(load_config(root / "projection.yaml")):
        raise ValueError("The transfer changed the common model or optimizer settings")
    if not all(config["optimization"][k] for k in ("freeze_template", "freeze_control_points")):
        raise ValueError("The transfer must keep the template and common controls frozen")
    m = _collect_reference_calibration_metrics_from_report(report)
    if m.invalid_face_count != 0:
        raise ValueError("Transfer output has degenerate surface faces")
    marker = "__Reconstruction__" + config["model"]["object_id"] + "__subject_" + name + ".vtk"
    rows = [r for r in report.inventory if r["path"].endswith(marker)]
    if len(rows) != 1:
        raise ValueError("Transfer output requires one reconstruction for this specimen")
    row = rows[0]
    endpoint = study._safe_study_path(run / "output", row["path"])
    if sha256_file(endpoint) != row["sha256"]:
        raise ValueError("The transfer endpoint changed")
    return dict(
        stage=stage,
        target=name,
        path=str(endpoint),
        sha256=row["sha256"],
        run_directory=str(run),
        manifest_sha256=sha256_file(run / "manifest.json"),
        momenta_path=str(field.momenta_path),
        momenta_sha256=sha256_file(field.momenta_path),
        control_points_sha256=d["assets"]["controls"]["sha256"],
        original_sha256=d["assets"]["original"]["sha256"],
        template_sha256=d["assets"]["template"]["sha256"],
        approved_reference=d["choice"]["approved_reference"],
        basis_reference=d["choice"]["basis_reference"],
    )


def _check_numerics(source_path, endpoint, field, cancelled):
    import numpy as np

    from diffeoforge.mesh_filter_worker import run_mesh_filter
    from diffeoforge.surface_io import load_surface_mesh

    if cancelled():
        raise InterruptedError("Transfer surface checks cancelled")
    source = load_surface_mesh(source_path).geometry
    output = load_surface_mesh(endpoint["path"]).geometry
    same_material_faces = np.array_equal(source.triangles, output.triangles)
    if not same_material_faces:
        return dict(passed=False, reason="Native output changed the triangle correspondence")
    flags = [
        run_mesh_filter(
            "intersections",
            vertices=np.asarray(m.vertices, float),
            faces=np.asarray(m.triangles, int),
        )["faces"]
        for m in (source, output)
    ]
    new = len(np.setdiff1d(flags[1], flags[0]))
    return dict(
        passed=new == 0 and field.get("passed", True),
        degenerate_faces=0,
        new_intersection_faces=new,
        initial_intersection_faces=len(flags[0]),
        fixed_field_quality=field,
    )


def verified_endpoint(directory, stage):
    if stage not in ("projection", "original"):
        raise ValueError("Unknown transfer stage")
    root = Path(directory).resolve()
    d = verified_inputs(root)
    receipt = _receipt(root, stage)
    saved = receipt["endpoint"]
    run = Path(saved["run_directory"]).resolve()
    if stage == "projection" and run.parent != (root / "projection-runs").resolve():
        raise ValueError("Projection evidence belongs to another experiment")
    if stage == "original":
        child = original_directory(root)
        if not child or not run.resolve().is_relative_to(child.resolve()):
            raise ValueError("Original-target evidence belongs to another experiment")
    output = (run / "output").resolve()
    if any(
        not Path(saved[key]).resolve().is_relative_to(output) for key in ("path", "momenta_path")
    ):
        raise ValueError("The native surface or momentum does not belong to this run")
    if not all(
        sha256_file(Path(path)) == digest
        for path, digest in (
            (saved["path"], saved["sha256"]),
            (run / "manifest.json", saved["manifest_sha256"]),
            (saved["momenta_path"], saved["momenta_sha256"]),
            (run / "result.json", receipt["result_sha256"]),
            (run / "output-inventory.json", receipt["inventory_sha256"]),
        )
    ):
        raise ValueError("The bound native transfer output changed")
    if not (
        saved["original_sha256"] == d["assets"]["original"]["sha256"]
        and saved["approved_reference"] == d["choice"]["approved_reference"]
        and saved["basis_reference"] == d["choice"]["basis_reference"]
        and saved["template_sha256"] == d["assets"]["template"]["sha256"]
        and saved["control_points_sha256"] == d["assets"]["controls"]["sha256"]
        and saved["target"] == d["choice"]["target"]
        and saved["stage"] == stage
    ):
        raise ValueError("The native endpoint does not belong to this approved reference")
    return dict(saved, retention=receipt["retention"])


class ProjectionRunner:
    """One explicit bounded action at a time, supervised by the existing native worker."""

    def __init__(self, directory, *, controller_factory=None):
        from threading import Event

        from diffeoforge.desktop.reference_execution_controller import ReferenceExecutionController

        self.directory = Path(directory).resolve()
        self._factory = controller_factory or ReferenceExecutionController
        self._cancel = Event()
        self._controller = None

    def request_cancel(self):
        self._cancel.set()
        if self._controller:
            self._controller.request_cancel()
        return True

    def run_projection(self, event_callback=None):
        return self._run("projection", event_callback)

    def run_original(self, event_callback=None):
        return self._run("original", event_callback)

    def _run(self, stage, callback):

        root = self.directory
        from diffeoforge.pilot_projection_worker import stage_lock

        with stage_lock(root, stage):
            return self._run_locked(root, stage, callback)

    def _run_locked(self, root, stage, callback):
        from uuid import uuid4

        from diffeoforge.anatomy_retention import compare_approved_endpoint
        from diffeoforge.mesh_filter_worker import mesh_filter_cancellation
        from diffeoforge.pilot_projection_worker import _native_run

        try:
            with mesh_filter_cancellation(self._cancel.is_set):
                if (root / f"{stage}-receipt.json").exists():
                    return verified_endpoint(root, stage)
                d = verified_inputs(root)
                if self._cancel.is_set():
                    raise InterruptedError("Transfer cancelled before native dispatch")
                if stage == "projection":
                    run = _native_run(root, self, d, callback)
                else:
                    proj = verified_endpoint(root, "projection")
                    if (
                        proj["retention"]["status"] != "comparable"
                        or not proj["numerical_checks"]["passed"]
                    ):
                        raise ValueError(
                            "The projected shape did not preserve all assessed anatomy. "
                            "Inspect the transfer before testing a different common model."
                        )
                    from diffeoforge.pilot_common_projection_child import prepare_original

                    child = prepare_original(root)
                    snapshot = study.load_reference_calibration_study(child)
                    if snapshot.candidates[0].status != "completed":
                        runner = study.ReferenceCalibrationStudyRunner(
                            child, controller_factory=self._factory
                        )
                        self._controller = runner
                        if self._cancel.is_set():
                            runner.request_cancel()
                        snapshot = runner.run_current_stage(event_callback=callback)
                    candidate = snapshot.candidates[0]
                    if candidate.status != "completed":
                        detail = candidate.error or candidate.status
                        raise ValueError(f"The native original-target fit stopped ({detail})")
                    run = study.calibration_candidate_run_directory(candidate)
                if callback:
                    callback(dict(event="qualification_phase",
                                  message="Checking the fitted shape and saved areas…"))
                endpoint = _evidence(root, run, stage, d)
                field_quality = {}
                if stage == "original":
                    from diffeoforge.guided_feedback import severe_regression

                    field_quality["passed"] = not severe_regression(
                        snapshot, candidate.candidate_id
                    )
                    subject = (
                        (candidate.metrics or {})
                        .get("attachment_comparison", {})
                        .get("subjects", {})
                        .get(endpoint["target"], {})
                    )
                    field_quality["warnings"] = subject.get("warnings", [])
                else:
                    from diffeoforge.reference_ordinary_guard import DECLARATION

                    cfg = load_config(root / "projection.yaml")
                    if (
                        cfg["project"]["parameter_provenance"].get("finite_accepted_guard")
                        == DECLARATION
                    ):
                        from diffeoforge.ordinary_field_quality import qualify

                        quality = qualify(
                            run,
                            root / ("fixed-field-" + uuid4().hex[:12]),
                            cancelled=self._cancel.is_set,
                            event_callback=callback,
                        )
                        field_quality["passed"] = quality["numerical_selection_suitable"]
                        for key in (
                            "spatial_resolution_sufficient",
                            "temporal_grid_stable",
                            "optimizer_grid_accuracy",
                            "native_export_reproduction",
                        ):
                            if key in quality:
                                field_quality[key] = quality[key]
                endpoint["numerical_checks"] = _check_numerics(
                    root / d["assets"]["template"]["copy"],
                    endpoint,
                    field_quality,
                    self._cancel.is_set,
                )
                if self._cancel.is_set():
                    raise InterruptedError("Transfer inspection cancelled")
                retention = compare_approved_endpoint(
                    endpoint["approved_reference"],
                    endpoint["path"],
                    endpoint["sha256"],
                    regions=d["regions"],
                    stage=stage,
                    material_template_sha256=endpoint["template_sha256"],
                    cancelled=self._cancel.is_set,
                )
                _store_receipt(
                    root,
                    stage,
                    dict(
                        endpoint=endpoint,
                        retention=retention,
                        result_sha256=sha256_file(run / "result.json"),
                        inventory_sha256=sha256_file(run / "output-inventory.json"),
                    ),
                )
                return dict(endpoint, retention=retention)
        except Exception as exc:
            study._write_json(
                root / (stage + "-last-error.json"), dict(message=str(exc)), overwrite=True
            )
            raise
        finally:
            self._controller = None


def attach_original(directory, snapshot):
    """Link a reviewed original-target child, without rewriting either fit or approval."""
    from diffeoforge.guided_feedback import severe_regression

    root = Path(directory).resolve()
    endpoint = verified_endpoint(root, "original")
    if (
        endpoint["retention"]["status"] != "comparable"
        or not endpoint["numerical_checks"]["passed"]
    ):
        raise ValueError("The fit to the original lost reviewed anatomy and cannot advance")
    d = contract(root)
    parent = snapshot.study_directory.resolve()
    if (
        parent != Path(d["choice"]["context_directory"]).resolve()
        or sha256_file(parent / study.STUDY_MANIFEST) != d["choice"]["context_manifest_sha256"]
    ):
        raise ValueError("Open the exact pilot where this transfer was prepared")
    lock = parent / "guided-transition-active.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ValueError("A guided transition is active or needs explicit recovery") from exc
    try:
        child = original_directory(root)
        old = study.load_reference_calibration_study(parent)
        result = study.load_reference_calibration_study(child)
        candidate = result.candidates[0]
        if (
            guided.record(result)["origin"] != guided.record(old)["origin"]
            or candidate.status != "completed"
            or result.visual_reviews.get(candidate.candidate_id) is not True
            or severe_regression(result, candidate.candidate_id)
        ):
            raise ValueError(
                "This original-target fit requires passing checks and explicit visual approval"
            )
        guided._approved_record(result, candidate.candidate_id)
        pointer = parent / "fit-search-latest.json"
        if pointer.exists():
            previous = study._read_json(pointer, "current pilot successor")
            if Path(previous["directory"]).resolve() != child or previous[
                "manifest_sha256"
            ] != sha256_file(child / study.STUDY_MANIFEST):
                raise ValueError(
                    "The pilot already advanced to another successor. "
                    "Open the saved transfer separately."
                )
        else:
            guided._pointer(parent, child)
        existing = study._load_events(parent)
        if not any(
            e["event"] == "guided_pilot_decision"
            and e.get("action") == "attach_approved_projection"
            and e.get("next_directory") == str(child)
            for e in existing
        ):
            study._append_event(
                parent,
                "guided_pilot_decision",
                dict(
                    action="attach_approved_projection",
                    candidate_id=candidate.candidate_id,
                    next_directory=str(child),
                    next_manifest_sha256=sha256_file(child / study.STUDY_MANIFEST),
                    anatomical_approval_created=False,
                    optimizer_started=False,
                ),
            )
        return child
    finally:
        lock.rmdir()
