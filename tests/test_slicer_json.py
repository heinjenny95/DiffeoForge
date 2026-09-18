from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis import import_landmark_json_folder, read_landmark_json
from diffeoforge.analysis.landmarks import read_landmark_csv
from diffeoforge.cli import main
from diffeoforge.config import ConfigurationError


def _markup(offset: float = 0) -> dict:
    return {
        "type": "Fiducial",
        "coordinateSystem": "LPS",
        "coordinateUnits": "mm",
        "controlPoints": [
            {
                "id": str(index),
                "label": f"specimen-{offset}-{index}",
                "position": [offset + x, y, z],
                "positionStatus": "defined",
                "visibility": False,
                "selected": False,
            }
            for index, (x, y, z) in enumerate(
                ((-1000.1234567890123, 2.5, -3), (4, 5, 6), (7, 8, 9)), start=1
            )
        ],
    }


def _write(path: Path, markup: dict | None = None) -> Path:
    path.write_text(
        json.dumps({"markups": [_markup() if markup is None else markup]}),
        encoding="utf-8-sig",
    )
    return path


@pytest.mark.parametrize("system", ["RAS", "LPS"])
@pytest.mark.parametrize("units", ["mm", ["mm", "UCUM", "millimeter"]])
def test_json_reader_preserves_float64_order_and_invisible_points(tmp_path, system, units):
    markup = _markup()
    markup.update(coordinateSystem=system, coordinateUnits=units)
    markup["controlPoints"][1]["label"] = markup["controlPoints"][0]["label"]
    source = _write(tmp_path / "mouse.mrk.json", markup)
    original = source.read_bytes()
    result = read_landmark_json(source)
    assert result.source_path == source.resolve()
    assert result.coordinate_system == system
    assert result.coordinate_units == ("mm", "UCUM")
    assert result.source_labels == tuple(point["label"] for point in markup["controlPoints"])
    assert result.coordinates.dtype == np.float64
    assert not result.coordinates.flags.writeable
    assert np.array_equal(
        result.coordinates, [point["position"] for point in markup["controlPoints"]]
    )
    assert source.read_bytes() == original


def test_json_reader_uses_slicer_point_status_default_but_does_not_guess_units(tmp_path):
    markup = _markup()
    del markup["coordinateUnits"]
    for point in markup["controlPoints"]:
        del point["positionStatus"]
        del point["id"]
        del point["label"]
    result = read_landmark_json(_write(tmp_path / "mouse.json", markup))
    assert result.coordinate_units is None
    assert result.source_labels == ("LM1", "LM2", "LM3")


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"markups": []}, {"markups": [None]}, {"markups": [_markup(), _markup()]}],
)
def test_json_reader_rejects_ambiguous_or_non_slicer_payload(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="exactly one Slicer Fiducial"):
        read_landmark_json(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("type", "Curve", "unsupported markup type"),
        ("type", "ClosedCurve", "unsupported markup type"),
        ("type", "Plane", "unsupported markup type"),
        ("coordinateSystem", None, "explicitly declare"),
        ("coordinateSystem", 1, "explicitly declare"),
        ("coordinateSystem", "XYZ", "explicitly declare"),
        ("coordinateSystem", {}, "explicitly declare"),
        ("coordinateUnits", None, "coordinateUnits"),
        ("coordinateUnits", "", "coordinateUnits"),
        ("coordinateUnits", ["mm", "UCUM"], "coordinateUnits"),
        ("controlPoints", [], "at least three"),
        ("controlPoints", [None, None, None], "must be an object"),
    ],
)
def test_json_reader_rejects_invalid_markup(tmp_path, field, value, message):
    markup = _markup()
    markup[field] = value
    with pytest.raises(ConfigurationError, match=message):
        read_landmark_json(_write(tmp_path / "bad.json", markup))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("positionStatus", "undefined", "not a defined control point"),
        ("positionStatus", "preview", "not a defined control point"),
        ("positionStatus", None, "not a defined control point"),
        ("positionStatus", "missing", "not a defined control point"),
        ("position", None, "numeric 3D"),
        ("position", [1, 2], "numeric 3D"),
        ("position", [1, 2, 3, 4], "numeric 3D"),
        ("position", [True, 2, 3], "numeric 3D"),
        ("position", ["1", 2, 3], "numeric 3D"),
        ("position", [[1], 2, 3], "numeric 3D"),
        ("position", [float("nan"), 2, 3], "non-finite"),
        ("position", [float("inf"), 2, 3], "non-finite"),
        ("position", [10**400, 2, 3], "non-finite"),
        ("label", 12, "label and id must be strings"),
    ],
)
def test_json_reader_rejects_bad_points_without_dropping_them(tmp_path, field, value, message):
    markup = _markup()
    markup["controlPoints"][1][field] = value
    with pytest.raises(ConfigurationError, match=message):
        read_landmark_json(_write(tmp_path / "bad.json", markup))


