"""Vectorized connectivity with the original face/edge/child order and winding."""
import numpy as np


def children(faces, edges, vertex_count):
    # Unique sorted (lo, hi) edges have the same order as these integer keys.
    # The declared material budget is much smaller than this overflow bound.
    if vertex_count**2 > np.iinfo(np.int64).max:
        raise ValueError("Original-source edge indices exceed the integer range")
    keys = edges[:, 0] * vertex_count + edges[:, 1]
    ends = np.roll(faces, -1, axis=1)
    all_keys = np.minimum(faces, ends) * vertex_count + np.maximum(faces, ends)
    positions = np.searchsorted(keys, all_keys)
    found = positions < len(keys)
    found[found] &= keys[positions[found]] == all_keys[found]
    mids = np.where(found, positions + vertex_count, -1)
    counts = found.sum(axis=1)
    sizes = counts + 1
    offsets = np.cumsum(sizes) - sizes
    output = np.empty((int(sizes.sum()), 3), dtype=np.int64)
    parents = np.repeat(np.arange(len(faces), dtype=np.int64), sizes)
    untouched = counts == 0
    output[offsets[untouched]] = faces[untouched]
    for count in (1, 2, 3):
        chosen = counts == count
        if not chosen.any():
            continue
        f, m, good = faces[chosen], mids[chosen], found[chosen]
        if count != 3:
            starts = good if count == 1 else good & np.roll(good, -1, axis=1)
            rotations = starts.argmax(axis=1)
            order = (np.arange(3) + rotations[:, None]) % 3
            f = np.take_along_axis(f, order, axis=1)
            m = np.take_along_axis(m, order, axis=1)
        a, b, c = f.T
        ab, bc, ca = m.T
        if count == 1:
            parts = ((a, ab, c), (ab, b, c))
        elif count == 2:
            parts = ((b, bc, ab), (a, ab, c), (ab, bc, c))
        else:
            parts = ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))
        for slot, part in enumerate(parts):
            output[offsets[chosen] + slot] = np.column_stack(part)
    return output, parents
