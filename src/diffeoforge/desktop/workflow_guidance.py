"""Plain-language guidance for anatomical decisions and existing alignment choices."""

LANDMARK_SUMMARY = (
    "Choose the same identifiable anatomical locations on every specimen, in the same "
    "label order. Use at least three well-spread points that do not lie on one line."
)
LANDMARK_GUIDE = (
    "Where to place them\n"
    "Choose reproducible features present in every specimen, such as a clear junction, "
    "attachment boundary or corresponding tip. The appropriate features depend on your "
    "organ and biological question; there is no universal set of locations.\n\n"
    "Spread points across the structure and across different directions. Three points "
    "very close together, or nearly on a straight line, give an unstable orientation. "
    "More points help only when you can identify their correspondence reliably.\n\n"
    "LM1 must mean the same feature on every mesh, including the template. Keep left/right "
    "and coordinate units consistent. Do not guess a missing feature or substitute the "
    "nearest-looking projection. Reconsider the landmark plan instead.\n\n"
    "These landmarks guide initial alignment. They do not force the atlas to match those "
    "points. Review the aligned cohort before approving it."
)
TEMPLATE_SUMMARY = (
    "Choose a complete, clean surface with a broadly representative shape. "
    "Avoid a damaged or unusually specialized specimen as the starting template."
)
TEMPLATE_GUIDE = (
    "The starting template supplies the surface that is deformed toward each specimen. "
    "Prefer a mesh with the same biological structure, complete features and good surface "
    "quality; a large number of triangles alone does not make a good template.\n\n"
    "Analyze meshes compares geometric descriptors and surface-quality warnings, then "
    "suggests a central form and contrasting alternatives. It runs in the background and "
    "does not fit an atlas or change your selected template. Preview the candidate and "
    "choose Use suggested template explicitly.\n\n"
    "This is a starting recommendation, not anatomical approval or a prediction of the "
    "best final atlas. Check alignment and test the important shape differences in the pilot."
)


def alignment_description(mode: str, *, enabled: bool, reflections: bool) -> str:
    if not enabled:
        return (
            "No new landmark alignment will be applied. Use this only when the input meshes "
            "already share a reviewed coordinate frame and intended size treatment."
        )
    choices = {
        "pams_surface_area_weighted_rms": (
            "Shape only: removes position, orientation and surface size. Area weighting makes "
            "the size measure insensitive to triangle subdivision."
        ),
        "pams_surface_vertex_centroid_size": (
            "Published PAMS: removes position, orientation and vertex-based surface size. "
            "Useful for reproducing that workflow; uneven vertex density can affect scale."
        ),
        "preserve_size": (
            "Size + shape: removes position and orientation while keeping specimen size. "
            "Choose this when size differences are part of the biological question."
        ),
        "landmark_centroid_size_legacy": (
            "Legacy: landmarks determine position, orientation and size. The landmark "
            "configuration influences how the complete surface is scaled."
        ),
    }
    text = choices.get(mode, "Landmarks guide alignment using the selected size treatment.")
    return text + (
        " Reflections are allowed: use only if mirrored forms are biologically interchangeable."
        if reflections else " Reflections are off: left/right handedness is preserved."
    )
