# Release checklist

Status: **pre-alpha evidence gate**

This checklist defines the minimum evidence required before publishing a
DiffeoForge release. It does not imply that the current software is validated
for scientific production. Every checked item must be supported by a link,
artifact, command transcript, or named reviewer. An item may be marked not
applicable only with a written justification.

## Release record

- Candidate version:
- Candidate commit:
- Release coordinator:
- Review date:
- Intended platforms and installation routes:
- Scientific claims made by this release:
- Explicitly unsupported uses:

## 1. Scope and change control

- [ ] The candidate commit and version are fixed for the review.
- [ ] User-visible, configuration, schema, and artifact changes are listed.
- [ ] Breaking changes and migration steps are explicit.
- [ ] Open blocking issues are resolved or documented as release limitations.
- [ ] Scientific changes link to a completed scientific-change issue and evidence record.

## 2. Automated software evidence

- [ ] `ruff check .` passes on the candidate commit.
- [ ] `pytest` passes on every supported Python version.
- [ ] `python -m build` produces both source and wheel distributions.
- [ ] `python tools/verify_wheel.py dist/<wheel>.whl` confirms all versioned
  schemas, CLI entry points, package metadata, and safe unique archive names.
- [ ] A clean environment can install the built artifact and display CLI help.
- [ ] GitHub Actions checks pass without ignored or manually skipped failures.

Record CI runs, build hashes, and clean-install evidence:

```text
CI:
sdist SHA-256:
wheel SHA-256:
clean-install environment:
```

## 3. Scientific validation evidence

- [ ] Every numerical claim maps to a validation protocol and pass criterion.
- [ ] The open synthetic reference suite passes at the declared tolerances.
- [ ] Objective, gradient, deformation, and convergence comparisons are included when affected.
- [ ] Tolerance changes are justified quantitatively and versioned.
- [ ] Backend versions, container digests, hardware, seeds, and numerical precision are recorded.
- [ ] Results that differ from the frozen reference are explained rather than silently accepted.
- [ ] Unsupported geometries, scales, parameter regimes, and platforms are stated.

Record validation reports and the decision owner:

```text
protocol:
reference run:
comparison report:
decision and reviewer:
```

## 4. Reproducible workflow evidence

- [ ] A clean user can run `doctor`, `init`, `validate`, `prepare`, and `report` as documented.
- [ ] At least one supported backend completes the public example end to end.
- [ ] Effective configuration, inputs, commands, versions, hashes, events, and outputs are inventoried.
- [ ] Every advertised modern-atlas bundle passes schema, exact-file inventory, SHA-256, and VTK verification.
- [ ] Every advertised modern workflow passes outer schema/inventory verification and nested bundle verification.
- [ ] Existing run directories cannot be silently overwritten or executed twice.
- [ ] Interruption, recovery, and resume behavior is rechecked when lifecycle code changes.
- [ ] Generated HTML reports remain self-contained and make no network requests.
- [ ] Reproduction instructions begin from a public or generated dataset, not a developer machine.

## 5. Data, privacy, licensing, and security

- [ ] Repository and release artifacts contain no unpublished meshes, manuscript results, or identifiers.
- [ ] Test and example data have recorded provenance and redistribution-compatible licenses.
- [ ] Logs, examples, and screenshots contain no credentials, usernames, or sensitive absolute paths.
- [ ] New dependencies and bundled components have compatible licenses and pinned provenance.
- [ ] The deterministic CycloneDX SBOM verifies against externally recorded
  freeze, dependency-evidence, and SBOM SHA-256 values.
- [ ] A named human reviewer has completed the separate license inventory,
  compatibility analysis, and redistribution decision; schema validity alone
  is not accepted as legal review.
- [ ] Python Pickle checkpoints are documented as trusted-source-only inputs.
- [ ] Security-relevant limitations and reporting instructions are current.

## 6. Documentation and usability

- [ ] README status, installation, first-run workflow, and limitations match the release.
- [ ] CLI help and the versioned configuration schema agree.
- [ ] Parameter units, defaults, generated values, and safe-use boundaries are explicit.
- [ ] Result and preflight reports have current interpretation documentation.
- [ ] At least one person other than the implementer follows the first-run instructions.
- [ ] Release notes distinguish software behavior, scientific behavior, and documentation changes.

## 7. Distribution and platform claims

- [ ] Each advertised operating system and installation route has clean-machine evidence.
- [ ] A desktop artifact installs, launches, runs the public CC0 smoke, and uninstalls offline on a clean machine without Python.
- [ ] Installer and uninstaller logs show that user-selected projects are preserved.
- [ ] Executables/installers have verified signatures, SHA-256 hashes, an SBOM, and a third-party license inventory.
- [ ] Paths with spaces, non-ASCII characters, and a non-administrator install are tested.
- [ ] The installed application makes no network request by default.
- [ ] CPU and GPU claims are kept separate and supported by their own comparisons.
- [ ] Container tags are backed by immutable image digests and build instructions.
- [ ] Archive/HPC instructions are tested when advertised.
- [ ] Resource expectations and known scaling limits are stated for supported workflows.

## 8. Publish and archive

- [ ] The final commit is unchanged from the reviewed candidate.
- [ ] The version tag and release title agree with package metadata.
- [ ] Release artifacts and SHA-256 hashes are attached.
- [ ] Release notes link validation evidence and list all known limitations.
- [ ] Documentation links resolve from the tagged repository state.
- [ ] A DOI/archive is created when the scientific-release milestone requires it.

## Sign-off

```text
Software review:
Scientific review:
Documentation/usability review:
Release coordinator decision:
Date:
```
