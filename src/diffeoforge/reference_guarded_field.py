"""Exact original input basis for NEW explicitly guarded regional fields only.

Common atlas/PCA loading and historical exported-CP semantics are unchanged.
"""

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.reference_finite_accepted_guard import DECLARATION, declaration
from diffeoforge.reference_pca import read_deformetrica_control_points


def _output_json_or_events(data, relative, *, events=False):
    report = data.run_report
    rows = [r for r in report.inventory if r["path"] == relative]
    if len(rows) != 1:
        raise ValueError("Guard evidence must be sealed in the output inventory: " + relative)
    row = rows[0]
    path = data.run_directory / "output" / relative
    if (
        path.is_symlink()
        or path.stat().st_size != row["bytes"]
        or sha256_file(path) != row["sha256"]
    ):
        raise ValueError("Guard evidence changed: " + relative)
    text = path.read_text(encoding="utf-8")
    if sha256_file(path) != row["sha256"]:
        raise ValueError("Guard evidence changed while reading: " + relative)
    return (
        [json.loads(line) for line in text.splitlines() if line.strip()]
        if events
        else json.loads(text)
    ), row["sha256"]


def bind_original_control_points(data):
    """Return a regional-only dataclass copy bound to original CP + accepted M.

    Call after the common completed-run loader. An unmarked historical field is
    returned by identity, without reinterpretation or accessing guard metadata.
    """
    config = data.run_report.manifest["effective_config"]
    marker = declaration(config)
    if marker is None:
        return data
    if (
        marker != DECLARATION
        or len(data.subject_labels) != 1
        or not config["project"]["parameter_provenance"].get("regional_fit")
        or config["optimization"]["method"] != "lbfgs"
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
        or data.run_report.result["status"] != "completed"
    ):
        raise ValueError("Only a completed frozen NEW guarded singleton field is supported")
    root = Path(data.run_directory).resolve()
    if (root / "output/numerical-guard/violation.json").exists():
        raise ValueError("A failed numerical guard cannot define an accepted field")
    session, session_sha = _output_json_or_events(data, "numerical-guard/session.json")
    events, events_sha = _output_json_or_events(data, "numerical-guard/events.jsonl", events=True)
    provenance = session["provenance"]
    if provenance["scope"] != DECLARATION:
        raise ValueError("Guard session scope differs from prepared field")
    model_path = root / "engine/model.xml"
    model_rows = [
        r
        for r in data.run_report.manifest["protected_artifacts"]
        if r["path"] == "engine/model.xml"
    ]
    if len(model_rows) != 1 or sha256_file(model_path) != model_rows[0]["sha256"]:
        raise ValueError("Protected field model XML changed")
    model = ET.fromstring(model_path.read_bytes())
    if sha256_file(model_path) != model_rows[0]["sha256"]:
        raise ValueError("Field model XML changed while reading")
    text = model.findtext("initial-control-points")
    if not text or Path(text).is_absolute():
        raise ValueError("Original frozen control-point input is not explicitly staged")
    lexical = Path(os.path.abspath(model_path.parent / text))
    path = lexical.resolve()
    try:
        path.relative_to(root / "input")
    except ValueError as error:
        raise ValueError("Original control basis escaped staged inputs") from error
    for candidate in (lexical, *lexical.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError("Original CP path contains a symlink")
    key = path.relative_to(root).as_posix()
    rows = [r for r in data.run_report.manifest["protected_artifacts"] if r["path"] == key]
    if len(rows) != 1:
        raise ValueError("Original CP input is not protected exactly once")
    record = rows[0]
    before = path.stat()
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if (
        path.is_symlink()
        or before.st_size != record["bytes"]
        or sha256_file(path) != record["sha256"]
    ):
        raise ValueError("Original protected CP input changed")
    controls = read_deformetrica_control_points(path, expected_count=data.momenta.shape[1])
    after = path.stat()
    if (
        identity
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or sha256_file(path) != record["sha256"]
    ):
        raise ValueError("Original CP input changed while reading")
    basis = provenance["actual_control_basis"]
    if (
        basis["basis"] != "staged_control_points"
        or basis["shape"] != list(controls.shape)
        or basis["dtype"] != controls.dtype.str
        or basis["sha256"] != hashlib.sha256(controls.tobytes()).hexdigest()
    ):
        raise ValueError("Original CP row order/bits differ from the native guarded basis")
    values = np.asarray(data.momenta).reshape(-1)
    parameter_key = hashlib.sha256(
        str(values.shape).encode() + values.dtype.str.encode() + values.tobytes()
    ).hexdigest()
    exports = [
        e
        for e in events
        if e.get("kind") == "native_export_parameter_binding"
        and e.get("internal_callback") is False
    ]
    accepted = [
        e
        for e in events
        if e.get("kind") in ("initial_accepted", "accepted_callback")
        and e.get("parameter_sha256") == parameter_key
        and e.get("gradient_finite") is True
    ]
    if not exports or exports[-1]["parameter_sha256"] != parameter_key or not accepted:
        raise ValueError("Exported momenta are not bound to the finite accepted native export")
    evaluation = exports[-1]["evaluation_reference"]
    finite = [
        e
        for e in events
        if e.get("kind") == "objective_evaluation"
        and e.get("parameter_sha256") == parameter_key
        and e.get("evaluation_id") == evaluation
        and e.get("objective_finite") is True
        and e.get("gradient_finite") is True
    ]
    if not finite or not any(e.get("evaluation_reference") == evaluation for e in accepted):
        raise ValueError("Native export is not bound to one matching finite accepted FG record")
    if sha256_file(data.momenta_path) != data.momenta_record["sha256"]:
        raise ValueError("Exported momenta changed after completed-run verification")
    hashes = dict(data.source_hashes)
    hashes.update(
        {
            key: record["sha256"],
            "engine/model.xml": sha256_file(model_path),
            "output/numerical-guard/session.json": session_sha,
            "output/numerical-guard/events.jsonl": events_sha,
        }
    )
    return replace(
        data,
        control_points_path=path,
        control_points=controls,
        control_points_record=dict(record, namespace="run", basis="original_frozen_input"),
        source_hashes=hashes,
    )
