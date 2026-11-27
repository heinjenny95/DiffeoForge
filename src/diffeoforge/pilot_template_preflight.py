"""Check the unchanged scientific template before common-model optimization."""

import json

from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file

VERSION = "ordinary-template-topology-v1"
COUNTS = ("vertices", "faces", "intersecting_faces", "nonpositive_faces")


class TemplateTopologyBlocked(ValueError):
    def __init__(self, source, digest, counts):
        self.failure = dict(
            code="template_geometry", template=source.name, sha256=digest, **counts
        )
        problems = []
        if counts["intersecting_faces"]:
            problems.append(f"{counts['intersecting_faces']:,} faces with self-intersections")
        if counts["nonpositive_faces"]:
            problems.append(f"{counts['nonpositive_faces']:,} faces with zero area")
        super().__init__(
            f"The template {source.name} has {' and '.join(problems)}. "
            "Inspect it before starting this common-model test."
        )


def _valid_counts(value):
    return (
        isinstance(value, dict)
        and set(value) == set(COUNTS)
        and all(type(value[key]) is int and value[key] >= 0 for key in COUNTS)
        and value["vertices"] >= 3
        and value["faces"] > 0
        and all(value[key] <= value["faces"] for key in COUNTS[2:])
    )


def source_topology(source, digest, study_directory):
    """Reuse counts only for identical bytes and the same surface check."""
    from diffeoforge.ordinary_field_quality import _surface

    if source.is_symlink() or sha256_file(source) != digest:
        raise ValueError("The template changed before its surface check.")
    cache = study_directory.parent / "common-template-checks" / f"{VERSION}-{digest}.json"
    try:
        row = json.loads(cache.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        row = None
    if (
        isinstance(row, dict)
        and row.get("version") == VERSION
        and row.get("sha256") == digest
        and _valid_counts(row.get("counts"))
    ):
        return row["counts"]

    counts = _surface(source)
    if sha256_file(source) != digest:
        raise ValueError("The template changed during its surface check.")
    if not _valid_counts(counts):
        raise ValueError("The template surface check returned invalid counts.")
    try:
        write_text_safely(
            cache, json.dumps(dict(version=VERSION, sha256=digest, counts=counts)),
            overwrite=True,
        )
    except OSError:
        pass  # The check itself remains usable if the optional cache is unwritable.
    return counts


def check_template(request, study_directory, template):
    from diffeoforge.reference_calibration_study import _safe_study_path

    source = _safe_study_path(study_directory, template["copy"])
    if sha256_file(request.config_path) != request.expected_config_sha256:
        raise ValueError("The configured inputs changed before checking the template.")
    config = load_config(request.config_path)
    inputs = validate_input_paths(config, request.config_path, minimum_subject_count=1)
    if inputs.template != source:
        raise ValueError("The configured template differs from the saved common-model template.")
    counts = source_topology(source, template["sha256"], study_directory)
    if counts["intersecting_faces"] or counts["nonpositive_faces"]:
        raise TemplateTopologyBlocked(source, template["sha256"], counts)
