"""Prospective Deformetrica Shooting designs for reference PCA shape endpoints."""

from __future__ import annotations

import json
import math
import shutil
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    REFERENCE_PCA_MANIFEST,
    ReferencePCAError,
    load_reference_momenta,
    verify_reference_pca_bundle,
)
from diffeoforge.runs import publish_directory_exclusive
from diffeoforge.strict_json import load_strict_json_object

DESIGN_VERSION = "0.1"
DESIGN_NAME = "reference-pca-deformation-design.json"
DESIGN_SIDECAR = "reference-pca-deformation-design.sha256"
DEFAULT_DIRECTORY_NAME = "reference-pca-deformations-v0.1"
DEFORMATION_EQUATION = (
    "mean_momenta +/- standard_deviations * sqrt(explained_variance) * "
    "component_loading"
)
SCIENTIFIC_BOUNDARY = (
    "This prospective design defines Deformetrica Shooting endpoints in the exact "
    "verified reference-momenta feature space. Component signs are conventional; "
    "endpoints are visualizations, not observed specimens, confidence intervals, "
    "biological effects, or evidence of group separation. No endpoint mesh exists "
    "until the separately supervised Shooting execution completes and is verified."
)


class ReferencePCADeformationError(RuntimeError):
    """Raised when a reference PCA deformation design is invalid."""


