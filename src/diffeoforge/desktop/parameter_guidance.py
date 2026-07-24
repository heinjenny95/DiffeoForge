"""Plain-language, source-grounded guidance for Deformetrica controls."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class ParameterGuidance:
    """Explanation shown below one Deformetrica-related control."""

    summary: str
    sections: tuple[tuple[str, str], ...]

    def to_html(self) -> str:
        """Render compact rich text for a Qt label."""

        parts = [f"<p>{escape(self.summary)}</p>"]
        parts.extend(
            f"<p><b>{escape(heading)}:</b> {escape(text)}</p>"
            for heading, text in self.sections
        )
        return "".join(parts)


DEFORMETRICA_PARAMETER_GUIDANCE: dict[str, ParameterGuidance] = {
    "recommendation_mode": ParameterGuidance(
        summary=(
            "Selects how DiffeoForge obtains the starting values. This choice does not "
            "run an atlas."
        ),
        sections=(
            (
                "Analyze aligned meshes first",
                "Keeps the numeric fields inactive until the GPA-aligned cohort has been "
                "measured. Use this when no current recommendation exists.",
            ),
            (
                "Data-assisted recommendation",
                "Uses measured mesh scale and sampling plus your detail choices. The "
                "proposed values are locked, recorded, and intended as pilot starting "
                "values—not as scientifically validated defaults.",
            ),
            (
                "Advanced manual control",
                "Makes the values editable. If an analysis exists, its values remain the "
                "starting point; otherwise DiffeoForge loads an exploratory profile.",
            ),
            (
                "Example",
                "Analyze a newly GPA-aligned cohort, review the proposed effective widths, "
                "then switch to manual control only when a documented pilot justifies a "
                "change.",
            ),
        ),
    ),
    "surface_detail": ParameterGuidance(
        summary=(
            "States the smallest surface detail that the attachment term should try to "
            "distinguish. It helps choose attachment width; geometry still enforces a "
            "mesh-sampling lower bound."
        ),
        sections=(
            (
                "Fine",
                "Requests a smaller comparison scale. This can preserve small anatomical "
                "features but is more sensitive to sampling, roughness, holes, and noise.",
            ),
            (
                "Coarse / global",
                "Requests a larger comparison scale. This favors robust broad agreement "
                "but may merge or underfit small features.",
            ),
            (
                "Example",
                "Choose Fine for a consistently sampled ridge that is part of the "
                "hypothesis; choose Coarse when only overall proportions are relevant.",
            ),
        ),
    ),
    "deformation_scale": ParameterGuidance(
        summary=(
            "States whether biologically meaningful differences are expected to be local "
            "or spatially broad. It helps choose deformation width."
        ),
        sections=(
            (
                "Local",
                "Uses a smaller nominal deformation scale, allowing more localized and "
                "flexible changes but increasing model complexity and overfit risk.",
            ),
            (
                "Global",
                "Uses a larger nominal scale, favoring smooth coherent changes and "
                "stability but potentially missing localized anatomy.",
            ),
            (
                "Example",
                "A localized process or spur may motivate Local; coordinated widening of "
                "an entire structure may motivate Global.",
            ),
        ),
    ),
    "attachment_ratio": ParameterGuidance(
        summary=(
            "The attachment-kernel width divided by the template bounding-box diagonal. "
            "For current or varifold matching, it sets the spatial resolution at which "
            "surface discrepancies are compared."
        ),
        sections=(
            (
                "Increase",
                "Averages discrepancies over broader neighborhoods. Matching becomes more "
                "global and less sensitive to small roughness, but fine anatomy can be "
                "underfit.",
            ),
            (
                "Decrease",
                "Resolves more local differences. It can retain fine signal, but becomes "
                "more sensitive to mesh sampling, artifacts, and residual misalignment.",
            ),
            (
                "Example",
                "For a diagonal of 100 units, 0.05 means a width of 5 units; 0.02 targets "
                "features around 2 units. Smaller is not automatically more accurate.",
            ),
        ),
    ),
    "deformation_ratio": ParameterGuidance(
        summary=(
            "The Gaussian deformation-kernel width divided by the template diagonal. It "
            "sets the spatial correlation length and smoothness of the velocity field."
        ),
        sections=(
            (
                "Increase",
                "Produces broader, smoother, more coherent deformations and usually a "
                "simpler, more stable model, but can underfit local anatomy.",
            ),
            (
                "Decrease",
                "Allows more localized and flexible deformations. It can capture local "
                "shape change, but may increase computation, instability, and overfit risk.",
            ),
            (
                "Example",
                "For a diagonal of 100, ratios 0.20, 0.10, and 0.05 correspond to widths "
                "20, 10, and 5—from broad to increasingly local deformation.",
            ),
        ),
    ),
    "control_spacing_ratio": ParameterGuidance(
        summary=(
            "The initial spacing of the control-point grid divided by the template "
            "diagonal. Control points parameterize the deformation."
        ),
        sections=(
            (
                "Increase",
                "Creates fewer control points, reducing memory and runtime but limiting "
                "local flexibility.",
            ),
            (
                "Decrease",
                "Creates a denser, more flexible grid. Runtime, memory use, and "
                "over-parameterization risk rise rapidly.",
            ),
            (
                "Example",
                "Halving spacing can create roughly eight times as many grid points in 3D "
                "over the same volume; the exact count depends on the bounding box.",
            ),
        ),
    ),
    "noise_ratio": ParameterGuidance(
        summary=(
            "The deterministic-atlas noise standard deviation divided by the template "
            "diagonal. It weights attachment relative to deformation regularization; it "
            "is not simply scanner or measurement noise."
        ),
        sections=(
            (
                "Increase",
                "Downweights close data fitting. Regularization has more relative influence, "
                "usually producing smoother, less tightly fitted registrations.",
            ),
            (
                "Decrease",
                "Makes attachment more influential. Fits may become closer, but noise and "
                "artifacts can be modeled as anatomy and optimization can become harder.",
            ),
            (
                "Example",
                "Because attachment is weighted by 1/noise-SD squared, halving the value "
                "gives that term four times the weight.",
            ),
        ),
    ),
    "maximum_iterations": ParameterGuidance(
        summary=(
            "The hard upper limit on gradient-ascent iterations. Optimization may stop "
            "earlier because of tolerance or line-search failure."
        ),
        sections=(
            (
                "Increase",
                "Allows more time to converge and can improve an atlas that was stopped by "
                "the cap, but increases worst-case runtime and cannot fix a plateau or bad "
                "model settings.",
            ),
            (
                "Decrease",
                "Makes pilots faster, but can stop while the objective and atlas are still "
                "changing materially.",
            ),
            (
                "Example",
                "Use 20–30 iterations for a technical smoke test, then justify a larger cap "
                "with objective and convergence plots.",
            ),
        ),
    ),
    "initial_step_size": ParameterGuidance(
        summary=(
            "Sets the optimizer's initial proposal magnitude. With step-size scaling "
            "enabled, it multiplies gradient-normalized step sizes; otherwise it is used "
            "directly for every parameter block."
        ),
        sections=(
            (
                "Increase",
                "Can accelerate early progress, but may overshoot and trigger repeated "
                "line-search shrinkage or instability.",
            ),
            (
                "Decrease",
                "Makes early updates more conservative and stable, but can lead to very slow "
                "progress or apparent stalling.",
            ),
            (
                "Example",
                "If early proposals are repeatedly rejected, try a smaller value; if every "
                "accepted change is tiny and smooth, a cautious increase can be piloted.",
            ),
        ),
    ),
    "convergence_tolerance": ParameterGuidance(
        summary=(
            "Controls the relative objective-change stopping test. Deformetrica stops when "
            "the newest improvement is small relative to the improvement accumulated so far."
        ),
        sections=(
            (
                "Increase",
                "Makes the stopping condition easier to satisfy, often shortening the run "
                "but increasing premature-stop risk.",
            ),
            (
                "Decrease",
                "Requires smaller relative changes before stopping. Runs may be longer and "
                "can spend time following numerical noise.",
            ),
            (
                "Example",
                "Changing 1e-4 to 1e-6 is a stricter criterion. Compare final shapes and "
                "objective curves; a stricter number does not prove biological validity.",
            ),
        ),
    ),
    "attachment_type": ParameterGuidance(
        summary=(
            "Selects the surface representation used by the attachment term. This is a "
            "categorical scientific choice, not a quality slider."
        ),
        sections=(
            (
                "Current",
                "Is orientation-sensitive. Use it only when face orientation and normals "
                "are meaningful and consistent across all meshes.",
            ),
            (
                "Varifold",
                "Is orientation-insensitive and is more robust to flipped surface normals, "
                "but intentionally discards orientation sign.",
            ),
            (
                "Example",
                "For meshes exported with inconsistent winding, Varifold avoids treating a "
                "normal flip as anatomy. Current can be appropriate after orientation QA.",
            ),
        ),
    ),
    "time_points": ParameterGuidance(
        summary=(
            "The number of discrete time points used to integrate the deformation path "
            "between the template and each subject."
        ),
        sections=(
            (
                "Increase",
                "Improves temporal integration resolution, especially for strong or local "
                "deformations, but raises trajectory computation and memory roughly "
                "linearly.",
            ),
            (
                "Decrease",
                "Runs faster and uses less memory, but coarse integration can distort the "
                "estimated path.",
            ),
            (
                "Example",
                "Compare 10 with 20 time points on a pilot. If atlas and objective remain "
                "stable, the smaller value may be sufficient.",
            ),
        ),
    ),
    "integration": ParameterGuidance(
        summary=(
            "Chooses whether shooting and flow use second-order Runge–Kutta integration "
            "(RK2) instead of the simpler first-order update."
        ),
        sections=(
            (
                "Enable RK2",
                "Usually reduces integration error at the same number of time points, but "
                "requires more computation per time step.",
            ),
            (
                "Disable RK2",
                "Is faster per step, but may require more time points for comparable "
                "trajectory accuracy.",
            ),
            (
                "Example",
                "Pilot RK2 when deformations are strong or time points are limited, then "
                "check whether the resulting atlas changes materially.",
            ),
        ),
    ),
    "line_search_limit": ParameterGuidance(
        summary=(
            "The maximum number of progressively smaller proposals tried when an optimizer "
            "step fails to improve the objective."
        ),
        sections=(
            (
                "Increase",
                "Gives a difficult iteration more chances to find an acceptable smaller "
                "step, but makes failed iterations take longer.",
            ),
            (
                "Decrease",
                "Fails faster, but can terminate a run even though a smaller improving step "
                "would have been found.",
            ),
            (
                "Example",
                "Repeated 'line search loops exceeded' messages justify reviewing the "
                "initial step size before raising this limit from 10 to 20.",
            ),
        ),
    ),
    "save_interval": ParameterGuidance(
        summary=(
            "Writes result snapshots and optimizer state every N iterations. It changes "
            "checkpoint frequency, not the intended atlas model."
        ),
        sections=(
            (
                "Increase",
                "Reduces disk I/O and file count, but leaves fewer recovery points and "
                "intermediate results.",
            ),
            (
                "Decrease",
                "Creates more frequent checkpoints and provenance, at the cost of disk "
                "space and write overhead.",
            ),
            (
                "Example",
                "100 saves rarely during a 150-iteration run; 10 preserves a much denser "
                "history for a long or failure-prone run.",
            ),
        ),
    ),
    "log_interval": ParameterGuidance(
        summary=(
            "Prints optimizer status every N iterations. It controls monitoring resolution, "
            "not the mathematical target."
        ),
        sections=(
            (
                "Increase",
                "Produces shorter, coarser logs with slightly less reporting overhead.",
            ),
            (
                "Decrease",
                "Provides more detailed live and post-run diagnostics, but creates more log "
                "output.",
            ),
            (
                "Example",
                "1 reports every iteration; 10 reports every tenth iteration and makes the "
                "visible convergence history less detailed.",
            ),
        ),
    ),
    "step_size_scaling": ParameterGuidance(
        summary=(
            "Determines how the initial step is applied to parameter blocks with very "
            "different gradient magnitudes."
        ),
        sections=(
            (
                "Enable",
                "Normalizes each initial block step by its gradient norm, then multiplies by "
                "the initial-step value. This reduces sensitivity to parameter scale.",
            ),
            (
                "Disable",
                "Uses the literal initial-step value for all blocks. It is simpler but one "
                "block may move too far while another barely moves.",
            ),
            (
                "Example",
                "With scaling enabled, 0.01 is a multiplier after normalization; without "
                "scaling, every block starts with a step size of 0.01.",
            ),
        ),
    ),
    "sobolev_gradient": ParameterGuidance(
        summary=(
            "Controls smoothing of the template-position gradient. It affects how the mean "
            "template updates; it does not replace deformation-kernel regularization."
        ),
        sections=(
            (
                "Enable",
                "Suppresses high-frequency template updates and can improve smoothness and "
                "stability, but may soften sharp anatomy.",
            ),
            (
                "Disable",
                "Uses the unsmoothed template gradient, allowing finer updates but making "
                "roughness or sampling artifacts more influential.",
            ),
            (
                "Example",
                "If the estimated template develops mesh-scale ripples, enable smoothing; "
                "if a validated sharp feature is lost, pilot a smaller width or disable it.",
            ),
        ),
    ),
    "sobolev_width_ratio": ParameterGuidance(
        summary=(
            "The Sobolev smoothing width divided by the deformation-kernel width. It is "
            "active only when Sobolev gradient smoothing and template updating are active."
        ),
        sections=(
            (
                "Increase",
                "Smooths template updates over broader neighborhoods, improving regularity "
                "but potentially blurring local features.",
            ),
            (
                "Decrease",
                "Retains more localized template updates, with greater sensitivity to "
                "surface noise and irregular sampling.",
            ),
            (
                "Example",
                "With deformation width 10, ratios 0.5, 1, and 2 produce Sobolev widths 5, "
                "10, and 20.",
            ),
        ),
    ),
    "template_update": ParameterGuidance(
        summary=(
            "Determines whether the template geometry is estimated or held at its initial "
            "shape. The checkbox wording is 'Freeze template'."
        ),
        sections=(
            (
                "Freeze",
                "Keeps the selected template fixed. The run estimates subject deformations "
                "from that reference rather than an updated population-mean template.",
            ),
            (
                "Update",
                "Allows the template to move toward the cohort estimate. This is normally "
                "needed for atlas estimation and is affected by Sobolev settings.",
            ),
            (
                "Example",
                "Freeze for registration to a deliberately fixed reference; leave "
                "unchecked when the scientific output should be an estimated mean atlas.",
            ),
        ),
    ),
    "control_point_update": ParameterGuidance(
        summary=(
            "Determines whether initial control-point locations can move during "
            "optimization. The checkbox wording is 'Freeze control points'."
        ),
        sections=(
            (
                "Freeze",
                "Keeps a fixed spatial basis, reducing optimized degrees of freedom and "
                "improving comparability, but a poor initial grid cannot adapt.",
            ),
            (
                "Update",
                "Allows locations to adapt to the data, adding flexibility and cost while "
                "potentially increasing sensitivity to local optima.",
            ),
            (
                "Example",
                "A regular grid with adequate spacing is a reason to freeze; movement should "
                "be piloted when fixed controls systematically miss relevant regions.",
            ),
        ),
    ),
    "cpu_threads": ParameterGuidance(
        summary=(
            "Sets the CPU thread limit for the Deformetrica process. It is a resource "
            "setting rather than an anatomical scale."
        ),
        sections=(
            (
                "Increase",
                "Can shorten runtime until CPU cores or memory bandwidth are saturated, but "
                "uses more system resources and can make the computer less responsive.",
            ),
            (
                "Decrease",
                "Leaves resources for other work and may reduce memory pressure, but usually "
                "runs more slowly.",
            ),
            (
                "Example",
                "Compare 4 and 8 threads on the same pilot. Do not assume doubling threads "
                "will halve runtime.",
            ),
        ),
    ),
    "random_seed": ParameterGuidance(
        summary=(
            "Records the seed supplied to stochastic components for reproducibility. Seed "
            "values have identities, not an ordered strength."
        ),
        sections=(
            (
                "Same seed",
                "Supports repeatability when software, hardware, inputs, and thread behavior "
                "are also controlled.",
            ),
            (
                "Different seed",
                "Can test sensitivity to stochastic initialization or ordering and may "
                "reach a different local solution.",
            ),
            (
                "Example",
                "200 is not 'more random' than 2. Reproduce the primary run with one recorded "
                "seed, then use predefined alternate seeds for a sensitivity analysis.",
            ),
        ),
    ),
}
