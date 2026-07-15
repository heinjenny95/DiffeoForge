# ADR 0001: Separate workflow and numerical engines

- Status: accepted
- Date: 2026-07-15

## Context

The immediate problem includes both usability failures and outdated numerical
dependencies. Replacing the numerical engine first would delay useful workflow
improvements and remove the reference implementation needed for validation.
Building only a graphical wrapper would preserve legacy limitations and hidden
behavior indefinitely.

## Decision

DiffeoForge will use an engine-independent workflow core with versioned
configuration and run-artifact contracts.

The original Deformetrica 4.3 behavior will be exposed through a pinned
reference backend. A modern engine will be developed or integrated behind the
same boundary and accepted only after the validation strategy is satisfied.

## Consequences

### Positive

- users receive one workflow independent of numerical backend;
- reference and modern engines can be compared on identical inputs;
- GUI development cannot hide engine configuration;
- numerical modernization can proceed incrementally;
- future engines or HPC adapters do not require redesigning the user interface.

### Costs

- backend capabilities and unsupported options must be modeled explicitly;
- configuration translation becomes a tested component;
- some engine-specific features may not fit the common contract;
- validation requires maintaining reference artifacts and tolerance policies.
