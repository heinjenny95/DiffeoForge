"""Strict descriptive comparison of two completed Modern optimizer studies."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from html import escape
from pathlib import Path, PurePosixPath
from statistics import fmean, median
from typing import Any

from diffeoforge.mesh import sha256_file
from diffeoforge.modern_optimizer_benchmark import verify_modern_optimizer_benchmark_report
from diffeoforge.modern_optimizer_benchmark_design import (
    DESIGN_JSON_NAME,
    verify_modern_optimizer_benchmark_design,
)
from diffeoforge.modern_optimizer_benchmark_study import (
    DESIGN_DIRECTORY_NAME,
    MANIFEST_NAME,
    verify_modern_optimizer_benchmark_study_run,
)

LEGACY_COMPARISON_VERSION = "0.1"
COMPARISON_VERSION = "0.2"
SUPPORTED_COMPARISON_VERSIONS = (LEGACY_COMPARISON_VERSION, COMPARISON_VERSION)
COMPARISON_JSON_NAME = "optimizer-study-comparison.json"
COMPARISON_SIDECAR_NAME = "optimizer-study-comparison.sha256"
COMPARISON_HTML_NAME = "optimizer-study-comparison.html"
SCIENTIFIC_BOUNDARY = (
    "This artifact descriptively compares two separately frozen, strictly verified optimizer "
    "studies on the same inputs and protocol. It does not select a winner, establish a safe "
    "tile preset, measure end-to-end workflow time, prove convergence or biological validity, "
    "or extrapolate to a larger cohort or 300 subjects. Sampled RSS can miss short peaks."
)
_DISCRETE_FIELDS = (
    "termination_reason",
    "converged",
    "failed_block",
    "cycles_completed",
    "accepted_decisions",
    "stationary_decisions",
    "failed_decisions",
    "line_search_evaluations",
    "objective_evaluations",
    "gradient_evaluations",
    "candidate_gradient_evaluations",
    "line_search_candidates_without_gradient",
)
_SCALAR_FIELDS = ("final_objective", "final_attachment", "final_regularity")
_HASH_FIELDS = (
    "history_sha256",
    "template_sha256",
    "control_points_sha256",
    "momenta_sha256",
)
_PERFORMANCE_FIELDS = (
    "target_preparation_wall_time_ns",
    "optimizer_wall_time_ns",
    "sampled_peak_rss_bytes",
    "sampled_rss_delta_bytes",
)


class ModernOptimizerBenchmarkComparisonError(RuntimeError):
    """Raised when completed optimizer studies cannot be compared safely."""


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _single_condition_evidence(root: Path) -> dict[str, Any]:
    manifest = verify_modern_optimizer_benchmark_study_run(root)
    design = verify_modern_optimizer_benchmark_design(root / DESIGN_DIRECTORY_NAME)
    if len(design["conditions"]) != 1 or len(manifest["conditions"]) != 1:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer study comparison currently requires exactly one frozen condition per run"
        )
    condition = design["conditions"][0]
    report_path = root.joinpath(
        *PurePosixPath(condition["output_directory"]).parts,
    )
    report = verify_modern_optimizer_benchmark_report(report_path)
    return {
        "root": root,
        "manifest": manifest,
        "design": design,
        "condition": condition,
        "report": report,
    }


def _without_pairwise(configuration: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(configuration))
    value.pop("pairwise_evaluation", None)
    return value


def _without_engine_implementation(software: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(software))
    value.pop("engine_implementation", None)
    return value


def _require_comparable(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    legacy: bool = False,
) -> str:
    baseline_design = baseline["design"]
    candidate_design = candidate["design"]
    if baseline_design["input"] != candidate_design["input"]:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer studies do not bind the same complete input inventory"
        )
    baseline_software = baseline_design["software"]
    candidate_software = candidate_design["software"]
    baseline_engine = baseline_software.get("engine_implementation")
    candidate_engine = candidate_software.get("engine_implementation")
    if legacy and baseline_software != candidate_software:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer studies do not bind the same software and engine implementation"
        )
    if not legacy and _without_engine_implementation(
        baseline_software
    ) != _without_engine_implementation(candidate_software):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer studies do not bind the same software outside engine implementation"
        )
    if baseline_design["protocol"] != candidate_design["protocol"]:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer studies do not use the same frozen benchmark protocol"
        )
    baseline_configuration = baseline_design["configuration"]
    candidate_configuration = candidate_design["configuration"]
    baseline_pairwise = baseline_configuration["pairwise_evaluation"]
    candidate_pairwise = candidate_configuration["pairwise_evaluation"]
    engine_differs = baseline_engine != candidate_engine
    pairwise_differs = baseline_pairwise != candidate_pairwise
    if engine_differs and pairwise_differs:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison cannot change engine implementation and "
            "pairwise evaluation together"
        )
    dimension = "engine_implementation" if engine_differs else "pairwise_evaluation"
    if dimension == "engine_implementation" and baseline_configuration != candidate_configuration:
        raise ModernOptimizerBenchmarkComparisonError(
            "Engine-implementation comparison requires identical optimizer configurations"
        )
    if dimension == "pairwise_evaluation" and _without_pairwise(
        baseline_configuration
    ) != _without_pairwise(candidate_configuration):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer study configurations differ outside pairwise evaluation"
        )
    for field in ("subject_count", "cycle_cap"):
        if baseline["condition"][field] != candidate["condition"][field]:
            raise ModernOptimizerBenchmarkComparisonError(
                "Optimizer study conditions use different subject or cycle counts"
            )
    if baseline["report"]["input"] != candidate["report"]["input"]:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer reports do not contain the same selected inputs"
        )
    baseline_report_configuration = baseline["report"]["configuration"]
    candidate_report_configuration = candidate["report"]["configuration"]
    report_configurations_match = (
        baseline_report_configuration == candidate_report_configuration
        if dimension == "engine_implementation"
        else _without_pairwise(baseline_report_configuration)
        == _without_pairwise(candidate_report_configuration)
    )
    if not report_configurations_match:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer report protocols differ outside the declared comparison dimension"
        )
    report_baseline_engine = baseline["report"]["environment"].get(
        "engine_implementation"
    )
    report_candidate_engine = candidate["report"]["environment"].get(
        "engine_implementation"
    )
    if (
        report_baseline_engine != baseline_engine
        or report_candidate_engine != candidate_engine
    ):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer reports do not bind their source design engine implementations"
        )
    return dimension


def _summary(samples: list[dict[str, Any]], field: str) -> dict[str, float]:
    values = [float(sample[field]) for sample in samples]
    if not values or any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ModernOptimizerBenchmarkComparisonError(
            f"Optimizer performance samples are invalid: {field}"
        )
    return {
        "minimum": min(values),
        "median": float(median(values)),
        "mean": float(fmean(values)),
        "maximum": max(values),
    }


def _performance(
    baseline_samples: list[dict[str, Any]],
    candidate_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline = {field: _summary(baseline_samples, field) for field in _PERFORMANCE_FIELDS}
    candidate = {field: _summary(candidate_samples, field) for field in _PERFORMANCE_FIELDS}
    ratios = {}
    for field in _PERFORMANCE_FIELDS:
        denominator = baseline[field]["median"]
        ratios[field] = (
            None if denominator <= 0.0 else candidate[field]["median"] / denominator
        )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "candidate_to_baseline_median_ratios": ratios,
    }


def _numerical_agreement(
    baseline_samples: list[dict[str, Any]],
    candidate_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_repeat = {int(sample["repeat"]): sample for sample in baseline_samples}
    candidate_by_repeat = {int(sample["repeat"]): sample for sample in candidate_samples}
    if set(baseline_by_repeat) != set(candidate_by_repeat):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer studies do not contain the same repeat identifiers"
        )
    records = []
    for repeat in sorted(baseline_by_repeat):
        baseline = baseline_by_repeat[repeat]
        candidate = candidate_by_repeat[repeat]
        scalar_differences = {
            field: abs(float(candidate[field]) - float(baseline[field]))
            for field in _SCALAR_FIELDS
        }
        scalar_matches = {
            field: math.isclose(
                float(candidate[field]),
                float(baseline[field]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for field in _SCALAR_FIELDS
        }
        records.append(
            {
                "repeat": repeat,
                "discrete_work_and_outcome_match": all(
                    baseline[field] == candidate[field] for field in _DISCRETE_FIELDS
                ),
                "scalar_components_match_within_tolerance": all(scalar_matches.values()),
                "scalar_absolute_differences": scalar_differences,
                "exact_hash_matches": {
                    field: baseline[field] == candidate[field] for field in _HASH_FIELDS
                },
            }
        )
    return {
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-12,
        "all_discrete_work_and_outcomes_match": all(
            record["discrete_work_and_outcome_match"] for record in records
        ),
        "all_scalar_components_match_within_tolerance": all(
            record["scalar_components_match_within_tolerance"] for record in records
        ),
        "all_history_hashes_match_exactly": all(
            record["exact_hash_matches"]["history_sha256"] for record in records
        ),
        "all_parameter_hashes_match_exactly": all(
            all(
                record["exact_hash_matches"][field]
                for field in ("template_sha256", "control_points_sha256", "momenta_sha256")
            )
            for record in records
        ),
        "repeats": records,
    }


def collect_modern_optimizer_benchmark_comparison(
    baseline_run: Path | str,
    candidate_run: Path | str,
    *,
    created_at: str | None = None,
    comparison_version: str = COMPARISON_VERSION,
) -> dict[str, Any]:
    """Verify and descriptively compare two completed single-condition studies."""

    if comparison_version not in SUPPORTED_COMPARISON_VERSIONS:
        raise ModernOptimizerBenchmarkComparisonError(
            f"Unsupported optimizer comparison version: {comparison_version}"
        )
    baseline_root = Path(baseline_run).expanduser().resolve()
    candidate_root = Path(candidate_run).expanduser().resolve()
    baseline = _single_condition_evidence(baseline_root)
    candidate = _single_condition_evidence(candidate_root)
    dimension = _require_comparable(
        baseline,
        candidate,
        legacy=comparison_version == LEGACY_COMPARISON_VERSION,
    )
    baseline_samples = baseline["report"]["samples"]
    candidate_samples = candidate["report"]["samples"]
    if not isinstance(baseline_samples, list) or not isinstance(candidate_samples, list):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer reports do not contain valid repeat samples"
        )
    baseline_engine = baseline["design"]["software"].get("engine_implementation")
    candidate_engine = candidate["design"]["software"].get("engine_implementation")
    baseline_record = {
        "path": str(baseline_root),
        "manifest_sha256": sha256_file(baseline_root / MANIFEST_NAME),
        "design_sha256": sha256_file(
            baseline_root / DESIGN_DIRECTORY_NAME / DESIGN_JSON_NAME
        ),
        "pairwise_evaluation": baseline["design"]["configuration"][
            "pairwise_evaluation"
        ],
        "repeat_consistent": baseline["report"]["repeat_consistency"]["consistent"],
    }
    candidate_record = {
        "path": str(candidate_root),
        "manifest_sha256": sha256_file(candidate_root / MANIFEST_NAME),
        "design_sha256": sha256_file(
            candidate_root / DESIGN_DIRECTORY_NAME / DESIGN_JSON_NAME
        ),
        "pairwise_evaluation": candidate["design"]["configuration"][
            "pairwise_evaluation"
        ],
        "repeat_consistent": candidate["report"]["repeat_consistency"]["consistent"],
    }
    protocol = {
        "subject_count": baseline["condition"]["subject_count"],
        "cycle_cap": baseline["condition"]["cycle_cap"],
        "repeats": baseline["design"]["protocol"]["repeats_per_condition"],
        "warmup_runs_per_repeat": baseline["design"]["protocol"][
            "warmup_runs_per_repeat"
        ],
    }
    if comparison_version == LEGACY_COMPARISON_VERSION:
        protocol["engine_implementation"] = baseline_engine
    else:
        baseline_record["engine_implementation"] = baseline_engine
        candidate_record["engine_implementation"] = candidate_engine
        protocol["baseline_engine_implementation"] = baseline_engine
        protocol["candidate_engine_implementation"] = candidate_engine
    result = {
        "comparison_version": comparison_version,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "baseline": baseline_record,
        "candidate": candidate_record,
        "protocol": protocol,
        "numerical_agreement": _numerical_agreement(
            baseline_samples,
            candidate_samples,
        ),
        "performance": _performance(baseline_samples, candidate_samples),
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    if comparison_version != LEGACY_COMPARISON_VERSION:
        result["comparison_dimension"] = dimension
    return result


def _render_html(comparison: dict[str, Any]) -> str:
    def optional_number(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.6g}"

    performance = comparison["performance"]
    agreement = comparison["numerical_agreement"]
    dimension = comparison.get("comparison_dimension", "pairwise_evaluation")
    baseline_engine = comparison["baseline"].get(
        "engine_implementation",
        comparison["protocol"].get("engine_implementation"),
    )
    candidate_engine = comparison["candidate"].get(
        "engine_implementation",
        comparison["protocol"].get("engine_implementation"),
    )
    if comparison["comparison_version"] == LEGACY_COMPARISON_VERSION:
        context_rows = (
            f"<ul><li>Subjects: {comparison['protocol']['subject_count']}; cycle cap:\n"
            f"{comparison['protocol']['cycle_cap']}; repeats: "
            f"{comparison['protocol']['repeats']}</li>"
        )
    else:
        context_rows = (
            f"<ul><li>Comparison dimension: {escape(dimension)}</li>\n"
            f"<li>Engine implementation: {escape(str(baseline_engine))} →\n"
            f"{escape(str(candidate_engine))}</li>\n"
            f"<li>Subjects: {comparison['protocol']['subject_count']}; cycle cap:\n"
            f"{comparison['protocol']['cycle_cap']}; repeats: "
            f"{comparison['protocol']['repeats']}</li>"
        )
    discrete_match = str(agreement["all_discrete_work_and_outcomes_match"]).lower()
    scalar_match = str(agreement["all_scalar_components_match_within_tolerance"]).lower()
    rows = "".join(
        "<tr>"
        f"<td>{escape(field)}</td>"
        f"<td>{performance['baseline'][field]['median']:.6g}</td>"
        f"<td>{performance['candidate'][field]['median']:.6g}</td>"
        "<td>"
        f"{optional_number(performance['candidate_to_baseline_median_ratios'][field])}"
        "</td>"
        "</tr>"
        for field in _PERFORMANCE_FIELDS
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Modern optimizer benchmark study comparison</title>
<style>body{{font:16px system-ui;max-width:1080px;margin:2rem auto;line-height:1.45}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:.4rem}}</style>
<h1>Modern optimizer benchmark study comparison</h1>
<p>{escape(comparison['scientific_boundary'])}</p>
{context_rows}
<li>Discrete work/outcomes match: {discrete_match}</li>
<li>Final scalar components match within 1e-12: 
{scalar_match}</li></ul>
<table><thead><tr><th>Measurement</th><th>Baseline median</th><th>Candidate median</th>
<th>Candidate / baseline</th></tr></thead><tbody>{rows}</tbody></table>
</html>\n"""


