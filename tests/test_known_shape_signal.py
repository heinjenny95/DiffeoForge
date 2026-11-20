from pathlib import Path

import numpy as np
import pytest

from diffeoforge.analysis import known_shape_signal as signal
from diffeoforge.mesh import read_vtk_polydata, sha256_file

TEMPLATE = Path(__file__).parents[1] / "examples" / "synthetic" / "meshes" / "template.vtk"


def test_recovers_local_dose_and_measures_outside_drift(tmp_path):
    target = tmp_path / "study"
    center, radius, direction = (0.9, 0.0, 0.0), 0.63, (1.0, 0.0, 0.0)
    doses = (0.0, 0.0, 0.06, 0.16)
    source_hash = sha256_file(TEMPLATE)
    signal.create_signal_study(
        TEMPLATE, target, center=center, radius=radius, direction=direction, doses=doses
    )
    assert sha256_file(TEMPLATE) == source_hash
    assert (target / (signal.TRUTH + ".sha256")).read_text().strip() == sha256_file(
        target / signal.TRUTH
    )

    mesh = read_vtk_polydata(target / "template.vtk")
    points, triangles = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    field = signal._field(points, center=center, radius=radius, direction=direction)
    known = tuple(
        np.asarray(read_vtk_polydata(p).vertices)
        for p in sorted((target / "specimens").glob("*.vtk"))
    )
    measured = signal.measure_signal(points, triangles, field, doses, known)
    assert [row["recovered_dose"] for row in measured] == pytest.approx(doses)
    assert [row["outside_support_rms"] for row in measured] == pytest.approx([0.0] * 4)

    attenuated = [points + 0.25 * dose * field for dose in doses]
    attenuated[0] += 0.02 * field
    attenuated[-1] += np.array([0.0, 0.0, 0.01]) * (field == 0.0)
    measured = signal.measure_signal(points, triangles, field, doses, attenuated)
    assert [row["recovered_dose"] for row in measured[:2]] == pytest.approx([0.02, -0.02])
    assert measured[-1]["retained_fraction"] == pytest.approx((0.25 * 0.16 - 0.01) / 0.16)
    assert measured[-1]["outside_support_rms"] == pytest.approx(0.01)


def test_invalid_known_signal_never_creates_a_study(tmp_path):
    with pytest.raises(ValueError, match="half the radius"):
        signal.create_signal_study(
            TEMPLATE,
            tmp_path / "invalid",
            center=(0.9, 0, 0),
            radius=0.63,
            direction=(1, 0, 0),
            doses=(0, 0, 0.08, 0.4),
        )
    assert not (tmp_path / "invalid").exists()
