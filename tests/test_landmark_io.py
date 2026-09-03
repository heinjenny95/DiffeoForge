from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis.landmarks import (
    import_landmark_fcsv_folder,
    import_landmark_txt_folder,
    read_landmark_csv,
    read_landmark_fcsv,
    read_landmark_txt,
    write_landmark_csv,
)
from diffeoforge.config import ConfigurationError


def _write_tagged_txt(path: Path, points: tuple[tuple[float, float, float], ...]) -> Path:
    rows = "\n".join(" ".join(str(value) for value in point) for point in points)
    path.write_text(
        "[individuals]\n"
        "1\n"
        "[dimensions]\n"
        "3\n"
        "[landmarks]\n"
        f"{len(points)}\n"
        "[rawpoints]\n"
        "'#1\n"
        f"{rows}\n",
        encoding="utf-8-sig",
    )
    return path


def _write_fcsv(
    path: Path,
    points: tuple[tuple[float, float, float], ...],
    *,
    coordinate_system: str = "LPS",
    mixed_slicer_5_line_endings: bool = False,
    position_status: int = 2,
) -> Path:
    rows = []
    for index, point in enumerate(points, start=1):
        prefix = (
            f'{index},{point[0]},{point[1]},{point[2]},0,0,0,1,1,1,0,'
            f'"specimen,{index}",,'
        )
        ending = f",{position_status},0\n"
        rows.append(prefix + ("\r" if mixed_slicer_5_line_endings else "") + ending)
    path.write_text(
        "# Markups fiducial file version = 5.2\n"
        f"# CoordinateSystem = {coordinate_system}\n"
        "# columns = id,x,y,z,ow,ox,oy,oz,vis,sel,lock,label,desc,associatedNodeID\n"
        + "".join(rows),
        encoding="utf-8",
        newline="",
    )
    return path


def test_landmark_csv_writer_round_trips_ordered_float64_values(tmp_path: Path) -> None:
    meshes = ("template.vtk", "subject.vtk")
    labels = ("anterior", "dorsal", "posterior")
    values = np.arange(18, dtype=np.float64).reshape(2, 3, 3)

    path = write_landmark_csv(tmp_path / "landmarks.csv", meshes, labels, values)
    observed_labels, observed_values = read_landmark_csv(path, meshes)

    assert observed_labels == labels
    assert np.array_equal(observed_values, values)
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_landmark_csv(path, meshes, labels, values)


def test_landmark_csv_writer_rejects_incomplete_or_wrong_precision_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="float64"):
        write_landmark_csv(
            tmp_path / "bad.csv",
            ("template.vtk", "subject.vtk"),
            ("a", "b", "c"),
            np.zeros((2, 3, 3), dtype=np.float32),
        )


