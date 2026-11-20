# v129 — guided pilot and a cached Visualization workspace

New pilots start with **Find fit**: one specimen, one attempt, then review. The
short overview explains rejection, approval and the subsequent combined fit.
Saved staged studies keep their protocol; saved sequential studies reopen in
the guided route. Scientific settings, original results and approval gates are
retained. Optional tools live inside the scroll area; the footer keeps the next
action reachable. Moving actual widget ownership with the layouts prevents the
old controls from drawing over headings. Pending, completed and density views
were visually checked at 850×650 and 1040×820.

Full-detail mesh geometry now has a bounded content/resolution cache shared by
preview loaders. Every hit still hashes current source bytes; unchanged files
avoid parsing and rebuilding full edges. Pilot proxy hits stream the hash rather
than reading a second complete byte array. UI-only option changes reuse the
verified study snapshot; explicit opens and scientific transitions retain their
verification. A public 178,800-triangle, 9.05 MB fixture measured 1.619 s cold and
0.0066 s warm for full detail; proxy preparation measured 0.422 s cold and
0.0062 s warm. These are single-machine engineering observations, not private
dataset or universal performance claims.

## Results and Visualization

After a verified reference result is released through its existing QC gate,
mean-momenta and ±2 SD shapes are prepared automatically for available nonzero
PC1–PC3 modes. SD views appear below the ordinary PCA plots. A new left-rail
**Visualization** page contains a zoomable mesh PCA, SD rows, six-view heatmaps
and native in-app movie playback. Changing pages reuses prepared media; it does
not repeat mesh loading, Shooting or rendering. Native work and rendering run
off the GUI thread, with progress, single dispatch per source identity, explicit
retry after failure and cancellation after the current native operation. Closing
waits for safe completion; stale or closed-window callbacks cannot start work
or apply another result's media.

Mesh glyphs occupy exact saved scores with one camera and scale, without jitter
or per-specimen resizing. Private specimen names are available in local tooltips;
sharing data use numeric glyph IDs. Heatmaps use corresponding full-resolution
endpoint vertices for magnitudes and signed mean-normal displacement. Ranges and
cameras are shared. Units remain model coordinates, including normalized GPA
coordinates where applicable; no physical-length conversion is inferred.

Movies show opposing XY/XZ/YZ views simultaneously. Seventeen native momenta
samples per axis cover −2 SD → mean → +2 SD; display interpolation occurs only
between adjacent corresponding samples. Original-template vertex subsets retain
the fitted controls, kernels, precision and integration grid, and must agree with
the full native mean/±2 SD anchors within the recorded precision/scale bound.
These are modeled PC-path views, not optimizer histories, observed specimens,
confidence intervals, exact nonlinear PGA or anatomical approval.

The complete, verified media cache is published once under the project folder.
**Export gallery ZIP** copies a checked archive atomically. Its offline English
gallery includes an interactive mesh plot, PNG/PDF figures and H.264 MP4 videos.
Raw meshes, source paths, native inputs, logs and identity keys stay outside the
sharing tree; unexpected file types are rejected before archive creation.

## Native endpoint repair

Deformetrica 4.3's Shooting entry point can ignore the declared point count when
constructing Geodesic. A run-local protected adapter now supplies concentration
`count − 1`, checks every effective time in [0,1] and exports physical **t=1**.
Every field has a native precision/momenta-hash/grid receipt. New designs and
results are v0.2; old v0.1 evidence remains readable and explicitly labeled with
unverified endpoint time. It is not reused as corrected media and is never
overwritten. Native equations and the source atlas/PCA are unchanged.

Public native Windows/WSL checks covered all seven mean/PC1–PC3 endpoints, all 51
display samples, matching anchors, source preservation, complete figures/ZIPs
and video decoding. The default Float32 KeOps runtime passed the full pipeline.
An isolated native Float64 Torch-Gaussian fixture verified the adapter's time
grid and serialized fields; this does not qualify an arbitrary Float64 KeOps
runtime or a private dataset. Local Float64 KeOps compilation was unavailable
in that separate probe. No runtime fallback or native package edit was made.

## Iteration budgets

New completed-pilot configurations retain or raise their starting iteration
budget using only selected, observed pilot runs. The policy allows 1.5× observed
iterations; use of at least 90% of a pilot cap adds 300 iterations, rounded upward
to 100 and bounded at 100,000. Higher declared budgets are retained. The proposal,
evidence and reason are recorded and shown before full-atlas execution; both the
new atlas and its individual initializers receive the budget. Existing completed
configurations and running jobs are unchanged.

This is transparent planning headroom, not a prediction of convergence. Control
points/timepoints affect work per step and do not alone determine iteration
count. A cap remains distinct from the native tolerance stop. Existing guarded
checkpoint continuation remains explicit; this change adds no automatic recovery,
unbounded continuation or new scientific stopping criterion.

Source/regression/native-media checks and frozen/installed acceptance are
separate. Packaging and installation status are recorded in the delivery note
only after their own verification. No installer Drive upload is implied.
