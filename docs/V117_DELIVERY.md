# v117 build and installation status

The [recovered-result import fix](V117_EXPORT_ONLY_RESULT_IMPORT.md) is built,
verified and installed locally as `0.0.0.dev117`. The final runtime and frozen
installer bind commit `ad5b545e8705348d0f38b16fe649bb54bf806cf3`; the initial
implementation is `d9b3d95`. Build 01 was superseded before delivery; build 02 is
the verified installed package. This package also includes the v116 live optimizer
and checkpoint-continuation features, which had not been installed separately.

Verification passed 112 scoped regressions and overlapping metric/snapshot/recovery
follow-up checks, Ruff/format/diff checks, frozen GUI and worker checks, and a real
Deformetrica 4.3 two-subject export-recovery import. The retained full-cohort result
also opened through the normal review route: all specimen QC pairs were available,
the original native tolerance stop was retained, critical source files were
unchanged and no optimizer iterations were added. Anatomical approval is separate.

The frozen inventory contains 2,830 files and 948,100,459 bytes. The final setup
has 359,180,330 bytes and SHA-256:
`4338f98cd68e7cc3e1f43033d59495c711f5ed838a2d06dc2af3fd19ef39f598`.
Verified installer-build evidence has SHA-256:
`8e5bec6d4d6794525661ba068246a342c9198e79460a213a7ff6c0eb7dfcae7b`.

A complete prior-application backup was hash-verified before installation, and
fresh application/backend idle checks passed. Setup exited successfully. All
2,832 installed bundle files, including the retained inventory files, match the
build; all six companion evidence files match. The registry reports dev117 and
the installed offscreen startup check exited successfully. Recorded critical
research-result files remained unchanged. No real-data job was started.

The full-cohort import took approximately 14.5 minutes because it verifies the
large output inventory and computes geometric QC. Each reopening verifies again;
this delivery does not implement a persistent QC cache. The retained original
run must remain available for source-bound recovery analysis. Owner first-use
review, scientific validation and public-release gates remain open.

GitHub and the existing Project log receive this scoped change. No installer
upload was requested; the last verified Drive distribution remains v98. No
public release, tag, merge or scientific approval is implied. Documentation-only
delivery updates do not change the installed runtime commit or require a rebuild.
