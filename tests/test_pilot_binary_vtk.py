import numpy as np
import pytest

from diffeoforge.desktop.pilot_binary_vtk import binary_triangles
from diffeoforge.mesh import read_vtk_polydata

_POINTS = ((-1.25, 0.0, 0.5), (1.0, 0.5, 0.0), (0.0, 1.875, -2.0))


def _binary(*, kind=b"float", points=_POINTS, cells=((3, 0, 1, 2),), newline=b"\n",
            extra=b"", title=b"Fixture"):
    point_data = np.asarray(points, dtype=">f4" if kind == b"float" else ">f8").tobytes()
    cell_data = np.asarray(cells, dtype=">i4").tobytes()
    return (newline.join((b"# vtk DataFile Version 3.0", title, b"BINARY", b"DATASET POLYDATA",
                          f"POINTS {len(points)} {kind.decode('ascii')}".encode(), b""))
            + point_data + newline + f"POLYGONS {len(cells)} {len(cell_data) // 4}".encode()
            + newline + cell_data + newline + extra)


@pytest.mark.parametrize(("kind", "newline"), [(b"float", b"\n"), (b"double", b"\r\n")])
def test_binary_preview_arrays_equal_exact_reader(tmp_path, kind, newline):
    raw = _binary(kind=kind, newline=newline)
    path = tmp_path / "triangle.vtk"
    path.write_bytes(raw)
    exact = read_vtk_polydata(path)
    points, faces = binary_triangles(raw)
    np.testing.assert_array_equal(points, exact.vertices)
    np.testing.assert_array_equal(faces, exact.triangles)
    assert not points.flags.writeable and not faces.flags.writeable
    assert path.read_bytes() == raw


@pytest.mark.parametrize("cells", [((4, 0, 1, 2),), ((3, 0, 0, 2),), ((3, 0, 1, 3),),
                                   ((3, -1, 1, 2),)])
def test_rejects_invalid_binary_triangle_records(cells):
    with pytest.raises(ValueError, match="Invalid binary VTK"):
        binary_triangles(_binary(cells=cells))


def test_rejects_nonfinite_binary_points_and_truncated_connectivity():
    with pytest.raises(ValueError, match="Invalid binary VTK"):
        binary_triangles(_binary(points=((float("inf"), 0, 0), *_POINTS[1:])))
    with pytest.raises(ValueError, match="Incomplete binary VTK polygons"):
        binary_triangles(_binary()[:-3])


def test_ignores_header_words_inside_title_and_binary_point_payload():
    raw = _binary(title=b"POINTS 300 float")
    points = b"\nPOLYGONS 1 4\n".ljust(36, b"\x00")
    header = raw.index(b"POINTS 3 float\n") + len(b"POINTS 3 float\n")
    data = raw[:header] + points + raw[header + len(points):]
    vertices, triangles = binary_triangles(data)
    np.testing.assert_array_equal(vertices, np.frombuffer(points, dtype=">f4").reshape(3, 3))
    np.testing.assert_array_equal(triangles, [(0, 1, 2)])
    with pytest.raises(ValueError, match="declared point boundary"):
        binary_triangles(data[:header + len(points)])


def test_defers_nonclassic_layouts_to_general_reader():
    assert binary_triangles(_binary(extra=b"POINT_DATA 3\n")) is None
    other_dataset = _binary().replace(b"DATASET POLYDATA", b"DATASET STRUCTURED_POINTS")
    assert binary_triangles(other_dataset) is None
    assert binary_triangles(_binary().replace(b"BINARY", b"ASCII")) is None
