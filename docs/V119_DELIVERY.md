# v119 build and local installation

The [Windows atlas-worker startup correction](V119_WORKER_STARTUP.md) is built,
verified and installed locally as `0.0.0.dev119`. Build01 binds runtime commit
`35f951fc7f2054131ecedeeda490fb4ab2a2207c`.

77 scoped Windows regressions passed, including both workers/controllers,
reference event transport, fresh-interpreter native loading with open stdin,
delayed UTF-8 commands and pilot-field handoff. Ruff and diff checks passed.
Frozen GUI/worker checks and parent-death audits passed. The added uncancelled
startup probes reached expected safe verification/preflight failure in 1.031
and 1.032 seconds without creating a run or executing Deformetrica.

The frozen inventory contains 2,830 files and 948,191,602 bytes. Setup contains
359,254,442 bytes with SHA-256:
`f5de1059d1643d602154f4e1899c9028c0e59c101e75f2ef8e7bc466021bc27e`.
Verified installer-build evidence has SHA-256:
`5075246c835e98d7c4bc71cd7b3f64eadfd6650cdd537e85a75b12d4116818e5`.

After owner closure and fresh application/backend idle checks, all 2,841 prior
dev118 application files were copied and hash-verified. Setup exited zero.
All 2,832 installed bundle files and six companion evidence files match the
build. Registry dev119 and installed GUI startup exit zero were verified.
Both uncancelled installed-worker probes also passed, in 1.172 and 1.125
seconds. Five tracked critical research-result files remained unchanged.
No owner scientific run was started.

Transport verification is distinct from anatomical acceptance or optimizer
convergence. Parameters, initialization/checkpoint rules, scientific results
and QC decisions were not changed by this correction. The intended use of
saved pilot fields still requires the separate preserved-pilot atlas setup and
owner early/final anatomical review. No installer upload was requested; Drive
intentionally retains the last verified v98 package. No public release, tag
or merge is implied. Later documentation does not change the runtime commit.
