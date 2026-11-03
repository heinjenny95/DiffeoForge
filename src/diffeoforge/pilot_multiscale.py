"""Finite broad/detail hypothesis and deterministic sites-only shared support."""

import math

import numpy as np

VERSION = "common-broad-detail-v1"
MAX_CONTROLS = 2000
AREA_SAMPLES = 8192
SOURCE_VERTEX_CANDIDATES = 65536
SAMPLE_SEED = 2026110207
VALUE_KEYS = (
    "attachment_kernel_width",
    "deformation_kernel_width",
    "initial_control_point_spacing",
    "noise_std",
)


def specification(values, *, precision, tolerance, required_controls):
    """One declared two-objective experiment, never an unchanged continuation."""
    if (
        precision != "float32"
        or type(required_controls) is not int
        or not 1 <= required_controls <= MAX_CONTROLS
    ):
        raise ValueError(
            "This qualified shared hypothesis requires Float32 and at most 2,000 controls"
        )
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or tolerance <= 0
        or any(
            isinstance(values.get(k), bool)
            or not isinstance(values.get(k), (int, float))
            or not math.isfinite(values[k])
            or values[k] <= 0
            for k in VALUE_KEYS
        )
    ):
        raise ValueError("A shared hypothesis needs finite positive retained model values")
    base = {k: float(values[k]) for k in VALUE_KEYS}
    width = base["deformation_kernel_width"] * 0.5
    capture = dict(
        base,
        attachment_kernel_width=width * 2,
        deformation_kernel_width=width,
        initial_control_point_spacing=width,
        noise_std=base["noise_std"] * 0.5,
    )
    detail = dict(capture, attachment_kernel_width=width * 0.45)
    return dict(
        version=VERSION,
        baseline=base,
        stages=[
            dict(name="capture", values=capture, maximum_iterations=120, initializer="native_zero"),
            dict(
                name="detail",
                values=detail,
                maximum_iterations=120,
                initializer="same_form_complete_capture_field",
            ),
        ],
        controls=MAX_CONTROLS,
        required_controls=required_controls,
        precision=precision,
        timepoints=37,
        use_rk2=True,
        tolerance=min(float(tolerance), 1e-6),
        optimizer="lbfgs",
        optimizer_history_restored=False,
        automatic_recovery=False,
        maximum_native_stages=2,
        maximum_total_accepted_steps=240,
        quality_policy="ordinary-fixed-field-quality-v1",
        native_cap_is_not_convergence=True,
        approval_transferred=False,
    )


def merge_sites(prefix, blocks, *, diagonal):
    """Use arbitrary ambient control locations only; never transfer momenta."""
    points = np.asarray(prefix, dtype=np.float64).copy()
    if (
        points.ndim != 2
        or points.shape[1:] != (3,)
        or not len(points)
        or not np.isfinite(points).all()
        or not math.isfinite(diagonal)
        or diagonal <= 0
    ):
        raise ValueError("Shared support requires finite three-dimensional control sites")
    # A relative tolerance covers legacy six-decimal control exports without
    # tying a sites-only candidate to one coordinate unit. Exact initial rows stay.
    tolerance = diagonal * 2e-7
    additions = []
    for block in blocks:
        sites = np.asarray(block, dtype=np.float64)
        if sites.ndim != 2 or sites.shape[1:] != (3,) or not np.isfinite(sites).all():
            raise ValueError("An accepted control-site block is invalid")
        before = len(points)
        for point in sites:
            if np.linalg.norm(points - point, axis=1).min() > tolerance:
                points = np.vstack((points, point))
                if len(points) > MAX_CONTROLS:
                    raise ValueError("Accepted shared support exceeds the 2,000-control guard")
        additions.append(len(points) - before)
    if len(points) > MAX_CONTROLS:
        raise ValueError("Accepted shared support exceeds the 2,000-control guard")
    return points, dict(
        original_sites=len(prefix),
        union_sites=len(points),
        added_per_block=additions,
        duplicate_tolerance=tolerance,
        sites_only=True,
        momenta_transferred=False,
    )


