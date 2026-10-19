"""Common, compact display topology mapped to unchanged reconstruction vertices."""

import numpy as np

from diffeoforge.desktop.display_proxy import build_display_proxy


def glyph_topology(mesh, budget):
    """Reduce the surface as a whole rather than displaying scattered source faces.

    A bounded proxy is snapped to source vertices once. The same vertex IDs and
    topology are then used for every corresponding reconstruction. This is lossy
    display geometry; it is never used for analysis or anatomical approval.
    """
    import vtk

    from diffeoforge.analysis.pca_media_rendering import faces, points

    proxy = build_display_proxy(points(mesh), faces(mesh), budget=budget)
    used = np.unique(proxy.triangles)
    locator = vtk.vtkStaticPointLocator()
    locator.SetDataSet(mesh)
    locator.BuildLocator()
    nearest = np.array([locator.FindClosestPoint(proxy.vertices[i]) for i in used])
    ids, inverse = np.unique(nearest, return_inverse=True)
    lookup = np.zeros(len(proxy.vertices), dtype=np.int64)
    lookup[used] = inverse
    topology = lookup[proxy.triangles]
    valid = (
        (topology[:, 0] != topology[:, 1])
        & (topology[:, 1] != topology[:, 2])
        & (topology[:, 2] != topology[:, 0])
    )
    topology = topology[valid]
    if not len(topology):
        raise ValueError("No usable mesh glyph fits the display budget")
    return ids, topology
