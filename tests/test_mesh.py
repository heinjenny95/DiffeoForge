from __future__ import annotations

import struct
from pathlib import Path

import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import inspect_vtk


def write_tetrahedron(path: Path) -> Path:
    path.write_text(
        """# vtk DataFile Version 3.0
tetrahedron
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0
1 0 0
0 1 0
0 0 1
POLYGONS 4 16
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""",
        encoding="ascii",
    )
    return path


def test_ascii_vtk_geometry_is_inspected(tmp_path: Path) -> None:
    metadata = inspect_vtk(write_tetrahedron(tmp_path / "mesh.vtk"))

    assert metadata.encoding == "ASCII"
    assert metadata.points == 4
    assert metadata.cells == 4
    assert metadata.triangular is True
    assert metadata.bounds == (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    assert metadata.bounding_box_diagonal == pytest.approx(3**0.5)


def test_non_triangular_polygons_are_rejected(tmp_path: Path) -> None:
    mesh = tmp_path / "quad.vtk"
    mesh.write_text(
        """# vtk DataFile Version 3.0
quad
ASCII
DATASET POLYDATA
POINTS 4 float
0 0 0  1 0 0  1 1 0  0 1 0
POLYGONS 1 5
4 0 1 2 3
""",
        encoding="ascii",
    )

    with pytest.raises(ConfigurationError, match="not exclusively triangular"):
        inspect_vtk(mesh)


def test_binary_vtk51_split_cell_arrays_are_inspected(tmp_path: Path) -> None:
    mesh = tmp_path / "vtk51.vtk"
    points = struct.pack(">12d", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)
    offsets = struct.pack(">5q", 0, 3, 6, 9, 12)
    connectivity = struct.pack(">12q", 0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3)
    mesh.write_bytes(
        b"# vtk DataFile Version 5.1\n"
        b"tetrahedron\n"
        b"BINARY\n"
        b"DATASET POLYDATA\n"
        b"POINTS 4 double\n"
        + points
        + b"\nPOLYGONS 5 12\n"
        + b"OFFSETS vtktypeint64\n"
        + offsets
        + b"\nCONNECTIVITY vtktypeint64\n"
        + connectivity
        + b"\n"
    )

    metadata = inspect_vtk(mesh)

    assert metadata.vtk_version == "5.1"
    assert metadata.encoding == "BINARY"
    assert metadata.points == 4
    assert metadata.cells == 4
    assert metadata.triangular is True
