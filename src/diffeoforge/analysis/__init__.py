"""Engine-independent morphometric analysis building blocks."""

from diffeoforge.analysis.landmarks import (
    LANDMARK_COLUMNS,
    LandmarkTxtImportResult,
    import_landmark_txt_folder,
    read_landmark_csv,
    read_landmark_txt,
    write_landmark_csv,
)
from diffeoforge.analysis.pca import PCAResult, momenta_pca, principal_component_analysis
from diffeoforge.analysis.pca_stability import (
    PCAStabilityEvidence,
    compare_pca_stability,
)
from diffeoforge.analysis.pca_visualization import (
    write_pca_score_pair_svg,
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
    "LANDMARK_COLUMNS",
    "LandmarkTxtImportResult",
    "PCAResult",
    "PCAStabilityEvidence",
    "ProcrustesIteration",
    "SimilarityTransform",
    "compare_pca_stability",
    "generalized_procrustes",
    "import_landmark_txt_folder",
    "momenta_pca",
    "principal_component_analysis",
    "read_landmark_csv",
    "read_landmark_txt",
    "write_landmark_csv",
    "write_pca_score_pair_svg",
    "write_pca_scores_svg",
    "write_pca_scree_svg",
]
