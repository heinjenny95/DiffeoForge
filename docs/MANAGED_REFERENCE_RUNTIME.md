# Managed Deformetrica reference runtime

Status: **implemented launcher selection and verification; bundled runtime
payload and public redistribution remain release gates**

## End-user contract

The supported Windows product must require no separate Docker, Python, Conda,
Deformetrica, XML, or command-line installation. DiffeoForge owns the complete
reference-runtime lifecycle and exposes only these user states:

- **Ready** — the exact Deformetrica 4.3.0 runtime is verified;
- **Repair required** — the managed runtime or WSL prerequisite is missing or
  differs; or
- **Restart required** — Windows must complete first-time WSL activation.

The stable managed launcher is:

```yaml
launcher:
  type: wsl
  distribution: DiffeoForge-Reference-4.3
  executable: /opt/diffeoforge/reference/bin/deformetrica
```

The desktop binds that complete launcher mapping to the reviewed configuration
hash and re-verifies its version in the execution worker immediately before
preparation. Docker configurations remain valid for developers and CI, but the
desktop no longer generates them for ordinary Windows projects.

## Same-owner alpha migration

Before a managed payload is installed, the private alpha may discover an
executable at `/home/<user>/deformetrica/bin/deformetrica` in an existing WSL
distribution. It accepts that launcher only after `--help` identifies exact
version 4.3.0. Discovery performs no writes and never changes the distribution.
New public installations must use the separately named managed distribution.

## Runtime payload release gates

A publishable payload needs all of the following:

1. a minimal WSL2 root filesystem built from pinned upstream artifacts;
2. a locked CPU dependency environment and reproducible build recipe;
3. an internal manifest binding every artifact and SHA-256;
4. exact Deformetrica 4.3.0 invocation and synthetic-atlas validation;
5. complete source, binary, and third-party license notices;
6. explicit presentation of the INRIA Non-Commercial License during install;
7. install, repair, upgrade, restart, and uninstall tests on clean Windows
   machines; and
8. an independent legal/license review before public redistribution.

The installed Deformetrica license permits only educational, research, or
evaluation use and requires redistribution under the same terms. DiffeoForge's
open-source license applies only to DiffeoForge code and does not broaden the
reference engine's permissions.

