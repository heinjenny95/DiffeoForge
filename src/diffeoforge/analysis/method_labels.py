"""Presentation terminology without altering recorded numerical method identities."""

TANGENT_PGA_LABEL = "LDDMM-metric tangent-space PCA (linearized PGA)"
TANGENT_PGA_DESCRIPTION = (
    "PCA of centered momenta in the fitted LDDMM tangent metric, followed by geodesic "
    "shooting for axis shapes. This is a tangent-space approximation to PGA, not an "
    "exact nonlinear PGA or proof of an intrinsic mean. Vaillant et al. (2004), "
    "Statistics on diffeomorphisms via tangent space representations, "
    "doi:10.1016/j.neuroimage.2004.07.023; PGA context: Fletcher et al. (2004), "
    "Principal geodesic analysis for the study of nonlinear statistics of shape, "
    "doi:10.1109/TMI.2004.831793. Cartesian PCA and generic RBF KernelPCA use "
    "different metrics and are not labelled PGA."
)


def shape_method_label(method_id: str, recorded_label: str) -> str:
    return TANGENT_PGA_LABEL if method_id == "lddmm_deformation_kernel_pca" else recorded_label
