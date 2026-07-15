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

__all__ = [
    "ShootingTrajectory",
    "current_squared_distance",
    "deformation_energy",
    "flow_points",
    "gaussian_convolve",
    "gaussian_convolve_gradient",
    "gaussian_kernel",
    "shoot",
    "triangle_centers_and_area_normals",
    "varifold_squared_distance",
]
