# Method-specific score dimensions

The v83 public Reference workflow exposed a cache/export defect: Isomap returned
three positive axes for five subjects, but cache and CSV verification required
four axes for every method. A method's positive spectral rank can be smaller
than `subjects - 1`; an export component setting is an upper limit, not a reason
to invent extra coordinates.

The cache, resumed comparison and CSV reader now require exactly
`min(exported_score_dimensions, available_dimensions)` axes for each method.
The method document is validated first. Hashes, source identity, finite numbers,
specimen/component order and equality with the source-bound cache remain required.
New cache payloads are checked before publication. Existing valid artifacts and
their schemas are preserved; scientific embeddings and eigenvalue thresholds do
not change, and no missing axes are padded into scientific score files.

Reports also tolerate a one-axis shared comparison. Pairwise metrics use the
declared shared dimension. Existing method caches contain 2D/3D/full-rank fidelity
and need not contain separate 1D fidelity. Where absent, the 1D profile explicitly
shows `n/a`, with an explanation in HTML/PDF, rather than relabeling 2D values or
mutating a completed cache. Recorded per-method fidelity remains in the metrics
CSV. The two-axis visual overview can place a one-axis embedding on a line;
its display-only zero ordinate is not an exported scientific component.

Regression coverage uses genuinely computed rank-one and rank-two momenta cases,
Isomap with one/three axes, export caps of one/two/four, all nine methods,
cache reuse, HTML/SVG/PDF generation and deterministic re-verification. Missing
cache columns and CSV rows still fail even when their file hashes are updated.
The actual public five-subject engine output now also completes all nine methods.

Local verification: 74 Reference PCA/comparison, shape-space and PCA-stability
tests passed; repository lint passed. The nine-page public comparison PDF was
rendered and visually checked. The pre-fix full-rank comparison/PDF remains
deterministically verifiable with the corrected code.

This corrects software handling; it does not validate a biological interpretation
or make agreement between methods a parameter-selection oracle.
