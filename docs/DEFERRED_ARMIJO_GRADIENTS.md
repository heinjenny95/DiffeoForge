# Deferred gradients for Armijo candidates

Status: **implemented with unchanged optimizer decisions and local regression
evidence; full-atlas performance is not yet validated**

## Why this exists

The full atlas and momenta-only optimizers use an ascent Armijo line search.
Each candidate first has to satisfy

`objective_candidate >= objective_current + c * step * ||gradient||^2`.

The earlier implementation requested the complete candidate gradient before
checking this objective-only condition. Every rejected candidate therefore paid
for a backward pass whose result could never be used.

The optimizer now retains the candidate's finite PyTorch objective graph,
checks the Armijo condition, and requests its gradient only if the objective is
acceptable. Rejected candidates release their graph without backward. An
acceptable candidate uses that same graph, so its forward pass is not repeated.
The complete initial objective-and-gradient evaluation is also reused for the
first parameter block rather than evaluating the identical initial state twice.

## Numerical and lifecycle contract

- The objective, search direction, step sequence, Armijo threshold, accepted
  parameters, history fields, and termination semantics are unchanged.
- A candidate with an acceptable finite objective but a non-finite gradient is
  still rejected and backtracking continues, matching the previous behavior.
- Cancellation is checked before and after objective and gradient work.
- Only one candidate graph is retained at a time.
- The public objective is unchanged; this is optimizer scheduling, not a new
  approximation or scientific model.

Focused tests instrument `torch.autograd.grad`. A failed one-candidate atlas
line search now requests only the current-state gradient, and a rejected
candidate requests none. Existing optimizer fixtures continue to verify
accepted steps, objective histories, parameter hashes, cancellation, rollback,
and dense/blockwise parity.

## Local engineering observation

The first matched observation used two private 1,500-face pilot subjects, nine
control points, ten timepoints, Current attachment, float64, and four PyTorch
CPU threads on the Windows/AMD Ryzen 9 7950X workstation described in
[prepared fixed-target attachments](PREPARED_ATTACHMENT_TARGETS.md). Each
condition used one warm-up followed by five complete optimizer repeats. The
baseline was exact commit `da82d2655b02c0a28b3e0a40f5b135b02bef9f48` in a
detached temporary worktree; the candidate used the same input tensors and
settings from the working tree.

| One-cycle condition | Baseline median | Deferred-gradient median | Observed ratio | Decision evidence |
|---|---:|---:|---:|---|
| Configured starter step sizes | 4.182120 s | 3.013895 s | 1.388x | Same 9 line-search evaluations: momenta accepted after 7, template after 1, control points after 1 |
| Deliberate 12-candidate failure | 4.612592 s | 2.540192 s | 1.816x | Same `line_search_failed`, 12 evaluations, and unchanged initial state |

These in-process observations isolate a rejection-heavy optimizer behavior.
They are not fresh-process benchmark artifacts, a converged atlas, peak-memory
evidence, or an extrapolation to 68 or 300 subjects. Runs with no rejected
candidates should receive only the smaller initial-state reuse benefit; they do
not justify the ratios above.

## Next evidence gates

1. Add backward-call and candidate-state accounting to a versioned optimizer
   benchmark without changing the existing benchmark schema retroactively.
2. Compare complete accepted histories and result bundles on matched multi-cycle
   pilots.
3. Measure wall time and peak RSS across rejection rates, face counts, and
   subject counts.
4. Use those observations to improve step initialization or warm-start policy
   without hiding or weakening the Armijo acceptance rule.
