from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis.landmarks import (
    import_landmark_txt_folder,
    read_landmark_csv,
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
