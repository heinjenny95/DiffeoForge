"""Coarse-to-fine singleton recovery on an unchanged deformation basis.

Rejected geometry can initialize an optimizer, never a scientific approval.
Branches are bounded and recorded; there is no wall-clock deadline.
"""

from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file

VERSION = "progressive-singleton-v1"
BRANCHES = 4
STEPS = 10


def next_attempt(center, observations, diagonal):
    """Alternate broad capture starts with warm, progressively finer matching.

    Observations are chronological attempts for one specimen. Widths depend on
    its measured mismatch/extent, not a species name or a claimed anatomy score.
    """
    previous = [o for o in observations if (o.get("progressive") or {}).get("version") == VERSION]
    last = previous[-1] if previous else None
    phase = last["progressive"] if last else {}
    branch = int(phase.get("branch", 0))
    step = int(phase.get("step", -1)) + 1
    seed = None
    floor = center["attachment_kernel_width"] / 16
    if (
        last
        and last.get("seed")
        and step < STEPS
        and last["values"]["attachment_kernel_width"] > floor * (1 + 1e-9)
    ):
        seed = last["seed"]
    elif last:
        branch += 1
        step = 0
    if branch >= BRANCHES:
        raise ValueError(
            "The coarse-to-fine branches are exhausted. All approvals are saved. "
            "Continue a saved fit or test a denser common model (all fits need new QC)."
        )
    if seed:
        width = max(
            center["attachment_kernel_width"] / 16, last["values"]["attachment_kernel_width"] / 2
        )
    else:
        mismatch = max((o.get("p95", 0) for o in observations), default=0)
        width = min(
            max(center["attachment_kernel_width"] * 2, diagonal / 4, mismatch * 2), diagonal * 2
        )
        width *= (1, 2, 0.5, 1)[branch]
        step = 0
    values = dict(
        center, attachment_kernel_width=width, noise_std=center["noise_std"] / (2 ** (branch + 1))
    )
    return dict(
        values=values,
        seed=seed,
        iterations=120 if seed else 160,
        progressive=dict(
            version=VERSION, branch=branch, step=step, phase="refine" if seed else "capture"
        ),
    )


def seed_request(snapshot, candidate_id, parent, values):
    """Describe a verified fixed-template field; copy it only after child creation."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.reference_pca import load_reference_momenta
    from diffeoforge.reference_sequential_fit import _basis, _values, sequence_info

    candidate = next(c for c in snapshot.candidates if c.candidate_id == candidate_id)
    if (
        candidate.status != "completed"
        or not candidate.metrics
        or candidate.metrics.get("invalid_face_count") != 0
        or _basis(_values(snapshot, candidate_id)) != _basis(values)
    ):
        raise ValueError("Warm continuation requires the same completed deformation basis")
    source = snapshot.study_directory
    info = sequence_info(source)
    bound = study._verify_manifest(parent)
    manifest = study._verify_manifest(source)
    if (
        not info
        or info["phase"] != "individual"
        or Path(info["root"]).resolve() != parent.resolve()
    ):
        raise ValueError("Warm continuation source is outside this specimen sequence")
    run = study.calibration_candidate_run_directory(candidate)
    inputs = load_reference_momenta(run, allow_singleton=True)
    config = inputs.run_report.manifest["effective_config"]
    controls = np.loadtxt(parent / bound["fit_search"]["controls"]["copy"])
    hashes = {
        Path(r["staged_path"]).name: r["geometry"]["sha256"]
        for r in inputs.run_report.manifest["inputs"]
        if r["role"] == "subject"
    }
    template_hashes = [
        r["geometry"]["sha256"]
        for r in inputs.run_report.manifest["inputs"]
        if r["role"] == "template"
    ]
    expected = {r["filename"]: r["sha256"] for r in manifest["fit_search"]["working_targets"]}
    if (
        inputs.subject_labels != (info["filename"],)
        or hashes != expected
        or template_hashes != [bound["inputs"]["template"]["sha256"]]
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
        or config["model"]["deformation"]["kernel_width"] != values["deformation_kernel_width"]
        or manifest["fit_search"]["controls"]["sha256"] != bound["fit_search"]["controls"]["sha256"]
        or inputs.control_points.shape != controls.shape
        or not np.allclose(inputs.control_points, controls, rtol=0, atol=5.000001e-7)
        or inputs.momenta.shape != (1, len(controls), 3)
        or not np.isfinite(inputs.momenta).all()
    ):
        raise ValueError("Warm field does not match the fixed template, subject and control basis")
    return dict(
        source_study=str(source),
        source_study_sha256=sha256_file(source / study.STUDY_MANIFEST),
        candidate_id=candidate_id,
        source_run=str(run),
        source_run_sha256=sha256_file(run / "manifest.json"),
        path=str(inputs.momenta_path),
        sha256=sha256_file(inputs.momenta_path),
        subject_labels=list(inputs.subject_labels),
        purpose="Initialization only; fresh human QC required; optimizer history restarts",
    )


def bind_seed(root, manifest, settings):
    """Reverify and copy the source field into the new immutable study."""
    from diffeoforge import reference_calibration_study as study

    request = settings["warm_seed"]
    source = Path(request["source_study"])
    info = settings["sequence"]
    if sha256_file(source / study.STUDY_MANIFEST) != request["source_study_sha256"]:
        raise ValueError("Warm source study changed")
    values = {
        **manifest["plan"]["baseline_effective_values"],
        **manifest["plan"]["stages"][0]["candidates"][0]["parameter_values"],
    }
    verified = seed_request(
        study.load_reference_calibration_study(source),
        request["candidate_id"],
        Path(info["root"]),
        values,
    )
    if verified != request or request["subject_labels"] != [info["filename"]]:
        raise ValueError("Warm initialization source changed or names another specimen")
    target = root / "warm-initialization" / "momenta.txt"
    study._copy_bound(Path(request["path"]), target, request["sha256"])
    return dict(request, copy=target.relative_to(root).as_posix())


def verify_seed(root, manifest):
    seed = manifest["fit_search"]["warm_seed"]
    path = (root / seed["copy"]).resolve()
    info = manifest["fit_search"]["sequence"]
    if (
        not path.is_relative_to(root.resolve())
        or sha256_file(path) != seed["sha256"]
        or seed["subject_labels"] != [info["filename"]]
    ):
        raise ValueError("Saved warm initialization changed")