def source_supported_sites(prefix, vertices, faces, *, target_count=MAX_CONTROLS):
    """Append deterministic source FPS sites, preserving every initial row."""
    from diffeoforge.reference_fit_search import surface_samples

    points = np.asarray(prefix, dtype=np.float64).copy()
    v, f = np.asarray(vertices, float), np.asarray(faces, int)
    if (
        points.ndim != 2
        or points.shape[1:] != (3,)
        or not len(points)
        or v.ndim != 2
        or v.shape[1:] != (3,)
        or not len(v)
        or f.ndim != 2
        or f.shape[1:] != (3,)
        or not len(f)
        or f.min() < 0
        or f.max() >= len(v)
        or not np.isfinite(v).all()
        or not np.isfinite(points).all()
        or type(target_count) is not int
        or not len(points) <= target_count <= MAX_CONTROLS
    ):
        raise ValueError("Invalid or over-budget original-source support candidate")
    diagonal = float(np.linalg.norm(np.ptp(v, axis=0)))
    if not diagonal > 0:
        raise ValueError("Original-source support requires a nonempty surface")
    ids = (
        np.arange(len(v))
        if len(v) <= SOURCE_VERTEX_CANDIDATES
        else np.linspace(0, len(v) - 1, SOURCE_VERTEX_CANDIDATES, dtype=np.int64)
    )
    cloud = np.concatenate((surface_samples(v, f, AREA_SAMPLES, seed=SAMPLE_SEED), v[ids]))
    minimum = np.full(len(cloud), np.inf)
    for start in range(0, len(points), 64):
        distances = np.sum((cloud[:, None] - points[None, start : start + 64]) ** 2, axis=2)
        minimum = np.minimum(minimum, distances.min(axis=1))
    before = float(np.sqrt(minimum.max()))
    added = []
    for _ in range(target_count - len(points)):
        index = int(np.argmax(minimum))
        if minimum[index] <= diagonal**2 * 1e-24:
            raise ValueError("Original source has too few distinct candidate sites for this basis")
        point = cloud[index]
        points = np.vstack((points, point))
        minimum = np.minimum(minimum, np.sum((cloud - point) ** 2, axis=1))
        added.append(index)
    return points, dict(
        version=VERSION,
        count=len(points),
        preserved_sites=len(prefix),
        source_vertex_candidates=len(ids),
        area_samples=AREA_SAMPLES,
        sample_seed=SAMPLE_SEED,
        farthest_candidate_indices=added,
        maximum_candidate_support_distance=float(np.sqrt(minimum.max())),
        maximum_candidate_support_distance_before=before,
        original_surface_unchanged=True,
        template_vertices=len(v),
        target_geometry_used=False,
        momenta_transferred=False,
    )


