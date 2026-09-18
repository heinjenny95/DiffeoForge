from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from diffeoforge.config import InputSummary
from diffeoforge.desktop.reference_production_readiness import (
    MAX_PRODUCTION_CHECKPOINT_INTERVAL,
    assess_reference_production_readiness,
    assess_reference_resume_production_readiness,
)
from diffeoforge.mesh import MeshMetadata
from diffeoforge.report import PreflightResult


def _mesh(path: Path, *, faces: int, byte_count: int) -> MeshMetadata:
    return MeshMetadata(
        path=str(path),
        bytes=byte_count,
        sha256="0" * 64,
        vtk_version="3.0",
        encoding="ASCII",
        dataset_type="POLYDATA",
        points=faces // 2 + 2,
        cells=faces,
        triangular=True,
        bounds=(0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
        bounding_box_extents=(1.0, 1.0, 1.0),
        bounding_box_diagonal=3**0.5,
    )


def _preflight(
    tmp_path: Path,
    *,
    subjects: int = 300,
    faces: int = 10_000,
    checkpoint_interval: int = 5,
    device: str = "cuda",
) -> PreflightResult:
    config_path = (tmp_path / "project" / "atlas.yaml").resolve()
    config_path.parent.mkdir(parents=True)
    template_path = tmp_path / "template.vtk"
    subject_paths = tuple(tmp_path / f"subject-{index:03d}.vtk" for index in range(subjects))
    config = {
        "model": {"deformation": {"timepoints": 20}},
        "optimization": {"save_every_n_iterations": checkpoint_interval},
        "runtime": {"device": device},
        "output": {"directory": "./runs"},
    }
    return PreflightResult(
        config_path=config_path,
        config=config,
        inputs=InputSummary(tmp_path, template_path, subjects, subject_paths),
        template=_mesh(template_path, faces=faces, byte_count=600_000),
        subjects=tuple(
            _mesh(path, faces=faces, byte_count=550_000) for path in subject_paths
        ),
        notices=(),
    )


def test_production_readiness_requires_frequent_checkpoint_and_resume_disk(
    tmp_path: Path,
) -> None:
    preflight = _preflight(tmp_path, checkpoint_interval=100)
    readiness_free = 100 * 1024**3

    readiness = assess_reference_production_readiness(
        preflight,
        observed_free_bytes=readiness_free,
    )

    assert readiness.production_scale is True
    assert readiness.ready is False
    assert readiness.observed_free_bytes == readiness_free
    assert readiness.projected_vtk_file_count == 6_301
    assert readiness.required_free_bytes > readiness.projected_output_bytes
    assert str(MAX_PRODUCTION_CHECKPOINT_INTERVAL) in readiness.blockers[0]


def test_production_readiness_accepts_300_by_10k_with_disk_reserve(
    tmp_path: Path,
) -> None:
    readiness = assess_reference_production_readiness(
        _preflight(tmp_path),
        observed_free_bytes=100 * 1024**3,
    )

    assert readiness.production_scale is True
    assert readiness.ready is True
    assert readiness.blockers == ()
    assert readiness.checkpoint_interval == 5
    assert readiness.projected_output_bytes > 3 * 1024**3


def test_production_gate_does_not_block_small_pilot(tmp_path: Path) -> None:
    readiness = assess_reference_production_readiness(
        _preflight(
            tmp_path,
            subjects=9,
            faces=10_000,
            checkpoint_interval=100,
            device="cpu",
        ),
        observed_free_bytes=0,
    )

    assert readiness.production_scale is False
    assert readiness.ready is True
    assert readiness.blockers == ()
    assert readiness.warnings == ()


def test_production_resume_rechecks_checkpoint_cadence_and_successor_disk(
    tmp_path: Path,
) -> None:
    source_run = tmp_path / "runs" / "interrupted-001"
    source_run.mkdir(parents=True)
    geometry = {"cells": 10_000, "bytes": 600_000}
    evidence = SimpleNamespace(
        source_run=source_run,
        manifest={
            "effective_config": {
                "model": {"deformation": {"timepoints": 20}},
                "optimization": {"save_every_n_iterations": 100},
                "runtime": {"device": "cuda"},
            },
            "input_count": {"subjects": 300, "templates": 1},
            "inputs": [
                {"role": "template", "geometry": geometry},
                *(
                    {"role": "subject", "geometry": geometry}
                    for _index in range(300)
                ),
            ],
        },
        result={"outputs": {"total_bytes": 4 * 1024**3}},
    )

    readiness = assess_reference_resume_production_readiness(
        evidence,
        observed_free_bytes=5 * 1024**3,
    )

    assert readiness.production_scale is True
    assert readiness.ready is False
    assert len(readiness.blockers) == 2
    assert "checkpoint" in readiness.blockers[0]
    assert "successor reserve" in readiness.blockers[1]
