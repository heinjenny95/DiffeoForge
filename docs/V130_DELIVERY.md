# v130 verified Windows build

The v130 process recorder is implemented and the Windows CPU installer is built
and verified from runtime source `cb114b9299745af880e1a9082f315cdc3604c1d2`.
The existing local installation is still dev129: the owner’s application window
must be closed normally before backup and installation. No running application
or scientific computation was interrupted to replace it.

## Verification

- 154 regression checks passed, with one expected skip. The final recording and
  version subset passed all 16 checks. Native video tests now explicitly skip
  when optional desktop video dependencies are absent; an analysis-only
  simulation passed one base check and skipped both video modules.
- The full five-executable frozen bundle passed desktop, synthetic worker,
  nonnumerical reference startup, preparation and parent-death boundary checks.
  All 3,461 payload files were inventoried; dependency metadata, six evidence
  companions and the CycloneDX SBOM were verified.
- A private engineering entry point used the exact product PYZ archive and
  actual bundled runtime, rather than a second analysis of source. It captured
  the public 178,800-face mesh fixture, including moving views and completed
  original detail, at 1920×1080. Automatic computation export and follow-up
  recording produced 66 decoded frames, 40 distinct frames, with no dropped
  samples or capture gaps. Native Qt MP4 playback passed. The original mesh
  object and input hash were preserved.
- The frozen probe observed capture median 3.79 ms / maximum 6.36 ms and active
  GUI heartbeat p95 24.96 ms / maximum 34.98 ms. These are short engineering
  observations, not a long-session or scientific performance qualification.

The installer compiler exited zero. Verified setup SHA-256:
`89abd315da746e552517a0998f9db93a7e234fe1f321bcfea80c14fbf6612588`.
Frozen application SHA-256:
`0455355216c36a4d735e1305f854263ce74a9adcf7df18fe12d8d2b3f77445ea`.
Product PYZ SHA-256:
`f50d6ba1ba483e4b2d9ec8690caba08a979e6e67ccce8ed8f30d0add7e659f5a`.

## Remaining delivery and scope

Installation is pending the ordinary owner close, a complete verified dev129
backup and fresh application/backend idle checks. Installed payload, companions,
recording/playback and normal shell startup must then be verified separately.
The saved recording opt-in is not enabled by engineering tests.

The last distributed installer is unchanged; no installer upload was requested.
No scientific run, anatomical approval, private PCA, remote deployment or
public release occurred. Demo removal remains backlog. Independent first-use
and a long real-study recording remain open. See
[operation and limits](V130_PROCESS_RECORDING.md).
