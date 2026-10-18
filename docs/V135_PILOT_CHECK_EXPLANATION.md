# v135 — explain the remaining pilot check

The selected Stage 4 fit has three short, persistent status lines: shape review,
time resolution and optimizer convergence. Anatomical approval remains visible
when the fixed-state time-grid check fails. An iteration-limited fit states its
recorded budget and keeps convergence unconfirmed. Missing or unknown evidence
does not become a pass.

For a time-grid mismatch, the status explains why a good-looking reconstruction
can still change with finer time steps. The primary button names the next grid
from the selected candidate, such as “Recalculate with 37 time steps”. The new
fit still needs review and another check; the action does not promise a pass.
Repeated specimen-level messages stay in folded details.

The summary uses the existing verified assessment and declared settings; selecting
a result does not reload meshes, rehash check artifacts, start work or write a
review. Native equations, thresholds, optimizer budgets and completion gates are
unchanged. This builds on the v134 next-step and v133 comparison changes. Source,
tested build, local installation and independent first use remain separate.
