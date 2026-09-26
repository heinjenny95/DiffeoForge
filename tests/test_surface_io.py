from __future__ import annotations

import csv
import importlib.util
import struct
from pathlib import Path

import pytest
import yaml

from diffeoforge.analysis.landmarks import LANDMARK_COLUMNS
from diffeoforge.config import ConfigurationError, validate_input_paths
from diffeoforge.desktop.mesh_preview import load_mesh_preview
from diffeoforge.desktop.project_setup import (
    DesktopEngine,
    ProjectSetupRequest,
    create_project,
)
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.preprocessing import (
    prepare_landmark_aligned_inputs,
    preview_landmark_alignment,
)
from diffeoforge.surface_io import load_surface_mesh

VERTICES = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)
TRIANGLES = (
    (0, 2, 1),
    (0, 1, 3),
    (1, 2, 3),
    (2, 0, 3),
)


def _transformed(
    *,
    scale: float = 1.0,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    vertices: tuple[tuple[float, float, float], ...] = VERTICES,
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(scale * value + offset[axis] for axis, value in enumerate(vertex))
        for vertex in vertices
    )


def _write_obj(
    path: Path,
    vertices: tuple[tuple[float, float, float], ...] = VERTICES,
    *,
    negative_indices: bool = False,
    triangles: tuple[tuple[int, int, int], ...] = TRIANGLES,
) -> Path:
    faces = (
        tuple(index - len(vertices) for index in triangle)
        if negative_indices
        else tuple(index + 1 for index in triangle)
        for triangle in triangles
    )
    path.write_text(
        "\n".join(
            (
                "# DiffeoForge OBJ fixture",
                *(f"v {x} {y} {z}" for x, y, z in vertices),
                *(f"f {a} {b} {c}" for a, b, c in faces),
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_ply(
    path: Path,
    vertices: tuple[tuple[float, float, float], ...] = VERTICES,
    *,
    encoding: str = "ascii",
    triangles: tuple[tuple[int, int, int], ...] = TRIANGLES,
) -> Path:
    header = "\n".join(
        (
            "ply",
            f"format {encoding} 1.0",
            f"element vertex {len(vertices)}",
            "property double x",
            "property double y",
            "property double z",
            "property uchar red",
            f"element face {len(triangles)}",
            "property list uchar int vertex_indices",
            "end_header",
        )
    ).encode("ascii") + b"\n"
    if encoding == "ascii":
        payload = (
            "\n".join(
                (
                    *(f"{x} {y} {z} 17" for x, y, z in vertices),
                    *(f"3 {a} {b} {c}" for a, b, c in triangles),
                )
            )
            + "\n"
        ).encode("ascii")
    else:
        endian = "<" if encoding == "binary_little_endian" else ">"
        payload = b"".join(
            struct.pack(f"{endian}dddB", x, y, z, 17)
            for x, y, z in vertices
        )
        payload += b"".join(
            struct.pack(f"{endian}Biii", 3, a, b, c)
            for a, b, c in triangles
        )
    path.write_bytes(header + payload)
    return path


def _write_stl(
    path: Path,
    vertices: tuple[tuple[float, float, float], ...] = VERTICES,
    *,
    binary: bool = False,
    triangles: tuple[tuple[int, int, int], ...] = TRIANGLES,
) -> Path:
    if binary:
        header = b"DiffeoForge binary STL fixture".ljust(80, b"\0")
        payload = header + struct.pack("<I", len(triangles))
        for triangle in triangles:
            coordinates = tuple(
                coordinate
                for index in triangle
                for coordinate in vertices[index]
            )
            payload += struct.pack("<12fH", 0.0, 0.0, 0.0, *coordinates, 0)
        path.write_bytes(payload)
    else:
        lines = ["solid diffeoforge"]
        for triangle in triangles:
            lines.extend(("  facet normal 0 0 0", "    outer loop"))
            lines.extend(
                f"      vertex {vertices[index][0]} {vertices[index][1]} "
                f"{vertices[index][2]}"
                for index in triangle
            )
            lines.extend(("    endloop", "  endfacet"))
        lines.append("endsolid diffeoforge")
        path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return path


@pytest.mark.parametrize(
    ("name", "writer", "source_format", "encoding"),
    (
        ("surface.obj", lambda path: _write_obj(path), "obj", "text/utf-8"),
        ("negative.obj", lambda path: _write_obj(path, negative_indices=True), "obj", "text/utf-8"),
        ("ascii.ply", lambda path: _write_ply(path), "ply", "ascii"),
        (
            "little.ply",
            lambda path: _write_ply(path, encoding="binary_little_endian"),
            "ply",
            "binary_little_endian",
        ),
        (
            "big.ply",
            lambda path: _write_ply(path, encoding="binary_big_endian"),
            "ply",
            "binary_big_endian",
        ),
        ("ascii.stl", lambda path: _write_stl(path), "stl", "ascii"),
        (
            "binary.stl",
            lambda path: _write_stl(path, binary=True),
            "stl",
            "binary_little_endian",
        ),
    ),
)
def test_supported_surface_readers_preserve_triangle_geometry(
    tmp_path: Path,
    name: str,
    writer,
    source_format: str,
    encoding: str,
) -> None:
    source = writer(tmp_path / name)

    loaded = load_surface_mesh(source)
    preview = load_mesh_preview(source)

    assert loaded.metadata.source_format == source_format
    assert loaded.metadata.encoding == encoding
    assert loaded.metadata.sha256 == sha256_file(source)
    assert loaded.metadata.points == 4
    assert loaded.metadata.triangles == 4
    assert set(loaded.geometry.vertices) == set(VERTICES)
    actual_faces = {
        frozenset(loaded.geometry.vertices[index] for index in triangle)
        for triangle in loaded.geometry.triangles
    }
    expected_faces = {
        frozenset(VERTICES[index] for index in triangle)
        for triangle in TRIANGLES
    }
    assert actual_faces == expected_faces
    if source_format != "stl":
        assert loaded.geometry.vertices == VERTICES
        assert loaded.geometry.triangles == TRIANGLES
    assert preview.sha256 == loaded.metadata.sha256
    assert preview.point_count == 4
    assert preview.triangle_count == 4


@pytest.mark.parametrize("suffix", (".obj", ".ply"))
def test_polygonal_obj_and_ply_fail_instead_of_silently_triangulating(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = tmp_path / f"quad{suffix}"
    if suffix == ".obj":
        source.write_text(
            "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n",
            encoding="utf-8",
        )
    else:
        source.write_text(
            "\n".join(
                (
                    "ply",
                    "format ascii 1.0",
                    "element vertex 4",
                    "property float x",
                    "property float y",
                    "property float z",
                    "element face 1",
                    "property list uchar int vertex_indices",
                    "end_header",
                    "0 0 0",
                    "1 0 0",
                    "1 1 0",
                    "0 1 0",
                    "4 0 1 2 3",
                )
            )
            + "\n",
            encoding="ascii",
        )

    with pytest.raises(ConfigurationError, match="exclusively triangular"):
        load_surface_mesh(source)


def _write_mixed_cohort(directory: Path) -> tuple[Path, tuple[Path, ...]]:
    directory.mkdir()
    template = _write_obj(directory / "template.obj")
    subjects = (
        _write_ply(
            directory / "subject-01.ply",
            _transformed(scale=1.4, offset=(2.0, -1.0, 0.5)),
        ),
        _write_stl(
            directory / "subject-02.stl",
            _transformed(scale=0.8, offset=(-1.0, 3.0, 1.5)),
            binary=True,
        ),
    )
    return template, subjects


def _write_project_cohort(directory: Path) -> tuple[Path, tuple[Path, ...]]:
    directory.mkdir()
    vertices = tuple(
        (x + component * 3.0, y, z)
        for component in range(3)
        for x, y, z in VERTICES
    )
    triangles = tuple(
        tuple(index + component * len(VERTICES) for index in triangle)
        for component in range(3)
        for triangle in TRIANGLES
    )
    template = _write_obj(
        directory / "template.obj",
        vertices,
        triangles=triangles,
    )
    subjects = (
        _write_ply(
            directory / "subject-01.ply",
            _transformed(
                scale=1.4,
                offset=(2.0, -1.0, 0.5),
                vertices=vertices,
            ),
            triangles=triangles,
        ),
        _write_stl(
            directory / "subject-02.stl",
            _transformed(
                scale=0.8,
                offset=(-1.0, 3.0, 1.5),
                vertices=vertices,
            ),
            binary=True,
            triangles=triangles,
        ),
    )
    return template, subjects


def _write_mixed_landmarks(
    path: Path,
    template: Path,
    subjects: tuple[Path, ...],
) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LANDMARK_COLUMNS)
        for source in (template, *subjects):
            vertices = load_surface_mesh(source).geometry.vertices
            for label, index in zip(("LM1", "LM2", "LM3"), (0, 1, 2), strict=True):
                writer.writerow((source.name, label, *vertices[index]))
    return path


def test_mixed_source_formats_publish_raw_and_aligned_vtk_separately(
    tmp_path: Path,
) -> None:
    source_directory = tmp_path / "source"
    template, subjects = _write_mixed_cohort(source_directory)
    landmarks = _write_mixed_landmarks(
        tmp_path / "landmarks.csv",
        template,
        subjects,
    )
    source_hashes = {
        path: sha256_file(path) for path in (template, *subjects)
    }
    preview = preview_landmark_alignment(
        source_directory,
        landmarks_file=landmarks,
        template=template,
        subject_pattern="*.*",
    )

    result = prepare_landmark_aligned_inputs(
        source_directory,
        project_directory=tmp_path / "project",
        landmarks_file=landmarks,
        template=template,
        subject_pattern="*.*",
        expected_fingerprint=preview.fingerprint,
    )

    assert result.raw_directory == result.directory / "raw"
    assert result.aligned_directory == result.directory / "aligned-vtk"
    assert result.template.name == "template.vtk"
    assert tuple(path.name for path in result.subjects) == (
        "subject-01.vtk",
        "subject-02.vtk",
    )
    assert {
        path: sha256_file(path) for path in (template, *subjects)
    } == source_hashes
    assert {
        path.name: sha256_file(result.raw_directory / path.name)
        for path in (template, *subjects)
    } == {
        path.name: digest for path, digest in source_hashes.items()
    }
    for aligned in (result.template, *result.subjects):
        geometry = read_vtk_polydata(aligned)
        assert len(geometry.vertices) == 4
        assert len(geometry.triangles) == 4


def test_existing_preprocessing_rejects_changed_raw_copy(tmp_path: Path) -> None:
    source_directory = tmp_path / "source"
    template, subjects = _write_mixed_cohort(source_directory)
    landmarks = _write_mixed_landmarks(
        tmp_path / "landmarks.csv",
        template,
        subjects,
    )
    project = tmp_path / "project"
    result = prepare_landmark_aligned_inputs(
        source_directory,
        project_directory=project,
        landmarks_file=landmarks,
        template=template,
        subject_pattern="*.*",
    )
    changed = result.raw_directory / subjects[0].name
    changed.write_bytes(changed.read_bytes() + b"\n")

    with pytest.raises(ConfigurationError, match="raw mesh copy"):
        prepare_landmark_aligned_inputs(
            source_directory,
            project_directory=project,
            landmarks_file=landmarks,
            template=template,
            subject_pattern="*.*",
        )


def test_desktop_rejects_non_vtk_sources_without_reviewed_gpa(tmp_path: Path) -> None:
    source_directory = tmp_path / "source"
    template, _ = _write_mixed_cohort(source_directory)
    project = tmp_path / "project"

    with pytest.raises(ConfigurationError, match="accepted only through reviewed"):
        create_project(
            ProjectSetupRequest(
                mesh_directory=source_directory,
                project_directory=project,
                units="unitless",
                engine=DesktopEngine.DEFORMETRICA_REFERENCE,
                template=template,
                subject_pattern="*.*",
            )
        )

    assert not project.exists()


@pytest.mark.parametrize(
    "engine",
    (DesktopEngine.DEFORMETRICA_REFERENCE, DesktopEngine.MODERN_CPU),
)
def test_desktop_project_routes_supported_sources_through_reviewed_vtk_conversion(
    tmp_path: Path,
    engine: DesktopEngine,
) -> None:
    if engine is DesktopEngine.MODERN_CPU and (
        importlib.util.find_spec("numpy") is None
        or importlib.util.find_spec("torch") is None
    ):
        pytest.skip("modern-engine dependencies are not installed")

    source_directory = tmp_path / "source"
    template, subjects = _write_project_cohort(source_directory)
    landmarks = _write_mixed_landmarks(
        tmp_path / "landmarks.csv",
        template,
        subjects,
    )
    preview = preview_landmark_alignment(
        source_directory,
        landmarks_file=landmarks,
        template=template,
        subject_pattern="*.*",
    )

    result = create_project(
        ProjectSetupRequest(
            mesh_directory=source_directory,
            project_directory=tmp_path / engine.value,
            units="unitless",
            engine=engine,
            template=template,
            subject_pattern="*.*",
            landmarks_file=landmarks,
            approved_procrustes_fingerprint=preview.fingerprint,
        )
    )

    config = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    inputs = validate_input_paths(config, result.config_path)
    assert result.preprocessing_report_path is not None
    assert result.preprocessing_report_path.is_file()
    assert inputs.input_directory.name == "aligned-vtk"
    assert config["input"]["subject_pattern"] == "*.vtk"
    assert inputs.template.name == "template.vtk"
    assert tuple(path.name for path in inputs.subjects) == (
        "subject-01.vtk",
        "subject-02.vtk",
    )
    if engine is DesktopEngine.MODERN_CPU:
        assert config["preprocessing"]["procrustes"]["enabled"] is False
