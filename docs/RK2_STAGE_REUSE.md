# RK2 first-stage reuse

Status: **exact duplicate-evaluation removal in Modern engine implementation 0.3**

The Hamiltonian RK2 shooting step needs two stages. Each stage evaluates one
Gaussian convolution for control-point velocity and one analytical Gaussian
x-gradient for momenta velocity.

Implementation 0.2 evaluated the first pair in `shoot`, then called an RK2
helper that evaluated the same first pair again before computing the midpoint
pair. The first results were discarded. Implementation 0.3 passes the already
computed first-stage tensors into the helper:

```text
per RK2 step before: 3 convolutions + 3 x-gradients = 6 Gaussian calls
per RK2 step now:    2 convolutions + 2 x-gradients = 4 Gaussian calls
```

For `S` subjects and `T-1` shooting steps, one atlas-objective evaluation now
avoids `2 * S * (T-1)` duplicate control-point all-pairs operations. This does
not reduce the Current/Varifold surface attachment or template-flow work, which
normally dominates high-face-count runs.

Tests require bit-identical complete control-point and momenta trajectories
against the established helper path, retain the Deformetrica 4.3 primitive
golden-value checks, exercise differentiability, instrument exactly four calls
per RK2 step, and cross-check the configured workload model against a real
objective forward for every supported shooting/flow/attachment combination.

This is exact implementation evidence, not a wall-time, convergence,
biological-validity, or production-scaling claim. Existing runs preserve their
recorded implementation revision; only newly started processes use 0.3.
