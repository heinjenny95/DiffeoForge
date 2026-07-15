# Result-report interpretation

Status: **pre-alpha engineering report; not a scientific acceptance test**

The result report turns a completed or failed run's recorded evidence into a
portable HTML document. It is designed to make the numerical process easier to
inspect without hiding the underlying files or assigning a stronger scientific
meaning than those files support.

## Create a report

After a run reaches a terminal state:

```powershell
diffeoforge report runs\pilot-001
```

The default destination is `runs/pilot-001/result-report.html`. A different
destination can be selected explicitly:

```powershell
diffeoforge report runs\pilot-001 --output reports\pilot-001.html
```

Existing files are never silently replaced. `--force` can replace only an HTML
file carrying the DiffeoForge result-report generator marker; unrelated files
remain protected.

Prepared or still-running directories do not yet have a terminal result and
are rejected. Failed runs are accepted because their partial objective history,
error, lifecycle, and output inventory can be diagnostically important.

## Recorded sources

The report reads, but does not alter or re-execute:

- `manifest.json` and `manifest.sha256` for the run identity, effective
  configuration, subject count, backend contract, and optimizer settings;
- `events.jsonl` for the append-only lifecycle;
- `result.json` for terminal status, return code, duration, command, and
  environment;
- `logs/convergence.csv` for observed log-likelihood, attachment, and
  regularity values;
- `output-inventory.json` for execution-time file sizes and SHA-256 hashes.

The HTML embeds its styles and SVG plots. It contains no JavaScript, network
requests, telemetry, or external assets. The report is a derived view and is
not itself part of the numerical output inventory.

## Evidence checks

Report generation verifies the prepared-manifest digest and schema through the
same read-only status service used by the CLI. It then reports whether:

- the last lifecycle event agrees with `result.json`;
- the output-inventory digest agrees with `result.json`;
- inventory file count and total bytes agree with the terminal summary;
- the number of parsed convergence rows agrees with `result.json`.

The report does not rehash every potentially large numerical output. It shows
the hashes recorded immediately after execution so an explicit integrity audit
can be implemented separately without making ordinary report generation scale
with every output byte.

## Reading the objective curves

The first plot shows log-likelihood and attachment on one recorded numeric
scale. The second shows regularity separately because its magnitude can differ
substantially. No smoothing, normalization, interpolation, or omitted rows are
used.

The report uses deliberately narrow language:

- **Engine completed** means the process returned zero and no execution
  exception was recorded.
- **Engine failed** means a nonzero return code or execution exception was
  recorded.
- **Stopped before the requested maximum** is an observation, not proof that a
  convergence criterion was satisfied.
- **Reached the requested maximum** is not labelled as convergence.
- a decreasing log-likelihood step is surfaced for review rather than silently
  smoothed away.

The full `logs/deformetrica.log` remains the authoritative source for backend
messages about its stopping decision.

## Scientific boundary

A successful exit, internally consistent evidence, and a stable-looking curve
do not establish:

- adequate surface registration or mesh quality;
- suitable kernel widths, noise, template, or optimizer parameters;
- biological validity or representative sampling;
- equivalence across computers, containers, CPU/GPU modes, or numerical
  engines;
- correctness of a future modern implementation.

Those claims require the separately versioned validation protocol, reference
comparisons, tolerances, benchmark study, and scientific review described in
the project roadmap.

## Privacy

The report contains the run directory, project name, effective configuration,
and output filenames. These may reveal specimen identifiers or workstation
paths. Review the HTML before sharing it outside the research team.
