"""Geometric and byte-preservation checks for the optional CT pilot utility."""

import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
tifffile = pytest.importorskip("tifffile")
ndimage = pytest.importorskip("scipy.ndimage")
pytest.importorskip("skimage.registration")

spec = importlib.util.spec_from_file_location(
    "stitch_ct_pair", Path(__file__).parents[1] / "tools" / "stitch_ct_pair.py",
)
stitch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stitch)


def test_large_axial_offset_uses_partial_overlap_not_periodic_wrap():
    world = ndimage.gaussian_filter(
        np.random.default_rng(81).normal(size=(144, 88, 88)).astype(np.float32), 0.7,
    )
    reference = world[64:128, 8:72, 8:72]
    moving = world[16:80, 11:75, 6:70]
    actual = stitch.coarse_translation(reference, moving, 1)
    np.testing.assert_array_equal(actual, [-48, 3, -2])


def test_composition_preserves_single_source_edges_and_feathers_only_shared_pixels():
    a = np.full((8, 6, 7), 100, dtype=np.uint8)
    b = np.full((8, 6, 7), 200, dtype=np.uint8)
    matrix, offset = np.eye(3), np.array([4.0, -2.0, 1.0])
    low, high = stitch.union_bounds(a.shape, b.shape, matrix, offset)
    np.testing.assert_array_equal(low, [-4, 0, -1])
    np.testing.assert_array_equal(high, [8, 8, 7])
    shape = high - low
    result = stitch.compose_block(a, b, matrix, offset, low, shape, 0, 12, 1.5, 2)
    # Reference z=1; shared voxel weight is 0.25 fixed, 0.75 moving.
    assert result[5, 3, 4] == 175
    assert result[5, 0, 4] == 100  # fixed-only lateral strip
    assert result[5, 7, 4] == 200  # moving-only lateral strip
    assert result[0, 3, 4] == 200  # moving-only axial region
    assert result[11, 3, 4] == 100  # fixed-only axial region
    assert result[0, 0, 0] == 0  # empty union corner


def test_rigid_sampling_axis_order_matches_an_analytic_linear_ramp():
    z, y, x = np.indices((12, 12, 12))
    moving = np.uint8(10 * z + 3 * y + x)
    reference = np.zeros_like(moving)
    angle = 0.04
    matrix = np.array([
        [1, 0, 0], [0, np.cos(angle), -np.sin(angle)],
        [0, np.sin(angle), np.cos(angle)],
    ])
    offset = np.array([0.2, 0.3, 0.4])
    low = np.zeros(3, dtype=int)
    result = stitch.compose_block(
        reference, moving, matrix, offset, low, np.array(reference.shape), 0, 5, 9, 1,
    )
    point = np.array([3, 4, 5])
    coordinate = matrix @ point + offset
    expected = int(np.rint(10 * coordinate[0] + 3 * coordinate[1] + coordinate[2]))
    assert result[tuple(point)] == expected


def test_full_tiff_readback_matches_pixels_and_refuses_overwrite(tmp_path):
    a = np.full((8, 6, 7), 100, dtype=np.uint8)
    b = np.full((8, 6, 7), 200, dtype=np.uint8)
    output = tmp_path / "stitched.tif"
    report = stitch.write_stitch(
        a, b, np.eye(3), np.array([4.0, 0, 0]), output, 1.5, 2, workers=2,
    )
    decoded = tifffile.imread(output)
    assert decoded.shape == (12, 6, 7)
    np.testing.assert_array_equal(decoded[:, 2, 3], [200] * 4 + [200, 175, 125, 100] + [100] * 4)
    assert report["scientific_approval"] is False
    assert not output.with_name("stitched.partial.tif").exists()
    assert np.all(a == 100) and np.all(b == 200)
    with pytest.raises(FileExistsError):
        stitch.write_stitch(a, b, np.eye(3), np.array([4.0, 0, 0]), output, 1.5, 2)


def test_cancelled_write_never_publishes_a_final_volume(tmp_path):
    cancel = tmp_path / "CANCEL"
    cancel.touch()
    volume = np.ones((8, 6, 7), dtype=np.uint8)
    output = tmp_path / "cancelled.tif"
    with pytest.raises(InterruptedError):
        stitch.write_stitch(
            volume, volume, np.eye(3), np.array([4.0, 0, 0]), output, 1.5, 2, cancel,
        )
    assert not output.exists()


@pytest.mark.parametrize("matrix", [np.diag([1, 1, -1]), np.diag([1, 1, 1.01])])
def test_reflection_and_scale_are_rejected(matrix):
    with pytest.raises(ValueError, match="proper rigid"):
        stitch.validate_transform(matrix, np.zeros(3))


def test_mapping_is_read_only_and_rejects_non_uint8_input(tmp_path):
    source = np.arange(12 * 8 * 8, dtype=np.uint8).reshape(12, 8, 8)
    path = tmp_path / "input.tif"
    tifffile.imwrite(path, source, photometric="minisblack", metadata={"axes": "ZYX"})
    mapped = stitch.map_stack(path)
    np.testing.assert_array_equal(mapped, source)
    assert not mapped.flags.writeable
    other = tmp_path / "unsupported.tif"
    tifffile.imwrite(other, source.astype(np.uint16), photometric="minisblack")
    with pytest.raises(ValueError, match="uint8"):
        stitch.map_stack(other)
