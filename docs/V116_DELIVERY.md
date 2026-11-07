# v116 build and installation status

The [live optimizer and continuation change](V116_LIVE_OPTIMIZER_AND_CONTINUATION.md)
is built and verified as dev116 on the established development branch. The final
runtime and frozen installer bind commit
`4bd948bfab8eda0bcc05adfdf7d54c19a99ca135`; implementation began in `ad29244`.
The earlier build was superseded before installation by the QC-footer shortcut.

Verification passed 171 scoped regressions (one dependency-presence skip), with
129 overlapping follow-up UI/registration checks (one skip), Ruff/diff checks,
Qt visual inspection and real Deformetrica 4.3 synthetic checkpoint continuation.
Frozen GUI startup and preparation/execution workers, cancellation and retained
dependency/SBOM bindings passed. The final bundle inventories 2,830 files and
948,052,434 bytes. The SBOM composition remains incomplete; these scoped checks
do not establish full scientific or public-release acceptance.

The final setup has 359,131,322 bytes and SHA-256:
`346373ba640220c5dbf92a6ed61f87674fa128a08b6900d974dd24282cfa9a07`.
Retained installer-build evidence is hash-bound and verified separately:
`c1cd4c8d51555f7a4b8bf82db814d09ff2ff8a9099787a70bcd30ca6c5271b2e`.

The owner application and full-atlas backend remain active. **v116 has not been
installed**; installed dev115 remains unchanged. Do not interrupt that calculation.
After the app and backend are idle, installation still requires a verified prior
backup and installed startup/file verification. No scheduled installation was set.
Native checkpoint continuation resets gradient/line-search state; convergence,
anatomical review and owner first-use acceptance remain open.

GitHub and the existing Project log receive this scoped change. No installer
upload was requested; the last verified Drive distribution remains v98. No
public release, tag, merge or scientific approval is implied.
