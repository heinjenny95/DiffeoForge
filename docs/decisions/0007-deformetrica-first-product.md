# ADR 0007: Deformetrica-first product, evidence-gated replacement engine

- Status: accepted
- Date: 2026-07-19

## Context

DiffeoForge's experimental dense CPU engine now completes atlas and PCA pilot
workflows, but the first 68-subject measurement is materially slower than the
researcher's existing Deformetrica/KeOps workflow despite much lower mesh
resolution. A universally faster, more reliable replacement cannot yet be
claimed. Making the desktop application's success depend on that replacement
would delay the usability and reproducibility improvements that motivated the
project.

The established numerical backend and the surrounding research workflow are
separate concerns. Researchers need installation help, mesh and landmark QC,
optional Procrustes alignment, understandable parameter review, supervised
execution, progress and bounded ETA evidence, result inspection, PCA, and a
complete provenance bundle regardless of which engine performs atlas
optimization.

## Decision

DiffeoForge 1.0 will be a Deformetrica-first, engine-independent application.
Deformetrica is the recommended numerical backend while DiffeoForge owns the
complete user workflow:

1. import and validate meshes;
2. optionally place/import homologous landmarks;
3. review and apply an explicit Procrustes transform to immutable mesh copies;
4. review every effective atlas parameter;
5. supervise Deformetrica and expose its logs, observed progress, cancellation,
   recovery, and an ETA to the configured iteration cap when enough timing data
   exist;
6. verify atlas outputs and generate engine-independent PCA tables, plots, and
   shape artifacts;
7. export a reproducible run bundle.

The Modern engine remains available only as an experimental research backend.
It may become recommended only after controlled scientific-equivalence,
robustness, memory, and performance gates are satisfied on representative
cohorts. Product completion does not depend on that promotion.

An ETA derived from observed iteration timing must always be labelled as time
to the configured iteration cap, not predicted time to convergence. Early
stopping and changing iteration cost make a convergence-time promise
scientifically and operationally unjustified.

## Consequences

### Positive

- useful software can ship without claiming a replacement engine prematurely;
- Deformetrica's legacy dependencies can be isolated from the modern desktop;
- landmark alignment, QC, PCA, and provenance remain reusable by every engine;
- the Modern engine has explicit acceptance criteria rather than product-driven
  scientific claims;
- a workflow/methods paper can evaluate accessibility and reproducibility
  independently from a later numerical-engine paper.

### Costs

- the external numerical runtime still needs a reliable installation and update
  strategy;
- Deformetrica logs and artifacts need strict adapters and versioned parsers;
- interactive landmark placement and downstream PCA must not silently introduce
  scientific choices;
- two backend paths remain testable, but only one is presented as recommended.
