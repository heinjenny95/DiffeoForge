"""Immutable local fitting objectives for explicit, single-form pilot trials.

Regions are geometric feedback, never anatomical correspondences. Derived point
guides are fitted only after a source/target shape-compatibility check. Ordinary
atlas runs cannot inherit this specimen-specific objective accidentally.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from diffeoforge.mesh import sha256_file

VERSION = "regional-fit-v1"


def declaration(config):
    return config.get("project", {}).get("parameter_provenance", {}).get("regional_fit")


def read_plan(config):
    entry = declaration(config)
    if entry is None:
        return None
    path = Path(entry["manifest"])
    if (
        entry.get("version") != VERSION
        or not path.is_absolute()
        or sha256_file(path) != entry["sha256"]
    ):
        raise ValueError("Regional fitting plan identity changed")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        data.get("version") != VERSION
        or data.get("anatomical_approval") is not False
        or not isinstance(data.get("objects"), list)
        or not data["objects"]
    ):
        raise ValueError("Invalid regional fitting plan")
    names = set()
    if data.get("residual"):
        row = data["residual"]["source"]
        if (
            Path(row["copy"]).name != row["copy"]
            or sha256_file(path.parent / row["copy"]) != row["sha256"]
        ):
            raise ValueError("Residual source changed")
        residual = data["residual"]
        if (
            sha256_file(Path(residual["parent_run"]) / "manifest.json")
            != residual["parent_manifest_sha256"]
        ):
            raise ValueError("Residual parent changed")
    for item in data["objects"]:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", item["id"])
            or item["id"] in names
            or item["kind"] not in {"SurfaceMesh", "Landmark"}
            or not math.isfinite(item["noise_std"])
            or item["noise_std"] <= 0
        ):
            raise ValueError("Invalid regional fitting object")
        if item["kind"] == "SurfaceMesh" and (
            not math.isfinite(item["kernel_width"]) or item["kernel_width"] <= 0
        ):
            raise ValueError("Invalid regional surface scale")
        names.add(item["id"])
        for role in ["source", "target"]:
            row = item[role]
            asset = path.parent / row["copy"]
            if (
                Path(row["copy"]).name != row["copy"]
                or not asset.is_file()
                or asset.stat().st_size != row["bytes"]
                or sha256_file(asset) != row["sha256"]
            ):
                raise ValueError("Regional fitting geometry changed")
    return data


def assets(config):
    plan = read_plan(config)
    if plan is None:
        return []
    entry = declaration(config)
    root = Path(entry["manifest"]).parent
    result = [(Path(entry["manifest"]), Path("input/regional/plan.json"), entry["sha256"])]
    if plan.get("residual"):
        row = plan["residual"]["source"]
        result.append((root / row["copy"], Path("input/regional") / row["copy"], row["sha256"]))
    for item in plan["objects"]:
        for role in ["source", "target"]:
            row = item[role]
            result.append((root / row["copy"], Path("input/regional") / row["copy"], row["sha256"]))
    return list({str(staged): (source, staged, sha) for source, staged, sha in result}.values())


def validate_scope(config, summary=None):
    plan = read_plan(config)
    if plan is None:
        return
    if (
        plan.get("execution_scope") != "single_specimen_probe"
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
    ):
        raise ValueError("Regional fitting requires an explicit frozen single-form pilot trial")
    if summary is not None:
        if (
            summary.subject_count != 1
            or sha256_file(summary.template)
            != plan.get("residual", {}).get("original_template_sha256", plan["template_sha256"])
            or sha256_file(summary.subjects[0]) != plan["target_sha256"]
        ):
            raise ValueError("Regional fitting source or target changed")


def apply_xml(config, model, dataset):
    import xml.etree.ElementTree as ET

    plan = read_plan(config)
    if plan is None:
        return
    validate_scope(config)
    subjects = dataset.findall("subject")
    if len(subjects) != 1:
        raise ValueError("Regional objectives cannot be shared across atlas subjects")
    template = model.find("template")
    if plan.get("residual"):
        template.find("object/filename").text = (
            "../input/regional/" + plan["residual"]["source"]["copy"]
        )
    existing = {item.attrib["id"] for item in template}
    for item in plan["objects"]:
        if item["id"] in existing:
            raise ValueError("Regional object collides with the surface object")
        obj = ET.SubElement(template, "object", id=item["id"])
        values = {
            "deformable-object-type": item["kind"],
            "attachment-type": "varifold" if item["kind"] == "SurfaceMesh" else "landmark",
            "noise-std": item["noise_std"],
            "filename": "../input/regional/" + item["source"]["copy"],
        }
        if item["kind"] == "SurfaceMesh":
            values.update(
                {
                    "kernel-width": item["kernel_width"],
                    "kernel-type": config["runtime"]["kernel_backend"],
                    "kernel-device": "cpu",
                }
            )
        for key, value in values.items():
            ET.SubElement(obj, key).text = str(value)
        ET.SubElement(subjects[0].find("visit"), "filename", object_id=item["id"]).text = (
            "../input/regional/" + item["target"]["copy"]
        )


def mask(vertices, regions, *, halo=0.0):
    import numpy as np

    points = np.asarray(vertices, float)
    selected = np.zeros(len(points), bool)
    for row in regions:
        if row.get("shape") == "box":
            bounds = np.asarray(row["bounds"], float).reshape(3, 2)
            selected |= ((points >= bounds[:, 0] - halo) & (points <= bounds[:, 1] + halo)).all(
                axis=1
            )
        else:
            selected |= np.linalg.norm(points - row["center"], axis=1) <= row["radius"] + halo
    return selected


def _save(path, vertices, faces=None):
    import numpy as np
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

    mesh = vtk.vtkPolyData()
    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(np.asarray(vertices, float), deep=True))
    mesh.SetPoints(points)
    if faces is not None:
        cells = vtk.vtkCellArray()
        cells.ImportLegacyFormat(
            numpy_to_vtkIdTypeArray(
                np.column_stack((np.full(len(faces), 3), faces)).astype(np.int64).ravel(), deep=True
            )
        )
        mesh.SetPolys(cells)
    writer = vtk.vtkPolyDataWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(mesh)
    writer.SetFileTypeToASCII()
    writer.SetPrecision(17)
    if writer.Write() != 1:
        raise ValueError("Could not save regional geometry")


def _patch(path, v, f, selected):
    import numpy as np

    chosen = f[selected]
    if not len(chosen):
        raise ValueError("Marked region contains no faces")
    ids, inv = np.unique(chosen, return_inverse=True)
    _save(path, v[ids], inv.reshape(-1, 3))


def _components(v, f):
    import numpy as np

    parent = np.arange(len(v))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for tri in f:
        roots = [find(int(x)) for x in tri]
        for other in roots[1:]:
            parent[other] = roots[0]
    labels = np.array([find(int(x)) for x in f[:, 0]])
    rows = []
    for key in np.unique(labels):
        faces = f[labels == key]
        t = v[faces]
        area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        if area.sum() > 0:
            rows.append(
                dict(
                    faces=faces,
                    area=float(area.sum()),
                    centroid=np.average(t.mean(1), axis=0, weights=area),
                )
            )
    return rows


def prepare(
    directory,
    template_path,
    target_path,
    regions,
    *,
    focus_regions=None,
    protection_halo=None,
    focus_width,
    focus_noise,
    protection_noise,
    guide_noise=None,
    guide_points=192,
    retained_path=None,
    fixed_regions=(),
):
    """Prepare native terms from feedback; no optimizer, oracle or acceptance.

    Explicit focus/halo settings are part of the auditable scientific recipe.
    They are not silently inferred from fixed anatomical coordinates.
    """
    import numpy as np

    from diffeoforge.reference_fit_search import distances_to_surface
    from diffeoforge.surface_io import load_surface_mesh

    root = Path(directory)
    if root.exists():
        raise ValueError("Never overwrite a regional fitting plan")
    source, target = load_surface_mesh(template_path), load_surface_mesh(target_path)
    sv, sf = np.asarray(source.geometry.vertices, float), np.asarray(source.geometry.triangles, int)
    tv, tf = np.asarray(target.geometry.vertices, float), np.asarray(target.geometry.triangles, int)
    diagonal = float(np.linalg.norm(np.ptp(tv, axis=0)))
    focus_regions = focus_regions or regions
    halo = diagonal * 0.065 if protection_halo is None else protection_halo
    if (
        any(not math.isfinite(x) or x <= 0 for x in [focus_width, focus_noise, protection_noise])
        or not math.isfinite(halo)
        or halo < 0
        or (guide_noise is not None and (not math.isfinite(guide_noise) or guide_noise <= 0))
        or type(guide_points) is not int
        or not 4 <= guide_points <= 2048
    ):
        raise ValueError("Regional scales must be finite and positive")
    root.mkdir(parents=True)
    objects = []

    def asset(name, v, f=None):
        path = root / name
        _save(path, v, f)
        return dict(copy=path.name, sha256=sha256_file(path), bytes=path.stat().st_size)

    for name, v, f in [("focus-source.vtk", sv, sf), ("focus-target.vtk", tv, tf)]:
        _patch(root / name, v, f, mask(v[f].mean(1), focus_regions))

    def row(name):
        p = root / name
        return dict(copy=name, sha256=sha256_file(p), bytes=p.stat().st_size)

    objects.append(
        dict(
            id="focus",
            kind="SurfaceMesh",
            noise_std=focus_noise,
            kernel_width=focus_width,
            source=row("focus-source.vtk"),
            target=row("focus-target.vtk"),
        )
    )
    t = sv[sf]
    area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    ids = np.unique(
        sf[np.searchsorted(np.cumsum(area), (np.arange(1800) + 0.5) * area.sum() / 1800), 0]
    )
    ids = ids[~mask(sv[ids], focus_regions, halo=halo) | mask(sv[ids], fixed_regions)]
    if len(ids) < 4:
        raise ValueError("The marked region leaves too little surface for outside protection")
    protected = sv[ids]
    protection = "already-close original source"
    if retained_path and (
        fixed_regions
        or np.quantile(distances_to_surface(protected, tv, tf), 0.95) > diagonal * 1e-6
    ):
        retained = load_surface_mesh(retained_path).geometry
        if np.asarray(retained.vertices).shape != sv.shape or not np.array_equal(
            retained.triangles, sf
        ):
            raise ValueError("Retained field needs identical source connectivity for protection")
        protected = np.asarray(retained.vertices, float)[ids]
        protection = "retained fit outside the marked transition halo"
    a = asset("protect-source.vtk", sv[ids])
    b = asset("protect-target.vtk", protected)
    objects.append(
        dict(id="protect", kind="Landmark", noise_std=protection_noise, source=a, target=b)
    )
    guidance = []
    if guide_noise is not None:
        from diffeoforge.reference_fit_search import surface_samples

        aa = _components(sv, sf[mask(sv[sf].mean(1), regions)])
        bb = _components(tv, tf[mask(tv[tf].mean(1), regions)])
        if not 1 <= len(aa) == len(bb) <= 8:
            raise ValueError(
                "Mark corresponding separated surface parts before preserving their form"
            )
        centres = np.array([r["centroid"] for r in bb])
        axis = int(np.argmax(np.ptp(centres, axis=0)))
        aa.sort(key=lambda r: r["centroid"][axis])
        bb.sort(key=lambda r: r["centroid"][axis])
        starts, ends = [], []
        for index, (a, b) in enumerate(zip(aa, bb, strict=True)):
            points = surface_samples(sv, a["faces"], guide_points, seed=2026102400 + index)
            delta = b["centroid"] - a["centroid"]
            translated = points + delta
            residual = float(np.quantile(distances_to_surface(translated, tv, b["faces"]), 0.95))
            extent = float(np.linalg.norm(np.ptp(tv[np.unique(b["faces"])], axis=0)))
            if (
                residual > max(extent * 0.02, diagonal * 1e-5)
                or abs(a["area"] / b["area"] - 1) > 0.05
            ):
                raise ValueError(
                    "These marked parts differ in shape: use local shape matching, "
                    "or revise the areas before requesting shape preservation"
                )
            starts.append(points)
            ends.append(translated)
            guidance.append(
                dict(
                    translation=delta.tolist(),
                    surface_p95=residual,
                    source_area=a["area"],
                    target_area=b["area"],
                    points=len(points),
                )
            )
        a = asset("guides-source.vtk", np.vstack(starts))
        b = asset("guides-target.vtk", np.vstack(ends))
        objects.append(
            dict(id="featureguides", kind="Landmark", noise_std=guide_noise, source=a, target=b)
        )
    retained_binding = (
            dict(path=str(Path(retained_path).resolve()), sha256=sha256_file(Path(retained_path)))
        if retained_path
        else None
    )
    data = dict(
        version=VERSION,
        execution_scope="single_specimen_probe",
        template_sha256=source.metadata.sha256,
        target_sha256=target.metadata.sha256,
        regions=regions,
        focus_regions=focus_regions,
        protection_halo=halo,
        protection=protection,
        protection_vertex_ids=ids.tolist(),
        fixed_regions=list(fixed_regions),
        retained_reference=retained_binding,
        objects=objects,
        guidance=guidance,
        anatomical_approval=False,
        scope="Experimental single-form protected objective; renewed coverage and "
        "a compatible joint scientific protocol are required before an atlas",
    )
    path = root / "regional-plan.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dict(version=VERSION, manifest=str(path.resolve()), sha256=sha256_file(path))
