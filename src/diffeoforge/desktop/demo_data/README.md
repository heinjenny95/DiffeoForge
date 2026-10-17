# Offline presentation fixture

Prepared by `tools/prepare_demo_assets.py` without running an optimizer. The
198647-byte JSON contains selected public `examples/synthetic` surfaces and
`reference/synthetic-v1` native endpoint/convergence/residual artifacts. Its SHA256
is checked on opening. Source file names and hashes are embedded in the payload.
Meshes and reference artifacts are CC0-1.0 (see LICENSE.md). Software and the
public landmark table are covered by the project's MIT license (see
SOFTWARE-LICENSE.txt).

Recorded native results: Deformetrica 4.3.0 CPU float32, five synthetic subjects,
36 control points, tolerance at iteration 22. This is an engineering fixture,
with no biological meaning and no relationship to any private running atlas.

Cartesian momenta PCA and template-landmark similarity alignment are prepared
offline. Alignment is not an iterative GPA result. Playback speed is arbitrary.
Pilot stages and metadata groups are explanatory; endpoint blends are display
interpolation, not native Shooting, PC deformations or retained flow trajectories.
The fixture is not a loadable production project, QC journal or result bundle.
