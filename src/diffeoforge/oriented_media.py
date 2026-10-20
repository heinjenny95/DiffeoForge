"""Immutable presentation derivatives of an already computed atlas media bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from pathlib import Path

import numpy as np

from diffeoforge.desktop.mesh_view import checked_rotation
from diffeoforge.mesh import sha256_file
from diffeoforge.pca_media import (
    MediaCancelled,
    _check,
    _record,
    _render_media,
    verify_media,
)
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    verify_reference_pca_bundle,
)
from diffeoforge.reference_pca_deformations import (
    DEFAULT_RESULT_DIRECTORY,
    verify_reference_pca_deformation_result,
)
from diffeoforge.runs import publish_directory_exclusive


def prepare_oriented_media(directory, rotation, name, cancelled=None, progress=lambda _: None):
    """Rerender all media, using saved native samples, without scientific execution."""
    directory = Path(directory).resolve()
    rotation = checked_rotation(rotation)
    cancelled = cancelled or threading.Event()
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("Give the view a name of at most 80 characters")

    def phase(text):
        if cancelled.is_set():
            raise MediaCancelled("View preparation cancelled")
        progress(text)

    phase("Verifying saved visualization inputs…")
    identity = sha256_file(directory / "media.json")
    metadata = verify_media(directory)
    key = hashlib.sha256(
        json.dumps(
            ["all-media-v1", identity, rotation.tolist(), name],
            allow_nan=False,
        ).encode()
    ).hexdigest()
    target = directory.parent / f"view-{key[:24]}"
    if target.exists():
        data = verify_media(target)
        if data.get("view_source_sha256") != identity or data.get("mesh_view") != {
            "name": name,
            "rotation": rotation.tolist(),
            "scope": "all visualizations",
        }:
            raise ValueError("Saved visualization view identity differs")
        return target
    run = Path(metadata["source_run"])
    pca = verify_reference_pca_bundle(run / DEFAULT_REFERENCE_PCA_DIRECTORY, source_run=run).pca
    endpoint_root = run / DEFAULT_RESULT_DIRECTORY
    result = verify_reference_pca_deformation_result(endpoint_root, source_run=run)
    if result["result_version"] != "0.2":
        raise ValueError("Verified native physical endpoint shapes are required")
    saved = json.loads((directory / "PCA-Gallery/mesh-pca.json").read_text())
    if list(pca.sample_labels) != metadata["specimen_labels"] or not np.array_equal(
        pca.scores[:, :3], [row["scores"] for row in saved]
    ):
        raise ValueError("Saved PCA rows differ from the visualization")
    reconstructions = []
    for label in pca.sample_labels:
        matches = [
            r
            for r in metadata["sources"]
            if "__Reconstruction__" in Path(r["path"]).name
            and Path(r["path"]).name.endswith(f"__subject_{label}.vtk")
        ]
        if len(matches) != 1:
            raise ValueError("Each specimen requires one verified reconstruction")
        reconstructions.append(matches[0])
    endpoints = [{**r, "path": str(endpoint_root / r["path"])} for r in result["endpoints"]]
    stage = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    stage.mkdir()
    try:
        _render_media(
            stage,
            pca,
            reconstructions,
            endpoints,
            phase,
            cancelled,
            endpoint_root=endpoint_root,
            config=None,
            sample_source=directory,
            rotation=rotation,
            view_name=name,
        )
        phase("Verifying complete visualization view…")
        # Recheck the native samples, source geometry and sealed original before publishing.
        verify_media(directory)
        if sha256_file(directory / "media.json") != identity:
            raise ValueError("Visualization source changed during rendering")
        for record in endpoints:
            _check(record)
        files = [
            {**_record(p), "path": p.relative_to(stage).as_posix()}
            for p in sorted(stage.rglob("*"))
            if p.is_file()
        ]
        data = {
            **metadata,
            "files": files,
            "view_source_sha256": identity,
            "mesh_view": {
                "name": name,
                "rotation": rotation.tolist(),
                "scope": "all visualizations",
            },
        }
        manifest = stage / "media.json"
        manifest.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
        (stage / "media.sha256").write_text(sha256_file(manifest), encoding="ascii")
        verify_media(stage, source_run=run)
        phase("All visualizations ready")
        publish_directory_exclusive(stage, target)
        return target
    finally:
        if stage.exists() and stage.parent == target.parent:
            shutil.rmtree(stage)
