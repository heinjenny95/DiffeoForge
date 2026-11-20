# ADR 0008: Installer-managed Deformetrica reference runtime on Windows

- Status: accepted
- Date: 2026-07-20

## Context

Requiring a researcher to install Docker, assemble an obsolete Python stack,
edit XML, or understand WSL defeats DiffeoForge's primary accessibility goal.
The numerical reference backend nevertheless requires Deformetrica 4.3.0 and
its legacy Linux dependencies. Docker Desktop also introduces a separate user
interface, service, and license boundary that is unnecessary for ordinary
Windows execution.

Deformetrica 4.3.0 is not open-source software. Its installed `LICENSE.txt`
identifies the INRIA Non-Commercial License: use is restricted to educational,
research, or evaluation purposes, redistribution must retain the same terms,
and publications using it must provide appropriate credit. DiffeoForge's own
source license cannot replace or broaden those terms.

## Decision

The normal Windows installer owns a uniquely named WSL2 distribution:
`DiffeoForge-Reference-4.3`. The configured executable is fixed at
`/opt/diffeoforge/reference/bin/deformetrica`. The installer imports a
versioned, hash-verified runtime payload, retains its complete third-party
license inventory, and verifies Deformetrica 4.3.0 before the application is
declared ready.

The desktop application selects launchers in this order:

1. the verified DiffeoForge-managed distribution;
2. for same-owner alpha migration only, an already installed and independently
   verified Deformetrica 4.3.0 environment, used read-only; or
3. the stable managed-runtime identity in a repair-required state.

Docker remains a developer, CI, and reproducibility-validation launcher. It is
not a normal end-user prerequisite. Modern-only controls are absent from the
Deformetrica parameter surface and internal approval/hash evidence is not an
end-user prerequisite.

The application and the reference runtime stay separate components. The
DiffeoForge source repository remains under its open-source license. Any
installer containing Deformetrica must display and ship the INRIA
Non-Commercial License, describe the noncommercial restriction, preserve all
required third-party notices, and must not be presented as an entirely
open-source or commercially unrestricted bundle.

## Integrity and ownership rules

- the distribution name and installation location are DiffeoForge-specific;
- no pre-existing user distribution is overwritten, upgraded, or unregistered;
- the runtime archive and manifest are SHA-256 verified before import;
- the manifest binds the Deformetrica version, executable, dependency lock,
  source provenance, license inventory, and archive digest;
- project data never live inside the managed distribution;
- uninstall and repair behavior must distinguish application files, the managed
  runtime, and researcher-owned project directories;
- a missing WSL Windows feature may require one Windows elevation prompt and a
  reboot, but never manual Docker, Python, terminal, or XML setup.

## Consequences

The user experience becomes a single guided installation and a folder-driven
workflow. Runtime isolation is reproducible without Docker Desktop. The cost is
a larger installer, Windows-specific lifecycle engineering, third-party license
inventory work, and testing of install, repair, upgrade, reboot, and uninstall
paths. Public distribution remains blocked until the complete dependency
license inventory and installer behavior have been independently reviewed.

