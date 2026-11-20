"""Read classic binary triangle geometry for a pilot display proxy."""

import re

import numpy as np

_HEADER = re.compile(
    rb"\A# vtk DataFile Version [0-9]+\.[0-9]+[ \t]*\r?\n"
    rb"[^\r\n]{0,256}\r?\nBINARY[ \t]*\r?\nDATASET[ \t]+POLYDATA[ \t]*\r?\n",
    re.IGNORECASE,
)
_POINTS = re.compile(rb"POINTS[ \t]+([0-9]{1,20})[ \t]+(float|double)[ \t]*\r?\n",
                     re.IGNORECASE)
_POLYGONS = re.compile(
    rb"(?:\r?\n[ \t]*)+POLYGONS[ \t]+([0-9]{1,20})[ \t]+([0-9]{1,20})[ \t]*\r?\n",
    re.IGNORECASE,
)
_OTHER_SECTION = re.compile(
    rb"(?:\r?\n[ \t]*)+(?:VERTICES|LINES|TRIANGLE_STRIPS|METADATA|FIELD|POINT_DATA|CELL_DATA)\b",
    re.IGNORECASE,
)
_TRAILING_SPACE = re.compile(rb"[ \t\r\n]*")


def binary_triangles(raw: bytes) -> tuple[np.ndarray, np.ndarray] | None:
    """Return read-only arrays for exact classic POLYDATA, or defer to the general reader."""
    header = _HEADER.match(raw)
    points = _POINTS.match(raw, header.end()) if header else None
    if points is None:
        return None
    point_count = int(points[1])
    point_dtype = np.dtype(">f4" if points[2].lower() == b"float" else ">f8")
    point_end = points.end() + point_count * 3 * point_dtype.itemsize
    if not point_count or point_end > len(raw):
        raise ValueError("Incomplete binary VTK points")

    # Look for this declaration only after the exact point bytes. Binary coordinates
    # may coincidentally contain text resembling a VTK section header.
    polygons = _POLYGONS.match(raw, point_end)
    if polygons is None:
        if _OTHER_SECTION.match(raw, point_end):
            return None
        raise ValueError("Binary VTK POLYGONS header is not at the declared point boundary")
    face_count, cell_size = int(polygons[1]), int(polygons[2])
    if cell_size != 4 * face_count or raw.startswith(b"OFFSETS", polygons.end()):
        return None
    face_end = polygons.end() + cell_size * 4
    if not face_count or face_end > len(raw):
        raise ValueError("Incomplete binary VTK polygons")
    if _TRAILING_SPACE.fullmatch(raw, face_end) is None:
        if _OTHER_SECTION.match(raw, face_end):
            return None
        raise ValueError("Unexpected bytes after binary VTK polygons")

    vertices = np.frombuffer(raw, dtype=point_dtype, count=point_count * 3,
                             offset=points.end()).reshape(-1, 3)
    cells = np.frombuffer(raw, dtype=">i4", count=cell_size, offset=polygons.end()).reshape(-1, 4)
    triangles = cells[:, 1:]
    a, b, c = triangles.T
    if (not np.isfinite(vertices).all() or not (cells[:, 0] == 3).all()
            or triangles.min() < 0 or triangles.max() >= point_count
            or np.any((a == b) | (b == c) | (c == a))):
        raise ValueError("Invalid binary VTK display geometry")
    return vertices, triangles
