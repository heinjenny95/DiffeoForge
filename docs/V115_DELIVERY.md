# v115 local build and installation evidence

Runtime source: `84756be8411ed7fd1ad78d15ef67d05e822a804f` on the established
development branch. Installed version: `0.0.0.dev115`. This delivery note is a
later documentation-only commit and does not change the frozen runtime.

The [checkpoint scheduling correction](V115_COMPACT_REFERENCE_CHECKPOINTS.md)
passed 92 scoped regressions, Ruff and diff checks. A real reference-runtime
synthetic comparison produced exactly equal learned arrays and byte-identical
final VTKs under native and compact schedules; native state restoration also
passed. A stopped owner checkpoint and desktop resume request were verified,
and a separate successor was prepared without executing a private fit.

Frozen GUI and worker executables passed startup, preparation-only, cancellation
and limited pre-request parent-death checks. Dependency metadata, SBOM and
installer evidence passed. These are scoped engineering checks, not a complete
test-suite or scientific-acceptance claim.

The full prior installation was backed up and hash-verified across 2,840 files.
Fresh native/backend idle checks preceded backup and installation. Setup and
installed startup exited zero. All 2,831 installed bundle files and six companion
evidence files match the verified build; all 10,185 recorded owner run files
remain unchanged. No user process was stopped and no private atlas was started.

The owner can use **Resume interrupted run…** to continue the verified checkpoint
in an immutable successor with compact checkpoints. Scientific parameters remain
unchanged. Native Deformetrica reinitializes gradient and line-search state on
resume, so an identical optimizer trajectory is not promised. Final trajectory
export still runs once and can be expensive; convergence, anatomical QC and
scientific acceptance remain open. The v114 desktop responsiveness fix is included.

- Installer: 359,048,248 bytes; SHA-256
  `e985c9a0ae0228ed2f488890705c8f8aea8adab68a988d38e99094c15e3a2fe3`.
- Installed GUI SHA-256:
  `04501d89c9dbf620392d1b25c84354c60b2cf62ce9edac573ab579cc2873fbd6`.
- Installer evidence SHA-256:
  `19850c0a56b70e59c89a221f530850c7a69848a0fe6d246f64808c7f1053f7b2`.

Detailed receipts and private project destinations remain outside GitHub.
The existing Project log receives the scoped update. No Drive upload was
requested; the last verified distributed version remains v98. No public release,
tag, merge or scientific approval is implied.
