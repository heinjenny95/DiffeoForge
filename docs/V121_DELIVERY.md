# v121 — Verified Windows build and local installation

Runtime commit `216ee0efcb14d0965692392a46fff13debab9304` was frozen as
`0.0.0.dev121`. The broad affected suite passed 245 regressions; 33 focused
protocol, resource-display and version checks also passed with overlapping scope.
Focused Ruff and diff checks passed. See [behavior and limits](V121_STORAGE_AND_ACTIVITY.md).

Frozen GUI/workers, synthetic worker/controller, uncancelled startup, cache reuse,
cancellation and hard-parent-death boundary probes passed. The immutable bundle
inventory contains 2,830 runtime files (948,284,013 bytes), plus two freeze-evidence
files. Dependency metadata, the deterministic 27-component SBOM and all six
companion evidence files verified. This is engineering verification, not a public
release or scientific acceptance.

Installer: `DiffeoForge-v121-Windows-CPU-x86_64-Setup.exe`, 359,360,091 bytes.
SHA-256: `b99964efb0cc82bdbdd32106c92c9078d40708753ee67ad11239dcd250962fa2`.

The tested build is installed locally after fresh application/backend idle checks
and a complete, hash-verified 2,841-file backup of the previous installation.
Setup, registry version, installed startup, all 2,832 bundle files and six
companions match. Five tracked completed-result files remain unchanged. The
independently deployed server computation was observed read-only and remains
isolated; no scientific job was started, stopped or altered by this development.

Source, frozen runtime and installed version remain separately recorded. Installer
distribution was not requested, so the existing Drive package is unchanged.
Native first-use acceptance and measured peak export storage remain separate from
these regression and packaging checks.
