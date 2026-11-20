# v99 native mesh-filter containment

A Windows desktop heap-corruption crash was reported while preparing another
individual fit after a recorded rejection. Its exact native origin is not proved
by the application-error record. v99 contains the native-plugin boundary rather
than treating an optimizer limit or a fit score as the cause.

MeshLab decimation and point-to-triangle distance filters now execute in fresh,
hidden helper processes without constructing the desktop application. Windows
kill-on-close supervision is established before plugins execute. A child failure
or timeout becomes a visible, recoverable pilot error; temporary geometry is
private and removed after child termination. The existing console worker is
launched with no console window; the windowed GUI does not handle pipe requests.

Individual and joint children inherit exact hash-bound working targets and
controls from their parent sequence. They no longer repeat native decimation.
Original specimen/template identities, filter settings, fitting parameters,
distance definitions and human approval requirements are unchanged. No private
parameter-tuning or atlas run is required for the software checks.

Verification covers repeated filters with a live Qt host and successive worker
lifetimes, actual hidden child exit and timeout/reaping, native synthetic
decimation/distance results, frozen dispatch, and exact inherited geometry.
Sequence/search/dialog regressions and version checks pass. Frozen helper and
installation evidence are recorded separately before delivery.

This is containment of a plausible native boundary, not proof of the precise
heap-corruption source or a guarantee against every desktop crash. Prospective
fit quality and whole-pilot approval remain separate user acceptance steps.
Installer uploads are on explicit request only under the current owner policy.
