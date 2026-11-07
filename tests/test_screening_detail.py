"""Public geometric fixtures; no private atlas execution or fit gate is mocked."""

import numpy as np
import pytest

from diffeoforge import mesh_filter_worker
from diffeoforge import screening_detail as detail
from diffeoforge.mesh import TriangleMesh
from diffeoforge.reference_fit_search import surface_fit


def plane(n=10):
    v = np.array([(x / n, y / n, 0) for x in range(n + 1) for y in range(n + 1)], float)
    f = []
    for x in range(n):
        for y in range(n):
            a = x * (n + 1) + y
            f.extend(((a, a + n + 1, a + 1), (a + 1, a + n + 1, a + n + 2)))
    return v, np.array(f, np.int32)


def octahedron(level=3):
    v = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], float)
    f = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
                  [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]], np.int32)
    for _ in range(level):
        vertices, midpoints, faces = list(v), {}, []

        def midpoint(a, b, v=v, midpoints=midpoints, vertices=vertices):
            key = tuple(sorted((int(a), int(b))))
            if key not in midpoints:
                p = (v[a] + v[b]) / 2
                midpoints[key] = len(vertices)
                vertices.append(p / np.linalg.norm(p))
            return midpoints[key]

        for a, b, c in f:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        v, f = np.array(vertices), np.array(faces, np.int32)
    return v, f


def test_small_attached_tip_is_detected_when_area_percentiles_miss_it():
    # The tip has far less than 1% of the area, and shares a vertex with the main face.
    v = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0], [0.0001, 0, 0],
                  [0, 0.0001, 0.1]], float)
    f = np.array([[0, 1, 2], [0, 3, 4]], np.int32)
    original, flattened = (v, f), (v[:3], f[:1])
    aggregate = surface_fit(TriangleMesh(*original), TriangleMesh(*flattened))
    assert aggregate["p99"] < 1e-5
    measured = detail.measure_detail(original, flattened)
    assert measured["maximum"] == pytest.approx(0.1, rel=1e-5)
    assert measured["original_components"] == measured["working_components"] == 1


def test_every_component_is_checked_even_when_close_to_another_surface():
    v, f = plane(1)
    original = (np.vstack((v, v + [0, 0, 1e-4])), np.vstack((f, f + len(v))))
    measured = detail.measure_detail(original, (v, f))
    assert measured["maximum"] < 0.01
    assert measured["original_components"] == 2
    assert measured["working_components"] == 1
    assert detail.component_count(np.vstack((f, f[:, ::-1]))) == 1


def test_rejected_approximation_escalates_from_originals_and_records_each_attempt(monkeypatch):
    original = plane()
    coarse_v, coarse_f = plane(1)
    calls = []

    def filtering(operation, **arrays):
        assert operation == "decimate"
        np.testing.assert_array_equal(arrays["vertices"], original[0])
        np.testing.assert_array_equal(arrays["faces"], original[1])
        calls.append(int(arrays["budget"]))
        return dict(vertices=coarse_v + [0, 0, 0.02 if len(calls) == 1 else 0], faces=coarse_f)

    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter",
                        lambda op, **kw: filtering(op, **kw) if op == "decimate"
                        else _NATIVE_FILTER(op, **kw))
    _, faces, receipt = detail.prepare_target(*original, attachment_width=1, target_faces=10)
    assert calls == [10, 20]
    assert len(faces) == 2 and receipt["status"] == "qualified"
    assert [a["accepted"] for a in receipt["attempts"]] == [False, True]
    assert receipt["maximum"] <= receipt["error_budget"] == 0.01


_NATIVE_FILTER = mesh_filter_worker.run_mesh_filter


