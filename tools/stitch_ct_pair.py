"""Standalone, provisional stitching of two overlapping uint8 CT stacks.

This optional research utility does not alter DiffeoForge, infer scientific
approval, or process a cohort. See docs/CT_PAIR_STITCHING.md for its limits.
All transforms map reference voxel coordinates to moving voxel coordinates,
in Z,Y,X order. Rigid rotation assumes isotropic voxels.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import itertools
import json
import time
from pathlib import Path

import numpy as np
import tifffile
from scipy import ndimage


def check_cancel(cancel: Path | None) -> None:
    if cancel is not None and cancel.exists():
        raise InterruptedError("Cancellation requested; partial output is not a delivery")


def digest(path: Path, cancel: Path | None = None) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024**2):
            check_cancel(cancel)
            value.update(block)
    return value.hexdigest()


def map_stack(path: Path) -> np.ndarray:
    """Map contiguous or regularly interleaved uncompressed uint8 TIFF pages."""
    with tifffile.TiffFile(path) as image:
        shape = image.series[0].shape
        if len(shape) != 3 or image.series[0].dtype != np.uint8:
            raise ValueError("Expected a three-dimensional uint8 scalar TIFF stack")
        try:
            return tifffile.memmap(path, mode="r")
        except ValueError:
            pass
        pages = list(image.pages)
        if len(pages) != shape[0] or len(pages) < 2:
            raise ValueError("Unsupported TIFF page layout")
        for page in pages:
            if (
                page.shape != shape[1:]
                or page.dtype != np.uint8
                or not page.is_memmappable
                or not page.is_contiguous
                or sum(page.databytecounts) != shape[1] * shape[2]
            ):
                raise ValueError("Unsupported compressed, tiled or irregular TIFF layout")
        offsets = np.array([p.dataoffsets[0] for p in pages], dtype=np.int64)
        stride = int(offsets[1] - offsets[0])
        if stride < shape[1] * shape[2] or not np.all(np.diff(offsets) == stride):
            raise ValueError("TIFF pages do not have a constant safe byte stride")
        if int(offsets[-1]) + shape[1] * shape[2] > path.stat().st_size:
            raise ValueError("Truncated TIFF pixel data")
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    return np.ndarray(
        shape, dtype=np.uint8, buffer=raw, offset=int(offsets[0]),
        strides=(stride, shape[2], 1),
    )


def overview(data: np.ndarray, factor: int, cancel: Path | None = None) -> np.ndarray:
    if factor < 1 or min(data.shape) < factor:
        raise ValueError("Invalid overview reduction factor")
    z, y, x = (n // factor for n in data.shape)
    result = np.empty((z, y, x), dtype=np.float32)
    for k in range(z):
        check_cancel(cancel)
        block = data[k * factor:(k + 1) * factor, :y * factor, :x * factor]
        result[k] = block.reshape(factor, y, factor, x, factor).mean(
            axis=(0, 2, 4), dtype=np.float32,
        )
    return result


def coarse_translation(a: np.ndarray, b: np.ndarray, factor: int) -> np.ndarray:
    from skimage.registration import phase_cross_correlation

    if a.shape != b.shape:
        raise ValueError("This pilot utility requires equal input stack dimensions")
    ah = a - ndimage.gaussian_filter(a, 2)
    bh = b - ndimage.gaussian_filter(b, 2)
    shifts = []
    for norm in (None, "phase"):
        shift, _, _ = phase_cross_correlation(
            ah, bh, normalization=norm, disambiguate=True,
        )
        shifts.append(shift)
    if not np.allclose(shifts[0], shifts[1], atol=1):
        raise ValueError("Coarse correlation variants disagree; inspect the inputs")
    shift = np.rint(shifts[0] * factor).astype(int)
    lo = np.maximum(0, shift)
    hi = np.minimum(np.array(a.shape) * factor, np.array(b.shape) * factor + shift)
    if np.any(hi <= lo):
        raise ValueError("No overlapping volume")
    return shift


def fit_rigid(
    a: np.ndarray, b: np.ndarray, placement: np.ndarray, roi: list[int],
    factor: int, initial_xyz: list[float], cancel: Path | None = None,
) -> dict:
    import SimpleITK as sitk

    # Explicitly bounded and isolated from production fitting defaults.
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(6)
    lo = np.array(roi[::2], dtype=int)
    hi = np.array(roi[1::2], dtype=int)
    if factor < 1 or np.any(hi <= lo) or np.any((hi - lo) % factor):
        raise ValueError("ROI dimensions must be positive and divisible by factor")
    if np.any(lo < np.maximum(0, placement)) or np.any(
        hi > np.minimum(a.shape, np.array(b.shape) + placement)
    ):
        raise ValueError("Registration ROI must lie within the common volume")
    images = []
    arrays = []
    for data, origin in ((a, np.zeros(3, dtype=int)), (b, placement)):
        check_cancel(cancel)
        crop = data[tuple(
            slice(int(start - delta), int(stop - delta))
            for start, stop, delta in zip(lo, hi, origin, strict=True)
        )]
        z, y, x = np.array(crop.shape) // factor
        reduced = crop.reshape(z, factor, y, factor, x, factor).mean(
            axis=(1, 3, 5), dtype=np.float32,
        )
        hp = reduced - ndimage.gaussian_filter(reduced, 1)
        arrays.append(hp)
        image = sitk.GetImageFromArray(hp)
        image.SetSpacing((float(factor),) * 3)
        image.SetOrigin(tuple((lo[::-1] + (factor - 1) / 2).astype(float)))
        images.append(image)
    fixed, moving = images
    mask = sitk.GetImageFromArray(
        ndimage.binary_dilation(np.abs(arrays[0]) > 2, iterations=1).astype(np.uint8),
    )
    mask.CopyInformation(fixed)
    center = fixed.TransformContinuousIndexToPhysicalPoint(
        tuple((np.array(fixed.GetSize()) - 1) / 2),
    )
    transform = sitk.Euler3DTransform()
    transform.SetCenter(center)
    transform.SetTranslation(initial_xyz)
    reg = sitk.ImageRegistrationMethod()
    reg.SetNumberOfThreads(6)
    reg.SetMetricAsCorrelation()
    reg.SetMetricFixedMask(mask)
    reg.SetMetricSamplingStrategy(reg.REGULAR)
    reg.SetMetricSamplingPercentage(0.25, 42)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(
        learningRate=1, minStep=0.001, numberOfIterations=100,
        relaxationFactor=0.5, gradientMagnitudeTolerance=1e-6,
    )
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetShrinkFactorsPerLevel([2, 1])
    reg.SetSmoothingSigmasPerLevel([1, 0])
    reg.SetSmoothingSigmasAreSpecifiedInPhysicalUnits(False)
    reg.SetInitialTransform(transform, inPlace=True)
    started = time.monotonic()
    trace = []
    stopped = []

    def observe():
        trace.append({
            "level": reg.GetCurrentLevel(), "iteration": reg.GetOptimizerIteration(),
            "metric": reg.GetMetricValue(), "seconds": time.monotonic() - started,
        })
        reason = None
        if cancel is not None and cancel.exists():
            reason = "cancelled"
        elif time.monotonic() - started >= 300:
            reason = "300-second registration cap"
        if reason:
            stopped.append(reason)
            reg.StopRegistration()

    reg.AddCommand(sitk.sitkIterationEvent, observe)
    reg.Execute(fixed, moving)
    if stopped:
        raise InterruptedError(stopped[-1])
    matrix = np.array(transform.GetMatrix()).reshape(3, 3)
    c = np.array(transform.GetCenter())
    offset = c + transform.GetTranslation() - matrix @ c - placement[::-1]
    return {
        "matrix_zyx": matrix[::-1, ::-1].tolist(), "offset_zyx": offset[::-1].tolist(),
        "rotation_xyz_degrees": np.rad2deg(transform.GetParameters()[:3]).tolist(),
        "roi_zyx": roi, "factor": factor, "seed": 42, "sampling_fraction": 0.25,
        "stop": reg.GetOptimizerStopConditionDescription(), "trace": trace,
        "max_iterations_per_level": 100, "max_seconds": 300,
        "isotropic_voxels_assumed": True,
    }


def validate_transform(matrix: np.ndarray, offset: np.ndarray) -> None:
    if matrix.shape != (3, 3) or offset.shape != (3,) or not (
        np.isfinite(matrix).all() and np.isfinite(offset).all()
    ):
        raise ValueError("Invalid transform dimensions or non-finite values")
    if not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-7) or not np.isclose(
        np.linalg.det(matrix), 1, atol=1e-7,
    ):
        raise ValueError("Only a proper rigid transform is supported")


def union_bounds(a_shape, b_shape, matrix, offset):
    validate_transform(matrix, offset)
    corners = np.array(list(itertools.product(*[(0, n - 1) for n in b_shape])), float)
    moving_world = (corners - offset) @ matrix
    low = np.floor(np.minimum(0, moving_world.min(axis=0))).astype(int)
    high = np.ceil(np.maximum(np.array(a_shape) - 1, moving_world.max(axis=0))).astype(int) + 1
    return low, high


def compose_block(a, b, matrix, offset, low, shape, z0, z1, seam, blend, cancel=None):
    check_cancel(cancel)
    world = low + np.array([z0, 0, 0])
    result = ndimage.affine_transform(
        b, matrix, offset=matrix @ world + offset,
        output_shape=(z1 - z0, int(shape[1]), int(shape[2])), output=np.float32,
        order=1, prefilter=False, mode="constant", cval=0,
    )
    yy = (np.arange(shape[1], dtype=float) + low[1])[:, None]
    xx = (np.arange(shape[2], dtype=float) + low[2])[None, :]
    ay0, ax0 = max(0, -low[1]), max(0, -low[2])
    ay1 = min(shape[1], a.shape[1] - low[1])
    ax1 = min(shape[2], a.shape[2] - low[2])
    moving_is_lower = offset[0] > 0
    for i, z in enumerate(range(z0 + low[0], z1 + low[0])):
        if 0 <= z < a.shape[0]:
            valid = np.ones((int(shape[1]), int(shape[2])), dtype=bool)
            for axis in range(3):
                coord = matrix[axis, 0] * z + matrix[axis, 1] * yy + matrix[axis, 2] * xx
                coord += offset[axis]
                valid &= (coord >= 0) & (coord <= b.shape[axis] - 1)
            weight_a = float(np.clip((z - (seam - blend / 2)) / blend, 0, 1))
            if not moving_is_lower:
                weight_a = 1 - weight_a
            source = a[z, ay0 + low[1]:ay1 + low[1], ax0 + low[2]:ax1 + low[2]]
            roi = result[i, ay0:ay1, ax0:ax1]
            roi[:] = np.where(
                valid[ay0:ay1, ax0:ax1], weight_a * source + (1 - weight_a) * roi, source,
            )
    return np.uint8(np.clip(np.rint(result), 0, 255))


def write_stitch(a, b, matrix, offset, output, seam, blend, cancel=None, workers=4):
    if blend <= 0 or workers < 1 or workers > 8:
        raise ValueError("Blend width must be positive; workers must be between 1 and 8")
    low, high = union_bounds(a.shape, b.shape, matrix, offset)
    shape = high - low
    temporary = output.with_name(output.stem + ".partial.tif")
    if output.exists() or temporary.exists():
        raise FileExistsError("Refusing to overwrite an earlier output")
    expected = hashlib.sha256()
    pool = cf.ThreadPoolExecutor(max_workers=workers)
    jobs = iter((z, min(z + 8, int(shape[0]))) for z in range(0, int(shape[0]), 8))
    pending = []
    started = last = time.monotonic()

    def submit(job):
        return pool.submit(
            compose_block, a, b, matrix, offset, low, shape, *job, seam, blend, cancel,
        )

    for _ in range(workers):
        if job := next(jobs, None):
            pending.append((job, submit(job)))

    def frames():
        nonlocal last
        while pending:
            job, future = pending.pop(0)
            data = future.result()
            check_cancel(cancel)
            if nxt := next(jobs, None):
                pending.append((nxt, submit(nxt)))
            expected.update(data.tobytes())
            yield from data
            if time.monotonic() - last >= 10:
                print(json.dumps({
                    "written_slices": job[1], "total_slices": int(shape[0]),
                }), flush=True)
                last = time.monotonic()

    try:
        with tifffile.TiffWriter(temporary, bigtiff=True) as writer:
            writer.write(
                data=frames(), shape=tuple(map(int, shape)), dtype=np.uint8,
                photometric="minisblack", compression=None,
                metadata={"axes": "ZYX", "unit": "voxel", "provisional_stitch": True},
            )
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    check_cancel(cancel)
    decoded = tifffile.memmap(temporary, mode="r")
    actual = hashlib.sha256()
    for z in range(0, len(decoded), 8):
        check_cancel(cancel)
        actual.update(decoded[z:z + 8].tobytes())
    if decoded.shape != tuple(shape) or actual.digest() != expected.digest():
        raise RuntimeError("Decoded output does not match the composed voxel stream")
    del decoded
    temporary.rename(output)
    return {
        "output_origin_reference_zyx": low.tolist(), "output_shape_zyx": shape.tolist(),
        "decoded_voxel_sha256": expected.hexdigest(), "file_sha256": digest(output, cancel),
        "bytes": output.stat().st_size, "seconds": time.monotonic() - started,
        "interpolation": "one trilinear moving-step resampling, fixed grid unchanged",
        "seam_reference_z": seam, "blend_width_voxels": blend,
        "intensity_correction": "none; local linear crossfade only",
        "physical_voxel_size": None, "scientific_approval": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("estimate", "compose"))
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--moving", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--overview-factor", type=int, default=8)
    parser.add_argument("--rigid-roi-zyx", nargs=6, type=int)
    parser.add_argument("--rigid-factor", type=int, default=4)
    parser.add_argument("--initial-residual-xyz", nargs=3, type=float, default=[0, 0, 0])
    parser.add_argument("--transform", type=Path)
    parser.add_argument("--residual-correction-zyx", nargs=3, type=float, default=[0, 0, 0])
    parser.add_argument("--seam-z", type=float)
    parser.add_argument("--blend-width", type=float, default=64)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    a, b = map_stack(args.reference), map_stack(args.moving)
    identities = [
        {"sha256": digest(p, args.cancel_file), "shape_zyx": list(v.shape), "dtype": str(v.dtype)}
        for p, v in ((args.reference, a), (args.moving, b))
    ]
    if args.mode == "estimate":
        aa = overview(a, args.overview_factor, args.cancel_file)
        bb = overview(b, args.overview_factor, args.cancel_file)
        placement = coarse_translation(aa, bb, args.overview_factor)
        report = {"matrix_zyx": np.eye(3).tolist(), "offset_zyx": (-placement).tolist()}
        if args.rigid_roi_zyx:
            report = fit_rigid(
                a, b, placement, args.rigid_roi_zyx, args.rigid_factor,
                args.initial_residual_xyz, args.cancel_file,
            )
        report.update({"inputs": identities, "coarse_placement_zyx": placement.tolist()})
    else:
        if args.transform is None or args.seam_z is None:
            parser.error("compose requires --transform and an inspected --seam-z")
        report = json.loads(args.transform.read_text(encoding="utf-8"))
        if report["inputs"] != identities:
            raise ValueError("Transform is bound to different input bytes")
        matrix = np.array(report["matrix_zyx"], dtype=float)
        offset = np.array(report["offset_zyx"], dtype=float)
        offset -= matrix @ np.array(args.residual_correction_zyx)
        report["applied_residual_correction_zyx"] = args.residual_correction_zyx
        report["final_offset_zyx"] = offset.tolist()
        report["composition"] = write_stitch(
            a, b, matrix, offset, args.output, args.seam_z, args.blend_width, args.cancel_file,
        )
    destination = args.output if args.mode == "estimate" else args.output.with_suffix(".json")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({"report": str(destination)}), flush=True)


if __name__ == "__main__":
    main()
