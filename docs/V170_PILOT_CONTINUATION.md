# Pilot continuation and pre-run visibility (dev170)

The three current owner-requested items are implemented in source. Historical
unchecked research, platform and acceptance entries remain separate gates.

- Stage 4 continuation restores the latest verified capped native GradientAscent
  checkpoint on the selected branch and extends its effective cap by 300. Repeating
  from the same card follows its completed continuation descendants. It preserves
  numerical settings and tolerance; earlier native convergence still stops work.
  It does not repeat the older tighter-tolerance trial from the same stage-3 seed.
- Native parameters and iteration are restored, but Deformetrica reinitializes the
  objective baseline, gradient and line-search step sizes. No uninterrupted
  numerical trajectory is claimed. A fixed-state result on another integration
  grid cannot silently resume the older optimizer grid.
- Individual continuation uses the explicitly selected saved momentum field,
  without silently returning to an older preferred fit. Its optimizer history
  restarts. Local native counts and cumulative branch effort are recorded and
  displayed separately. The additional budget retains source optimization and
  runtime settings. New results require their own visual review.
- Effective parameters shows control-point count beside spacing before execution:
  verified actual count for a supplied field, otherwise an explicitly approximate
  bounding-box grid estimate. Refresh uses the current template, cohort, spacing
  and seed. Merely displaying it performs no fitting or grid allocation.
- Action buttons have bounded normal, hover and disabled surfaces, including
  secondary saved-fit actions and help disclosures. Existing primary/danger
  hierarchy, light/dark themes and custom accent handling remain available.

Verification includes chained checkpoint dispatch and immutable-source checks,
source/Qt regressions, and a new public synthetic CPU native checkpoint restored
at iteration 2 with cap extended to 302 and unchanged source bytes. This is an
engineering qualification, not an anatomical success or speedup claim. Existing
owner fits are neither modified nor restarted. Source, installed runtime and Drive
distribution are tracked separately; installation evidence is recorded after the
qualified package and fresh backup/idle checks.
