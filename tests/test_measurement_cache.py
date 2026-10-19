from pathlib import Path

import numpy as np
import pytest

from diffeoforge import reference_recommendation as analysis
from diffeoforge.analysis.procrustes import SimilarityTransform


def cohort(tmp_path):
    import shutil

    sources = Path(__file__).parents[1] / "examples/synthetic/meshes"
    paths = [sources / "template.vtk", *sorted(sources.glob("subject-*.vtk"))]
    for path in paths:
        shutil.copyfile(path, tmp_path / path.name)
    return tuple(tmp_path / path.name for path in paths)


def test_cached_measurements_are_identical_but_fresh_hashes_are_required(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    settings = dict(
        alignment_basis="declared_gpa",
        surface_detail_intent="fine",
        deformation_scale_intent="local",
        cache_directory=tmp_path / "cache",
    )
    cold = analysis.recommend_reference_parameters(paths, **settings)
    monkeypatch.setattr(analysis, "load_surface_mesh", lambda path: pytest.fail("Warm parsing"))
    warm = analysis.recommend_reference_parameters(paths, **settings)
    assert cold == warm
    paths[-1].write_text(paths[-1].read_text() + "\n")
    with pytest.raises(BaseException, match="Warm parsing"):
        analysis.recommend_reference_parameters(paths, **settings)


def test_cache_rejects_corruption_and_transform_changes(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    transforms = tuple(SimilarityTransform(np.zeros(3), 1.0, np.eye(3)) for _ in paths)
    settings = dict(
        alignment_basis="diffeoforge_gpa",
        alignment_fingerprint="bound-alignment",
        surface_detail_intent="fine",
        deformation_scale_intent="local",
        transforms=transforms,
        cache_directory=tmp_path / "cache",
    )
    analysis.recommend_reference_parameters(paths, **settings)
    reads = []
    original = analysis.load_surface_mesh

    def count(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(analysis, "load_surface_mesh", count)
    one = next((tmp_path / "cache").glob("*.json"))
    one.write_text('{"tampered": true}')
    analysis.recommend_reference_parameters(paths, **settings)
    assert len(reads) == 1
    reads.clear()
    settings["transforms"] = tuple(SimilarityTransform(np.zeros(3), 2.0, np.eye(3)) for _ in paths)
    doubled = analysis.recommend_reference_parameters(paths, **settings)
    assert len(reads) == len(paths)
    assert doubled.template_diagonal > 0


def test_preparation_cancel_preserves_inputs_and_does_not_measure_next_mesh(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    original_bytes = {p: p.read_bytes() for p in paths}
    reads = []
    original = analysis.load_surface_mesh

    def count(path):
        reads.append(path)
        return original(path)

    cancelled = False

    def progress(*_args):
        nonlocal cancelled
        cancelled = True

    monkeypatch.setattr(analysis, "load_surface_mesh", count)
    with pytest.raises(InterruptedError, match="cancelled"):
        analysis.recommend_reference_parameters(
            paths,
            alignment_basis="declared_gpa",
            surface_detail_intent="fine",
            deformation_scale_intent="local",
            progress_callback=progress,
            cancel_requested=lambda: cancelled,
            cache_directory=tmp_path / "cache",
        )
    assert reads == [paths[0]]
    assert {p: p.read_bytes() for p in paths} == original_bytes
