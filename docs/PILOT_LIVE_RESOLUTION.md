# Select the pilot's live display resolution

The live fit preview offers three display budgets per surface: Light (1,600
triangles), Balanced (6,000) and Detailed (16,000). Balanced is the initial
selection for a supported new trial. The choice remains available across the
pilot's candidates. The label reports the actual triangles shown for the fit and
target, which can be below the chosen maximum.

Changing resolution prepares a new display request in the background and keeps
the last snapshot visible until the replacement arrives. That old image remains
labelled with its own accepted iteration. Each request has a distinct identity;
late frames or late cleanup from another resolution cannot replace or retire the
current view. A new resolution can display the same accepted iteration. Camera
orientation, zoom and the optional sampled control-point display are retained.

## Bounded observation

Both layers are reduced once per request. Every displayed source point retains
its exact index into the native material grid, so later snapshots sample that
same material directly from an already computed accepted endpoint. The scientific
mesh, objective, optimizer, iteration budget and numerical checks are unchanged.

The native observer still publishes at most once every 20 seconds, with one
background writer and a short viewer lease. It skips frames when busy or hidden.
Requests and frames have explicit byte/point ceilings. Higher detail increases
display preparation, sampled data transfer and rendering work; it is not a
guarantee of zero runtime overhead. Light remains available on slower machines.
This is a progress display; the separate final quality review determines fit
suitability.

## Existing runs

New trials declare the version 2 display protocol. Already declared version 1
trials keep their exact original protected publisher and their Light budget.
The selector explains this limitation and disables the unsupported choices for
that run. A preferred higher setting is restored for a subsequent version 2
trial. No saved or running manifest, engine script or numerical contract is
upgraded in place to enable a display setting.

## Verification

Tests cover exact source-index sampling, bounded geometry and frame decoding at
each tier, protocol and generation mismatch rejection, protected input changes,
legacy publisher identity, active-request leases, and nonblocking accepted-state
observation. Qt journeys cover same-iteration resolution changes, retained last
snapshot and camera, late-frame rejection, local control-point toggling and
explicit legacy limits. Native/platform packaging and private display timings
remain distinct from scientific validation or a measured full-fit speed claim.