def _positive_real(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real scalar")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _artifact(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            value,
            handle,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")


def _write_momenta(path: Path, values: np.ndarray) -> None:
    if values.ndim != 3 or values.shape[2] != 3:
        raise ValueError("Shooting momenta must have shape (endpoints, control points, 3)")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{values.shape[0]} {values.shape[1]} 3\n")
        for endpoint in values:
            handle.write("\n")
            for row in endpoint:
                handle.write(" ".join(format(float(value), ".17g") for value in row))
                handle.write("\n")


def _estimated_template_record(inventory: tuple[Mapping[str, object], ...]):
    matches = tuple(
        record
        for record in inventory
        if "__EstimatedParameters__Template_" in PurePosixPath(str(record["path"])).name
        and PurePosixPath(str(record["path"])).suffix.casefold() == ".vtk"
    )
    if len(matches) != 1:
        raise ReferencePCADeformationError(
            "Reference PCA deformation design requires exactly one estimated VTK "
            f"template; found {len(matches)}"
        )
    return matches[0]


def _safe_output_path(run: Path, record: Mapping[str, object]) -> Path:
    relative = PurePosixPath(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ReferencePCADeformationError("Estimated-template inventory path is unsafe")
    path = run / "output" / Path(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise ReferencePCADeformationError("Estimated reference template is missing or symbolic")
    if path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(
        record["sha256"]
    ):
        raise ReferencePCADeformationError(
            "Estimated reference template differs from the verified output inventory"
        )
    return path


def _render_shooting_model(source: bytes) -> bytes:
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ReferencePCADeformationError(
            f"Source Deformetrica model XML is invalid: {error}"
        ) from error
    if root.tag.casefold() != "model":
        raise ReferencePCADeformationError("Source Deformetrica XML has no model root")
    model_type = root.find("model-type")
    template_filename = root.find("./template/object/filename")
    if model_type is None or template_filename is None:
        raise ReferencePCADeformationError(
            "Source Deformetrica model lacks model type or template filename"
        )
    model_type.text = "Shooting"
    template_filename.text = "../source/estimated-template.vtk"
    for tag in ("initial-control-points", "initial-momenta"):
        existing = root.find(tag)
        if existing is not None:
            root.remove(existing)
    template_index = list(root).index(root.find("template"))
    controls = ET.Element("initial-control-points")
    controls.text = "../source/control-points.txt"
    momenta = ET.Element("initial-momenta")
    momenta.text = "../source/endpoint-momenta.txt"
    root.insert(template_index, controls)
    root.insert(template_index + 1, momenta)
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _endpoint_definition(pca, components: int, standard_deviations: float):
    feature_shape = (len(pca.feature_labels) // 3, 3)
    values = [np.asarray(pca.mean, dtype=np.float64).reshape(feature_shape)]
    endpoints: list[dict[str, object]] = [
        {
            "index": 0,
            "role": "mean",
            "component": None,
            "direction": None,
            "label": "Mean momenta",
        }
    ]
    skipped: list[int] = []
    zero_components = set(pca.zero_variance_components)
    for index in range(components):
        component = index + 1
        if index in zero_components:
            skipped.append(component)
            continue
        deviation = standard_deviations * math.sqrt(float(pca.explained_variance[index]))
        displacement = deviation * pca.components[index]
        for direction, sign in (("minus", -1.0), ("plus", 1.0)):
            values.append(
                np.asarray(pca.mean + sign * displacement, dtype=np.float64).reshape(
                    feature_shape
                )
            )
            endpoints.append(
                {
                    "index": len(endpoints),
                    "role": "principal_component_endpoint",
                    "component": component,
                    "direction": direction,
                    "label": f"PC{component} {direction}",
                    "explained_variance": float(pca.explained_variance[index]),
                    "explained_variance_ratio": float(
                        pca.explained_variance_ratio[index]
                    ),
                }
            )
    return np.stack(values), endpoints, skipped


def create_reference_pca_deformation_design(
    run_directory: Path | str,
    destination: Path | str | None = None,
    *,
    pca_bundle: Path | str | None = None,
    components: int = 3,
    standard_deviations: float = 2.0,
    created_at: str | None = None,
) -> Path:
    """Freeze a no-execution design for exact Deformetrica PCA Shooting."""

    run = Path(run_directory).expanduser().resolve()
    bundle_path = (
        Path(pca_bundle).expanduser().resolve()
        if pca_bundle is not None
        else run / DEFAULT_REFERENCE_PCA_DIRECTORY
    )
    bundle = verify_reference_pca_bundle(bundle_path, source_run=run)
    inputs = load_reference_momenta(run)
    requested_components = _positive_integer("components", components)
    if requested_components > bundle.pca.number_of_components:
        raise ValueError(
            "components cannot exceed the retained reference PCA component count "
            f"({bundle.pca.number_of_components})"
        )
    resolved_deviations = _positive_real("standard_deviations", standard_deviations)
    target = (
        Path(destination).expanduser().resolve()
        if destination is not None
        else run / "analysis" / DEFAULT_DIRECTORY_NAME
    )
    if target.exists():
        raise FileExistsError(f"PCA deformation design destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    if temporary.exists():
        raise FileExistsError(f"Temporary PCA deformation design already exists: {temporary}")

    source_model = run / "engine" / "model.xml"
    source_optimization = run / "engine" / "optimization_parameters.xml"
    if any(path.is_symlink() or not path.is_file() for path in (source_model, source_optimization)):
        raise ReferencePCADeformationError(
            "Verified source run lacks immutable model or optimization XML"
        )
    template_record = _estimated_template_record(inputs.run_report.inventory)
    template_path = _safe_output_path(run, template_record)
    endpoint_values, endpoints, skipped = _endpoint_definition(
        bundle.pca,
        requested_components,
        resolved_deviations,
    )
    try:
        temporary.mkdir()
        source_directory = temporary / "source"
        engine_directory = temporary / "engine"
        source_directory.mkdir()
        engine_directory.mkdir()
        copied_template = source_directory / "estimated-template.vtk"
        copied_controls = source_directory / "control-points.txt"
        endpoint_path = source_directory / "endpoint-momenta.txt"
        shutil.copyfile(template_path, copied_template)
        shutil.copyfile(inputs.control_points_path, copied_controls)
        _write_momenta(endpoint_path, endpoint_values)
        model_path = engine_directory / "model.xml"
        model_path.write_bytes(_render_shooting_model(source_model.read_bytes()))
        optimization_path = engine_directory / "optimization_parameters.xml"
        shutil.copyfile(source_optimization, optimization_path)

        artifacts = [
            _artifact(temporary, path)
            for path in sorted(path for path in temporary.rglob("*") if path.is_file())
        ]
        timestamp = created_at or datetime.now(UTC).isoformat(timespec="seconds")
        manifest = {
            "design_version": DESIGN_VERSION,
            "created_at": timestamp,
            "status": "prospective_not_executed",
            "source": {
                "run_directory": str(run),
                "run_manifest_sha256": sha256_file(run / "manifest.json"),
                "run_result_sha256": sha256_file(run / "result.json"),
                "run_output_inventory_sha256": sha256_file(
                    run / "output-inventory.json"
                ),
                "pca_bundle": str(bundle_path),
                "pca_manifest_sha256": sha256_file(
                    bundle_path / REFERENCE_PCA_MANIFEST
                ),
                "model_xml_sha256": sha256_file(source_model),
                "optimization_xml_sha256": sha256_file(source_optimization),
                "estimated_template_sha256": sha256_file(template_path),
                "control_points_sha256": sha256_file(inputs.control_points_path),
            },
            "shooting": {
                "engine": "Deformetrica 4.3 compute Shooting",
                "equation": DEFORMATION_EQUATION,
                "standard_deviations": resolved_deviations,
                "requested_components": requested_components,
                "skipped_zero_variance_components": skipped,
                "endpoint_count": len(endpoints),
                "endpoints": endpoints,
                "control_point_count": inputs.control_point_count,
                "dimension": 3,
                "model_path": model_path.relative_to(temporary).as_posix(),
                "optimization_parameters_path": optimization_path.relative_to(
                    temporary
                ).as_posix(),
                "momenta_path": endpoint_path.relative_to(temporary).as_posix(),
                "template_path": copied_template.relative_to(temporary).as_posix(),
            },
            "runtime": inputs.run_report.manifest["effective_config"]["runtime"],
            "artifacts": artifacts,
            "scientific_boundary": SCIENTIFIC_BOUNDARY,
        }
        _write_json_exclusive(temporary / DESIGN_NAME, manifest)
        (temporary / DESIGN_SIDECAR).write_text(
            f"{sha256_file(temporary / DESIGN_NAME)}  {DESIGN_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        verify_reference_pca_deformation_design(temporary)
        publish_directory_exclusive(temporary, target)
        verify_reference_pca_deformation_design(target, source_run=run)
        return target
    except Exception:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _safe_design_path(root: Path, value: object) -> Path:
    relative = PurePosixPath(str(value))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ReferencePCADeformationError("Design artifact path is unsafe")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file():
        raise ReferencePCADeformationError(
            f"Design artifact is missing or symbolic: {relative.as_posix()}"
        )
    return path


def verify_reference_pca_deformation_design(
    design_directory: Path | str,
    *,
    source_run: Path | str | None = None,
) -> Mapping[str, object]:
    """Strictly verify inventory, PCA endpoint values, XML, and source binding."""

    root = Path(design_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReferencePCADeformationError(
            f"PCA deformation design is missing or symbolic: {root}"
        )
    manifest_path = root / DESIGN_NAME
    sidecar_path = root / DESIGN_SIDECAR
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise ReferencePCADeformationError("Design manifest or SHA-256 sidecar is missing")
    sidecar = sidecar_path.read_text(encoding="ascii").strip().split()
    if sidecar != [sha256_file(manifest_path), DESIGN_NAME]:
        raise ReferencePCADeformationError("Design manifest SHA-256 sidecar differs")
    try:
        manifest = load_strict_json_object(
            manifest_path.read_bytes(),
            manifest_path,
            label="Reference PCA deformation design",
        )
    except (OSError, ValueError) as error:
        raise ReferencePCADeformationError(str(error)) from error
    if (
        manifest.get("design_version") != DESIGN_VERSION
        or manifest.get("status") != "prospective_not_executed"
        or manifest.get("scientific_boundary") != SCIENTIFIC_BOUNDARY
    ):
        raise ReferencePCADeformationError("Design identity or status is invalid")
    records = manifest.get("artifacts")
    if not isinstance(records, list) or not records:
        raise ReferencePCADeformationError("Design artifact inventory is invalid")
    declared: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ReferencePCADeformationError("Design artifact record is invalid")
        relative = str(record.get("path", ""))
        if relative in declared:
            raise ReferencePCADeformationError(f"Duplicate design artifact: {relative}")
        declared.add(relative)
        path = _safe_design_path(root, relative)
        if path.stat().st_size != int(record.get("bytes", -1)) or sha256_file(path) != str(
            record.get("sha256", "")
        ):
            raise ReferencePCADeformationError(f"Design artifact differs: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {DESIGN_NAME, DESIGN_SIDECAR}
    }
    if actual != declared:
        raise ReferencePCADeformationError("Design artifact inventory is incomplete")

    source = manifest.get("source")
    shooting = manifest.get("shooting")
    if not isinstance(source, Mapping) or not isinstance(shooting, Mapping):
        raise ReferencePCADeformationError("Design source or Shooting definition is invalid")
    run = (
        Path(source_run).expanduser().resolve()
        if source_run is not None
        else Path(str(source["run_directory"])).expanduser().resolve()
    )
    bundle_path = Path(str(source["pca_bundle"])).expanduser().resolve()
    try:
        bundle = verify_reference_pca_bundle(bundle_path, source_run=run)
        inputs = load_reference_momenta(run)
    except ReferencePCAError as error:
        raise ReferencePCADeformationError(str(error)) from error
    expected_hashes = {
        "run_manifest_sha256": sha256_file(run / "manifest.json"),
        "run_result_sha256": sha256_file(run / "result.json"),
        "run_output_inventory_sha256": sha256_file(run / "output-inventory.json"),
        "pca_manifest_sha256": sha256_file(bundle_path / REFERENCE_PCA_MANIFEST),
        "model_xml_sha256": sha256_file(run / "engine" / "model.xml"),
        "optimization_xml_sha256": sha256_file(
            run / "engine" / "optimization_parameters.xml"
        ),
        "control_points_sha256": sha256_file(inputs.control_points_path),
    }
    template_record = _estimated_template_record(inputs.run_report.inventory)
    template_path = _safe_output_path(run, template_record)
    expected_hashes["estimated_template_sha256"] = sha256_file(template_path)
    if any(source.get(key) != value for key, value in expected_hashes.items()):
        raise ReferencePCADeformationError("Design source binding differs")
    if manifest.get("runtime") != inputs.run_report.manifest["effective_config"]["runtime"]:
        raise ReferencePCADeformationError("Design runtime differs from the source run")

    components = _positive_integer(
        "requested_components", shooting.get("requested_components")
    )
    deviations = _positive_real(
        "standard_deviations", shooting.get("standard_deviations")
    )
    expected_values, expected_endpoints, expected_skipped = _endpoint_definition(
        bundle.pca,
        components,
        deviations,
    )
    from diffeoforge.reference_pca import read_deformetrica_momenta

    observed_values = read_deformetrica_momenta(
        _safe_design_path(root, shooting.get("momenta_path"))
    )
    if observed_values.shape != expected_values.shape or not np.array_equal(
        observed_values,
        expected_values,
    ):
        raise ReferencePCADeformationError(
            "Shooting endpoint momenta differ from exact PCA recomputation"
        )
    if (
        shooting.get("equation") != DEFORMATION_EQUATION
        or shooting.get("endpoints") != expected_endpoints
        or shooting.get("skipped_zero_variance_components") != expected_skipped
        or shooting.get("endpoint_count") != len(expected_endpoints)
        or shooting.get("control_point_count") != inputs.control_point_count
        or shooting.get("dimension") != 3
    ):
        raise ReferencePCADeformationError("Shooting endpoint definition differs")
    expected_model = _render_shooting_model((run / "engine" / "model.xml").read_bytes())
    if _safe_design_path(root, shooting.get("model_path")).read_bytes() != expected_model:
        raise ReferencePCADeformationError("Shooting model XML differs from source derivation")
    if _safe_design_path(
        root,
        shooting.get("optimization_parameters_path"),
    ).read_bytes() != (run / "engine" / "optimization_parameters.xml").read_bytes():
        raise ReferencePCADeformationError(
            "Shooting optimization parameters differ from the source run"
        )
    if sha256_file(_safe_design_path(root, shooting.get("template_path"))) != sha256_file(
        template_path
    ):
        raise ReferencePCADeformationError("Copied estimated template differs")
    return manifest
