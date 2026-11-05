# macOS v193 colleague test packaging

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
