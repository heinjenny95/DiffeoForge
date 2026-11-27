# macOS v197 colleague packages

The Mac application baseline is `6efc9725691416ea75e44df0bb07e6255611c5b8`, the verified Windows v197
application source. The package source `51ae08d387d3989a9d1e094403de3a520d2b79d3` changes only packaging.
The development branch contains additional changes outside that exact application
baseline. Rebuild or independently check these images by dispatching
`windows-freeze-evidence.yml` on `codex/macos-v197-delivery` with
`target=macos` or `target=macos-verify`. The independent job selects the
candidate from the exact build SHA.

- [Native package builds](https://github.com/heinjenny95/DiffeoForge/actions/runs/42772208095)
- [Intel independent installation checks](https://github.com/heinjenny95/DiffeoForge/actions/runs/42777317252)
- [Apple Silicon independent installation checks](https://github.com/heinjenny95/DiffeoForge/actions/runs/42779480242)
- [Colleague-test prerelease](https://github.com/heinjenny95/DiffeoForge/releases/tag/v197-macos-test)

Both builds passed 64 focused software checks. Two optional Modern-engine
tests were skipped on each architecture. Fresh macOS 15 and 26 runners
mounted and installed the exact downloaded images, launched the native GUI,
exported media, ran Current and Varifold examples, continued a checkpoint and
checked cancellation before preparation and after native progress. Both
architectures preserved the signed application bytes during these checks.

| Package | macOS checked | Colleague ZIP SHA-256 |
| --- | --- | --- |
| Intel | 15.7.9, 26.6.1 | `477c25698cc3a36f2c634293c1eb0d841a566664078a1f8755ed1d12b8a68c2a` |
| Apple Silicon | 15.8.2, 26.7.2 | `a232d55f3562b968f7dbe4886fa60e48179bf8969273c5a20ac5904f23c040e4` |

The Deformetrica 4.3 reference runtime is CPU-only. Apple Silicon uses Rosetta
for the reference runtime and a native ARM desktop. The first KeOps build
needs Apple Command Line Tools. The images are ad-hoc signed and lack Apple
notarization. Colleague first use and scientific acceptance are separate
from these automated checks.
