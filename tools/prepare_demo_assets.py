"""Build the bounded public presentation fixture, never run an atlas/backend."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from diffeoforge.analysis.pca import momenta_pca
from diffeoforge.desktop.mesh_preview import load_mesh_preview
from diffeoforge.reference_pca import read_deformetrica_momenta

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "src/diffeoforge/desktop/demo_data"


def build_assets() -> dict:
    sources = {}

    def source(path: Path) -> Path:
        sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def mesh(path: Path) -> dict:
        model = load_mesh_preview(source(path))
        return {"vertices": model.vertices, "triangles": model.triangles}

    example = ROOT / "examples/synthetic"
    reference = ROOT / "reference/synthetic-v1"
    manifest = json.loads(source(reference / "reference-manifest.json").read_text())
    for item in manifest["artifacts"]:
        assert (
            hashlib.sha256((reference / item["fixture_path"]).read_bytes()).hexdigest()
            == item["sha256"]
        )
    landmarks = {}
    for row in csv.DictReader(source(example / "landmarks.csv").read_text().splitlines()):
        landmarks.setdefault(row["mesh_file"], {})[row["landmark"]] = [
            float(row[key]) for key in ("x", "y", "z")
        ]
    template = mesh(example / "meshes/template.vtk")
    subjects = []
    target = np.array(list(landmarks["template.vtk"].values()))
    target_center = target.mean(axis=0)
    target_norm = np.linalg.norm(target - target_center)
    for index in range(1, 6):
        label = f"subject-{index:02d}"
        original = mesh(example / f"meshes/{label}.vtk")
        points = np.array(list(landmarks[f"{label}.vtk"].values()))
        center = points.mean(axis=0)
        scale = target_norm / np.linalg.norm(points - center)
        u, _, vt = np.linalg.svd(((points - center) * scale).T @ (target - target_center))
        correction = np.diag([1, 1, np.linalg.det(u @ vt)])
        rotation = u @ correction @ vt
        aligned = (np.array(original["vertices"]) - center) * scale @ rotation + target_center
        subjects.append(
            {
                "label": label,
                "original": original,
                "reconstruction": mesh(reference / f"artifacts/reconstructions/{label}.vtk"),
                "aligned": {"vertices": aligned.tolist(), "triangles": original["triangles"]},
                "landmarks": landmarks[f"{label}.vtk"],
                "group": "Example A" if index <= 2 else "Example B",
            }
        )
    momenta = read_deformetrica_momenta(source(reference / "artifacts/momenta.txt"))
    pca = momenta_pca(momenta, subject_labels=tuple(subject["label"] for subject in subjects))
    convergence = [
        {key: (int(value) if key == "iteration" else float(value)) for key, value in row.items()}
        for row in csv.DictReader(
            source(reference / "artifacts/convergence.csv").read_text().splitlines()
        )
    ]
    residuals = [
        float(value) for value in source(reference / "artifacts/residuals.txt").read_text().split()
    ]
    for path in (example / "LICENSE.md", reference / "LICENSE.md", reference / "README.md"):
        source(path)
    return {
        "format": "diffeoforge-presentation-fixture-1",
        "license": "CC0-1.0",
        "template": template,
        "estimated_template": mesh(reference / "artifacts/estimated-template.vtk"),
        "subjects": subjects,
        "convergence": convergence,
        "residuals": residuals,
        "pca": {
            "scores": pca.scores.tolist(),
            "variance_ratio": pca.explained_variance_ratio.tolist(),
            "method": "Cartesian momenta PCA (precomputed float64 SVD)",
            "rank": pca.numerical_rank,
        },
        "execution": manifest["execution"],
        "engine_environment": manifest["engine_environment"],
        "sources": sources,
        "limits": "Public synthetic engineering example; no biological meaning or private "
        "project evidence. "
        "Alignment is a precomputed similarity fit to template landmarks, not an iterative GPA "
        "run. "
        "Morphs are endpoint interpolation, not native Shooting. Pilot cards and groups are "
        "illustrative.",
    }


def main() -> None:
    DESTINATION.mkdir(exist_ok=True)
    payload = (json.dumps(build_assets(), separators=(",", ":"), allow_nan=False) + "\n").encode()
    (DESTINATION / "presentation.json").write_bytes(payload)
    (DESTINATION / "presentation.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "\n", encoding="ascii"
    )
    (DESTINATION / "LICENSE.md").write_text(
        (ROOT / "reference/synthetic-v1/LICENSE.md").read_text(), encoding="utf-8"
    )
    print(f"Prepared {len(payload)} public fixture bytes; no backend executed.")


if __name__ == "__main__":
    main()
