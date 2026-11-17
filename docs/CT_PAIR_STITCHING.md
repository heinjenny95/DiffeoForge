# Standalone two-step CT stitching pilot

`tools/stitch_ct_pair.py` is an optional research utility for two overlapping
reconstructed CT steps. It is separate from the desktop application and its
surface-fitting workflow. It does not introduce a production stitching feature
or qualify an unattended dataset batch.

The current scope is equal-sized, scalar uint8 TIFF stacks from axial steps,
with the same voxel spacing, substantial overlap and only small relative
rotations. The reader supports uncompressed contiguous or regularly interleaved
pages; unsupported layouts fail explicitly. Originals are mapped read-only.
Physical voxel size is not invented when absent from the input.

## Environment

Use a separate Python environment. The pilot was exercised with Python 3.13,
NumPy 2.4.6, SciPy 1.18.0, tifffile 2026.11.16, scikit-image 0.26.0 and
SimpleITK 2.5.7. These are optional tool dependencies, not application
dependencies. No application version bump or installer is needed.

## Inspect, estimate and compose

1. Make verified working copies and keep the source bytes intact. Use area
   averages for the initial overview. The two correlation variants must agree
   on the coarse translation; agreement alone does not prove a correct match.
2. Estimate a six-parameter rigid correction in an explicitly inspected common
   ROI when needed. Rotation assumes isotropic voxels. Supply ROI coordinates
   in reference Z,Y,X order, as `z_start z_stop y_start y_stop x_start x_stop`.
   ROI dimensions must be divisible by the rigid reduction factor. A fixed
   sampling seed, 100 iterations per pyramid level and a 300-second stop request
   checked at iteration boundaries make the effort reproducible and bounded.
3. Check spatially separated details in original resolution. A residual
   correction is a measured translation of the resampled moving image in the
   reference grid; it updates the sampling offset by `offset - matrix @ delta`.
   Preserve poorly matching regions in the evidence rather than hiding them.
4. Select the transition plane and local blend width inside the reliable
   overlap. `compose` is a separate explicit action, bound to input SHA-256,
   shape and dtype. Its matrix maps reference to moving coordinates in Z,Y,X.

Generic commands, with paths and ROI resolved for the actual acquisition:

```powershell
python tools/stitch_ct_pair.py estimate `
  --reference reference.tif --moving moving.tif --output transform.json

# Add --rigid-roi-zyx Z0 Z1 Y0 Y1 X0 X1 only after inspecting the overlap.
# Optional --initial-residual-xyz TX TY TZ seeds that rigid refinement.

python tools/stitch_ct_pair.py compose `
  --reference reference.tif --moving moving.tif --transform transform.json `
  --output stitched.tif --seam-z INSPECTED_REFERENCE_Z --blend-width 64
```

The output grid covers both transformed volumes. Only the moving step receives
one trilinear interpolation. The fixed grid and single-source boundary pixels
retain their values. A local linear crossfade changes overlapping intensities;
there is no global brightness correction, scale change or elastic deformation.
The final values are rounded to uint8, so this pilot is not a qualification for
quantitative attenuation measurements.

## Verification, cancellation and limits

The writer uses a bounded queue of eight-slice blocks, writes a separate
`.partial.tif`, and verifies every decoded output voxel against the generated
voxel stream before publishing the final filename. It records both voxel-stream
and file SHA-256. Existing final or partial outputs are not overwritten.

Pass `--cancel-file PATH` to both commands and create that file to request a
stop. Checks run between overview blocks, hash blocks, registration iterations
and output blocks. A running FFT or ITK iteration must return first. Cancellation
leaves any partial file visibly incomplete and does not publish it as a final
volume. No background work or automatic restart is installed.

Focused tests cover a large axial shift with partial overlap, analytic rigid
sampling in Z,Y,X order, single-source boundary preservation, crossfade values,
TIFF readback, refusal to overwrite, cancellation and exclusion of scale or
reflection. Actual acquisitions still need visual transition review; numerical
completion is not scientific approval. Reconstruction artefacts, specimen
movement, anisotropic voxels and changes of voxel size require separate
assessment. Private scans, transforms, quality measurements and result files
stay outside this public repository.
