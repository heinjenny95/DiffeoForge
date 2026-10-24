"""Bound, endpoint-only dense evaluation of a regional pilot's learned field."""

import json
from pathlib import Path

from diffeoforge.mesh import sha256_file


def endpoint(candidate):
    """Return the exact measured endpoint, checking its immutable binding."""
    subjects = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
    rows = [
        r["regional_quality"]["evaluation"]["endpoint"]
        for r in subjects.values()
        if r.get("regional_quality")
    ]
    if not rows:
        return None
    if len(rows) != 1 or sha256_file(Path(rows[0]["path"])) != rows[0]["sha256"]:
        raise ValueError("The evaluated regional reconstruction changed")
    return rows[0]


def evaluate(
    run,
    destination,
    *,
    count=73,
    cancelled=lambda: False,
    event_callback=None,
    _source=None,
    _seen=(),
):
    from diffeoforge.reference_fixed_shooting import shoot
    from diffeoforge.reference_pca import load_reference_momenta

    run, destination = Path(run), Path(destination)
    if run.resolve() in _seen or len(_seen) >= 12:
        raise ValueError("Cyclic or excessive residual field chain")
    inputs = load_reference_momenta(run, allow_singleton=True)
    report = inputs.run_report
    config = report.manifest["effective_config"]
    if len(inputs.subject_labels) != 1 or not config["optimization"]["freeze_template"]:
        raise ValueError("Regional field evaluation requires a frozen singleton source")
    template = next(r for r in report.manifest["inputs"] if r["role"] == "template")
    source = run / template["staged_path"]
    if _source is not None:
        source = Path(_source)
    from diffeoforge.regional_fit import read_plan

    plan = read_plan(config)
    prefix = None
    if plan and plan.get("residual"):
        parent = plan["residual"]
        if (
            sha256_file(Path(parent["parent_run"]) / "manifest.json")
            != parent["parent_manifest_sha256"]
        ):
            raise ValueError("Residual parent changed before full-chain evaluation")
        prefix = evaluate(
            parent["parent_run"],
            destination.with_name(destination.name + "-prefix"),
            count=count,
            cancelled=cancelled,
            event_callback=event_callback,
            _source=_source,
            _seen=(*_seen, run.resolve()),
        )
        source = Path(prefix["endpoint"]["path"])
    seed = dict(
        source_run_directory=str(run),
        subject_labels=list(inputs.subject_labels),
        files={
            name: dict(copy=str(path.resolve()), sha256=sha256_file(path))
            for name, path in [
                ("template", source),
                ("control_points", inputs.control_points_path),
                ("momenta", inputs.momenta_path),
            ]
        },
    )
    endpoints, protected = shoot(
        config,
        Path("/"),
        seed,
        destination,
        count,
        surface_only=config["model"]["object_id"],
        precision="float64",
        cancelled=cancelled,
        event_callback=event_callback,
    )
    path = endpoints[inputs.subject_labels[0]]
    receipt = dict(
        version="regional-field-evaluation-v1",
        source_run=str(run),
        source_manifest_sha256=sha256_file(run / "manifest.json"),
        controls_sha256=sha256_file(inputs.control_points_path),
        momenta_sha256=sha256_file(inputs.momenta_path),
        source_template_sha256=sha256_file(source),
        timepoints=count,
        precision="float64",
        optimizer_updates=0,
        endpoint=dict(path=str(path), sha256=sha256_file(path)),
        protected=protected,
        anatomical_approval=False,
        prefix=prefix,
    )
    (destination / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