@pytest.mark.parametrize("content", [b"{", b"\xff", b'{"markups": [], "markups": []}'])
def test_json_reader_wraps_invalid_json_and_duplicate_keys(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_bytes(content)
    with pytest.raises(ConfigurationError, match="Could not read landmark JSON"):
        read_landmark_json(path)


def test_json_folder_matches_compound_stems_and_round_trips_without_source_changes(tmp_path):
    first = _write(tmp_path / "FIRST.MRK.JSON")
    second = _write(tmp_path / "second.json", _markup(10))
    extra = tmp_path / "unselected.json"
    extra.write_text("not interpreted", encoding="utf-8")
    originals = {path: path.read_bytes() for path in (first, second, extra)}
    result = import_landmark_json_folder(
        tmp_path, ("first.ply", "Second.obj"), tmp_path / "project" / "landmarks.csv"
    )
    labels, values = read_landmark_csv(result.csv_path, result.mesh_files)
    assert result.mesh_files == ("first.ply", "Second.obj")
    assert result.json_files == (first.resolve(), second.resolve())
    assert result.ignored_json_files == (extra.resolve(),)
    assert result.units_label == "mm (UCUM)"
    assert labels == result.landmark_labels == ("LM1", "LM2", "LM3")
    assert np.array_equal(
        values, np.stack([read_landmark_json(p).coordinates for p in (first, second)])
    )
    assert all(path.read_bytes() == content for path, content in originals.items())
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        import_landmark_json_folder(tmp_path, result.mesh_files, result.csv_path)
    import_landmark_json_folder(tmp_path, result.mesh_files, result.csv_path, overwrite=True)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing", "Missing landmark JSON"),
        ("duplicate", "unique stems"),
        ("count", "same ordered defined-point count"),
        ("system", "same coordinate system"),
        ("units", "same coordinate units"),
        ("missing-units", "same coordinate units"),
        ("undefined", "not a defined control point"),
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_json_folder_fails_without_writing_or_replacing_output(tmp_path, change, message, existing):
    _write(tmp_path / "first.mrk.json")
    second = _markup()
    if change == "duplicate":
        _write(tmp_path / "first.json")
    elif change == "count":
        second["controlPoints"].append(second["controlPoints"][0])
    elif change == "system":
        second["coordinateSystem"] = "RAS"
    elif change == "units":
        second["coordinateUnits"] = "um"
    elif change == "missing-units":
        del second["coordinateUnits"]
    elif change == "undefined":
        second["controlPoints"][0]["positionStatus"] = "undefined"
    if change != "missing":
        _write(tmp_path / "second.mrk.json", second)
    output = tmp_path / "landmarks.csv"
    if existing:
        output.write_bytes(b"reviewed CSV")
    with pytest.raises(ConfigurationError, match=message):
        import_landmark_json_folder(tmp_path, ("first.ply", "second.ply"), output, overwrite=True)
    assert output.read_bytes() == b"reviewed CSV" if existing else not output.exists()


@pytest.mark.parametrize("meshes", [("first.ply",), ("first.ply", "FIRST.obj")])
def test_json_folder_rejects_invalid_cohort(tmp_path, meshes):
    with pytest.raises(ConfigurationError):
        import_landmark_json_folder(tmp_path, meshes, tmp_path / "landmarks.csv")


@pytest.mark.parametrize("target", ["json", "mesh"])
def test_json_import_never_overwrites_source_files_even_with_force(tmp_path, target):
    first = _write(tmp_path / "first.mrk.json")
    _write(tmp_path / "second.mrk.json")
    meshes = (tmp_path / "first.ply", tmp_path / "second.ply")
    for mesh in meshes:
        mesh.write_bytes(b"source mesh")
    output = first if target == "json" else meshes[0]
    original = output.read_bytes()
    with pytest.raises(ConfigurationError, match="must not replace a source"):
        import_landmark_json_folder(tmp_path, meshes, output, overwrite=True)
    assert output.read_bytes() == original


def test_json_folder_accepts_equivalent_coded_units(tmp_path):
    _write(tmp_path / "first.mrk.json")
    second = _markup()
    second["coordinateUnits"] = ["mm", "UCUM", "millimetre"]
    _write(tmp_path / "second.mrk.json", second)
    result = import_landmark_json_folder(
        tmp_path, ("first.ply", "second.ply"), tmp_path / "landmarks.csv"
    )
    assert result.coordinate_units == ("mm", "UCUM")


def test_json_cli_import_and_explicit_overwrite(tmp_path, capsys):
    for stem in ("first", "second"):
        (tmp_path / f"{stem}.ply").touch()
        _write(tmp_path / f"{stem}.mrk.json")
    output = tmp_path / "landmarks.csv"
    args = [
        "landmarks-import-json",
        str(tmp_path),
        str(tmp_path),
        "--mesh-pattern",
        "*.ply",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert "Matched meshes/JSON files: 2" in captured.out
    assert "Coordinate units: mm (UCUM)" in captured.out
    assert "no RAS/LPS conversion" in captured.out
    assert main(args) == 2
    assert "will not be overwritten" in capsys.readouterr().err
    assert main([*args, "--force"]) == 0
    assert read_landmark_csv(output, ("first.ply", "second.ply"))[1].shape == (2, 3, 3)


@pytest.mark.parametrize("route", ["file", "folder"])
def test_desktop_json_import_creates_and_selects_working_csv(tmp_path, monkeypatch, route):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["json-import-test"])
    cohort = (tmp_path / "first.ply", tmp_path / "second.ply")
    for mesh in cohort:
        _write(mesh.with_suffix(".mrk.json"))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (
            str(tmp_path / "first.mrk.json"),
            "3D Slicer Markups JSON (*.mrk.json *.json)",
        ),
    )
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(DiffeoForgeWindow, "_current_surface_cohort", lambda self: cohort)
    monkeypatch.setattr(DiffeoForgeWindow, "_start_input_preflight", lambda self: None)
    window = DiffeoForgeWindow()
    window.project_edit.setText(str(tmp_path / "project"))
    try:
        if route == "file":
            window._choose_landmarks()
        else:
            window._import_landmark_txt_folder()
        output = tmp_path / "project" / "landmarks.csv"
        assert window.landmarks_edit.text() == str(output.resolve())
        assert window.landmark_count_spin.value() == 3
        assert read_landmark_csv(output, ("first.ply", "second.ply"))[1].shape == (2, 3, 3)
        assert "Coordinate units: mm (UCUM)" in messages[0]
        assert "GPA preview remains required" in messages[0]
    finally:
        window.close()
        application.processEvents()


