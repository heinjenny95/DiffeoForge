# v118 build and installation status

The [pilot-preserving atlas and visual-QC changes](V118_PILOT_ATLAS_HANDOFF.md)
and [PC Shooting launch correction](V118_PC_SHOOTING_LAUNCH.md) are built,
verified and installed locally as `0.0.0.dev118`. Build 01 binds runtime commit
`a4f0a4ba84096de02e5e7499cf8043f39aaa8318`.

The broad final regression group passed 167 tests with one dependency-related
skip; an overlapping 136-test group covered PCA/QC. A final 48-test handoff/QC
group passed after moving approved-continuation preparation off the GUI thread.
Ruff and diff checks passed. Bounded native Deformetrica CPU checks exercised
five synthetic subjects, pilot-field preservation, early review and joint
continuation. An independent fixed-basis singleton fit matched the initialized
momentum row exactly. Native PC Shooting completed from a 295-character design
path with unchanged source evidence. Actual synthetic Qt overlays and navigation
were checked. These checks do not establish biological acceptance.

The frozen inventory contains 2,830 files and 948,206,638 bytes. The setup
contains 359,281,067 bytes with SHA-256:
`624b01d63481d25348657df05e4870cb51bc75153e378c2212b94c41dbfd51d0`.
Verified installer-build evidence has SHA-256:
`5d304cba22478967486a9c5e019bc0f1a8e175e6ad9e837afeaf6d0e5b1cdede`.

Frozen GUI/worker checks passed. A complete prior dev117 application backup was
hash-verified, and fresh application/backend idle checks passed before local
installation. Setup exited successfully. All 2,832 installed bundle files match
the build, and all six companion evidence files match. Registry version dev118
and installed startup exit zero were verified. Five tracked critical research
result files remained unchanged. No owner scientific run was started.

Existing atlas/PCA results are retained and are not retrospectively repaired.
The new initialization requires a separately prepared atlas, and may itself take
substantial time. It does not guarantee anatomy, convergence or runtime. Early
pilot review and final full-cohort QC remain separate requirements. Owner first-use
review, scientific validation and public-release gates remain open.

GitHub and the existing Project log receive the scoped change. No installer
upload was requested; Drive intentionally retains the last verified v98 package.
No public release, tag or merge is implied. Delivery-document updates do not
change the installed runtime commit or require another build.
