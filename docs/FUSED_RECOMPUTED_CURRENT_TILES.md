# Fused recomputed Current tiles

Status: **implemented in Modern engine implementation 0.5; formal real-input
qualification remains required before promotion to a production preset**

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

## Exploratory observation

One local engineering run used the frozen five-subject, approximately 10k-face
Weevil input, one optimizer cycle, four CPU threads, float64, Current
attachment, and 1024 × 1024 tiles. The fused prototype measured 57.585 seconds
of optimizer time and 0.553 GiB sampled peak RSS. A separate Engine 0.4
observation measured 68.850 seconds and 0.642 GiB. The final reported objective
was equal at displayed precision.

These are separate single-repeat engineering observations. They do not select
a safe preset, establish a stable speed ratio, prove convergence, extrapolate
to 300 subjects, or validate biological results. Only a separately frozen,
strictly verified Engine 0.4 versus 0.5 study may support a formal implementation
comparison.

## Remaining gates

1. Freeze and run matched multi-repeat Engine 0.4 and Engine 0.5 studies on the
   same real inputs and 1024 × 1024 tile protocol.
2. Verify scalar agreement, discrete optimizer work, termination, and sampled
   memory with the strict comparison workflow.
3. Run the complete automated test suite and repository lint checks.
4. Preserve Engine 0.4 artifacts and reject continuation/recovery across the
   implementation-version boundary unless an explicit migration is developed.
