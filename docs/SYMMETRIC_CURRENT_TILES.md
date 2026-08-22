# Symmetric blockwise Current self terms

Status: **exact mathematical optimization with float64 parity evidence**

The Current surface distance contains two self inner products and one cross
inner product:

```text
<source, source> + <target, target> - 2 <source, target>
```

For a self term, the Gaussian kernel and normal dot product are symmetric. The
old blockwise implementation nevertheless evaluated both tile `A × B` and its
mirror `B × A`. When query and source tile sizes are equal, DiffeoForge now
evaluates only the diagonal and upper triangle of the tile grid. Each
off-diagonal kernel matrix contributes both forward and transposed normal
products, preserving the full ordered sum and its gradients.

For `T` tiles, one self term now evaluates `T(T+1)/2` Gaussian matrices instead
of `T²`. The cross term remains complete. Fixed target self terms still remain
prepared once outside optimization. If query and source tile sizes differ, the
implementation deliberately retains the established full-grid path rather than
silently changing the declared tile geometry.

Tests cover standard and analytical-recompute autograd, explicit tile counts,
dense forward/gradient parity on a hand-checkable tetrahedron, and dense
forward/gradient parity on the public 320-face CC0 mesh. This changes
floating-point summation order, so parity is tolerance-bound rather than
bit-identical. It is not a convergence, biological-validity, or large-cohort
wall-time claim. Existing completed runs retain their original engine identity
and hashes.
