"""Experimental numerical-engine building blocks.

The modern engine is deliberately separate from the production backend interface. Importing
this package requires the optional ``modern-engine`` dependency set.
"""

from diffeoforge.engine.dense import (
    ShootingTrajectory,
    current_squared_distance,
    deformation_energy,
    flow_points,
    gaussian_convolve,
    gaussian_convolve_gradient,
    gaussian_kernel,
    shoot,
    triangle_centers_and_area_normals,
    varifold_squared_distance,
)
from diffeoforge.engine.objective import (
    AtlasObjective,
    SubjectObjective,
    atlas_objective,
    subject_objective,
)
from diffeoforge.engine.optimizer import (
    MomentaOptimizationResult,
    OptimizationRecord,
    optimize_momenta,
)

__all__ = [
    "ShootingTrajectory",
    "AtlasObjective",
    "MomentaOptimizationResult",
    "OptimizationRecord",
    "SubjectObjective",
    "atlas_objective",
    "current_squared_distance",
    "deformation_energy",
    "flow_points",
    "gaussian_convolve",
    "gaussian_convolve_gradient",
    "gaussian_kernel",
    "optimize_momenta",
    "shoot",
    "subject_objective",
    "triangle_centers_and_area_normals",
    "varifold_squared_distance",
]
