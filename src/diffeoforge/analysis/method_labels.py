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


def shape_method_description(method_id: str) -> str:
    """Short decision help, without changing any numerical method or default."""
    descriptions = {
        "lddmm_deformation_kernel_pca": (
            "Summarizes fitted deformations using the atlas's LDDMM metric. "
            "The default tangent-space approximation to PGA; inspect the PC shapes."
        ),
        "lddmm_tangent_pcoa": (
            "Builds a coordinate view from LDDMM tangent distances. "
            "Use it to cross-check the tangent PCA; it is not a second atlas fit."
        ),
        "cartesian_momenta_pca": (
            "Linear PCA of raw momentum coordinates, without the LDDMM metric. "
            "Useful for legacy comparisons; distances can differ from the default."
        ),
        "cartesian_initial_momenta_pca": (
            "Linear PCA of raw initial momentum coordinates from the Modern Engine. "
            "This uses Cartesian coordinates, not the fitted LDDMM metric."
        ),
        "roberts_2026_cartesian_momenta_rbf_kpca": (
            "Nonlinear RBF KernelPCA of Cartesian momenta with the published fixed-gamma "
            "preset. Use for workflow compatibility; it is not LDDMM tangent PCA."
        ),
        "isomap": (
            "Explores neighborhood paths through LDDMM tangent distances. "
            "Its layout depends on the selected neighborhood; it is not PCA."
        ),
        "diffusion_map": (
            "Explores neighborhood connectivity in LDDMM tangent distances. "
            "Its axes describe diffusion structure, not percentages of PCA variance."
        ),
    }
    if method_id.startswith("rbf_kpca_gamma_"):
        return (
            "Nonlinear RBF KernelPCA of LDDMM tangent distances. Gamma controls the "
            "distance scale; compare settings before interpreting clusters."
        )
    return descriptions.get(
        method_id, "Read the saved method description before interpreting axes."
    )
