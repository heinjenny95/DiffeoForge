# Reference single-fit performance qualification

The reduced live view is a display proxy. It does not replace scientific fitting
geometry. A local correction may still include the complete original-surface
attachment, a focus patch, preserved material and repeated deformation integration.
The actual prepared contract determines its time grid and effort; a generic recipe
does not describe every saved run.

Deformetrica 4.3's legacy `GpuMode.KERNEL` keeps model tensors on the CPU while
KeOps reductions can run on the GPU with host arrays. The model XML's
`kernel-device=cpu` therefore does not establish CPU-only computation. The native
target-self attachment norm and target triangle centres/normals are already
cached. After that first self term, complete source-self and source-target
reductions remain in every attachment evaluation. Avoiding a dense pair matrix
does not remove the underlying pair interactions.

## Offline measurements

`tools/probe_reference_target_preparation.py` uses generated public octahedra,
one CPU thread and the actual native RK2 flow, varifold attachment and backward
pass. It compares four identical bounded gradient steps and hashes their fields,
endpoints and gradients. It also separates integration, attachment/regularity and
backward time. Its optional KeOps route explicitly selects CPU operations and an
isolated compilation cache. This tool is never imported by scientific dispatch.

An isolated target-area/unit-normal cache saves the remaining fixed target
normalisation work in a microbenchmark. In the tested native Torch CPU flow,
however, exact gradient-path identity did not pass: gradient differences reached
approximately `1.33e-15`, while endpoint differences were approximately
`2.17e-19`. These tiny differences do not demonstrate worse anatomical fitting;
they do fail the stricter exact-reuse requirement. The cache is consequently
**not enabled in production**. Target-only microbenchmark timings must not be
reported as complete-fit acceleration. The attempted additional native KeOps CPU
probe encountered a host-compiler qualification failure and does not provide a
KeOps result.

## Scientific multiresolution feasibility

`tools/probe_reference_multiresolution.py` performs a separate actual SciPy
L-BFGS-B experiment using native Deformetrica RK2 flow, attachment and gradients.
It compares full-only fitting against explicit coarse-to-full fitting on generated
nested sphere meshes. A narrow known projection has doses zero, 0.10 and 0.20.
The same frozen controls, zero initial momenta, five timepoints, Float64, kernel
widths, noise, tolerance and eight-iteration total allowance apply to both arms.
The full arm gets eight iterations; the candidate gets four coarse then four
full iterations, with an explicitly restarted optimizer history at the transition.

Both arms finish on the complete material grid. Measurements include total wall
time, working-geometry preparation, integration, attachment, backward, objective
evaluation counts during line search, final full-material flow and QC. QC uses
512 deterministic area samples in each direction with exact point-to-triangle
queries on the complete surfaces, plus known material-coordinate and projection
errors. These synthetic checks are separate from the normal scientific QC and
independent anatomical review. A capped optimizer remains capped.

The 512/128-triangle, 66-control CPU comparison rejected the shortcut. At nonzero
doses, observed complete-arm times were approximately 0.295/0.267 seconds for the
full route and 0.218/0.200 seconds for coarse-to-full. But local projection errors
increased from 0.0363/0.0680 to 0.0418/0.0801, and surface-distance tails worsened.
Material-coordinate RMS improved, so that one summary alone would have hidden
the lost local signal. The unchanged control passed the declared synthetic gate.
The smaller 128/32-triangle feasibility comparison also rejected the candidate.
These short CPU timings are not a speed prediction for skulls or GPU execution.

`prepare_resolution_comparison` records the protocol for future separately copied
real surfaces: original and candidate hashes, the common initial control/momentum
field and the entire unchanged numerical contract. It requires complete-original
evaluation, fine-structure and preservation checks, and independent anatomical
review. Preparing a contract starts nothing and qualifies nothing.

For a bounded replay on a copied regional fit, keep the same verified starting
field, full focus and preservation objects, controls, time grid, precision and
optimizer tolerance in both arms. Count accepted updates and objective/gradient
evaluations separately, including the extra evaluations after restarting on the
full mesh. Time integration, attachment and backward calculation within each
evaluation, and record geometry preparation and final surface checks separately.
Re-evaluating the same field can test reproducibility, but only repeated calls
at the *same* field in a real optimization represent possible result-cache hits.

A short paired GPU replay tests where time goes and how early changes affect
the marked material. Prospective long-run comparisons and independent review of
fine anatomy are still required before enabling a different fitting resolution.
Schedule a local benchmark for a time when the owner's GPU is idle.
