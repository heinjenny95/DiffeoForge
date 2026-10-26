# Finite accepted-state checks for new regional pilot runs

Newly prepared, frozen, single-specimen regional L-BFGS trials explicitly declare
`new-regional-c5-v1`. Their native objective and gradients pass through unchanged.
The run-local observer checks numerical validity and the identity of accepted
parameters before a result can be exported. This addresses native convergence
messages that can otherwise follow a non-finite evaluation or an accepted cost
increase.

The marker is added while writing a new candidate configuration. Existing
prepared runs without the marker retain their exact generated engine bytes.
Ordinary atlas, joint-fit and PCA processes do not opt into this regional policy.

## What the observer records

- Each native objective/gradient evaluation is associated with the exact
  Float64 parameter vector supplied to SciPy. Non-finite values stop the run;
  no substitute objective or gradient is returned.
- Each accepted callback must match a recorded finite evaluation of the same
  vector and must not increase the minimized objective. These comparisons are
  meaningful only within the same immutable objective.
- Each improved accepted state is saved in an immutable directory containing its
  parameters, gradient, native parameter checkpoint and file hashes. A small
  pointer advances only after persisted coefficient and gradient bits are checked.
- Native exports and final results must bind to an accepted finite state. A
  callback iteration-cap stop is checked against its committed accepted vector;
  it is not reclassified as convergence.
- Staged XML, objective inputs, generated adapters, the manifest and the qualified
  native source/profile are checked at startup and around execution/export.
  Observer boundaries also recheck file identities and the frozen control basis.

The native checkpoint contains parameter state. It does not serialize SciPy's
complete L-BFGS history or line-search memory. Guarded resume/restore preparation
is therefore rejected explicitly; preserving a checkpoint does not authorize an
automatic restart or turn an unsuccessful run into a completed result.

## Initializers and runtime scope

The control-point basis must be supplied explicitly and remain frozen. A warm
field is read through the native reader and compared bitwise with the staged
seed. An implicit native-zero momentum initializer is also supported and checked
against the actual model. Native-generated control-point bases are outside this
version's qualified scope because their hash alone would not preserve a
recoverable, full-precision basis.

Generated run-local Python files carry the qualified observer and adapter; they
do not import a development workspace. The packaged profile pins the tested
Deformetrica 4.3.0 source and dependency versions. An incompatible runtime or
adapter initialization failure stops before fitting. The compatibility wrapper
for SciPy's message type remains separate from objective/gradient values.

## Verification and limits

Actual native CPU probes through generated regional manifests and adapters cover
explicit warm and native-zero momentum starts. Their complete finite objective,
gradient and accepted-parameter sequences agree bitwise with the unguarded
baseline, with no extra objective calls. Negative probes cover non-finite values,
unbound exports, changed inputs, writing before an update, repeated updates and
failed adapter setup. Source preparation, schema, packaging, legacy rendering
and unsupported-scope tests are separate checks.

Passing this observer establishes neither stationarity nor a suitable mesh.
Independent original-surface distances, preservation, temporal/spatial resolution
and intersection checks still apply. Regional single-form results do not approve
a common cohort objective, an atlas, PCA or anatomical correspondence. The native
scientific equations, physical fitting settings and acceptance bounds are not
changed by this guard.