@pytest.mark.parametrize("case", ["mixed", "decline", "accept", "invalid"])
def test_desktop_json_import_safety(tmp_path, monkeypatch, case):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    application = QApplication.instance() or QApplication(["json-safety-test"])
    cohort = (tmp_path / "first.ply", tmp_path / "second.ply")
    for mesh in cohort:
        _write(mesh.with_suffix(".mrk.json"))
    output = tmp_path / "project" / "landmarks.csv"
    output.parent.mkdir()
    output.write_bytes(b"reviewed CSV")
    monkeypatch.setattr(DiffeoForgeWindow, "_current_surface_cohort", lambda self: cohort)
    monkeypatch.setattr(DiffeoForgeWindow, "_start_input_preflight", lambda self: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: (
            QMessageBox.StandardButton.No if case == "decline" else QMessageBox.StandardButton.Yes
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    window = DiffeoForgeWindow()
    window.project_edit.setText(str(output.parent))
    try:
        if case == "mixed":
            (tmp_path / "first.fcsv").touch()
            window._import_landmark_txt_folder()
            assert "multiple landmark file formats" in warnings[0]
        else:
            if case == "invalid":
                (tmp_path / "second.mrk.json").write_text("{}", encoding="utf-8")
            window._complete_landmark_json_import(tmp_path)
        if case == "accept":
            assert window.landmarks_edit.text() == str(output.resolve())
            read_landmark_csv(output, ("first.ply", "second.ply"))
        else:
            assert output.read_bytes() == b"reviewed CSV"
            assert window.landmarks_edit.text() == ""
            if case == "invalid":
                assert "exactly one Slicer Fiducial" in warnings[0]
    finally:
        window.close()
        application.processEvents()
