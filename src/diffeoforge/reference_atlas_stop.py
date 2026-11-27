"""Independent, run-bound stopping choices for the reference atlas."""

from pathlib import Path

from diffeoforge.config import ConfigurationError, load_config, validate_schema

OPTIMIZER_CONVERGENCE = "optimizer_convergence"
DIFFEOFORGE_TOLERANCE = "diffeoforge_tolerance"
DEFORMETRICA_TOLERANCE = "deformetrica_tolerance"
NATIVE_PRESETS = {DIFFEOFORGE_TOLERANCE: 1e-6, DEFORMETRICA_TOLERANCE: 1e-4}
MORPHOSPACE_STABILITY = "morphospace_stability"
MORPHOSPACE_STABILITY_UNLIMITED = "morphospace_stability_unlimited"
ITERATION_TARGET = "iteration_target"
_MODES = (OPTIMIZER_CONVERGENCE, MORPHOSPACE_STABILITY, ITERATION_TARGET)


def stop_policy(mode, *, unlimited_iterations=False):
    if mode not in _MODES:
        raise ConfigurationError("Unknown atlas stopping mode.")
    if type(unlimited_iterations) is not bool or (
        unlimited_iterations and mode != MORPHOSPACE_STABILITY
    ):
        raise ConfigurationError("Only automatic morphospace stopping can run without a limit.")
    policy = {
        "mode": mode,
        "window_iterations": 200,
        "long_window_iterations": 400,
        "check_interval": 25,
        "cohort_threshold_percent": 1.0,
        "specimen_threshold_percent": 2.0,
    }
    if unlimited_iterations:
        policy["unlimited_iterations"] = True
    return policy


def project_tolerance(config):
    """Return the tolerance used before choosing a joint optimizer preset."""
    policy = config["project"].get("atlas_stop", {})
    return policy.get("project_convergence_tolerance",
                      config["optimization"]["convergence_tolerance"])


def atlas_stop_choice(config):
    """Return the setup choice represented by a saved policy."""
    policy = config.get("project", {}).get("atlas_stop", {})
    if policy.get("unlimited_iterations") is True:
        return MORPHOSPACE_STABILITY_UNLIMITED
    if policy.get("mode") == OPTIMIZER_CONVERGENCE:
        for preset, value in NATIVE_PRESETS.items():
            if config["optimization"]["convergence_tolerance"] == value:
                return preset
    return policy.get("mode")


def atlas_iteration_limit(config):
    """Return the effective joint limit. Individual initialization keeps its budget."""
    if config["project"].get("atlas_stop", {}).get("unlimited_iterations") is True:
        return None
    return int(config["optimization"]["max_iterations"])


def atlas_stop_available(config):
    project = config.get("project", {})
    provenance = project.get("parameter_provenance", {})
    calibration = provenance.get("recommendation", {}).get("calibration_plan", {})
    return (
        config["runtime"]["backend"] == "deformetrica_reference"
        and config["optimization"]["method"] == "gradient_ascent"
        and config["output"].get("checkpoint_mode", "compact_final_export")
        == "compact_final_export"
        and not any(key in provenance for key in (
            "regional_fit", "finite_accepted_guard", "final_export_recovery"
        ))
        and calibration.get("execution_scope") != "single_specimen_probe"
    )


def validate_atlas_stop(config, *, subject_count=None):
    if "atlas_stop" not in config["project"]:
        return
    if not atlas_stop_available(config) or (subject_count is not None and subject_count < 2):
        raise ConfigurationError(
            "Atlas stopping choices require a full-cohort GradientAscent atlas with final export."
        )
    policy = config["project"]["atlas_stop"]
    if "unlimited_iterations" in policy and (
        policy["unlimited_iterations"] is not True or policy["mode"] != MORPHOSPACE_STABILITY
    ):
        raise ConfigurationError("Only automatic morphospace stopping can run without a limit.")


def choose_atlas_stop(config_path, mode, *, unlimited_iterations=False):
    """Save a sibling choice and preserve the original project and pilot evidence."""
    from diffeoforge.reference_atlas_handoff import _write_linked_atlas_config

    path = Path(config_path).resolve()
    config = load_config(path)
    original = project_tolerance(config)
    tolerance = NATIVE_PRESETS.get(mode, original)
    rule = OPTIMIZER_CONVERGENCE if mode in NATIVE_PRESETS else mode
    policy = stop_policy(rule, unlimited_iterations=unlimited_iterations)
    if tolerance != original:
        policy["project_convergence_tolerance"] = original
    if (config["project"].get("atlas_stop") == policy
            and config["optimization"]["convergence_tolerance"] == tolerance):
        return path
    config["optimization"]["convergence_tolerance"] = tolerance
    config["project"]["atlas_stop"] = policy
    validate_schema(config)
    validate_atlas_stop(config)
    stem = path.stem
    for other in (*_MODES, *NATIVE_PRESETS, MORPHOSPACE_STABILITY_UNLIMITED):
        stem = stem.removesuffix(f"-stop-{other}")
    choice = atlas_stop_choice(config)
    return _write_linked_atlas_config(config, path.with_name(f"{stem}-stop-{choice}.yaml"))
