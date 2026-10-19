"""Concise control help. Full method descriptions remain in parameter_guidance."""

SHORT_HELP = {
    "recommendation_mode": (
        "Analyze aligned meshes first. Guided pilot requires visual review; Advanced makes the "
        "measured settings editable."
    ),
    "surface_detail": (
        "Fine matching notices smaller features but also surface noise. Coarse matching "
        "emphasizes the broad outline. This is separate from deformation reach."
    ),
    "deformation_scale": (
        "Local movement lets small regions change independently. Broad movement keeps larger "
        "neighborhoods together. This does not set matching resolution."
    ),
    "shape_disparity": (
        "Declare the size of biologically plausible differences. High disparity widens the "
        "search; it does not excuse invalid or anatomically poor fits."
    ),
    "attachment_ratio": (
        "Surface-matching width in mesh units. Smaller notices finer detail and noise; larger "
        "emphasizes broader form."
    ),
    "deformation_ratio": (
        "Deformation width in mesh units. Larger makes movement broader and smoother; smaller "
        "allows more local change."
    ),
    "control_spacing_ratio": (
        "Distance between control points. Smaller spacing adds flexibility, memory and "
        "computation; larger uses fewer points. New densities require a fit and review."
    ),
    "noise_ratio": (
        "Balances matching against regularization. Smaller noise demands a closer match; larger"
        " permits more residual mismatch. Inspect anatomy when comparing fits."
    ),
    "maximum_iterations": (
        "An upper limit, not predicted convergence. The native tolerance can stop earlier. A "
        "capped run can be continued explicitly with +300 iterations."
    ),
    "initial_step_size": (
        "Initial optimizer step. Too large may trigger more line-search attempts; too small can"
        " slow progress. Native line search chooses accepted steps."
    ),
    "convergence_tolerance": (
        "Native stopping tolerance. Smaller requires a stricter numerical stop and may take "
        "longer. Convergence does not approve anatomy."
    ),
    "attachment_type": (
        "Varifolds compare unoriented surface elements; currents also use orientation. Keep the"
        " chosen surface representation consistent across the project."
    ),
    "time_points": (
        "Samples along each deformation path. More improves time resolution at greater cost. A "
        "saved-field integration check tests whether further refinement changes the endpoint."
    ),
    "integration": (
        "Numerical integration scheme for deformation paths. Keep it fixed when comparing fits;"
        " a changed scheme requires fresh numerical checks."
    ),
    "line_search_limit": (
        "Maximum attempts to find an accepted optimizer step. Exhaustion is a stop requiring "
        "inspection, not convergence."
    ),
    "save_interval": (
        "Iterations between saved states. More frequent saves improve recovery granularity but "
        "add disk work. Final exports are separate."
    ),
    "log_interval": (
        "Iterations between printed objective observations. Sparse or rounded logs can limit "
        "end-of-run improvement advice."
    ),
    "step_size_scaling": (
        "Controls how line search expands or reduces trial steps. It changes optimizer "
        "behavior; retain the backend defaults unless justified."
    ),
    "sobolev_gradient": (
        "Smooths template gradients spatially. This is separate from deformation width and does"
        " not change which surface details the attachment measures."
    ),
    "sobolev_width_ratio": (
        "Spatial width used for Sobolev template-gradient smoothing. Larger spreads template "
        "updates more broadly."
    ),
    "template_update": (
        "Choose whether optimization changes the template or only fits subject deformations. A "
        "frozen template must be a deliberate model choice."
    ),
    "control_point_update": (
        "Choose whether control-point positions can move during optimization. Freezing them "
        "preserves the chosen basis, not the fitted momenta."
    ),
    "compute_acceleration": (
        "CUDA uses the configured GPU and KeOps kernels; CPU uses the configured thread count. "
        "Availability is checked before launch."
    ),
    "cpu_threads": (
        "CPU threads assigned to this run. More threads are not always faster; leave resources "
        "for the desktop and other work."
    ),
    "random_seed": (
        "Records the random seed for reproducible preparation. It does not guarantee identical "
        "numerical trajectories across devices or runtime versions."
    ),
}
