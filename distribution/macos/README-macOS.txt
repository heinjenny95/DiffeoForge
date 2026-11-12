DiffeoForge v200 - macOS colleague test build

Requires macOS 15 or newer. Choose AppleSilicon for M-series Macs or Intel for Intel Macs. These packages
contain the v200 application code, supervised workers and an isolated Deformetrica
4.3.0 / Python 3.8 / Torch 1.6 CPU environment. On Apple Silicon the reference
environment uses Rosetta 2. The application interface itself uses the selected
native architecture. GPU/MPS and the optional Modern engine are not included.
The Rosetta 2 reference runtime on Apple Silicon is supported through macOS 27.

INSTALL
1. Open the DMG and drag DiffeoForge.app to Applications.
2. Launch the installed application, not the copy in the DMG.
3. These colleague test builds are ad-hoc signed, not Apple-notarized. If macOS
   blocks the first launch, use System Settings > Privacy & Security > Open Anyway
   for this verified application. Do not disable Gatekeeper globally.
4. Apple Silicon requires Apple's Rosetta 2. If not already installed, macOS
   normally offers its installation when the Intel reference interpreter starts.
5. The KeOps CPU backend needs Apple's Command Line Tools (clang compiler). If
   absent, install them with `xcode-select --install`, then reopen DiffeoForge.

FIRST CHECK
The mounted DMG includes the public CC0 synthetic meshes and an example config.
Copy the entire Example folder into Documents before using it. Do not save a
project inside the DMG or inside DiffeoForge.app. The native reference executable
is selected from the application's isolated environment; no system Python or
pip installation is needed. The example is a software check, not anatomy approval.
The first KeOps computation compiles formula-specific CPU kernels and can take
several minutes. Later runs reuse the local cache. This one-time setup is separate
from optimization iterations; detailed compiler messages remain in the run log.

Keep Windows projects unchanged while testing a copy on Mac. Existing native
checkpoints are tied to their original runtime and platform; do not move a Windows
or Linux checkpoint into this Mac runtime and expect a compatible continuation.

SCOPE
Automated Mac build/execution evidence accompanies the package. Interactive first
use on the colleague's own hardware remains the next check. Please record the Mac
chip, macOS version, exact error and diagnostic log if anything fails. CPU runs may
be slower than an NVIDIA-accelerated Windows run. Numerical completion and anatomy
approval remain separate.

The archive includes package hashes, source/build identity and third-party notices.
This package is intended for colleague testing.
