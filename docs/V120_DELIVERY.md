# v120 — verified Windows installer, installation deferred

The application was frozen from clean runtime commit
`3e4b5cc2025e4c4cc977457b3ac950965d61ed37` as `0.0.0.dev120`.
202 scoped source regressions passed with one intentional dependency skip,
including an additional frozen-probe fixture regression. Focused Ruff/diff checks
passed. GUI, worker/controller, cancellation and parent-death checks passed.
The uncancelled cache probe reused three saved mesh checks and rejected an invalid
added mesh before preparation or engine execution, in about 1.1 seconds.

The first qualification stopped because its new warm-cache test fixture had only
one subject. Test-only commit `b8d0cece6b2052589e384635310e07fecbafe268` supplies the
required second subject and a regression. The exact diff contains only the
external smoke script and its test; all application/spec/schema/package sources
are unchanged. The original bundle was retained and its remaining qualification
continued. Freeze evidence truthfully retains runtime commit `3e4b5cc`; installer
observation separately records test/observer commit `b8d0cec`. The original failed
observation and successful continuation are retained privately.

The bundle has 2,830 inventoried runtime files (948,208,284 bytes), plus the two
freeze-evidence files. Dependency metadata, deterministic CycloneDX SBOM and all
six evidence companions verified. The engineering-only installer was compiled
and independently verified; it has not been executed or publicly distributed.

Installer: `DiffeoForge-v120-Windows-CPU-x86_64-Setup.exe`, 359,277,307 bytes.
SHA256: `e17db06391306a87b46e52a7eed9822232e092a6cb8d59c9a2cc51c80ef42b6a`.
Installer-build evidence SHA256:
`325a09996def755c49d45319531f6daf6cd29e795450edc86fcb0255b5906f5c`.

The owner app and atlas backend remain active. Installation is deferred under
the standing idle/backup rule; installed runtime remains dev119. No owner run was
started, stopped or altered by development, and no scientific acceptance is
claimed. The change accelerates engineering preparation only; it does not change
fitting parameters, checkpoints, anatomical QC or existing results. Drive remains
v98 because no upload was requested. Source, frozen runtime, local installation
and Drive distribution must continue to be tracked separately.