def write_modern_optimizer_benchmark_comparison(
    comparison: dict[str, Any],
    destination: Path | str,
) -> Path:
    output = Path(destination).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Optimizer comparison destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        json_path = temporary / COMPARISON_JSON_NAME
        json_path.write_text(_json_text(comparison), encoding="utf-8", newline="\n")
        (temporary / COMPARISON_HTML_NAME).write_text(
            _render_html(comparison),
            encoding="utf-8",
            newline="\n",
        )
        (temporary / COMPARISON_SIDECAR_NAME).write_text(
            f"{sha256_file(json_path)}  {COMPARISON_JSON_NAME}\n",
            encoding="ascii",
            newline="\n",
        )
        temporary.rename(output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return output


def compare_modern_optimizer_benchmark_studies(
    baseline_run: Path | str,
    candidate_run: Path | str,
    destination: Path | str,
    *,
    created_at: str | None = None,
) -> Path:
    comparison = collect_modern_optimizer_benchmark_comparison(
        baseline_run,
        candidate_run,
        created_at=created_at,
    )
    return write_modern_optimizer_benchmark_comparison(comparison, destination)


def verify_modern_optimizer_benchmark_comparison(
    directory: Path | str,
) -> dict[str, Any]:
    """Recompute and strictly verify a published optimizer-study comparison."""

    root = Path(directory).expanduser().resolve()
    expected_names = {
        COMPARISON_JSON_NAME,
        COMPARISON_SIDECAR_NAME,
        COMPARISON_HTML_NAME,
    }
    if (
        not root.is_dir()
        or root.is_symlink()
        or {path.name for path in root.iterdir()} != expected_names
        or any(
            not (root / name).is_file() or (root / name).is_symlink()
            for name in expected_names
        )
    ):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison directory has unexpected files"
        )
    json_path = root / COMPARISON_JSON_NAME
    expected_sidecar = f"{sha256_file(json_path)}  {COMPARISON_JSON_NAME}\n"
    if (root / COMPARISON_SIDECAR_NAME).read_text(encoding="ascii") != expected_sidecar:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison SHA-256 sidecar differs"
        )
    try:
        comparison = json.loads(json_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModernOptimizerBenchmarkComparisonError(
            f"Optimizer comparison is unreadable: {error}"
        ) from error
    if (
        not isinstance(comparison, dict)
        or comparison.get("comparison_version") not in SUPPORTED_COMPARISON_VERSIONS
        or not isinstance(comparison.get("created_at"), str)
        or not comparison["created_at"]
    ):
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison identity is invalid"
        )
    try:
        baseline = Path(comparison["baseline"]["path"])
        candidate = Path(comparison["candidate"]["path"])
    except (KeyError, TypeError) as error:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison source binding is invalid"
        ) from error
    with tempfile.TemporaryDirectory(prefix="diffeoforge-optimizer-comparison-verify-") as value:
        expected_root = Path(value) / "expected"
        expected = collect_modern_optimizer_benchmark_comparison(
            baseline,
            candidate,
            created_at=comparison["created_at"],
            comparison_version=comparison["comparison_version"],
        )
        write_modern_optimizer_benchmark_comparison(expected, expected_root)
        if comparison != expected:
            raise ModernOptimizerBenchmarkComparisonError(
                "Optimizer comparison differs from deterministic recomputation"
            )
        expected_html = (expected_root / COMPARISON_HTML_NAME).read_text(encoding="utf-8")
    if (root / COMPARISON_HTML_NAME).read_text(encoding="utf-8") != expected_html:
        raise ModernOptimizerBenchmarkComparisonError(
            "Optimizer comparison HTML differs from deterministic regeneration"
        )
    return comparison
