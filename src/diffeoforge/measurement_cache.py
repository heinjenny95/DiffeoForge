"""Content/transform-bound scalar measurements; never cache a scientific mesh."""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from pathlib import Path

from diffeoforge import __version__


def measurement_key(path, digest, transform, budget, descriptor_version):
    return {
        "software_version": __version__,
        "measurement_version": "1",
        "filename": path.name,
        "sha256": digest,
        "triangle_budget": budget,
        "shape_descriptor_version": descriptor_version,
        "transform": None
        if transform is None
        else {
            "centroid": transform.centroid.tolist(),
            "scale": transform.scale,
            "rotation": transform.rotation.tolist(),
        },
    }


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def cache_path(directory, key):
    return Path(directory) / (hashlib.sha256(_json(key).encode()).hexdigest() + ".json")


def read_measurement(directory, key):
    if directory is None:
        return None
    path = cache_path(directory, key)
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        payload = record["payload"]
        if (
            record["key"] != key
            or record["sha256"] != hashlib.sha256(_json(payload).encode()).hexdigest()
        ):
            return None
        observation = payload["observation"]
        if observation["sha256"] != key["sha256"] or observation["filename"] != key["filename"]:
            return None
        if any(
            type(observation[k]) is not int or observation[k] <= 0 for k in ("points", "triangles")
        ):
            return None
        if any(
            not math.isfinite(observation[k]) or observation[k] <= 0
            for k in (
                "bounding_box_diagonal",
                "rms_radius",
                "median_sampled_edge_length",
            )
        ):
            return None
        if len(payload["centroid"]) != 3 or not all(math.isfinite(v) for v in payload["centroid"]):
            return None
        if not observation["shape_descriptor"] or not all(
            math.isfinite(v) for v in observation["shape_descriptor"]
        ):
            return None
        observation["shape_descriptor"] = tuple(observation["shape_descriptor"])
        return payload
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_measurement(directory, key, payload):
    if directory is None:
        return
    path = cache_path(directory, key)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            _json(
                {
                    "key": key,
                    "payload": payload,
                    "sha256": hashlib.sha256(_json(payload).encode()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        pass  # Cache storage is optional; source measurement errors are not.
    finally:
        temporary.unlink(missing_ok=True)
