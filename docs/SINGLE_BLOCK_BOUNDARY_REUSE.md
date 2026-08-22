# Single-block optimizer boundary reuse

Status: **exact evaluation-elision optimization**

The atlas optimizer evaluates an accepted Armijo candidate's objective and
gradient before committing it. In a multi-block atlas, the next decision needs
a gradient for a different parameter block, so a new autograd evaluation is
required. In a one-block atlas, such as the fixed-reference momenta-only
qualification, the accepted gradient is already exactly the gradient needed at
the next cycle boundary.

DiffeoForge now carries that detached accepted evaluation into the next cycle
when and only when `block_order` contains one block. It still performs the same
cancellation check before using it. No candidate, Armijo condition, accepted
step, objective, gradient norm, parameter value, history record, or convergence
test is added, removed, or changed.

For `C` accepted one-block cycles, the exact work arithmetic changes from:

```text
initial objective+gradient + C candidate objective+gradients
                              + (C - 1) repeated boundary objective+gradients
```

to:

```text
initial objective+gradient + C candidate objective+gradients
```

Thus a ten-cycle accepted momenta-only run avoids nine complete redundant
objective-plus-gradient evaluations. The regression suite compares a combined
multi-cycle run with independently restarted one-cycle evaluations and requires
bit-identical final momenta, objective values, gradient norms, accepted steps,
and line-search decisions. Multi-block evaluation counts and behavior remain
unchanged.

This is exact implementation evidence, not a convergence or wall-time claim.
Runtime savings depend on how many cycles accept a candidate and on the relative
cost of line-search candidates. Existing runs keep their original provenance;
the optimization applies only to processes started from the new source.
