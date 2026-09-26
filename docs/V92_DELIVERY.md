# v92 pilot appearance correction and delivery

Verified on 2026-09-26. Making the pilot window independent in v91 removed its
inherited main-window stylesheet. v92 explicitly applies that existing stylesheet
before showing the window, restoring the former typography, cards and green
buttons while retaining modeless operation and minimization. The scientific
workflow and parameters are unchanged by this appearance fix.

- Version: **0.0.0.dev92**.
- Runtime source: `34dd5504d225d2af65b69752f9bbd14ba95586f5`.
- Installer: `DiffeoForge-v92-Windows-CPU-x86_64-Setup.exe`.
- Size: **323,247,343 bytes**.
- SHA-256: `7ed3a56e0d5fa2d61fdeafbed3b8e320b7e1af9d79af420531b64596295b4780`.
- Build-evidence SHA-256:
  `155003f9a8df3076db2f5d5e24412d1b9ab718c535de7600c677709ff93b9ae7`.

Nine focused regressions passed, including the production pilot-opening route,
rendered title/button style, minimization, dialog review and reopen behavior.
Ruff, diff checks and a synthetic visual comparison passed. The regression test
does not apply an application-wide theme, which would mask the lost inheritance.
Frozen GUI/worker smoke checks, cancellation/parent-death harnesses, the 2,677-file
bundle inventory, dependency/SBOM checks and installer verification passed.
This is not a fresh full-suite or cross-application focus acceptance claim.

The established Drive channel contains a complete four-part binary installer,
join script and README. All six files were downloaded with authentication and
anonymously; exact sizes and SHA-256 hashes matched. Both downloaded join scripts
reconstructed the exact installer above. Only then was the existing current
README updated in place and read back through both routes. Existing sharing and
file identity were preserved; the complete prior v91 package remains recoverable.
The installer remains unsigned and no GitHub Release or tag was created.

**Installation is pending:** the owner's installed runtime remains v91 because
an active pilot and execution worker were observed. The standing authorization
to install tested updates applies, but does not authorize interrupting a running
computation to update. No app or backend was closed, no study was rewritten, and
no scientific calculation was started by this change. Source/documentation HEAD
and the packaged runtime commit remain distinct. Install after a fresh idle check,
verified backup and preservation of ongoing/unsaved work.

A separate usability gap was identified: opening a completed result does not
replace the current setup inputs. The roadmap tracks clearer project context and
prevention of unintended cross-project pilot starts; v92 does not claim that fix.
