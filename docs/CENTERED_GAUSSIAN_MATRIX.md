# Centered Gaussian matrix evaluation

Status: **implemented with value, gradient, translation, and optimizer evidence;
representative scaling remains open**

## Purpose

Gaussian kernels are evaluated repeatedly by deformation, template flow, and
surface attachment. A direct implementation constructs a rank-3 tensor of all
pairwise coordinate differences before reducing it to a rank-2 squared-distance
matrix. For `m` query points and `n` source points, that temporary contains
`3mn` float64 values.

DiffeoForge now evaluates ordinary Gaussian matrices using

```text
||x - y||² = ||x - o||² + ||y - o||² - 2 (x - o) (y - o)ᵀ
```

where `o` is one shared, detached origin. This produces rank-2 matrices and
does not change the exact all-pairs model, Gaussian convention, kernel width,
or differentiable variables. The direct rank-3 path remains only where the
analytical Gaussian x-gradient explicitly requires vector differences.

## Numerical safeguards

The common origin is the midpoint of the detached query and source centroids.
Centering avoids the severe cancellation that an uncentered norm/matrix-product
identity can suffer when meshes carry a large global translation. Detaching the
origin makes it a constant coordinate shift in autograd; the mathematical
derivatives with respect to `x` and `y` remain those of the original distances.

Small negative squared distances caused by floating-point roundoff are clamped
to zero before exponentiation. This is not distance truncation or a compact
kernel approximation.

Automated evidence includes:

- direct rank-3 versus centered rank-2 Gaussian values on random float64 data;
- gradients with respect to both query and source coordinates;
- stability after a joint translation on the order of `10⁹` coordinate units;
- frozen Deformetrica primitive and complete-objective fixtures;
- dense/blockwise, standard/recompute, Current/Varifold, and optimizer tests;
- instrumentation proving ordinary `gaussian_kernel` does not call the
  rank-3 helper; and
- exact logical Gaussian-operation accounting after the implementation change.

## Exploratory implementation observation

The versioned optimizer benchmark was run in fresh processes on the same local
five-subject, approximately 1,500-face dense Current pilot, for one optimization
cycle and four CPU threads. The prior two-repeat report had a 6.477 s median
optimizer time and 1,993 MiB median sampled peak RSS. A three-repeat centered
matrix report had a 2.318 s median optimizer time and 985 MiB median sampled
peak RSS, an observed 2.79x time ratio. Target preparation decreased from a
0.142 s to 0.039 s median. The final objective differed by approximately
`1.5e-14`; every centered-matrix repeat had exact matching histories, parameters,
work counters, and hashes internally.

This comparison is exploratory implementation evidence. The reports used
different repeat counts, sampled rather than authoritative peak memory, a
five-subject prefix, one cycle, and one machine. It is not a convergence result,
Deformetrica comparison, 300-subject forecast, or production performance claim.

A second real-input observation used all 68 available approximately 1,500-face
subjects, one cycle, four CPU threads, and two fresh processes. Optimizer times
were 61.513 s and 61.715 s (61.614 s median); target preparation had a 0.534 s
median. Median sampled peak RSS was 10.103 GiB and median sampled RSS growth was
9.832 GiB. Both repeats produced exact matching discrete decisions and complete
result hashes as well as the declared numerical match. Each run performed 19
objective evaluations, 6 gradient evaluations, and 16 line-search evaluations;
13 rejected candidates avoided backward. This demonstrates deterministic
one-cycle execution of the complete available pilot cohort, not convergence or
safe extrapolation to 300 subjects.

## Workload-report compatibility

Workload v0.2 and existing benchmark schemas retain fields named
`float64_xyz_difference_tensor_bytes`. Changing those versioned names would
invalidate already published reports. Their values now have an explicitly
conservative meaning: the dense-equivalent rank-3 payload for the reported
logical pair or execution tile. They do not claim that ordinary centered
matrix evaluation allocates such a tensor. Actual peak RSS remains a measured
quantity, not a workload-plan output.

## Remaining gates

1. Run the frozen prospective multi-size and tile study on representative
   meshes rather than selecting a favorable observation after measurement.
2. Measure complete multi-cycle pilots and convergence, not only one cycle.
3. Characterize standard versus recompute saved tensors and process RSS after
   the matrix change.
4. Compare atlas and PCA stability across mesh resolutions and subject counts.
5. Keep the dense direct formula in independent tests as the numerical oracle.
