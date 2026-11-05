# macOS v193 colleague test packaging

## Verified colleague packages — 5 November 2026

Both native package builds passed at source
`73efd0e9482350877bada9c1feb968bde9ae9e17`
([build evidence](https://github.com/heinjenny95/DiffeoForge/actions/runs/42000032958)).
The application-source baseline remains v193/`54fb9ff`. Each Mac build passed
49 pilot/dialog/worker software cases; two optional Modern-engine cases were
skipped because that engine is outside these packages. Nine local packaging
entrypoint/request-boundary cases also passed.

The exact downloaded DMGs then passed independent installation and computation
on four fresh runners
([qualification](https://github.com/heinjenny95/DiffeoForge/actions/runs/42008396497),
verification source `e58b46c676548e58ddda19dd102fae295cd770fb`). The checked
families are macOS15 and macOS26, each on Intel and Apple Silicon. Fresh user
homes and absent build prefixes excluded prior KeOps caches. Checks covered
Cocoa startup, media export, actual frozen execution, Current/Varifold output,
checkpoint continuation from cap2 to302 without changing its source, queued
cancellation and an interrupted live calculation. Live cancellation took
0.397–0.570 seconds on these public fixtures; this is not a general latency
guarantee. Installed file inventories and ad-hoc signatures remained unchanged.

| DMG | Bytes | SHA-256 |
| --- | ---: | --- |
| Intel | 912663508 | `8494a46780d2916446d25b36f80e3546b569a213e3d0741c4a47cc478920f9a1` |
| Apple Silicon | 919632222 | `dc8b8aca8b86f5ab42668bd89a0605c6e0263bb5acf7b2583ed135d51fe6174b` |

Both DMGs were downloaded and hash-verified locally. Their two temporary
installer artifacts were deleted through the exact artifact IDs after local
retrieval and independent qualification. Public test receipts remain separate.
Colleague ZIPs retain the image, hashes, exact platform observations, instructions
and upstream source/license notices. The initial local delivery did not create
a release or tag, merge code or upload to Drive. Physical colleague first use
and scientific dataset acceptance remain open.
The owner's Windows installation and active scientific work were not changed.

## Owner-requested GitHub distribution

The owner subsequently requested repository-based download links. The complete
packages are available in the
[v193 macOS test prerelease](https://github.com/heinjenny95/DiffeoForge/releases/tag/v193-macos-test).
Its tag points to the actual build source `73efd0e`, and its five assets contain
the two complete colleague ZIPs, their checksum sidecars and the installation
guide. All assets were staged as a draft and matched GitHub's server-side
SHA-256 digests before publication. Anonymous downloads of both published ZIPs
returned the correct archive header and expected full size.

This is an explicitly requested development prerelease, not a general stable
release or a new scientific approval. Binaries are release assets rather than
Git source-history entries. No existing package was replaced, no main-branch
merge occurred, and no Drive upload completed. The application version and
the owner's installed runtime remain unchanged.

## Application and runtime scope

The requested targets are native Apple-Silicon and Intel desktop bundles using
the unchanged v193 application source baseline
`54fb9ffc454f3f19a10943aeac25203037f22e32`. Packaging and platform-launcher work
does not create a new optimizer or a new application feature version. The build
refuses changes to that baseline's application sources or project metadata.

The isolated reference environment uses CPython 3.8.20, Deformetrica 4.3.0,
Torch 1.6.0 and PyKeOps 1.4.1 Intel binaries. Apple Silicon executes this
reference environment through Rosetta 2 while keeping its GUI/workers native.
The optional Modern engine and GPU/MPS execution are outside these packages.
An external system Python is unnecessary. The current target is macOS15+.
Rosetta is a compatibility route rather than a permanent native-ARM backend:
[Apple's September2026 guidance](https://support.apple.com/en-us/102527) limits
general Rosetta support to macOS27 or earlier. macOS28 is outside this package's
reference-runtime support; a future native-ARM reference environment needs its
own numerical qualification. Current advertised tests are the observed macOS
runner versions, not an assumption about future releases.

## Compatibility boundary

The reference interpreter comes from a SHA-256-pinned standalone CPython
archive. Native package installation records resolved URLs and hashes. Relative
launcher wrappers select the packaged CMake and explicit x86_64 compiler target.
The legacy KeOps plaintext `version` metadata file shadows modern libc++'s
`<version>` header. Renaming that metadata and its Python read path avoids the
collision; all KeOps mathematical source bytes are checked unchanged. No
deformation equation, tolerance, integration grid or optimization cap changes.

KeOps compiles formula-specific CPU kernels on first use, requiring Apple's
Command Line Tools. A user's subsequent computations reuse their cache. This
setup time is distinct from fit progress. The app must resolve its reference
environment after installation to a different path, and computation must leave
signed application files unchanged.

## Engineering gates

The manual packaging workflow checks the relevant pilot/dialog/worker software
paths, actual native Torch/KeOps computation on the public CC0 cohort, the
frozen execution-worker protocol, Current/Varifold full output, a checkpoint
successor with additional cumulative iterations, queued cancellation, Cocoa
startup and media export. It checks ad-hoc signatures, creates/verifies a DMG,
mounts it, copies the app out and starts that copied app.

An independent second workflow downloads the exact candidate and repeats the
installation/computation checks on a fresh Mac runner. Its fresh user home
excludes build-prefix paths, old preferences and compiled KeOps caches. The
package's exact hashes and application inventory bind both observations.
Failure of any gate remains a failure; it does not authorize weaker tolerances.

This is development test packaging. Ad-hoc signing is not Developer-ID signing
or notarization, and automated native checks do not establish interactive first
use on the colleague's hardware, biological validity, general performance,
checkpoint portability across operating systems or a public scientific release.
Final package/independent-run outcomes must be recorded with their actual
workflow observations before describing a package as verified.

The owner authorized temporary GitHub Actions artifacts for these Mac v193
packages on 5 November2026, followed by local download, hash verification and
artifact deletion. This exception does not authorize releases, tags, merges,
research-data uploads or future installer uploads. Source/scripts and public
engineering evidence remain separate from local installer delivery.
