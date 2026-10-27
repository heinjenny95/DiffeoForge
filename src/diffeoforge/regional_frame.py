"""Qualify the retained ambient field before using it as a new residual source."""
import json
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file

TEMPORAL_COUNTS = (73, 145, 289, 577)
TEMPORAL_TOLERANCE = 1e-4


def compatible(receipt):
    return bool(receipt and receipt.get("integrator") == "rk2"
                and receipt.get("precision") == "float64"
                and receipt.get("timepoints", 0) >= 73
                and receipt.get("starting_frame_qualification", {}).get("temporal_stable"))


def qualify(run, directory, *, source=None):
    from diffeoforge.reference_fixed_shooting import movement
    from diffeoforge.regional_evaluation import evaluate
    from diffeoforge.surface_io import load_surface_mesh

    directory = Path(directory)
    directory.mkdir()
    cache = {}
    coarse = evaluate(run, directory / "grid37", count=37, _source=source, _cache=cache)
    grid = Path(coarse["reference_source"]["path"])
    vertices = np.asarray(load_surface_mesh(grid).geometry.vertices)
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    checks = []
    for count in TEMPORAL_COUNTS:
        fine = evaluate(run, directory / f"grid{count}", count=count,
                        _source=grid, _cache=cache)
        delta = movement(Path(coarse["endpoint"]["path"]),
                         Path(fine["endpoint"]["path"]), diagonal)
        checks.append(dict(coarse=coarse["timepoints"], fine=count, **delta))
        if delta["maximum"] <= TEMPORAL_TOLERANCE:
            fine["starting_frame_qualification"] = dict(
                temporal_checks=checks, temporal_stable=True, optimizer_updates=0,
                purpose="Same saved momenta; consistent original-source RK2 residual frame")
            (directory / "qualification.json").write_text(json.dumps(fine, indent=2) + "\n")
            return fine
        coarse = fine
    raise ValueError(
        "The retained starting field is numerically unresolved; inspect it before fitting")


def verify_source(receipt):
    for name in ("endpoint", "reference_source"):
        row = receipt[name]
        if sha256_file(Path(row["path"])) != row["sha256"]:
            raise ValueError("Qualified retained geometry changed")
    run = Path(receipt["source_run"])
    if sha256_file(run / "manifest.json") != receipt["source_manifest_sha256"]:
        raise ValueError("Qualified retained field manifest changed")
    for name, digest in (("control_points", "controls_sha256"), ("momenta", "momenta_sha256")):
        if sha256_file(Path(receipt["field_paths"][name])) != receipt[digest]:
            raise ValueError("Qualified retained field parameters changed")
