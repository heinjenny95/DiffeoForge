"""Explicit completed-field fixture for receipt-only calibration controllers."""

from types import SimpleNamespace

import numpy as np

from diffeoforge.config import load_config


def field_fixture(run):
    from diffeoforge import reference_calibration_study as study

    config_path = next(
        p / "atlas.yaml" for p in (run, *run.parents) if (p / "atlas.yaml").is_file()
    )
    config = load_config(config_path)
    root = next(p for p in (run, *run.parents) if (p / study.STUDY_MANIFEST).is_file())
    manifest = study._read_json(root / study.STUDY_MANIFEST, "synthetic study")
    controls = manifest["attachment_comparison"]["controls"]
    points = np.loadtxt(root / controls["copy"]).reshape(-1, 3)
    labels = tuple(r["filename"] for r in manifest["inputs"]["subjects"])
    momenta = np.full((len(labels), len(points), 3), 0.001, dtype=np.float64)
    path = run / "synthetic-final-momenta.txt"
    path.write_text(
        f"{len(labels)} {len(points)} 3\n" + "0.001 0.001 0.001\n" * (len(labels) * len(points)),
        encoding="utf-8",
    )
    inputs = [
        dict(role="subject", staged_path=r["filename"], geometry=dict(sha256=r["sha256"]))
        for r in manifest["inputs"]["subjects"]
    ]
    inputs.append(
        dict(role="template", geometry=dict(sha256=manifest["inputs"]["template"]["sha256"]))
    )
    return SimpleNamespace(
        momenta=momenta,
        momenta_path=path,
        control_points=points,
        subject_labels=labels,
        run_report=SimpleNamespace(manifest=dict(effective_config=config, inputs=inputs)),
    )
