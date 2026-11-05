# Fixed-basis initialization performance qualification

The preserved-pilot atlas handoff first fits the remaining subjects against the
same frozen template and control basis. These independent initializers are a
candidate for bounded parallel execution. Their output still initializes one
subsequent joint atlas. The joint template, controls and cohort objective must
continue to be optimized together.

Production execution remains sequential. This source follow-up adds a numerical
comparison tool, not a new runtime mode or a changed optimizer contract. Existing
prepared studies, iteration allowances, tolerances, geometry, approvals and the
installed application remain unchanged.

## Equality gate

`tools/compare_initializer_fields.py` reads two separately produced evidence
packets. It checks:

- Original template/connectivity and control-basis identities, ordered subjects
  and their recorded hashes, and all supplied effective settings.
- Checksum-verified template, control and momentum arrays, including shapes,
  finite values, storage precision and every bit of every retained field.
- Exactly one completion receipt for each nonpilot subject, with matching native
  iterations and stop reasons. Out-of-order worker completion is permitted.
- Explicit pilot indices, including an explicitly empty set for a comparison
  without retained pilot rows. Missing rows, duplicates and unknown or failed
  native stops cannot qualify.

A capped initializer remains capped in the report. Numerical equality does not
establish convergence, anatomical suitability, final atlas quality, or the
truth of unverified execution metadata. Source hashes and effective settings
must come from independently verified actual runs. An equality report alone
does not authenticate those runs.

Run the comparison with the repository's analysis dependencies available:

```text
python tools/compare_initializer_fields.py reference/packet.json candidate/packet.json --output proof.json
```

The command never launches an optimizer or accesses a GPU. It reads packet data
and writes one new proof file; an existing proof cannot be overwritten. A valid
but unequal comparison returns exit code 1 and withholds a wall-time ratio.
Invalid or incomplete evidence fails before producing a qualification report.

## Packet contract

Each packet uses protocol `fixed-basis-initializer-equality-v1` and contains:

- `subjects`: the ordered list of `{id, sha256}` input identities.
- `basis_identity`: `template_sha256` and `controls_sha256`, including the
  original mesh connectivity through the template file hash.
- `settings`: the complete effective initializer contract. At minimum the tool
  requires `max_iterations`, `convergence_tolerance`, `timepoints`, `precision`
  (`float32` or `float64`), and both `freeze_template` and
  `freeze_control_points` set to true. Producers must also record the actual
  attachment, noise, movement, integration, line-search and native runtime
  settings rather than relying on undocumented defaults.
- `arrays`: checksum-verified `template`, `controls` and `momenta` entries, each
  with a relative `path` to a numeric NPY file and its `sha256`. Paths must resolve
  inside the packet directory. Momentum shape is subjects × controls × dimension;
  counts are derived from the supplied cohort and basis.
- `pilot_indices`: explicitly retained rows in that ordered cohort.
- `completed`: one `{index, iterations, stop}` per other row. Supported completed
  stops are `native_tolerance` and `iteration_limit`; the latter must reach the
  recorded allowance exactly.
- `wall_seconds`: a finite positive measured duration for the declared comparison.

Additional packet fields can describe hardware, worker limits, cache state,
measurement scope and execution receipts. They do not replace verifying those
conditions. The reported ratio describes only the supplied measured durations;
it is not a general speedup or a cross-device runtime prediction.

## Qualification sequence and limits

First establish that isolated serial workers reproduce the original native
initializer fields and stops on full scientific geometry. Then compare bounded
concurrent workers against those same references. Verify complete coverage,
retained pilot fields and the assembled common starting state. Recheck the
initial common objective and gradients when integrating a new execution path.

CPU scheduling screens on reduced geometry can test independence and accounting,
but cannot qualify production GPU speed or justify replacing full scientific
geometry. Coarse-only fields and warm starts selected by initial objective need
separate full-surface and important-feature checks. Better average distances
can conceal a locally lost projection. Any coarse-to-fine proposal must keep
its original combined allowance and earn its own quality evidence.

Owner-authorized GPU comparisons wait for the active atlas's normal completion.
All tests use separate copied inputs, isolated output/cache directories and
bounded resources. Running work is never stopped or reconfigured to benchmark.
No scientific result, default change or installation follows from software
regression tests alone.

The focused software tests cover changed basis/connectivity identities, subject
order, tolerance, pilot fields, signed zero, precision, missing/duplicate rows,
invalid stops, nonfinite/tampered arrays, external paths and proof preservation.
Private native execution and surface comparisons remain separate evidence.
