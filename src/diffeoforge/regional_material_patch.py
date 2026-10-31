"""Geometric movable-material proposals; never anatomical correspondences."""

import heapq

import numpy as np


def select(vertices, faces, target_vertices, target_faces, regions, fixed_ids=(), *, infer=True):
    """Exclude every fixed-incident face, including in absent-feature fallbacks.

    An absent feature gets one connected free patch, grown by edge distance until
    it covers the marked target area. A coordinate brush around the nearest face
    can otherwise consume a nearby retained tooth and unrelated surface parts.
    """
    from diffeoforge.regional_fit import mask

    v, f = np.asarray(vertices, float), np.asarray(faces, int)
    tv, tf = np.asarray(target_vertices, float), np.asarray(target_faces, int)
    centres, target_centres = v[f].mean(1), tv[tf].mean(1)
    blocked = np.isin(f, fixed_ids).any(1)
    selected = np.zeros(len(f), bool)
    proposals = []
    adjacency = None
    triangles = v[f]
    areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0],
                                    triangles[:, 2]-triangles[:, 0]), axis=1)*.5
    for index, region in enumerate(regions):
        target_selected = mask(target_centres, [region])
        if not target_selected.any():
            raise ValueError('The marked original area contains no face centres; enlarge it')
        brush = mask(centres, [region])
        if not infer and (brush & blocked).any():
            raise ValueError('Shape-preservation guides overlap a Retain area. '
                             'Separate the areas or use local shape matching.')
        chosen = brush & ~blocked
        if not chosen.any():
            if not infer:
                raise ValueError('The marked source has no movable surface outside Retain areas. '
                                 'Review the areas or use local shape matching.')
            free = np.flatnonzero(~blocked & (areas > 0))
            if not len(free):
                raise ValueError('No movable source surface remains outside Retain areas. '
                                 'Review the problem and Retain areas.')
            target_triangles = tv[tf[target_selected]]
            target_area = float(np.linalg.norm(np.cross(
                target_triangles[:, 1]-target_triangles[:, 0],
                target_triangles[:, 2]-target_triangles[:, 0]), axis=1).sum()*.5)
            centre = target_centres[target_selected].mean(0)
            start = int(free[np.argmin(np.linalg.norm(centres[free]-centre, axis=1))])
            if adjacency is None:
                adjacency = [[] for _ in f]
                edges = {}
                for i in free:
                    a, b, c = f[i]
                    for x, y in ((a, b), (b, c), (c, a)):
                        key = (int(min(x, y)), int(max(x, y)))
                        for other in edges.get(key, ()):
                            adjacency[i].append(other)
                            adjacency[other].append(int(i))
                        edges.setdefault(key, []).append(int(i))
            queue, lengths, area = [(0., start)], {start: 0.}, 0.
            while queue and area < target_area:
                distance, i = heapq.heappop(queue)
                if chosen[i] or distance != lengths[i]:
                    continue
                chosen[i] = True
                area += float(areas[i])
                for other in adjacency[i]:
                    length = distance+float(np.linalg.norm(centres[other]-centres[i]))
                    if not chosen[other] and length < lengths.get(other, np.inf):
                        lengths[other] = length
                        heapq.heappush(queue, (length, other))
            if area+target_area*1e-12 < target_area:
                raise ValueError('The nearest free source patch is too small for this mark. '
                                 'Review the problem and Retain areas; '
                                 'no retained part was selected.')
            proposals.append(dict(region=index, source_faces=np.flatnonzero(chosen).tolist(),
                source_patch_area=area, target_patch_area=target_area,
                biological_correspondence_claim=False))
        selected |= chosen
    assert not blocked[selected].any()
    return selected, proposals
