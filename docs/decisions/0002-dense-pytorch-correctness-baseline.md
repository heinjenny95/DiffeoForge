# ADR 0002: Use dense PyTorch as the modern-engine correctness baseline

- Status: accepted for feasibility development
- Date: 2026-07-15

## Context

The modern engine must eventually support large surface-atlas studies without
retaining Deformetrica 4.3's obsolete runtime. A full dependency port would
inherit broad internal coupling. Making PyKeOps mandatory would impose compiler
and platform requirements that conflict with the planned accessible Windows
application. Adopting an external registration library would not by itself
provide or validate the required deterministic atlas workflow.

Scientific optimization and performance work need a small implementation whose
individual operations can be read, differentiated, and compared with the frozen
reference before optimized kernels obscure discrepancies.

## Decision

DiffeoForge will implement only its declared deterministic 3D surface scope.
Dense PyTorch CPU/float64 operations are the correctness oracle for modern-engine
development. PyTorch is an optional package extra and the experimental module
is not yet connected to the workflow backend.

The frozen Deformetrica 4.3 backend remains the independent comparison baseline.
PyKeOps, GPU kernels, chunking, or other acceleration may be introduced behind
the same observable operations only after parity with the dense oracle. The
dense path will remain available for small regression cases even after an
accelerated backend exists.

## Consequences

### Positive

- equations map to short, inspectable tensor operations;
- autograd and finite differences can test explicit derivatives independently;
- current Windows and Linux CPU environments can execute the same baseline;
- accelerators cannot silently redefine scientific behavior;
- the implementation scope follows the published DiffeoForge model boundary.

### Costs and limits

- dense pairwise kernels require quadratic compute and memory;
- PyTorch substantially increases the optional installation size;
- atlas optimization and 300-subject scalability remain unproven;
- two numerical paths will eventually require ongoing parity tests;
- final equivalence tolerances cannot be chosen from this primitive fixture.

This ADR selects a development oracle, not a scientifically accepted production
engine. Acceptance remains governed by the validation strategy and issue #12.
