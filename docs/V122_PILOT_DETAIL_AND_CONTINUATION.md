# v122: screening detail and stop-aware continuation

## Scope

New fit-search targets are checked before optimization. Initial decimation still
requests 20,000 faces. A failed check tries 40,000 then 80,000 faces, always from
the original rather than a previously simplified mesh. When no checked reduction
is available, retain the original geometry. A native filter/measurement failure
also falls back to originals; invalid source geometry is not certified.

The check probes every vertex and triangle centroid, in both surface directions,
using the existing isolated MeshLab point-to-triangle worker. The maximum probed
distance must be at most 1% of the smallest planned screening attachment width;
the number of vertex-connected face components must be unchanged. The declared
1% is an engineering approximation budget, **not** a new fit threshold or a
universal anatomical guarantee. Discrete probes do not certify continuous
Hausdorff error, correspondence, orientation or all features between probes.

The immutable study manifest binds the working bytes to their original input
hashes and records each attempt, distance/count measurements, budget, outcome
and limitations. Full-target confirmation remains mandatory. A later trial with
finer matching uses originals when the retained approximation exceeds its new
budget. Compatible checked targets can be inherited; new independent searches
recheck an old unqualified or too-coarse working source. Existing saved studies
remain readable without inventing detail receipts or rewriting evidence.

Explicit iteration-capped adaptive centers retain unchanged-model warm
continuation at the exact seed tolerance. Explicit tolerance-stopped centers skip
that redundant trial; the existing parameter probes remain available at the same
tolerance. Unknown/error stops or inconsistent stop/convergence flags cannot
seed automatic search. Older contexts without a stop field remain readable and
never acquire implicit stricter tolerances in newly prepared configurations.
Manual selected continuation already retains tolerance and remains available.

## Unchanged scientific boundaries

- Per-specimen original-surface fit metrics, ranking and non-regression rules.
- Final optimizer tolerance, validity, integration and human anatomy gates.
- Original targets, existing results, final selections and review history.
- Native likelihood, gradient, line search, stopping equations and arithmetic.
- Independently staged institutional-server code, runtime, parameters and jobs.

Preparation may take longer or retain more faces when a coarse target loses
detail. Skipping a redundant continuation reduces one trial after a confirmed
tolerance stop; no general speedup or universal fit improvement is claimed.
No private scientific fit is started by this change. Broader anatomical and native
fit noninferiority qualification remains open in the
[pilot robustness plan](PILOT_ROBUSTNESS_PLAN.md).

## Verification

Focused regressions exercise a tiny attached tip missed by area percentiles,
lost close components, resolution escalation, native-filter failure, scale
changes, invalid geometry, and actual native decimation of smooth, thin, concave,
disconnected and planar public surfaces. Continuation tests cover caps, tolerance
stops, unknown/error stops, unchanged tolerances, immutable source evidence,
warm initialization, bounded budgets and legacy contexts. Pilot/search/full-target
and desktop regressions retain the existing scientific gates. All 267 currently
collected affected cases have passing reports: the broad run passed 263, then
focused checks passed 25 cases plus one retention case, with overlapping scope.
Two historical test assumptions were corrected to the existing preserved-pilot
initializer and modification-time listing contracts, without changing those
runtime paths. Ruff and diff checks passed. Windows delivery evidence is recorded
separately after verification.
