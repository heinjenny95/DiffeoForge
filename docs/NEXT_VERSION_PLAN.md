# Next DiffeoForge development version

Scope agreed on 2026-09-14: implement the current usability backlog and plan the
larger roadmap. This is a development plan, not a public release or scientific
qualification claim. The established development branch remains authoritative.

## Delivery order and acceptance gates

1. **Validation Lab reliability:** responsive opening, frozen-study creation and
   preflight; safe cancellation and explicit launch confirmation. Count the
   entire frozen training-plus-holdout design, separately show backend completion
   and verified evidence, retain original-start wall time across restarts, and
   never call an iteration fraction a measured work fraction or a reliable ETA.
   Verify cancellation races, failed evidence, retries and legacy ledgers.
2. **Large-mesh viewing:** reduced, cached display geometry in every mesh viewer,
   including settled frames; original scientific geometry and exact picking stay
   protected. Explicit original-detail inspection remains available. QC must not
   claim inspection of hidden details. Verify all rendering routes, bounded
   memory/jobs, stale results, source integrity and responsiveness on large meshes.
3. **AFK pilot:** explicit opt-in and a bounded pilot-only scope; automatically
   select eligible stage recommendations with an auditable provisional policy.
   Stop on missing eligibility/hard failure. Preserve cancellation/resume and
   return-to-desk review; never manufacture visual approvals or launch the atlas.
4. **Concise guided workflow:** short next-action summaries, collapsed supporting
   explanations, essential warnings/decisions visible. Include finite GPA review
   navigation and audit the remaining staged-calibration UX checklist.
5. **Engineering handoff:** run regressions and large-mesh UI checks, build and
   verify a private local installer, and record exact code/evidence provenance.
   Installation, public releases and changes to live scientific runs require
   their own user decision; no private datasets or installers go to GitHub.

Each completed package includes a scoped commit/push and a concise English entry
in the existing Google Docs Project log. Partial implementation is not completion.

## Larger roadmap: planned work, not automatically completed by this version

Large-mesh viewing is implemented as bounded, cached, display-only quadric
clustering, shared background rendering/loading and explicit original-detail
inspection. See `LARGE_MESH_VIEWER.md` for the measured private-mandible example
and limits: fine anatomical detail can be lost in a proxy, so exact picking and
QC confirmation still require the original view. This is not scientific mesh
decimation, GPU rendering or a hard frame-latency guarantee.

| Workstream | Dependencies and next work | Acceptance gate |
| --- | --- | --- |
| Modern/reference qualification | Review frozen Weevil continuation, then execute the authorized continuation; predeclare numerical and geometric comparisons | Converged, independently recomputed gradient/objective/deformation and performance evidence; inconclusive runs remain inconclusive |
| Scientific parameter validation | Independent anatomical landmarks, PCA/subspace stability, predeclared test/holdout separation | Report uncertainty and sensitivity; no tuning to published PCs or universal-optimum claim |
| Multiresolution analysis | Prospective approved face-count levels and immutable provenance, distinct from display proxies | Compare atlas geometry, residuals, tangent/PCA stability and PC endpoint shapes before recommending scientific decimation |
| Pilot selection/search | Optional biological strata/extremes; bounded adaptive search with explicit attachment/deformation/noise labels | Tail stability tests, boundary-winner regression, safety caps and honest unbounded-search reporting |
| Runtime/memory calibration | Representative small/medium/large cohorts and fresh-process measurements | End-to-end runtime and peak-memory evidence; confidence-calibrated estimates rather than an untested fixed ETA |
| GPU | Identify accessible NVIDIA hardware, memory budget and supported environment; preserve CPU fallback | Same scientific gates plus CPU/GPU parity/tolerance, determinism and failure/memory tests; no GPU speedup claim from CPU tests |
| HPC/Apptainer | Obtain target cluster policy, storage/mounts, scheduler and container support; stage-only dry run first | Reproducible submission, cancellation, restart, path/provenance and data-permission checks on the actual target; NAS storage alone is not compute |
| Linux/macOS CPU | Qualified build runners and supported backend/toolchain per platform | Clean-system install, smoke, run/reopen and uninstall/project-preservation evidence per platform |
| Distribution | Review pinned release lock, SBOM and licenses; signing and clean-VM resources | Signed installer and retained-integrity evidence, followed by explicit release authorization |
| External usability and documentation | Recruit independent testers with consent; task-based protocol; update user/method docs | Observed completion/errors, documented limitations, reproducible examples; internal tests do not substitute for external usability evidence |
| Scientific release | Complete qualification, benchmarks, documentation and authors' review | Approved archived release/DOI and manuscript submission; neither is implied by implementing UI features |

These gates have no invented dates or approvals. Hardware access, cluster policy,
independent testers, author decisions and scientific observations are dependencies
to resolve explicitly. Existing roadmap items stay open until their evidence is
actually available.

## Validation Lab implementation notes

The first package adds hash-chained UTC event times for new events, without
rewriting legacy ledgers. If the first execution event was untimed, the UI says
the original start is unavailable instead of using a later resume or file mtime.
Wall time includes interruptions; it is not accumulated compute time. Completed
whole-study wall time stops at the recorded holdout-report completion.

The progress denominator includes every frozen training/resampling run and every
planned fixed-template holdout run, even before holdout input preparation. A local
backend receipt is only an observed backend finish; it does not verify scientific
evidence. Failed postprocessing cannot silently trigger a repeated completed atlas
or registration. Results are not called fully validated until both reports exist.

Opening, source/result verification, protected study preparation, workload checks
and terminal snapshot reloads run off the GUI thread. Cancellation is cooperative
at phase boundaries: a long individual verification/copy may finish before it is
acknowledged, and a valid prepared study may be retained, but no engine launches
after cancellation. Integrity failures are surfaced, not hidden by creating a
fresh replacement study. Existing source/configuration hash gates remain active.
