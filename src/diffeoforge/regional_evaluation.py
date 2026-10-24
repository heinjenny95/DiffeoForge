"""Bound, endpoint-only dense evaluation of a regional pilot's learned field."""

import json
from pathlib import Path

from diffeoforge.mesh import sha256_file


def field_inputs(run, cache):
    """Operation-local verified field cache with fresh live input identities."""
    from diffeoforge.reference_pca import load_reference_momenta

    key = str(Path(run).resolve())
    if cache is None:
        return load_reference_momenta(run, allow_singleton=True)
    if key not in cache:
        data = load_reference_momenta(run, allow_singleton=True)
        paths = [
            Path(run) / name
            for name in [
                "manifest.json",
                "result.json",
                "output-inventory.json",
                "engine/model.xml",
                "engine/optimization_parameters.xml",
            ]
        ]
        paths.extend([data.control_points_path, data.momenta_path])
        paths.extend(
            Path(run) / row["staged_path"]
            for row in data.run_report.manifest["inputs"]
            if row["role"] == "template"
        )
        cache[key] = data, {p: sha256_file(p) for p in paths}
    data, identities = cache[key]
    if any(sha256_file(p) != digest for p, digest in identities.items()):
        raise ValueError("A cached fixed field or its source changed")
    return data


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


def evaluate_points(
    run,
    points,
    destination,
    *,
    count,
    cancelled=lambda: False,
    event_callback=None,
    _seen=(),
    _cache=None,
):
    """Evaluate new material points only; controls/momenta never depend on their batch."""
    from diffeoforge.mesh import read_vtk_points
    from diffeoforge.reference_fixed_shooting import shoot
    from diffeoforge.regional_fit import _save, read_plan

    run, destination = Path(run), Path(destination)
    if run.resolve() in _seen or len(_seen) >= 12:
        raise ValueError("Cyclic or excessive residual field chain")
    inputs = field_inputs(run, _cache)
    config = inputs.run_report.manifest["effective_config"]
    if len(inputs.subject_labels) != 1 or not config["optimization"]["freeze_template"]:
        raise ValueError("New-point evaluation requires a frozen singleton field")
    plan = read_plan(config)
    prefix = None
    if plan and plan.get("residual"):
        parent = plan["residual"]
        if sha256_file(Path(parent["parent_run"]) / "manifest.json") != parent[
            "parent_manifest_sha256"
        ]:
            raise ValueError("Residual parent changed before new-point evaluation")
        prefix = evaluate_points(
            plan["residual"]["parent_run"],
            points,
            destination.with_name(destination.name + "-prefix"),
            count=count,
            cancelled=cancelled,
            event_callback=event_callback,
            _seen=(*_seen, run.resolve()),
            _cache=_cache,
        )
        points = read_vtk_points(Path(prefix["endpoint"]["path"]))
    source = destination.with_name(destination.name + "-points.vtk")
    _save(source, points)
    seed = dict(
        source_run_directory=str(run),
        subject_labels=list(inputs.subject_labels),
        files={
            role: dict(copy=str(path.resolve()), sha256=sha256_file(path))
            for role, path in [
                ("template", source),
                ("control_points", inputs.control_points_path),
                ("momenta", inputs.momenta_path),
            ]
        },
    )
    paths, protected = shoot(
        config,
        Path("/"),
        seed,
        destination,
        count,
        surface_only=config["model"]["object_id"],
        precision="float64",
        point_cloud=True,
        cancelled=cancelled,
        event_callback=event_callback,
    )
    path = paths[inputs.subject_labels[0]]
    return dict(
        source_run=str(run),
        timepoints=count,
        prefix=prefix,
        protected=protected,
        controls_sha256=sha256_file(inputs.control_points_path),
        momenta_sha256=sha256_file(inputs.momenta_path),
        optimizer_updates=0,
        endpoint=dict(path=str(path), sha256=sha256_file(path)),
    )


def evaluate(
    run,
    destination,
    *,
    count=73,
    cancelled=lambda: False,
    event_callback=None,
    _source=None,
    _seen=(),
    _cache=None,
):
    from diffeoforge.reference_fixed_shooting import shoot

    run, destination = Path(run), Path(destination)
    if run.resolve() in _seen or len(_seen) >= 12:
        raise ValueError("Cyclic or excessive residual field chain")
    inputs = field_inputs(run, _cache)
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
    if _source is None and plan and plan.get("residual", {}).get("original_source_grid"):
        row = plan["residual"]["original_source_grid"]
        source = Path(config["project"]["parameter_provenance"]["regional_fit"]["manifest"]).parent
        source = source / row["copy"]
    reference_source = dict(path=str(source.resolve()), sha256=sha256_file(source))
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
            _source=source,
            _seen=(*_seen, run.resolve()),
            _cache=_cache,
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
        reference_source=reference_source,
    )
    (destination / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
