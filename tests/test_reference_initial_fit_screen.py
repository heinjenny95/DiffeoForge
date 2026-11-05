"""A small missed projection must flag either surface direction."""

import numpy as np
import pytest

from diffeoforge.reference_initial_fit_screen import NATIVE_SCREEN

vtk = pytest.importorskip("vtk")


def _sphere(center, radius):
    sphere = vtk.vtkSphereSource()
    sphere.SetCenter(*center)
    sphere.SetRadius(radius)
    sphere.SetThetaResolution(24)
    sphere.SetPhiResolution(24)
    sphere.Update()
    return sphere.GetOutput()


def test_bidirectional_screen_flags_small_patch_but_accepts_identical_meshes():
    native = {}
    exec(NATIVE_SCREEN, native)
    screen = native["_df_initial_residuals"]
    body = _sphere((0, 0, 0), 1)
    patch = _sphere((1.18, 0, 0), .08)
    combination = vtk.vtkAppendPolyData()
    combination.AddInputData(body)
    combination.AddInputData(patch)
    combination.Update()
    extended = combination.GetOutput()
    assert screen(body, body, .04)["patches"] == []
    for original, fit, direction in (
        (extended, body, "missing_surface"), (body, extended, "extra_surface")
    ):
        result = screen(original, fit, .04)
        assert result["distance_threshold"] == pytest.approx(.08)
        finding, = result["patches"]
        assert finding["direction"] == direction
        assert .00025 < finding["area_fraction"] < .02
        assert np.isfinite(finding["peak_point"]).all()
        assert finding["peak_point"][0] > 1.2
