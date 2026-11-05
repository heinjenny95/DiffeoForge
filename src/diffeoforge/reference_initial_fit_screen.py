"""Local residual screen on native initializer endpoints, before joint fitting."""

VERSION = "local-surface-residual-v1"
RECEIPT = "initial-fit-screen.json"
REVIEW_PRIORITY = 0.4

# The pinned reference interpreter already supplies NumPy and VTK.
# Embed only this independent geometry code in its immutable run adapter.
NATIVE_SCREEN = """
def _df_initial_residuals(original, fitted, width):
    import numpy as np
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy

    if not np.isfinite(width) or width <= 0:
        raise ValueError("Initial fit screen needs a positive attachment kernel width")
    diagonal = np.linalg.norm(np.ptp(vtk_to_numpy(original.GetPoints().GetData()), axis=0))
    if not np.isfinite(diagonal) or diagonal <= 0:
        raise ValueError("Initial fit screen needs a nondegenerate original surface")
    # An inspection threshold, expressed at the selected fitting scale.
    # Reject isolated spikes by requiring a connected area of whole faces.
    limit = max(2 * width, 0.02 * float(diagonal))
    distance = vtk.vtkDistancePolyDataFilter()
    distance.SetInputData(0, original)
    distance.SetInputData(1, fitted)
    distance.SignedDistanceOff()
    distance.ComputeSecondDistanceOn()
    distance.ComputeCellCenterDistanceOff()
    distance.Update()
    patches = []
    for direction, surface in (("missing_surface", distance.GetOutput()),
                               ("extra_surface", distance.GetSecondDistanceOutput())):
        values = vtk_to_numpy(surface.GetPointData().GetArray("Distance"))
        vertices = vtk_to_numpy(surface.GetPoints().GetData()).astype(float)
        cells = surface.GetPolys()
        face_data = vtk_to_numpy(cells.GetConnectivityArray())
        offsets = vtk_to_numpy(cells.GetOffsetsArray())
        if (not np.all(np.diff(offsets) == 3)
                or len(values) != len(vertices) or not np.isfinite(values).all()):
            raise ValueError("Initial fit screen requires finite triangular surfaces")
        faces = face_data.reshape(-1, 3)
        triangles = vertices[faces]
        areas = 0.5 * np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                              triangles[:, 2] - triangles[:, 0]), axis=1)
        total = areas.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError("Initial fit screen requires positive surface area")
        selected = np.flatnonzero(np.all(values[faces] >= limit, axis=1) & (areas > 0))
        if not len(selected):
            continue
        used, compact = np.unique(faces[selected], return_inverse=True)
        compact = compact.reshape(-1, 3)
        parents = list(range(len(used)))
        def root(node):
            while parents[node] != node:
                parents[node] = parents[parents[node]]
                node = parents[node]
            return node

        for a, b, c in compact.tolist():
            parent = root(a)
            parents[root(b)] = parent
            parents[root(c)] = parent
        components, groups = np.unique([root(i) for i in range(len(used))],
                                       return_inverse=True)
        count = len(components)
        component_areas = np.bincount(groups[compact[:, 0]], weights=areas[selected],
                                      minlength=count)
        qualifying = np.flatnonzero(component_areas >= total * 0.00025)
        component_peaks = np.zeros(count)
        np.maximum.at(component_peaks, groups, values[used])
        ranked = sorted(qualifying, key=lambda group: (
            -component_peaks[group] * component_areas[group]**0.5, int(group)))
        for group in ranked[:3]:
            indices = used[groups == group]
            peak = indices[np.argmax(values[indices])]
            points = vertices[indices]
            patches.append(dict(direction=direction, peak_distance=float(values[peak]),
                                peak_point=vertices[peak].tolist(),
                                bounds=[points.min(0).tolist(), points.max(0).tolist()],
                                area_fraction=float(component_areas[group] / total)))
    priority = max((p["peak_distance"] / limit * p["area_fraction"]**0.5
                    for p in patches), default=0.)
    return dict(distance_threshold=limit, priority=priority, patches=patches)
"""
