# Project specification

Status: **draft 0.1**

## Problem

Diffeomorphic surface atlas construction is scientifically powerful but often
requires users to combine fragile software environments, hand-written XML,
working-directory conventions, notebooks, and undocumented hardware choices.
An atlas can appear to succeed without leaving a complete record of which
files, defaults, software versions, or computational backend produced it.

DiffeoForge aims to provide a transparent workflow around atlas estimation and,
after independent validation, a modern numerical implementation.

## Target users

- researchers working with collections of 3D biological or anatomical surfaces;
- users without programming experience;
- method developers who need explicit, scriptable configuration;
- reviewers and collaborators who need to reproduce a published atlas.

## Version 0.1 scope

- three-dimensional triangular surface meshes;
- deterministic atlas construction;
- surfaces without point correspondence;
- Current and Varifold attachment models;
- Gaussian deformation kernels;
- CPU reference execution;
- explicit initial-template selection;
- configuration, preflight, immutable runs, and quality reports;
- a local GUI backed by the same API and schema as the CLI.

## Explicit non-goals for version 0.1

- medical images or voxel data;
- longitudinal atlases or geodesic regression;
- Bayesian population models;
- automatic biological interpretation;
- silent mesh repair or alignment;
- claiming numerical equivalence before validation;
- reproducing every feature ever exposed by Deformetrica.

## Reproducibility contract

Every completed run must contain enough information to audit and re-execute it:

```text
runs/<run-id>/
├── config/                source and fully resolved YAML configuration
├── input/                 staged template and subject meshes
├── engine/                backend-specific, generated inputs such as XML
├── output/                numerical engine outputs only
├── logs/                  full backend log and parsed convergence CSV
├── manifest.json          write-once pre-execution evidence
├── manifest.sha256        manifest integrity sidecar
├── events.jsonl           append-only lifecycle events
├── result.json            terminal status, environment, command, and duration
└── output-inventory.json  sizes and SHA-256 hashes for every output file
```

The prepared-manifest schema and retention behavior are versioned. Existing
run directories are never silently overwritten or re-executed.

## Scientific guardrails

- Units are mandatory and kernel widths are reported in those units.
- Template selection is explicit; selecting the first alphabetic mesh is not a
  permitted hidden default.
- Effective user parameters and known fixed backend constants are materialized
  before a run; any newly discovered implicit engine choice is treated as a
  reproducibility defect.
- Geometry checks distinguish errors, warnings, and informational variation.
- CPU and GPU results are compared under declared numerical tolerances.
- Parameter recommendations must be supported by experiments or literature,
  not embedded as unexplained constants.

## Initial acceptance criteria

Version 0.1 will not be declared scientifically usable until:

1. reference datasets and expected outputs have redistributable licenses;
2. reference-backend runs are reproducible from a pinned container image;
3. critical gradients pass finite-difference tests;
4. CPU repeatability and CPU/GPU agreement have defined tolerances;
5. failure cases and known limitations are documented;
6. at least one researcher outside the development workflow completes a run
   without direct developer intervention.
