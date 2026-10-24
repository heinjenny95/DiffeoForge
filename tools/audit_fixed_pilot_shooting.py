"""Opt-in public synthetic reference-runtime audit; never reads private geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import yaml

from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_fixed_shooting import movement, shoot
from diffeoforge.reference_holdout_study import _trained_model_artifacts
from diffeoforge.reference_pca import load_reference_momenta
from diffeoforge.reference_pca_deformations import _write_momenta
from diffeoforge.reference_pilot_qualification import _reconstructions
from diffeoforge.runs import execute_run, prepare_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--wsl-distribution", required=True)
    parser.add_argument("--reference-executable", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--kernel-backend", choices=("torch", "keops"), default="torch")
    parser.add_argument("--rk2", action="store_true")
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1]
    config = load_config(source / "examples/minimal-atlas.yaml")
    config["input"].update(
        directory=str(source / "examples/synthetic/meshes"),
        template=str(source / "examples/synthetic/meshes/template.vtk"),
        subject_pattern="subject-0[1-3].vtk",
    )
    config["runtime"].update(
        kernel_backend=args.kernel_backend,
        device=args.device,
        threads=1,
        precision="float32",
        launcher=dict(
            type="wsl", distribution=args.wsl_distribution, executable=args.reference_executable
        ),
    )
    config["optimization"].update(
        max_iterations=2,
        freeze_template=True,
        freeze_control_points=True,
        save_every_n_iterations=1,
    )
    controls = root / "initial-controls.txt"
    np.savetxt(controls, [[-0.5, 0, 0], [0, 0, 0], [0.5, 0, 0], [0, 0.3, 0]])
    momenta = root / "initial-momenta.txt"
    fields = np.array([[[0.0, 0.1, 0.02], [0.1, 0.0, -0.03], [0.0, -0.08, 0.03], [0.06, 0.02, 0]]])
    _write_momenta(momenta, np.concatenate([fields, -fields, 0.7 * fields]))
    config["model"]["deformation"].update(
        timepoints=5,
        initial_control_points=str(controls),
        initial_momenta=str(momenta),
        initial_momenta_subjects=[f"subject-0{i}.vtk" for i in (1, 2, 3)],
        use_rk2=args.rk2,
    )
    config["output"]["directory"] = str(root / "runs")
    path = root / "atlas.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run = prepare_run(path, run_id="public-synthetic")
    if execute_run(run) != 0:
        raise RuntimeError("Public synthetic reference atlas audit failed")
    inputs = load_reference_momenta(run)
    template, *_ = _trained_model_artifacts(run)
    seed = dict(source_run_directory=str(run), subject_labels=list(inputs.subject_labels), files={})
    for role, bound in (
        ("template", template),
        ("control_points", inputs.control_points_path),
        ("momenta", inputs.momenta_path),
    ):
        seed["files"][role] = dict(copy=str(bound.relative_to(root)), sha256=sha256_file(bound))
    grids = {}
    for count in (5, 9, 17):
        grids[count], _ = shoot(config, root, seed, root / f"shoot-{count}", count)
    _, recon = _reconstructions(run)
    roundtrip = {n: movement(p, grids[5][n], 1) for n, p in recon.items()}
    differences = {
        f"{a}->{b}": {n: movement(grids[a][n], grids[b][n], 1) for n in recon}
        for a, b in ((5, 9), (9, 17))
    }
    if any(r["maximum"] > 1e-4 for r in roundtrip.values()):
        raise RuntimeError("Source-count endpoints did not round-trip")
    if not np.any(np.abs(inputs.momenta) > 1e-6):
        raise RuntimeError("Audit must exercise a nonzero nonlinear deformation")
    if any(differences["9->17"][n]["rms"] >= differences["5->9"][n]["rms"] for n in recon):
        raise RuntimeError("Nested-grid differences did not decrease for every public specimen")
    result = dict(
        status="passed",
        subjects=list(recon),
        roundtrip=roundtrip,
        integration=differences,
        boundary="Public synthetic runtime/identity audit; "
        "not scientific validation of a private atlas",
        artifacts={
            str(p.relative_to(root)): sha256_file(p) for p in root.rglob("*") if p.is_file()
        },
    )
    (root / "audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(dict(status="passed", roundtrip=roundtrip, integration=differences)))


if __name__ == "__main__":
    main()