def retained_support(snapshot, value):
    """Read complete accepted-field sites on their verified original cohort.

    Original common settings remain the physics reference. A matching current
    ordinary candidate may contribute its extra control locations, even when
    its shape was rejected; none of its momenta or approval is reused.
    Every accepted field/prefix contributes locations only, not coefficients.
    """
    from pathlib import Path

    from diffeoforge import reference_calibration_study as study
    from diffeoforge import reference_guided_pilot as guided
    from diffeoforge.config import load_config
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_refinement import load_field
    from diffeoforge.mesh import sha256_file
    from diffeoforge.pilot_common_capacity import demand
    from diffeoforge.pilot_form_progress import verify_marker
    from diffeoforge.regional_fit import read_plan
    from diffeoforge.surface_io import load_surface_mesh

    info = guided.record(snapshot)
    verify_marker(value, info["origin"], info["pilot_order"])
    if {r["filename"] for r in value["reviews"]} != set(info["pilot_order"]):
        raise ValueError("A new common hypothesis requires all retained individual reviews")
    rows = value["reviews"]
    original = value["protocol"]["reference"]
    base = verify_reference(original)
    manifest = study._verify_manifest(base.study_directory)
    candidate = next(c for c in base.candidates if c.candidate_id == original["candidate_id"])
    config = load_config(candidate.config_path)
    template_row = manifest["inputs"]["template"]
    template = study._safe_study_path(base.study_directory, template_row["copy"])
    source = load_surface_mesh(template).geometry
    diagonal = float(np.linalg.norm(np.ptp(source.vertices, axis=0)))
    controls = base.attachment_comparison["controls"]
    prefix_study = base
    current = study._verify_manifest(snapshot.study_directory)
    if (
        not snapshot.attachment_comparison.get("regional_objective")
        and current["inputs"]["template"]["sha256"] == template_row["sha256"]
        and snapshot.attachment_comparison["controls"]["count"] > controls["count"]
    ):
        controls = snapshot.attachment_comparison["controls"]
        prefix_study = snapshot
    path = study._safe_study_path(prefix_study.study_directory, controls["copy"])
    if sha256_file(path) != controls["sha256"]:
        raise ValueError("Retained original control basis changed")
    prefix = np.loadtxt(path, ndmin=2)
    blocks, records, seen = [], [], set()

    def include(run, target, target_sha, stack=()):
        root = Path(run).resolve()
        if root in stack or len(stack) >= 12:
            raise ValueError("Cyclic or excessive accepted field history")
        if root in seen:
            return
        field = load_field(root)
        if field.subject_labels != (target,):
            raise ValueError("Accepted control sites belong to another original form")
        report = field.run_report
        subjects = [r for r in report.manifest["inputs"] if r["role"] == "subject"]
        if len(subjects) != 1 or subjects[0]["geometry"]["sha256"] != target_sha:
            raise ValueError("Accepted control sites changed their original input binding")
        seen.add(root)
        sites = np.asarray(field.control_points, dtype=np.float64).copy()
        blocks.append(sites)
        records.append(
            dict(
                run=str(root),
                manifest_sha256=sha256_file(root / "manifest.json"),
                control_points=str(field.control_points_path),
                control_points_sha256=sha256_file(field.control_points_path),
                count=len(sites),
            )
        )
        plan = read_plan(report.manifest["effective_config"])
        parent = (plan or {}).get("residual")
        if parent:
            p = Path(parent["parent_run"])
            if sha256_file(p / "manifest.json") != parent["parent_manifest_sha256"]:
                raise ValueError("Accepted prefix manifest changed")
            include(p, target, target_sha, (*stack, root))

    for row in rows:
        ref = dict(row)
        ref["target"] = ref.pop("filename")
        parent = verify_reference(ref)
        old = study._verify_manifest(parent.study_directory)
        target = next(r for r in old["inputs"]["subjects"] if r["filename"] == ref["target"])
        c = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        include(study.calibration_candidate_run_directory(c), ref["target"], target["sha256"])
    union, merged = merge_sites(prefix, blocks, diagonal=diagonal)
    counts = demand(value)
    spec = specification(
        original["values"],
        precision=config["runtime"]["precision"],
        tolerance=config["optimization"]["convergence_tolerance"],
        required_controls=max(counts.values()),
    )
    return (
        union,
        source,
        dict(
            version=VERSION,
            original_protocol=original,
            template=dict(path=str(template), sha256=sha256_file(template)),
            prefix=dict(
                path=str(path),
                sha256=sha256_file(path),
                count=len(prefix),
                study_directory=str(prefix_study.study_directory),
                study_manifest_sha256=sha256_file(
                    prefix_study.study_directory / study.STUDY_MANIFEST
                ),
                sites_only=True,
                momenta_transferred=False,
            ),
            blocks=records,
            union=merged,
            accepted_control_demand=counts,
            specification=spec,
            accepted_reviews=rows,
            sites_only=True,
            momenta_transferred=False,
        ),
    )
