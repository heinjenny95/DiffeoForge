# Strict optimizer-study comparison

Two compatible, completed optimizer benchmark studies can be compared without
weakening either frozen protocol:

```powershell
diffeoforge modern-optimizer-benchmark-study-compare `
  BASELINE_STUDY CANDIDATE_STUDY --output COMPARISON

diffeoforge modern-optimizer-benchmark-study-comparison-verify COMPARISON
```

The comparison first strictly verifies both study manifests, copied designs,
source configurations, event histories, and every raw optimizer report. The
current v0.2 contract accepts exactly one condition per study and records one
isolated comparison dimension: `pairwise_evaluation` or
`engine_implementation`. It requires:

- the complete template and subject inventory to match;
- the software outside the explicitly recorded Engine implementation to match;
- subject count, cycle cap, repeats, warm-ups, and deterministic protocol to
  match;
- for a pairwise comparison, the Engine implementation and every configuration
  field outside the pairwise-evaluation plan to match;
- for an Engine-implementation comparison, the complete optimizer configuration
  including the pairwise-evaluation plan to match;
- the two dimensions may never change together; and
- the selected report inputs and measured optimizer protocol to match.

Legacy v0.1 comparisons remain strictly verifiable and retain their original
same-engine, pairwise-only semantics. New comparison writers produce v0.2.

The output contains exactly three files: authoritative JSON, its SHA-256
sidecar, and deterministic HTML. It records per-study medians for target-cache
preparation, optimizer wall time, sampled process peak RSS, and sampled RSS
growth, plus candidate/baseline median ratios. Every paired repeat is checked
for identical termination, decisions, work counters, and line-search behavior;
final objective components are compared at `1e-12` absolute and relative
tolerance. Exact history and parameter-hash matches are reported separately so
floating-point accumulation changes are never hidden. This lets a prospective
Engine 0.4 study be compared with its frozen Engine 0.3 baseline without also
changing tile size, subject selection, cycle cap, or any scientific parameter.

The dedicated verifier reopens both source studies and deterministically
recomputes all comparison fields and HTML. Moving or changing a source study
therefore invalidates the comparison rather than silently preserving stale
claims.

This is descriptive local engineering evidence. It does not choose a winner,
promote a tile size to a safe preset, measure end-to-end atlas time, establish
convergence or biological validity, or extrapolate to 300 subjects. Sampled RSS
can miss peaks shorter than the benchmark sampling interval.
