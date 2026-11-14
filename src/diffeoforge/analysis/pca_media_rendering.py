"""Deterministic offscreen surface rendering; display geometry never replaces inputs."""

from __future__ import annotations

import numpy as np
import vtk
from PIL import Image
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

VIEWS = (
    ("XY · +Z", (0, 0, 1), (0, 1, 0)),
    ("XY · −Z", (0, 0, -1), (0, 1, 0)),
    ("XZ · −Y", (0, -1, 0), (0, 0, 1)),
    ("XZ · +Y", (0, 1, 0), (0, 0, 1)),
    ("YZ · +X", (1, 0, 0), (0, 0, 1)),
    ("YZ · −X", (-1, 0, 0), (0, 0, 1)),
)


def read_mesh(path):
    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    mesh = vtk.vtkPolyData()
    mesh.DeepCopy(reader.GetOutput())
    vertices = points(mesh)
    if not len(vertices) or not mesh.GetNumberOfPolys() or not np.isfinite(vertices).all():
        raise ValueError("Mesh has no finite surface geometry")
    cells = mesh.GetPolys()
    if not np.all(np.diff(vtk_to_numpy(cells.GetOffsetsArray())) == 3):
        raise ValueError("Media requires a triangular surface")
    return mesh


def points(mesh):
    return np.asarray(vtk_to_numpy(mesh.GetPoints().GetData()), dtype=np.float64)


def faces(mesh):
    return vtk_to_numpy(mesh.GetPolys().GetConnectivityArray()).reshape(-1, 3)


def with_points(mesh, values):
    result = vtk.vtkPolyData()
    result.DeepCopy(mesh)
    data = vtk.vtkPoints()
    data.SetData(numpy_to_vtk(np.ascontiguousarray(values), deep=True))
    result.SetPoints(data)
    return result


def display_proxy(mesh, budget=20_000):
    if mesh.GetNumberOfPolys() <= budget:
        return mesh, np.arange(mesh.GetNumberOfPoints())
    decimator = vtk.vtkDecimatePro()
    decimator.SetInputData(mesh)
    decimator.SetTargetReduction(1 - budget / mesh.GetNumberOfPolys())
    decimator.PreserveTopologyOn()
    decimator.SplittingOff()
    decimator.BoundaryVertexDeletionOff()
    decimator.Update()
    proxy = vtk.vtkPolyData()
    proxy.DeepCopy(decimator.GetOutput())
    # DecimatePro preserves original vertices; bind IDs without nearest-point guesses.
    lookup = {tuple(row): i for i, row in enumerate(points(mesh))}
    ids = np.array([lookup[tuple(row)] for row in points(proxy)], dtype=np.int64)
    if not np.array_equal(points(mesh)[ids], points(proxy)):
        raise ValueError("Display proxy vertices differ from source")
    return proxy, ids


def merge_bounds(bounds):
    a = np.asarray(bounds)
    return np.column_stack((a[:, ::2].min(axis=0), a[:, 1::2].max(axis=0))).ravel()


def point_normals(mesh):
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(mesh)
    normals.SplittingOff()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.Update()
    return vtk_to_numpy(normals.GetOutput().GetPointData().GetNormals()).copy()


class SurfaceRenderer:
    def __init__(self, size=(420, 360)):
        self.size = size
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(1, 1, 1)
        self.renderer.SetBackgroundAlpha(0)
        self.window = vtk.vtkRenderWindow()
        self.window.SetOffScreenRendering(1)
        self.window.SetSize(*size)
        self.window.SetMultiSamples(4)
        self.window.SetAlphaBitPlanes(1)
        self.window.AddRenderer(self.renderer)
        self.mapper = vtk.vtkPolyDataMapper()
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)
        self.actor.GetProperty().SetInterpolationToPhong()
        self.actor.GetProperty().SetColor(0.20, 0.47, 0.57)
        self.actor.GetProperty().SetAmbient(0.3)
        self.renderer.AddActor(self.actor)
        self.capture = vtk.vtkWindowToImageFilter()
        self.capture.SetInput(self.window)
        self.capture.SetInputBufferTypeToRGBA()
        self.capture.ReadFrontBufferOff()

    def render(self, mesh, bounds, view=VIEWS[0], scalars=None, limits=None, signed=False):
        import matplotlib as mpl

        self.mapper.SetInputData(mesh)
        if scalars is None:
            self.mapper.ScalarVisibilityOff()
        else:
            data = numpy_to_vtk(np.asarray(scalars, dtype=float), deep=True)
            data.SetName("displacement")
            mesh.GetPointData().SetScalars(data)
            lookup = vtk.vtkLookupTable()
            lookup.SetNumberOfTableValues(256)
            lookup.SetRange(*limits)
            lookup.Build()
            cmap = mpl.colormaps["coolwarm" if signed else "viridis"]
            for i in range(256):
                lookup.SetTableValue(i, *cmap(i / 255))
            self.mapper.ScalarVisibilityOn()
            self.mapper.SetLookupTable(lookup)
            self.mapper.SetScalarRange(*limits)
        lo, hi = np.asarray(bounds)[::2], np.asarray(bounds)[1::2]
        center = (lo + hi) / 2
        diagonal = max(float(np.linalg.norm(hi - lo)), 1e-12)
        direction, up = np.asarray(view[1], float), np.asarray(view[2], float)
        direction /= np.linalg.norm(direction)
        right = np.cross(up, direction)
        right /= np.linalg.norm(right)
        up = np.cross(direction, right)
        corners = (
            np.array(
                [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            )
            - center
        )
        scale = (
            max(
                np.abs(corners @ up).max(),
                np.abs(corners @ right).max() / (self.size[0] / self.size[1]),
            )
            * 1.08
        )
        camera = self.renderer.GetActiveCamera()
        camera.ParallelProjectionOn()
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(center + direction * diagonal * 3))
        camera.SetViewUp(*up)
        camera.SetParallelScale(max(float(scale), 1e-12))
        self.renderer.ResetCameraClippingRange()
        self.window.Render()
        self.capture.Modified()
        self.capture.Update()
        image = self.capture.GetOutput()
        w, h, _ = image.GetDimensions()
        pixels = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(h, w, 4)
        return Image.fromarray(np.flipud(pixels).copy())

    def close(self):
        self.window.Finalize()
