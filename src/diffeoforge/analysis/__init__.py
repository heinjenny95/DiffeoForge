"""Engine-independent morphometric analysis building blocks."""

from diffeoforge.analysis.pca import PCAResult, momenta_pca, principal_component_analysis
from diffeoforge.analysis.pca_visualization import (
    write_pca_scores_svg,
    write_pca_scree_svg,
)
from diffeoforge.analysis.procrustes import (
    GeneralizedProcrustesResult,
    ProcrustesIteration,
    SimilarityTransform,
    generalized_procrustes,
)

__all__ = [
    "GeneralizedProcrustesResult",
    "PCAResult",
    "ProcrustesIteration",
    "SimilarityTransform",
    "generalized_procrustes",
    "momenta_pca",
    "principal_component_analysis",
    "write_pca_scores_svg",
    "write_pca_scree_svg",
]
