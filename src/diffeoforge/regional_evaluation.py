"""Bound, endpoint-only dense evaluation of a regional pilot's learned field."""

import copy
import hashlib
import json
from pathlib import Path

from diffeoforge.mesh import sha256_file


def _cancellation(cancelled):
    from diffeoforge.mesh_filter_worker import current_cancellation

    callback = cancelled if cancelled is not None else current_cancellation()
    if callback is not None and not callable(callback):
        raise TypeError("Fixed-field cancellation must be callable")
    callback = callback or (lambda: False)
    if callback():
        raise InterruptedError("Fixed-field checks cancelled; saved fields retained")
    return callback


def _prefix_identity(receipt):
    if receipt is None:
        return None
    return dict(
        source_run=str(Path(receipt["source_run"]).resolve()),
        source_manifest_sha256=sha256_file(Path(receipt["source_run"]) / "manifest.json"),
        controls_sha256=receipt["controls_sha256"], momenta_sha256=receipt["momenta_sha256"],
        source_template_sha256=receipt.get("source_template_sha256"),
        reference_source_sha256=receipt.get("reference_source", {}).get("sha256"),
        endpoint_sha256=receipt["endpoint"]["sha256"], timepoints=receipt["timepoints"],
        precision=receipt.get("precision", "float64"), integrator=receipt["integrator"],
        prefix=_prefix_identity(receipt["prefix"]),
    )


def _native_key(config, inputs, seed, count, prefix, point_cloud):
    run = Path(seed["source_run_directory"])
    paths = [run / name for name in ("manifest.json", "result.json", "output-inventory.json",
                                    "engine/model.xml", "engine/optimization_parameters.xml")]
    paths.extend([inputs.control_points_path, inputs.momenta_path])
    paths.extend(run / name for name in inputs.source_hashes)
    for row in seed["files"].values():
        if sha256_file(Path(row["copy"])) != row["sha256"]:
            raise ValueError("Fixed Shooting source changed before endpoint reuse")
    identity = dict(config=config, run=str(run.resolve()),
        fields=[(str(Path(path).resolve()), sha256_file(path)) for path in paths],
        source_files={role: row["sha256"] for role, row in seed["files"].items()},
        subjects=seed["subject_labels"], prefix=_prefix_identity(prefix), count=count,
        precision="float64", integrator="rk2", point_cloud=point_cloud,
        surface_only=config["model"]["object_id"])
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return ("regional-native-endpoint-v1", hashlib.sha256(encoded).hexdigest())


def _check_artifact(root, relative, digest):
    path = root / relative
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve()) or sha256_file(path) != digest):
        raise ValueError("A cached fixed Shooting artifact changed or is missing")
    return path


def _snapshot_native(destination, paths, protected):
    """Seal only fixed Shooting artifacts, never an Atlas run or later QC files."""
    allowed = {"source", "engine", "output", "endpoints"}
    files = {}
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Fixed Shooting cache cannot contain linked artifacts")
        if path.is_dir():
            continue
        if (relative.parts[0] not in allowed
                and relative.as_posix() not in {"stdout.log", "stderr.log"}):
            raise ValueError("Unexpected fixed Shooting artifact; cannot cache this scope")
        files[relative.as_posix()] = sha256_file(path)
    endpoints = {label: path.relative_to(destination).as_posix() for label, path in paths.items()}
    if (not endpoints or any(name not in files for name in endpoints.values())
            or any(files.get(name.replace("\\", "/")) != digest
                   for name, digest in protected.items())):
        raise ValueError("Fixed Shooting cache lacks its bound endpoint or protected inputs")
    return dict(directory=destination.resolve(), files=files, endpoints=endpoints,
                protected=copy.deepcopy(protected))


def _copy_native(entry, destination, cancelled):
    source = entry["directory"]
    if destination.exists():
        raise FileExistsError(destination)
    if (destination.resolve().is_relative_to(source)
            or source.is_relative_to(destination.resolve())):
        raise ValueError("Cached fixed Shooting destinations must remain separate")
    for relative, digest in entry["files"].items():
        _check_artifact(source, relative, digest)
    if cancelled():
        raise InterruptedError("Fixed-field evaluation cancelled before endpoint reuse")
    destination.mkdir(parents=True, exist_ok=False)
    for relative, digest in entry["files"].items():
        origin = _check_artifact(source, relative, digest)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with origin.open("rb") as incoming, target.open("xb") as outgoing:
            while data := incoming.read(1024 * 1024):
                if cancelled():
                    raise InterruptedError("Fixed-field endpoint reuse cancelled")
                outgoing.write(data)
        _check_artifact(destination, relative, digest)
    paths = {label: destination / relative for label, relative in entry["endpoints"].items()}
    return paths, copy.deepcopy(entry["protected"])


