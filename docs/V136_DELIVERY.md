# v136 local delivery verification

The tested private Windows build is installed as **0.0.0.dev136**. It includes
the earlier uninstalled v133–v135 changes and the finer saved-evaluation workflow.
84 scoped cases pass across the broad regression and corrected fixture/UI-contract
reruns; all 10 adoption cases pass on the final runtime. Source, exact frozen and
installed three-state UI probes verify explicit reuse, fresh evaluated QC and
the alternative to an unstarted queued refit. Fixture bytes and QC stay unchanged.

Runtime source `8e0893b90767b6db3d560d54e64012a2c77b46a0` and packaging/observer
source `b96e6a23fc6a397e62c3de4e79260caf6f9a8011` have byte-identical runtime and
build inputs. Only tests and documentation changed between them. The original
observer correctly refused the older Git identifier; installer observation then
used the exact clean current source with an explicit equivalence record. The
verified bundle was preserved, without an identical runtime rebuild.

- Five executables, startup, supervised worker/preparation checks, dependency
  evidence and SBOM pass. Core bundle: 3,461 files, 1,391,186,875 bytes; the two
  root freeze-evidence files are additional self-describing receipts.
- Setup: 458,222,393 bytes; SHA-256
  `f392fcbd2304977e73c50a7f9bb1816ee3847435b84267e41a402b032cfa5ccc`.
- GUI SHA-256:
  `cfbde6b0d3fe70a8a6c445a0b094ae47b82f5009f05c20f73a353b459122fe92`.
  Product PYZ SHA-256:
  `bdf36b1d4e3f4131b5bc019cd302c2b0c0497e138b61a8869f4d5d30e9b267f3`.
- Fresh closed/idle checks and verified recoverable application/project-state
  backups preceded installation. Every installed bundle file and all six
  companions match; registry version and startup smoke pass. Preserved project
  and completed-run metadata remain unchanged.
- Installed product PYZ, runtime and four workers match the exact frozen probe.
  Ordinary Windows-shell/service ancestry and survival after the tool launcher
  exited are verified. No scientific computation was dispatched by these checks.

Native study evaluation, human anatomy approval and independent first use remain
separate. Installation does not finish or approve a pilot and does not start an
atlas. No installer upload, tag, release, merge or public research-data delivery
was requested or performed; the separately distributed v98 package is unchanged.
