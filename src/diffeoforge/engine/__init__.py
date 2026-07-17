"""Experimental numerical-engine building blocks.

The modern engine is deliberately separate from the production backend interface. Importing
this package requires the optional ``modern-engine`` dependency set.
"""

from diffeoforge.engine.atlas_optimizer import (
    AtlasCancellationCallback,
    AtlasOptimizationCancelled,
    AtlasOptimizationRecord,
    AtlasOptimizationResult,
    AtlasOptimizerSettings,
    AtlasParameterBlock,
    AtlasProgressCallback,
    optimize_atlas,
)
from diffeoforge.engine.dense import (
    GaussianTilePlan,
    ShootingTrajectory,
    TileAutogradStrategy,
    current_squared_distance,
    current_squared_distance_blockwise,
    deformation_energy,
    flow_points,
    gaussian_convolve,
    gaussian_convolve_blockwise,
    gaussian_convolve_gradient,
    gaussian_convolve_gradient_blockwise,
    gaussian_kernel,
    shoot,
    triangle_centers_and_area_normals,
    varifold_squared_distance,
    varifold_squared_distance_blockwise,
)
from diffeoforge.engine.execution import PairwiseEvaluationPlan
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
    "GaussianTilePlan",
    "TileAutogradStrategy",
    "PairwiseEvaluationPlan",
    "AtlasObjective",
    "AtlasCancellationCallback",
    "AtlasOptimizationCancelled",
    "AtlasOptimizationRecord",
    "AtlasOptimizationResult",
    "AtlasOptimizerSettings",
    "AtlasParameterBlock",
    "AtlasProgressCallback",
    "MomentaOptimizationResult",
    "OptimizationRecord",
    "SubjectObjective",
    "atlas_objective",
    "current_squared_distance",
    "current_squared_distance_blockwise",
    "deformation_energy",
    "flow_points",
    "gaussian_convolve",
    "gaussian_convolve_blockwise",
    "gaussian_convolve_gradient",
    "gaussian_convolve_gradient_blockwise",
    "gaussian_kernel",
    "optimize_momenta",
    "optimize_atlas",
    "shoot",
    "subject_objective",
    "triangle_centers_and_area_normals",
    "varifold_squared_distance",
    "varifold_squared_distance_blockwise",
]
