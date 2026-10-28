# DiffeoForge continuation and completion rules

Read `docs/DEVELOPMENT_CONTINUITY.md` and the relevant roadmap/acceptance documents
before continuing a transferred task. Inspect the current branch and dirty state;
preserve unrelated changes and private scientific work.

## Standing owner instruction

Owner priority (2026-10-28): the feature cutoff is **2026-11-15**. Focus on a
usable, reliable pilot and bounded waiting/cancellation. Clarify iteration effort
against observed fit quality before further feature expansion. Do not silently
raise iteration limits, relax accuracy or deploy an unqualified experimental
solver. After the cutoff, stabilize the agreed functionality rather than adding
new features. Existing scientific work and owner-paused side work stay preserved.
Owner clarification: the pilot should capture important projections and the
overall shape; small surface differences are acceptable. Offer first review after
about ten active optimization minutes, preserving the optimizer while waiting.

After every completed feature, fix, configuration or documentation change:

1. Commit and push only task-scoped code/tests/documentation to the established
   development branch (`codex/deformetrica-first-workflow`). Do not force-push,
   merge, tag or create a public release without separate authorization.
2. Proactively append a concise English entry to the existing DiffeoForge Google
   Docs **Project log** tab: change, verification, limitations/next step and commit
   link. Preserve the document's tabs, styles and existing content; verify readback.
3. Upload the tested installer to the owner's established Google Drive
   distribution folder only when explicitly requested. The owner's 2026-10-01
   instruction supersedes automatic distribution after every version; GitHub
   and Project log updates above remain mandatory. Resolve the exact private
   destination from the local project
   handoff, not by guessing. Preserve sharing and stable links where practical,
   stage a complete usable package, verify uploaded content and version, and keep
   a recoverable prior version. Do not announce a partial split archive as ready.
4. Verify all applicable destinations; disclose any pending/failed synchronization.
   Documentation-only changes do not require an identical installer rebuild or
   version bump. Drive may intentionally retain an older tested binary if no
   upload was requested; that does not block completion. Track the last verified
   distributed version separately and verify any requested update completely.

Source HEAD, installed executable and distributed installer are distinct states.
Updating one does not prove the others are current. Keep exact source/build/hash
provenance. This checklist is not permission to schedule background tasks.

Owner storage instruction (2026-10-25): when local space is low, completed,
inactive material may be archived to the owner's NAS. Prefer older packaging
working copies. Verify the intended destination is reachable, record restoration
paths and file checksums, and verify the copied bytes before removing a local
copy. Preserve active jobs, installed runtimes, current deliveries and scientific
input/field dependencies. If the NAS is unavailable, retain local files; do not
silently substitute a different network destination.
See [inactive build archiving](docs/BUILD_ARCHIVING.md) for the copy, verification
and restoration boundary.

Standing installation authorization (2026-09-26): an owner go-ahead to develop a
new DiffeoForge version includes installing the resulting tested version, without
another confirmation. Verify a recoverable backup and idle application/backends
first. Preserve unsaved work and never interrupt a scientific computation. This
supersedes earlier separate-confirmation requirements; it does not authorize
unrelated software installations or starting scientific runs.

## Scientific and operational boundaries

- This repository is public. Never commit private meshes, specimen-level results,
  checkpoints, logs, credentials, local paths or installer binaries. Keep detailed
  dataset/run handoffs in the private artifact workspace. Public method notes may
  describe generic implementation and verification without private study details.
- Do not mutate original inputs or completed evidence. Use explicitly scoped,
  separately identified successor runs/copies; record transformations and hashes.
- Landmarks support prealignment, not atlas attachment terms. Display proxies
  must not silently replace scientific geometry. Numerical completion, a pilot
  recommendation and anatomical/biological approval are distinct.
- Owner UI clarification (2026-10-27): matching settled display previews are
  sufficient for visual approval/rejection/comparison. Do not require or
  automatically load full-resolution meshes for approval; full detail is an
  explicit option. Preserve source identity, nonempty displayed layers,
  navigation settling and feedback provenance.
- Do not tune to match a published PC axis, silently exclude a difficult specimen,
  splice separately fitted momenta into an existing PCA, or manufacture QC approval.
- Before installation, verify no relevant pilot, atlas, validation or backend job
  is active. Do not close the app or replace runtimes during computation. Existing
  installation permission does not authorize stopping a scientific job.
- For owner-authorized persistent desktop computations, open the installed app
  through the ordinary Windows shell and use its normal execution/recovery UI.
  Do not keep the scientific GUI in an assistant-owned interpreter or transient
  tool process tree. Verify executable, creation time and shell ancestry before
  dispatch; a live process alone does not prove independence from a tool restart.
  Preserve the app's own worker supervision and explicit stopped-process recovery
  guards. Never test independence by interrupting a live scientific computation.
- Native/platform tests, independent first-use review, scientific validation and
  public-release gates remain separate from internal regression-test success.
