# Desktop reference preparation status

Status: **read-only desktop presentation; no recovery or execution action**

The Deformetrica reference review screen can present the same strict
approval-bound reconciliation report as the CLI. The user supplies:

1. the previously reviewed preparation-only approval JSON; and
2. the independently recorded SHA-256 of that complete file.

The desktop service also requires the exact configuration SHA-256 captured by
the completed parameter review. It calls the shared
`reconcile_reference_preparation` core; Qt does not reimplement destination,
private-stage, manifest, lifecycle, or path-surface classification.

## Display states

- `clear_to_prepare`: the approved destination is absent and there is no exact
  private stage;
- `published_prepared_not_executed_verified`: the exact destination is a fully
  verified prepared run with no engine execution evidence and no exact private
  stage; or
- `attention_required`: an exact destination or private-stage observation
  requires an explicit human decision.

The background task returns a bounded immutable view model containing the
approval/config bindings, run ID, plan fingerprint, exact destination status
and reason, optional manifest hash, exact private stages, stable-observation
flag, mutation flag, and scientific boundary. The GUI shows these values but
does not treat `clear_to_prepare` as permission to prepare or
`verified_complete_unpublished` as permission to publish.

## Stale-result boundary

The inspection runs outside the Qt event loop. If the selected approval path,
entered hash, reviewed config path, or reviewed config hash no longer matches
when the result returns, the GUI discards the result. Editing either approval
field immediately clears the previous display model. A failed inspection never
leaves an earlier status visible as current.

## Explicit non-capabilities

This path does not delete, rename, publish, repair, recover, resume, prepare,
execute, or cancel anything. It does not enable the reference start button and
does not decide what should happen to a verified private stage. It makes no
claim about process liveness, crash recovery, engine containment after request
delivery, parameter suitability, numerical validity, convergence,
registration quality, or biological interpretation.

The underlying versioned report is documented in
[Approval-bound reference preparation status](REFERENCE_PREPARATION_RECONCILIATION.md).
