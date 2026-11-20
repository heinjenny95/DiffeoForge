"""Generate and measure a known local deformation on a copied triangular surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import numpy as np

from diffeoforge.analysis.atlas_group_anatomy import _area_weights
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.mesh import read_vtk_polydata_with_metadata, sha256_file, write_vtk_polydata
from diffeoforge.result_report import collect_run_report
from diffeoforge.runs import publish_directory_exclusive

TRUTH = "known-signal.json"
VERSION = "known-local-shape-signal-v1"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def _field(points, *, center, radius, direction):
    center = np.asarray(center, dtype=float)
    direction = np.asarray(direction, dtype=float)
    norm = np.linalg.norm(direction)
    if (
        center.shape != (3,)
        or direction.shape != (3,)
        or not np.isfinite(center).all()
        or not np.isfinite(norm)
        or norm == 0
        or not np.isfinite(radius)
        or radius <= 0
    ):
        raise ValueError("Provide a finite centre, positive radius and nonzero direction")
    radius_fraction = np.linalg.norm(points - center, axis=1) / radius
    profile = np.square(np.maximum(0.0, 1.0 - radius_fraction**2)) * np.maximum(
        0.0, 1.0 - radius_fraction**2
    )
    if np.count_nonzero(profile) < 3 or np.all(profile > 0):
        raise ValueError(
            "The local field needs at least three affected vertices and an outside area"
        )
    return profile[:, None] * (direction / norm)


def _doses(values, radius):
    result = tuple(float(v) for v in values)
    if (
        len(result) < 4
        or len(result) > 64
        or not np.isfinite(result).all()
        or result.count(0.0) < 2
        or len({v for v in result if v > 0}) < 2
        or min(result) < 0
        or 2 * max(result) >= radius
    ):
        raise ValueError(
            "Use at least two zero controls and two distinct positive doses below half the radius"
        )
    return result


def create_signal_study(source, destination, *, center, radius, direction, doses) -> Path:
    """Create a separate fixed-topology cohort and freeze its dose schedule."""
    source = Path(source).resolve()
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(target)
    doses = _doses(doses, radius)
    metadata, geometry = read_vtk_polydata_with_metadata(source)
    points = np.asarray(geometry.vertices, dtype=float)
    triangles = np.asarray(geometry.triangles, dtype=np.int64)
    field = _field(points, center=center, radius=radius, direction=direction)
    _area_weights(points, triangles)
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".known-signal-", dir=target.parent) as temporary:
        root = Path(temporary)
        (root / "specimens").mkdir()
        template = write_vtk_polydata(root / "template.vtk", points, triangles)
        rows = []
        for index, dose in enumerate(doses):
            name = f"subject-{index + 1:03d}.vtk"
            mesh = write_vtk_polydata(root / "specimens" / name, points + dose * field, triangles)
            rows.append(dict(name=name, dose=dose, sha256=sha256_file(mesh)))
        manifest = dict(
            version=VERSION,
            source_sha256=metadata.sha256,
            template_sha256=sha256_file(template),
            center=list(center),
            radius=radius,
            direction=list(direction),
            specimens=rows,
        )
        write_text_safely(root / TRUTH, _json(manifest), overwrite=False)
        write_text_safely(
            root / (TRUTH + ".sha256"), sha256_file(root / TRUTH) + "\n", overwrite=False
        )
        publish_directory_exclusive(root, target)
    return target


def _projection(displacement, field, weights, energy):
    return float(np.einsum("v,vi,vi->", weights, field, displacement) / energy)


def measure_signal(points, triangles, field, doses, fitted):
    """Measure the recovered dose against zero controls and drift outside the support."""
    weights = _area_weights(points, triangles)
    energy = float(np.einsum("v,vi,vi->", weights, field, field))
    outside = weights * ~np.any(field != 0, axis=1)
    if energy == 0 or outside.sum() == 0:
        raise ValueError("Signal region and outside region each need positive surface area")
    outside /= outside.sum()
    points = np.asarray(points, dtype=float)
    fitted = tuple(np.asarray(v, dtype=float) for v in fitted)
    if len(doses) != len(fitted) or any(
        v.shape != points.shape or not np.isfinite(v).all() for v in fitted
    ):
        raise ValueError("Every specimen needs a complete finite reconstruction")
    zeros = [vertices for vertices, dose in zip(fitted, doses, strict=True) if dose == 0]
    if len(zeros) < 2:
        raise ValueError("At least two zero controls are required")
    zero_sum = np.sum(zeros, axis=0)
    reference = zero_sum / len(zeros)
    rows = []
    for dose, vertices in zip(doses, fitted, strict=True):
        baseline = reference if dose else (zero_sum - vertices) / (len(zeros) - 1)
        displacement = vertices - baseline
        recovered = _projection(displacement, field, weights, energy)
        rows.append(
            {
                "applied_dose": dose,
                "recovered_dose": recovered,
                "retained_fraction": recovered / dose if dose else None,
                "outside_support_rms": float(
                    np.sqrt(np.einsum("v,vi,vi->", outside, displacement, displacement))
                ),
            }
        )
    return rows


def evaluate_signal_study(study, run) -> dict:
    """Read one terminal, inventory-verified Deformetrica run without generating PCA."""
    root = Path(study).resolve()
    run = Path(run).resolve()
    truth_path = root / TRUTH
    digest = sha256_file(truth_path)
    if (root / (TRUTH + ".sha256")).read_text(encoding="utf-8").strip() != digest:
        raise ValueError("The frozen signal manifest changed")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    if truth["version"] != VERSION:
        raise ValueError("Unknown signal benchmark format")
    report = collect_run_report(run)
    if (
        report.result["status"] != "completed"
        or report.result["return_code"] != 0
        or any(check.status == "fail" for check in report.checks)
    ):
        raise ValueError("A complete, verified native run is required")
    if [
        row["geometry"]["sha256"] for row in report.manifest["inputs"] if row["role"] == "template"
    ] != [truth["template_sha256"]]:
        raise ValueError("The run did not start from the frozen benchmark template")
    rows = truth["specimens"]
    expected = {row["name"]: row["sha256"] for row in rows}
    staged_subjects = [row for row in report.manifest["inputs"] if row["role"] == "subject"]
    observed = {
        PurePosixPath(row["staged_path"]).name: row["geometry"]["sha256"] for row in staged_subjects
    }
    if expected != observed or len(rows) != len(staged_subjects):
        raise ValueError("The run did not fit the exact benchmark specimens")
    for name, sha in expected.items():
        if not name or Path(name).name != name or sha256_file(root / "specimens" / name) != sha:
            raise ValueError("A frozen signal specimen changed")
    metadata, geometry = read_vtk_polydata_with_metadata(root / "template.vtk")
    if metadata.sha256 != truth["template_sha256"]:
        raise ValueError("The frozen template changed")
    points = np.asarray(geometry.vertices, dtype=float)
    triangles = np.asarray(geometry.triangles, dtype=np.int64)
    field = _field(
        points, center=truth["center"], radius=truth["radius"], direction=truth["direction"]
    )
    doses = _doses([row["dose"] for row in rows], truth["radius"])
    object_id = report.manifest["effective_config"]["model"]["object_id"]
    marker = f"__Reconstruction__{object_id}__subject_"
    fitted = []
    for row in rows:
        records = [
            item
            for item in report.inventory
            if PurePosixPath(item["path"]).name.endswith(marker + row["name"] + ".vtk")
        ]
        if len(records) != 1:
            raise ValueError("A benchmark specimen does not have one exact reconstruction")
        record = records[0]
        path = (run / "output" / record["path"]).resolve()
        if not path.is_relative_to(run / "output"):
            raise ValueError("Reconstruction path escapes the bound output")
        metadata, reconstructed = read_vtk_polydata_with_metadata(path)
        if metadata.sha256 != record["sha256"] or not np.array_equal(
            reconstructed.triangles, triangles
        ):
            raise ValueError("Reconstruction bytes or common material connectivity differ")
        fitted.append(reconstructed.vertices)
    measurements = measure_signal(points, triangles, field, doses, fitted)
    return dict(
        version=VERSION,
        truth_sha256=digest,
        run_manifest_sha256=sha256_file(run / "manifest.json"),
        max_iterations=report.max_iterations,
        last_logged_iteration=report.final_iteration,
        specimens=[
            dict(name=row["name"], **value) for row, value in zip(rows, measurements, strict=True)
        ],
        boundary="Known deformation recovery in material coordinates. "
        "Zero controls use leave-one-out means. This is an engineering benchmark.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    create = actions.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    create.add_argument("--center", nargs=3, required=True, type=float)
    create.add_argument("--direction", nargs=3, required=True, type=float)
    create.add_argument("--radius", required=True, type=float)
    create.add_argument("--doses", nargs="+", required=True, type=float)
    evaluate = actions.add_parser("evaluate")
    evaluate.add_argument("study", type=Path)
    evaluate.add_argument("run", type=Path)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "create":
        print(create_signal_study(**args))
    else:
        print(_json(evaluate_signal_study(**args)), end="")


if __name__ == "__main__":
    main()
