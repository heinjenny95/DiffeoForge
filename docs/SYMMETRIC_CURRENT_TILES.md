# Symmetric blockwise Current and Varifold self terms

Status: **exact mathematical optimization with float64 parity evidence**

Current and Varifold surface distances each contain two self inner products and
one cross inner product:

```text
<source, source> + <target, target> - 2 <source, target>
```

For a self term, the Gaussian kernel and Current normal dot product are
symmetric. Varifold's squared orientation similarity is symmetric as well. The
old blockwise implementation nevertheless evaluated both tile `A × B` and its
mirror `B × A`. When query and source tile sizes are equal, DiffeoForge now
evaluates only the diagonal and upper triangle of the tile grid. Each
off-diagonal surface product is symmetric, so its one evaluated scalar is
doubled. This preserves the full ordered sum and its gradients while avoiding
both the mirrored Gaussian tile and a redundant transposed matrix product.

For `T` tiles, either self term now evaluates `T(T+1)/2` Gaussian matrices
instead of `T²`. The cross term remains complete. Fixed target self terms still
remain prepared once outside optimization. If query and source tile sizes
differ, the implementation deliberately retains the established full-grid path
rather than silently changing the declared tile geometry.

Tests cover standard and analytical-recompute autograd, explicit tile counts,
dense forward/gradient parity on a hand-checkable tetrahedron, and dense
forward/gradient parity on the public 320-face CC0 mesh. This changes
floating-point summation order, so parity is tolerance-bound rather than
bit-identical. It is not a convergence, biological-validity, or large-cohort
wall-time claim. Existing completed runs retain their original engine identity
and hashes.
