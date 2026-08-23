# Fused recomputed Current tiles

Status: **implemented in Modern engine implementation 0.5 and formally compared
with Engine 0.4 on the frozen five-subject full-resolution Weevil protocol;
larger-cohort and multi-cycle qualification remains open**

## Purpose

The blockwise Current attachment evaluates

```text
sum_i n_i · sum_j K(c_i, d_j) m_j
```

for every bounded face-pair tile. Engine 0.4 combined a query-level PyTorch
checkpoint with a separately recomputed Gaussian-matrix backward. That kept
pair-sized tensors out of the retained forward graph, but a differentiated
tile could construct the same Gaussian matrix three times: the original
forward, checkpoint replay, and analytical Gaussian backward.

Engine 0.5 represents one complete Current tile as a single custom autograd
operation. Its forward returns only the scalar inner product. It retains the
two center and normal arrays, not the Gaussian matrix or a rank-3 difference
tensor. Its analytical backward reconstructs the Gaussian once and returns
gradients for both center and normal inputs. A differentiated tile therefore
uses two Gaussian evaluations rather than the previous three.

The symmetric self term still evaluates only one triangle of the tile matrix
and doubles off-diagonal contributions. Cross terms retain their explicit
query/source traversal order. Tile bounds, the Gaussian convention, kernel
width, float64 CPU arithmetic, and Current orientation sensitivity are
unchanged.

## Automated evidence

The implementation is covered by:

- dense versus blockwise Current values and gradients;
- standard versus recompute values and gradients;
- numerical first- and second-derivative checks of the fused operation;
- saved-tensor hooks proving that no pair-sized rank-2 or rank-3 tensor is
  retained by a fused tile;
- symmetric-tile accounting and explicit tile-bound tests;
- complete objective and optimizer regression tests; and
- versioned benchmark and comparison schemas that retain Engine 0.3 and 0.4
  compatibility while accepting Engine 0.5 evidence.

The fused gradient is mathematically the same as the unfused path. Floating
operation scheduling can change last-bit results; automated comparisons use
the predeclared float64 tolerances rather than requiring parameter hashes to be
identical across engine implementations.

## Real-input evidence

A prospective Engine 0.5 design and the already frozen Engine 0.4 baseline use
the same five approximately 10k-face Weevil subjects, input hashes, optimizer
configuration, one-cycle cap, two fresh-process repeats, zero warmups, four CPU
threads, float64, Current attachment, 1024 × 1024 tiles, and deterministic order
seed 20260823. The only declared comparison dimension is the engine
implementation.

Both studies and their comparison pass strict recomputation-based verification.
Engine 0.4 measured 68.971 seconds median optimizer time and 0.642 GiB median
sampled peak RSS. Engine 0.5 measured 53.704 seconds and 0.555 GiB: a candidate
to baseline time ratio of 0.778647 and peak-RSS ratio of 0.864452. The two Engine
0.5 repeats were internally identical in all decisions, result hashes, and
reported scalar values.

Across Engine 0.4 and 0.5, all discrete optimizer work and outcomes match. Final
attachment and objective differ by `5.684341886080802e-14` in each paired
repeat, final regularity is equal, and all scalar components pass the frozen
`1e-12` absolute and relative tolerances. Template and control-point hashes
match exactly. Momenta and history hashes do not, as expected from the changed
last-bit gradient scheduling.

This evidence describes one machine, one five-subject prefix, and one optimizer
cycle. It does not select a universally safe tile preset, prove convergence,
extrapolate to 300 subjects, compare with Deformetrica, or validate biological
results. Sampled RSS can miss short peaks.

## Remaining gates

1. Run the complete automated test suite and repository lint checks.
2. Qualify multiple optimizer cycles and a larger subject cohort without
   extrapolating from this limited study.
3. Preserve Engine 0.4 artifacts and reject continuation/recovery across the
   implementation-version boundary unless an explicit migration is developed.