def _shoot(config, inputs, seed, destination, count, prefix, *, point_cloud, cache,
           cancelled, event_callback):
    from diffeoforge.reference_fixed_shooting import shoot

    def identity():
        # A prefix replay can take time. Recheck every field after recursion,
        # not only before it, and never trust the memoized endpoint's path alone.
        field_inputs(Path(seed["source_run_directory"]), cache)
        previous = prefix
        while previous:
            field_inputs(Path(previous["source_run"]), cache)
            row = previous["endpoint"]
            if sha256_file(Path(row["path"])) != row["sha256"]:
                raise ValueError("A cached prefix endpoint changed")
            previous = previous["prefix"]
        return _native_key(config, inputs, seed, count, prefix, point_cloud)

    key = identity() if cache is not None else None
    if key is not None and key in cache:
        entry = cache[key]
        paths, protected = _copy_native(entry, destination, cancelled)
        if identity() != key:
            raise ValueError("Fixed Shooting inputs changed during endpoint reuse")
        return paths, protected, dict(version=key[0], source=str(entry["directory"]),
            identity=key[1], native_process_started=False,
            scope="Byte-verified fixed Shooting artifact reuse, not a new native run")
    options = dict(surface_only=config["model"]["object_id"], precision="float64", use_rk2=True,
                   cancelled=cancelled, event_callback=event_callback)
    if point_cloud:
        options["point_cloud"] = True
    paths, protected = shoot(config, Path("/"), seed, destination, count, **options)
    if key is not None:
        if identity() != key:
            raise ValueError("Fixed Shooting inputs changed during evaluation")
        cache[key] = _snapshot_native(destination, paths, protected)
    return paths, protected, None


def field_inputs(run, cache):
    """Operation-local verified field cache with fresh live input identities."""
    from diffeoforge.reference_pca import load_reference_momenta

    key = str(Path(run).resolve())
    if cache is None:
        from diffeoforge.reference_guarded_field import bind_original_control_points

        return bind_original_control_points(load_reference_momenta(run, allow_singleton=True))
    if key not in cache:
        from diffeoforge.reference_guarded_field import bind_original_control_points

        data = bind_original_control_points(load_reference_momenta(run, allow_singleton=True))
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
        paths.extend(Path(run) / name for name in data.source_hashes)
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


def endpoints(candidate):
    """Return the exact measured endpoint per form, checking every binding."""
    subjects = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
    result = {}
    for subject, r in subjects.items():
        rows = [r[kind]["evaluation"]["endpoint"] for kind in
                ("regional_quality", "ordinary_quality", "cohort_quality") if r.get(kind)]
        if not rows:
            continue
        if len(rows) != 1 or sha256_file(Path(rows[0]["path"])) != rows[0]["sha256"]:
            raise ValueError("The evaluated reconstruction changed or is ambiguous")
        result[subject] = rows[0]
    return result


def endpoint(candidate, subject=None):
    """Singleton callers retain their strict scope; cohort callers name a form."""
    rows = endpoints(candidate)
    if subject is not None:
        return rows.get(subject)
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("The evaluated singleton reconstruction changed or is ambiguous")
    return next(iter(rows.values()))


def evaluate_points(
    run,
    points,
    destination,
    *,
    count,
    cancelled=None,
    event_callback=None,
    _seen=(),
    _cache=None,
):
    """Evaluate new material points only; controls/momenta never depend on their batch."""
    cancelled = _cancellation(cancelled)
    from diffeoforge.mesh import read_vtk_points
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
    paths, protected, reuse = _shoot(config, inputs, seed, destination, count, prefix,
        point_cloud=True, cache=_cache, cancelled=cancelled, event_callback=event_callback)
    path = paths[inputs.subject_labels[0]]
    receipt = dict(
        source_run=str(run),
        timepoints=count,
        prefix=prefix,
        protected=protected,
        controls_sha256=sha256_file(inputs.control_points_path),
        momenta_sha256=sha256_file(inputs.momenta_path),
        optimizer_updates=0,
        integrator="rk2",
        endpoint=dict(path=str(path), sha256=sha256_file(path)),
    )
    if reuse:
        receipt["native_endpoint_reuse"] = reuse
    return receipt


def evaluate(
    run,
    destination,
    *,
    count=73,
    cancelled=None,
    event_callback=None,
    _source=None,
    _seen=(),
    _cache=None,
):
    cancelled = _cancellation(cancelled)
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
    endpoints, protected, reuse = _shoot(config, inputs, seed, destination, count, prefix,
        point_cloud=False, cache=_cache, cancelled=cancelled, event_callback=event_callback)
    path = endpoints[inputs.subject_labels[0]]
    receipt = dict(
        version="regional-field-evaluation-v1",
        source_run=str(run),
        source_manifest_sha256=sha256_file(run / "manifest.json"),
        controls_sha256=sha256_file(inputs.control_points_path),
        momenta_sha256=sha256_file(inputs.momenta_path),
        source_template_sha256=sha256_file(source),
        field_paths=dict(control_points=str(inputs.control_points_path),
                         momenta=str(inputs.momenta_path)),
        timepoints=count,
        precision="float64",
        integrator="rk2",
        optimizer_updates=0,
        endpoint=dict(path=str(path), sha256=sha256_file(path)),
        protected=protected,
        anatomical_approval=False,
        prefix=prefix,
        reference_source=reference_source,
    )
    if reuse:
        receipt["native_endpoint_reuse"] = reuse
    (destination / "evaluation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
