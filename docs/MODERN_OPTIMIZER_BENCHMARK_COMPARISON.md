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
current v0.1 contract accepts exactly one condition per study and requires:

- the complete template and subject inventory to match;
- the software and Modern Engine implementation to match;
- subject count, cycle cap, repeats, warm-ups, and deterministic protocol to
  match;
- every configuration field outside the explicit pairwise-evaluation plan to
  match; and
- the selected report inputs and measured optimizer protocol to match.

The output contains exactly three files: authoritative JSON, its SHA-256
sidecar, and deterministic HTML. It records per-study medians for target-cache
preparation, optimizer wall time, sampled process peak RSS, and sampled RSS
growth, plus candidate/baseline median ratios. Every paired repeat is checked
for identical termination, decisions, work counters, and line-search behavior;
final objective components are compared at `1e-12` absolute and relative
tolerance. Exact history and parameter-hash matches are reported separately so
floating-point accumulation changes are never hidden.

The dedicated verifier reopens both source studies and deterministically
recomputes all comparison fields and HTML. Moving or changing a source study
therefore invalidates the comparison rather than silently preserving stale
claims.

This is descriptive local engineering evidence. It does not choose a winner,
promote a tile size to a safe preset, measure end-to-end atlas time, establish
convergence or biological validity, or extrapolate to 300 subjects. Sampled RSS
can miss peaks shorter than the benchmark sampling interval.