@pytest.mark.parametrize("failure", ["native", "components", "detail"])
def test_unqualified_or_failed_decimation_falls_back_to_exact_originals(monkeypatch, failure):
    v, f = plane()
    working_v, working_f = plane(1)
    if failure == "components":
        v, f = np.vstack((v, v + [0, 0, 1e-4])), np.vstack((f, f + len(v)))
    if failure == "detail":
        working_v = working_v + [0, 0, 0.1]

    def filtering(operation, **kw):
        if operation != "decimate":
            return _NATIVE_FILTER(operation, **kw)
        if failure == "native":
            raise RuntimeError("public injected filter failure")
        return dict(vertices=working_v, faces=working_f)

    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter", filtering)
    av, af, receipt = detail.prepare_target(v, f, attachment_width=1, target_faces=10)
    assert receipt["status"] == "original" and receipt["maximum"] == 0
    np.testing.assert_array_equal(av, v)
    np.testing.assert_array_equal(af, f)
    assert all(a["accepted"] is False for a in receipt["attempts"])


@pytest.mark.parametrize("family", ["smooth", "thin", "concave", "disconnected", "plane"])
def test_real_native_decimator_checked_across_public_mesh_families(family):
    v, f = octahedron()
    if family == "thin":
        v[:, 2] *= 0.02
    elif family == "concave":
        v[:, 0] *= 0.2 + v[:, 2] ** 2
    elif family == "disconnected":
        v, f = np.vstack((v, v + [3, 0, 0])), np.vstack((f, f + len(v)))
    elif family == "plane":
        v, f = plane()
    original_v, original_f = v.copy(), f.copy()
    av, af, receipt = detail.prepare_target(v, f, attachment_width=0.2, target_faces=40)
    np.testing.assert_array_equal(v, original_v)
    np.testing.assert_array_equal(f, original_f)
    assert detail.supports_width(receipt, 0.2)
    if receipt["status"] == "original":
        np.testing.assert_array_equal(av, v)
        np.testing.assert_array_equal(af, f)
    else:
        independent = detail.measure_detail((v, f), (av, af))
        assert independent["maximum"] <= 0.002
        assert independent["original_components"] == independent["working_components"]
        assert len(af) < len(f)


@pytest.mark.parametrize("scale", [0.001, 1, 1000])
def test_detail_measurement_and_budget_scale_with_coordinate_units(scale):
    v, f = plane(1)
    m = detail.measure_detail((v * scale, f), ((v + [0, 0, 0.02]) * scale, f))
    assert m["maximum"] / scale == pytest.approx(0.02, rel=1e-5)


@pytest.mark.parametrize("width", [0, -1, float("nan"), float("inf"), True])
def test_invalid_budgets_never_prepare_geometry(width):
    with pytest.raises(ValueError, match="attachment width"):
        detail.prepare_target(*plane(1), attachment_width=width)


def test_unchanged_geometry_skips_native_filters_and_supports_finer_matching(monkeypatch):
    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter",
                        lambda *a, **k: pytest.fail("filter"))
    v, f = plane(1)
    av, af, receipt = detail.prepare_target(v, f, attachment_width=1)
    assert not receipt["attempts"] and receipt["status"] == "original"
    assert detail.supports_width(receipt, 0.00001)
    assert not detail.supports_width(None, 1)
    assert not detail.supports_width({**receipt, "maximum": float("nan")}, 1)
    assert not detail.supports_width({**receipt, "version": "unknown"}, 1)
    np.testing.assert_array_equal(av, v)
    np.testing.assert_array_equal(af, f)


def test_degenerate_source_is_rejected_instead_of_claiming_a_detail_pass():
    with pytest.raises(ValueError, match="nondegenerate"):
        detail.prepare_target([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1, 2]],
                              attachment_width=1)


def test_topology_limited_no_reduction_skips_repeated_filters_and_distance_work(monkeypatch):
    v, f = plane()
    calls = []

    def unreduced(operation, **arrays):
        assert operation == "decimate"
        calls.append(int(arrays["budget"]))
        return dict(vertices=v.copy(), faces=f.copy())

    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter", unreduced)
    av, af, receipt = detail.prepare_target(v, f, attachment_width=1, target_faces=10)
    assert calls == [10] and receipt["status"] == "original"
    assert receipt["attempts"][0]["reason"] == "no_reduction"
    np.testing.assert_array_equal(av, v)
    np.testing.assert_array_equal(af, f)
