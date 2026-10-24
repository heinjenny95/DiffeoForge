"""Run-local adapter for Deformetrica 4.3's squeezed singleton momentum reader."""

# Deformetrica's read_3D_array returns (N, D) when its header says (1, N, D).
# DeterministicAtlas still expects a subject axis. This preserves every number
# and restores only that axis, in the isolated engine process, without installing
# or changing the reference environment. The generated file is protected evidence.
SITECUSTOMIZE = '''"""DiffeoForge singleton initial-momenta shape adapter v1."""
from deformetrica.core.models import deterministic_atlas as _atlas
_original = _atlas.initialize_momenta
def _initialize(initial_momenta, number_of_control_points, dimension,
                number_of_subjects=0, random=False):
    field = _original(initial_momenta, number_of_control_points, dimension,
                      number_of_subjects=number_of_subjects, random=random)
    if initial_momenta is not None and number_of_subjects == 1:
        if field.shape == (number_of_control_points, dimension):
            field = field[None, :, :]
        if field.shape != (1, number_of_control_points, dimension):
            raise ValueError("Singleton momentum dimensions do not match the fixed basis")
    return field
_atlas.initialize_momenta = _initialize
'''


def needs_adapter(config):
    return bool(
        config.get("project", {})
        .get("parameter_provenance", {})
        .get("recommendation", {})
        .get("calibration_plan", {})
        .get("execution_scope")
        == "single_specimen_probe"
        and config["model"]["deformation"].get("initial_momenta")
        and config["optimization"]["freeze_template"]
        and config["optimization"]["freeze_control_points"]
    )
