"""Read bound accepted-state previews and send generation-specific decisions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.pilot_review_assets import DECLARATION

VERSION = DECLARATION["version"]


def _json(path, limit=32768):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("Invalid pilot review file")
    return json.loads(path.read_text(encoding="utf-8"))


def read_review(run):
    """Return one immutable preview receipt, never an approved candidate."""
    run = Path(run).resolve()
    root = run / "output/pilot-review"
    pointer = root / "live.json"
    if not pointer.is_file():
        return None
    live = _json(pointer)
    if live.get("status") != "waiting":
        return None
    if (run / "result.json").is_file():
        result = _json(run / "result.json", 1_048_576)
        if result.get("status") != "running":
            return None
    return _bound(run, live)


def _bound(run, live):
    generation = live.get("generation")
    if type(generation) is not int or not 0 < generation < 1_000_000:
        raise ValueError("Invalid review generation")
    folder = run / "output/pilot-review" / f"review-{generation:04d}"
    if folder.is_symlink() or folder.resolve().parent != (run / "output/pilot-review").resolve():
        raise ValueError("Review folder leaves the active run")
    manifest_sha = sha256_file(run / "manifest.json")
    if live.get("version") != VERSION or live.get("manifest_sha256") != manifest_sha:
        raise ValueError("Pilot review belongs to a different manifest")
    if sha256_file(folder / "receipt.json") != live.get("receipt_sha256"):
        raise ValueError("Pilot review receipt changed")
    receipt = _json(folder / "receipt.json")
    if any(
        receipt.get(k) != live.get(k) for k in ("version", "generation", "nonce", "manifest_sha256")
    ):
        raise ValueError("Pilot review generation or binding changed")
    if receipt.get("run_id") != run.name or receipt.get("anatomical_approval") is not False:
        raise ValueError("Invalid review scope")
    manifest = _json(run / "manifest.json", 16_777_216)
    provenance = manifest["effective_config"]["project"]["parameter_provenance"]
    if provenance.get("pilot_review") != DECLARATION:
        raise ValueError("Run has no declared intermediate review")
    for name in ("points.npy", "parameters.npy"):
        path = folder / name
        expected = receipt["files"][name]
        if (
            path.is_symlink()
            or path.stat().st_size != expected["bytes"]
            or sha256_file(path) != expected["sha256"]
        ):
            raise ValueError("Pilot review array changed")
    return dict(run=run, folder=folder, live=live, receipt=receipt, manifest=manifest)


def request_review_action(bound, action):
    if action not in {"continue", "finish"}:
        raise ValueError("Choose continuation or completion of this attempt")
    fresh = read_review(bound["run"])
    if fresh is None or fresh["live"] != bound["live"]:
        raise ValueError("This intermediate review is no longer waiting")
    command = {k: bound["live"][k] for k in ("version", "generation", "nonce", "manifest_sha256")}
    command["action"] = action
    destination = bound["folder"] / "command.json"
    if destination.exists():
        raise ValueError("A decision for this review has already been sent")
    temporary = destination.with_name(".decision-" + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(command, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        # Publish complete bytes without replacing a concurrently submitted decision.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def verified_finish(run):
    """An early normal stop needs matching decision, finite parameters and guard return."""
    run = Path(run).resolve()
    root = run / "output/pilot-review"
    live = _json(root / "live.json")
    if live.get("status") != "finishing":
        raise ValueError("No final pilot review decision")
    bound = _bound(run, live)
    finish = _json(root / "finish.json")
    decision = _json(bound["folder"] / "decision.json")
    command = _json(bound["folder"] / "command.json")
    if (
        finish != decision
        or finish.get("action") != "finish"
        or finish.get("manifest_sha256") != live["manifest_sha256"]
        or finish.get("receipt_sha256") != live["receipt_sha256"]
        or finish.get("command_sha256") != sha256_file(bound["folder"] / "command.json")
        or command
        != {
            **{k: live[k] for k in ("version", "generation", "nonce", "manifest_sha256")},
            "action": "finish",
        }
    ):
        raise ValueError("Pilot review finish is not bound to the user decision")
    values = np.load(bound["folder"] / "parameters.npy", allow_pickle=False, mmap_mode="r")
    if values.ndim != 1 or values.dtype != np.float64 or not np.isfinite(values).all():
        raise ValueError("Invalid review parameters")
    key = hashlib.sha256(
        str(values.shape).encode() + values.dtype.str.encode() + values.tobytes()
    ).hexdigest()
    guard = run / "output/numerical-guard"
    if (guard / "violation.json").exists():
        raise ValueError("A numerical violation cannot qualify as a review finish")
    events = [
        json.loads(line)
        for line in (guard / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    returned = [e for e in events if e["kind"] == "native_update_returned_bound_to_accepted"]
    accepted = [e for e in events if e["kind"] == "accepted_callback"]
    if (
        not returned
        or not accepted
        or returned[-1].get("original_update_returned_normally") is not True
        or returned[-1].get("native_iteration") != bound["receipt"]["native_state_index"]
        or accepted[-1].get("native_iteration") != bound["receipt"]["native_state_index"]
        or returned[-1].get("parameter_sha256") != key
        or accepted[-1].get("parameter_sha256") != key
        or bound["receipt"]["parameter_sha256"] != key
        or finish.get("parameter_sha256") != key
    ):
        raise ValueError("Final native state differs from the reviewed accepted parameters")
    return finish


def preview_models(bound, *, full_detail=False):
    """Full native coordinates → bounded DISPLAY geometry, away from the UI thread."""
    from diffeoforge.desktop.display_proxy import build_display_proxy
    from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
    from diffeoforge.desktop.pilot_preview import load_pilot_preview
    from diffeoforge.surface_io import load_surface_mesh

    fresh = read_review(bound["run"])
    if fresh is None or fresh["live"] != bound["live"]:
        raise ValueError("Intermediate review is no longer active")
    run, manifest, receipt = bound["run"], bound["manifest"], bound["receipt"]
    import xml.etree.ElementTree as ET

    protected = {row["path"]: row["sha256"] for row in manifest["protected_artifacts"]}
    if sha256_file(run / "engine/model.xml") != protected.get("engine/model.xml"):
        raise ValueError("Review model declaration changed")
    model = ET.parse(run / "engine/model.xml")
    obj = next(
        o for o in model.getroot().find("template") if o.attrib["id"] == receipt["source_object_id"]
    )
    source = (run / "engine" / obj.find("filename").text).resolve()
    if not source.is_relative_to(run) or sha256_file(source) != protected.get(
        source.relative_to(run).as_posix()
    ):
        raise ValueError("Review source geometry changed")
    target_row = next(r for r in manifest["inputs"] if r["role"] == "subject")
    target = run / target_row["staged_path"]
    if sha256_file(target) != protected.get(target_row["staged_path"]):
        raise ValueError("Review target geometry changed")
    geometry = load_surface_mesh(source).geometry
    points = np.load(bound["folder"] / "points.npy", allow_pickle=False, mmap_mode="r")
    if points.shape != (len(geometry.vertices), 3) or not np.isfinite(points).all():
        raise ValueError("Review coordinates do not match the original source topology")
    faces = np.asarray(geometry.triangles)
    bound["fixed_preservation"] = fixed_preservation(bound, points, faces)
    proxy = (
        build_display_proxy(points, faces, budget=len(faces))
        if full_detail
        else build_display_proxy(points, faces)
    )
    low, high = points.min(0), points.max(0)
    reconstruction = MeshPreviewModel(
        path=bound["folder"] / "points.npy",
        sha256=receipt["files"]["points.npy"]["sha256"],
        vertices=tuple(map(tuple, proxy.vertices.tolist())),
        triangles=tuple(map(tuple, proxy.triangles.tolist())),
        edges=tuple(map(tuple, proxy.edges.tolist())),
        bounds=tuple(np.column_stack((low, high)).ravel()),
        display_proxy=proxy,
        geometry_is_proxy=not full_detail,
        source_triangle_count=len(geometry.triangles),
    )
    return (
        load_mesh_preview(target) if full_detail else load_pilot_preview(target)
    ), reconstruction


def fixed_preservation(bound, points, faces):
    """Read-only endpoint protection check; never accepts or changes an optimizer state."""
    from diffeoforge.mesh import read_vtk_points
    from diffeoforge.regional_fit import read_plan
    from diffeoforge.regional_preservation import assess
    from diffeoforge.surface_io import load_surface_mesh

    config = bound["manifest"].get("effective_config", {})
    plan = read_plan(config)
    if not plan or not plan.get("fixed_regions"):
        return None
    root = Path(config["project"]["parameter_provenance"]["regional_fit"]["manifest"]).parent
    declared = plan.get("fixed_protection")
    if declared:
        obj = next(o for o in plan["objects"] if o["id"] == "fixed")
        expected = np.asarray(read_vtk_points(root / obj["target"]["copy"]), float)
        ids = plan["fixed_vertex_ids"]
        if not ids or max(ids) >= len(points):
            raise ValueError("Retain-area points do not match this intermediate source")
        distances = np.linalg.norm(np.asarray(points)[ids] - expected, axis=1)
        maximum = float(distances.max())
        return dict(active=True, available=True, checked_vertices=len(ids),
                    maximum=maximum, limit=declared["limit"],
                    passed=maximum <= declared["limit"], anatomical_approval=False)
    # Legacy plans protected a small global sample. When their full retained
    # material mesh matches, audit the whole marked patch rather than that sample.
    retained = plan.get("retained_reference")
    if retained:
        path = Path(retained["path"])
        if sha256_file(path) != retained["sha256"]:
            raise ValueError("Retain-area starting fit changed")
        geometry = load_surface_mesh(path).geometry
        reference = np.asarray(geometry.vertices, float)
        if reference.shape == np.asarray(points).shape and np.array_equal(
                np.asarray(geometry.triangles), faces):
            if not bound.get("run"):
                return dict(active=True, available=False, passed=False, anatomical_approval=False)
            row = next(r for r in bound["manifest"]["inputs"] if r["role"] == "subject")
            target = Path(bound["run"]) / row["staged_path"]
            protected = {r["path"]: r["sha256"] for r in
                         bound["manifest"]["protected_artifacts"]}
            if (not target.resolve().is_relative_to(Path(bound["run"]).resolve())
                    or sha256_file(target) != protected.get(row["staged_path"])):
                raise ValueError("Retain-area check target changed")
            target_geometry = load_surface_mesh(target).geometry
            diagonal = float(np.linalg.norm(np.ptp(target_geometry.vertices, axis=0)))
            result = assess(points, reference, faces, plan["fixed_regions"], diagonal * 1e-4)
            return dict(result, available=True, legacy_objective=True)
    return dict(active=True, available=False, passed=False, anatomical_approval=False)