def test_tagged_landmark_txt_reader_preserves_order_units_and_float64(
    tmp_path: Path,
) -> None:
    source = _write_tagged_txt(
        tmp_path / "specimen.txt",
        ((1000.0, 2.5, -3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
    )

    values = read_landmark_txt(source)

    assert values.dtype == np.float64
    assert values.shape == (3, 3)
    assert values.tolist()[0] == [1000.0, 2.5, -3.0]


def test_slicer_fcsv_reader_preserves_lps_order_and_handles_slicer_5_extension(
    tmp_path: Path,
) -> None:
    source = _write_fcsv(
        tmp_path / "specimen.fcsv",
        ((1000.0, 2.5, -3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        mixed_slicer_5_line_endings=True,
    )

    result = read_landmark_fcsv(source)

    assert result.version == "5.2"
    assert result.coordinate_system == "LPS"
    assert result.source_labels == ("specimen,1", "specimen,2", "specimen,3")
    assert result.coordinates.dtype == np.float64
    assert result.coordinates.flags.writeable is False
    assert result.coordinates.tolist()[0] == [1000.0, 2.5, -3.0]


@pytest.mark.parametrize(("coordinate_header", "expected"), (("0", "RAS"), ("1", "LPS")))
def test_slicer_fcsv_reader_accepts_legacy_numeric_coordinate_system(
    tmp_path: Path,
    coordinate_header: str,
    expected: str,
) -> None:
    source = _write_fcsv(
        tmp_path / "legacy.fcsv",
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        coordinate_system=coordinate_header,
    )

    assert read_landmark_fcsv(source).coordinate_system == expected


def test_slicer_fcsv_reader_rejects_undefined_control_point(tmp_path: Path) -> None:
    source = _write_fcsv(
        tmp_path / "undefined.fcsv",
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        position_status=0,
    )

    with pytest.raises(ConfigurationError, match="not a defined control point"):
        read_landmark_fcsv(source)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        (("[dimensions]\n3", "[dimensions]\n2"), "must contain 3D"),
        (("[landmarks]\n3", "[landmarks]\n4"), "declares 4 landmarks"),
        (("7.0 8.0 9.0", "nan 8.0 9.0"), "non-finite"),
    ),
)
def test_tagged_landmark_txt_reader_rejects_invalid_contracts(
    tmp_path: Path,
    replacement: tuple[str, str],
    message: str,
) -> None:
    source = _write_tagged_txt(
        tmp_path / "bad.txt",
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
    )
    content = source.read_text(encoding="utf-8-sig").replace(*replacement)
    source.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        read_landmark_txt(source)


def test_landmark_txt_folder_import_matches_mesh_stems_and_writes_canonical_csv(
    tmp_path: Path,
) -> None:
    txt_directory = tmp_path / "txt"
    txt_directory.mkdir()
    first_points = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0))
    second_points = ((10.0, 20.0, 30.0), (40.0, 50.0, 60.0), (70.0, 80.0, 90.0))
    _write_tagged_txt(txt_directory / "FIRST.txt", first_points)
    _write_tagged_txt(txt_directory / "second.TXT", second_points)
    _write_tagged_txt(txt_directory / "unselected.txt", first_points)

    result = import_landmark_txt_folder(
        txt_directory,
        (tmp_path / "first.ply", tmp_path / "Second.ply"),
        tmp_path / "landmarks.csv",
    )
    labels, values = read_landmark_csv(result.csv_path, result.mesh_files)

    assert result.mesh_files == ("first.ply", "Second.ply")
    assert tuple(path.name for path in result.txt_files) == ("FIRST.txt", "second.TXT")
    assert tuple(path.name for path in result.ignored_txt_files) == ("unselected.txt",)
    assert result.landmark_labels == ("LM1", "LM2", "LM3")
    assert labels == result.landmark_labels
    assert values.tolist() == [list(map(list, first_points)), list(map(list, second_points))]
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        import_landmark_txt_folder(
            txt_directory,
            result.mesh_files,
            result.csv_path,
        )


def test_landmark_txt_folder_import_writes_nothing_when_a_mesh_is_missing(
    tmp_path: Path,
) -> None:
    txt_directory = tmp_path / "txt"
    txt_directory.mkdir()
    _write_tagged_txt(
        txt_directory / "first.txt",
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
    )
    output = tmp_path / "landmarks.csv"

    with pytest.raises(ConfigurationError, match="Missing landmark TXT"):
        import_landmark_txt_folder(
            txt_directory,
            ("first.ply", "second.ply"),
            output,
        )

    assert not output.exists()


def test_landmark_fcsv_folder_import_matches_stems_and_writes_canonical_csv(
    tmp_path: Path,
) -> None:
    fcsv_directory = tmp_path / "fcsv"
    fcsv_directory.mkdir()
    first_points = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0))
    second_points = ((10.0, 20.0, 30.0), (40.0, 50.0, 60.0), (70.0, 80.0, 90.0))
    _write_fcsv(fcsv_directory / "FIRST.fcsv", first_points)
    _write_fcsv(fcsv_directory / "second.FCSV", second_points)
    _write_fcsv(fcsv_directory / "unselected.fcsv", first_points)

    result = import_landmark_fcsv_folder(
        fcsv_directory,
        (tmp_path / "first.ply", tmp_path / "Second.ply"),
        tmp_path / "landmarks.csv",
    )
    labels, values = read_landmark_csv(result.csv_path, result.mesh_files)

    assert result.mesh_files == ("first.ply", "Second.ply")
    assert tuple(path.name for path in result.fcsv_files) == ("FIRST.fcsv", "second.FCSV")
    assert tuple(path.name for path in result.ignored_fcsv_files) == ("unselected.fcsv",)
    assert result.landmark_labels == ("LM1", "LM2", "LM3")
    assert result.coordinate_system == "LPS"
    assert labels == result.landmark_labels
    assert values.tolist() == [list(map(list, first_points)), list(map(list, second_points))]


def test_landmark_fcsv_folder_import_rejects_mixed_coordinate_systems_without_output(
    tmp_path: Path,
) -> None:
    fcsv_directory = tmp_path / "fcsv"
    fcsv_directory.mkdir()
    points = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0))
    _write_fcsv(fcsv_directory / "first.fcsv", points, coordinate_system="LPS")
    _write_fcsv(fcsv_directory / "second.fcsv", points, coordinate_system="RAS")
    output = tmp_path / "landmarks.csv"

    with pytest.raises(ConfigurationError, match="same coordinate system"):
        import_landmark_fcsv_folder(
            fcsv_directory,
            ("first.ply", "second.ply"),
            output,
        )

    assert not output.exists()
