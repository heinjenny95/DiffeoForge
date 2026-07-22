# Prepared fixed-target surface attachments

Status: **implemented with exact dense/blockwise value and source-gradient
parity; full-atlas scaling is not yet validated**

## Why this exists

For a deformed template surface `A` and a fixed observed target `B`, both the
Current and Varifold squared distances have the form

`distance(A, B) = <A, A> + <B, B> - 2 <A, B>`.

During atlas optimization, `A` changes but `B` does not. The earlier
implementation nevertheless reconstructed the target triangle centers and
normals and reevaluated `<B, B>` during every objective/gradient evaluation.
That target-only work is quadratic in the target face count and has zero effect
on any optimized-parameter gradient.

`prepare_surface_attachment_target` now computes the target centers, target
area normals, and `<B, B>` once. `optimize_atlas` and `optimize_momenta` reuse
those values for every later evaluation. The source self term `<A, A>`, cross
term `<A, B>`, shooting, template flow, regularity, and all gradients are still
evaluated normally.

## Exactness and safety contract

- Preparation uses the same float64 dense or exact blockwise arithmetic and
  the same tile/autograd plan as the ordinary distance call.
- Current and Varifold are both supported.
- Prepared targets must be fixed tensors that do not require gradients.
- A prepared target is bound to its exact vertex and triangle tensor objects,
  attachment type, kernel width, and tile plan.
- Reuse with different tensors, settings, dtype/device, or in-place-mutated
  target tensors fails explicitly rather than returning a stale result.
- The uncached public distance/objective path remains available as the numerical
  oracle.

Automated tests compare dense and blockwise `standard`/`recompute` values and
source gradients with zero tolerance on hand-checkable surfaces. Existing
objective and optimizer regression suites additionally exercise the cache in
the production optimizer path.

## Local engineering observation

The first implementation observation was recorded on 2026-07-22 on Windows 11
Enterprise (build 26200), an AMD Ryzen 9 7950X, 127.1 GiB RAM, Python 3.12.13,
PyTorch 2.13.0 CPU, float64, and four PyTorch threads. It used two private pilot
meshes with 1,500 triangular faces each and a Current kernel width of
`0.1566652729750018`. Private input paths and meshes are not committed.

Median of 11 in-process repeats after one warm-up:

| Operation | Uncached | Prepared target | Observed ratio |
|---|---:|---:|---:|
| One Current forward distance | 0.064813 s | 0.044108 s | 1.469x |
| Current forward + source gradient | 0.163506 s | 0.131865 s | 1.240x |

The median one-time preparation cost for the target was 0.021475 s.

A second observation used five 1,500-face subjects, nine control points, ten
timepoints, the configured Current attachment, and a momenta gradient. The
one-time preparation cost was 0.112000 s. Median objective-plus-gradient time
over five repeats changed from 1.007140 s to 0.812742 s (1.239x). Objective and
gradient tensors were exactly equal at zero tolerance.

These are local implementation observations, not fresh-process benchmark
artifacts, full optimizer runtimes, convergence evidence, or an extrapolation
to 68 or 300 subjects. The versioned Modern benchmark remains the uncached
numerical-operation baseline until a prospective cache-aware benchmark schema
records preparation and repeated-evaluation costs separately.

## Next evidence gates

1. Add a versioned fresh-process benchmark that measures preparation separately
   from repeated objective/gradient evaluations.
2. Run matched full-atlas pilots with cache enabled and disabled, preserving
   identical initialization and optimizer settings.
3. Measure dense and blockwise paths at approximately 1,500, 5,000, and 10,000
   faces and multiple subject counts.
4. Confirm result-bundle equality and compare end-to-end runtime, peak RSS, and
   optimizer histories before making a production performance claim.
