# v110 — verified saved-pilot compatibility update

Runtime/build source:
[ab84c1f](https://github.com/heinjenny95/DiffeoForge/commit/ab84c1f8c0b6f9f6dc6c12460d8c0b50afefcff6).
Later delivery-documentation commits do not change the installed runtime.

The integration/viewer suite passed 19 tests; five qualification compatibility
cases passed, including original and extended legacy queues, pending-declaration
resumption, fresh QC, final reports and artifact tampering. Ruff and scoped diff
checks passed. The saved pilot, its old results and approvals were opened read-only.
An earlier combined diagnostic run with a faulthandler timer ended in a native
access violation while reading YAML; the affected cases passed in the separate
scoped run without that timer. This is not a full-suite success claim or proof
of the diagnostic failure's cause.

Frozen startup/workers, preparation-only/cancel, limited parent-death, dependency/
SBOM and installer verification passed. The setup is 358,981,032 bytes; SHA-256:
`bf213a62c954e22ea2d0abbd5ff173c3e6f6ec4fb17aeb633d26b36971626d66`.
Installer-evidence SHA-256:
`af0edabc1a870591292d39cada6be673fd6b466cbafd5801e0752bdf37200671`.

Fresh application/backend idle checks and a complete, hash-verified 2,840-file
backup preceded the authorized installation. Setup and installed dev110 startup
exited zero; no Windows restart. All 2,831 bundle files and six companions match;
all 4,114 recorded saved pilot files are unchanged.
Installed EXE SHA-256:
`fadd92316334e8d4858e0e4b9c57ec312ead0239a75feb0fa06368beb7bf23fa`.

Reopen the same saved Stage 4 and use **Check saved model** to resume the existing
declaration. No deletion or complete restart is needed. All v109 numerical gates,
fresh human anatomy review and scientific-validation limitations remain. No
private fit, parameter search, stage selection or QC decision was performed.
Native owner workflow acceptance remains open. Drive intentionally retains v98;
no installer upload, release, tag or merge was made.
