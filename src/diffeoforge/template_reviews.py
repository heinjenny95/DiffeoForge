"""Bounded, read-only contextual fit evidence for a template suggestion."""

import json
import os
from pathlib import Path

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file


def _original_template_hash(project, manifest, source_config):
    digest = manifest["inputs"]["template"]["sha256"]
    preprocessing = source_config.get("preprocessing", {}).get("procrustes", {})
    if not preprocessing:
        return digest
    original_config = Path(manifest["source_config"]["original_path"])
    evidence_path = (original_config.parent / preprocessing["evidence_file"]).resolve()
    if (not evidence_path.is_relative_to(project) or evidence_path.is_symlink()
            or sha256_file(evidence_path) != preprocessing["evidence_sha256"]):
        raise ValueError("Original/aligned template mapping changed or is outside this project")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    mapping = [r for r in evidence["meshes"] if r["aligned_sha256"] == digest]
    if len(mapping) != 1:
        raise ValueError("Original/aligned template mapping is ambiguous")
    return mapping[0]["source_sha256"]


def previous_template_reviews(project, *, cancel_requested=None):
    """Inspect up to 64 saved studies under the selected project, without fitting.

    The normal study loader verifies review/result bindings. Only exact template
    bytes, or a verified original-to-aligned byte mapping, attach evidence to a
    candidate. These records never change its rank or scientific acceptance.
    """
    from diffeoforge.reference_calibration_study import (
        STUDY_MANIFEST,
        _safe_study_path,
        _verify_manifest,
        load_reference_calibration_study,
    )

    if project is None or not Path(project).is_dir():
        return []
    project = Path(project).resolve()
    rows, scanned = [], 0
    for visited, (folder, children, files) in enumerate(os.walk(project, followlinks=False)):
        if visited >= 1024:
            break
        if cancel_requested and cancel_requested():
            raise InterruptedError("Template suggestion cancelled")
        root = Path(folder)
        depth = len(root.relative_to(project).parts)
        children[:] = sorted(c for c in children if c not in {
            "runs", "input", "inputs", "preprocessing", ".git", "output", "raw",
        } and not (root / c).is_symlink()) if depth < 9 else []
        if STUDY_MANIFEST not in files:
            continue
        scanned += 1
        if scanned > 64:
            break
        try:
            manifest = _verify_manifest(root)
            snapshot = load_reference_calibration_study(root)
            source_config = load_config(_safe_study_path(root, manifest["source_config"]["copy"]))
            source_hash = _original_template_hash(project, manifest, source_config)
            for candidate in snapshot.candidates:
                decision = snapshot.visual_reviews.get(candidate.candidate_id)
                if decision is None:
                    continue
                config = load_config(candidate.config_path)
                rows.append(dict(
                    source_sha256=source_hash, source_study=str(root),
                    candidate_id=candidate.candidate_id, approved=decision,
                    targets=[dict(filename=r["filename"], sha256=r["sha256"])
                             for r in manifest["inputs"]["subjects"]],
                    method=config["model"]["attachment"]["type"],
                    settings=config["model"],
                ))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            # Changed/incompatible evidence is not presented as a past result.
            continue
    return rows
