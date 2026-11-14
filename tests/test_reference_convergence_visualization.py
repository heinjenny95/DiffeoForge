from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from diffeoforge.analysis.reference_convergence_visualization import (
    detect_reference_stop_evidence,
    write_reference_convergence_svg,
)
from diffeoforge.result_report import ConvergenceRow

SVG = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("message", [
    ">> CONVERGENCE: REL_REDUCTION_OF_F_<=_FACTR*EPSMCH",
    "2026-10-28 13:05:37 - native.scipy - INFO - >> CONVERGENCE: "
    "REL_REDUCTION_OF_F_<=_FACTR*EPSMCH",
    ">> CONVERGENCE: NORM_OF_PROJECTED_GRADIENT_<=_PGTOL",
])
def test_explicit_native_lbfgs_tolerance_is_recognized_separately(message):
    stop = detect_reference_stop_evidence(message, final_iteration=346, maximum_iterations=600)
    assert stop.signal == "lbfgs_tolerance"
    assert "does not establish" in stop.summary


@pytest.mark.parametrize("message", [
    "CONVERGENCE: REL_REDUCTION_OF_F_<=_FACTR*EPSMCH",  # Not the native emitter.
    ">> CONVERGENCE: unsupported criterion",
    "The process returned 0.",
])
def test_generic_completion_does_not_create_a_tolerance_claim(message):
    assert detect_reference_stop_evidence(
        message, final_iteration=346, maximum_iterations=600
    ).signal == "unknown"


@pytest.mark.parametrize("terminal,expected", [
    (">> Number of line search loops exceeded. Stopping.", "line_search_exhausted"),
    (">> STOP: PILOT REVIEW REQUEST (accepted state; not convergence)", "pilot_review_request"),
])
def test_lbfgs_text_cannot_hide_a_failure_or_explicit_review_stop(terminal, expected):
    message = ">> CONVERGENCE: REL_REDUCTION_OF_F_<=_FACTR*EPSMCH\n" + terminal
    assert detect_reference_stop_evidence(
        message, final_iteration=346, maximum_iterations=600
    ).signal == expected


def test_reference_convergence_svg_is_static_repeatable_and_bounded(tmp_path: Path) -> None:
    rows = (
        ConvergenceRow(0, -100.0, -95.0, -5.0),
        ConvergenceRow(1, -80.0, -74.0, -6.0),
        ConvergenceRow(2, -79.5, -73.0, -6.5),
    )
    stop = detect_reference_stop_evidence(
        "Tolerance threshold met. Stopping the optimization process.",
        final_iteration=2,
        maximum_iterations=100,
    )

    first = write_reference_convergence_svg(
        tmp_path / "first.svg",
        rows,
        maximum_iterations=100,
        duration_seconds=250.125,
        stop_evidence=stop,
    )
    second = write_reference_convergence_svg(
        tmp_path / "second.svg",
        rows,
        maximum_iterations=100,
        duration_seconds=250.125,
        stop_evidence=stop,
    )

    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert "last logged iteration 2 of maximum 100" in text
    assert "tolerance threshold" in text
    assert "not print the final accepted step" in text
    root = ET.parse(first).getroot()
    assert root.tag == f"{SVG}svg"
    assert not root.findall(f".//{SVG}script")


def test_reference_stop_evidence_does_not_infer_convergence_from_early_completion() -> None:
    evidence = detect_reference_stop_evidence(
        "Estimation took: 04 minutes and 03 seconds",
        final_iteration=32,
        maximum_iterations=100,
    )

    assert evidence.signal == "unknown"
    assert "does not establish convergence" in evidence.summary


def test_reference_convergence_svg_rejects_nonmonotonic_iterations(tmp_path: Path) -> None:
    stop = detect_reference_stop_evidence(
        "",
        final_iteration=0,
        maximum_iterations=10,
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        write_reference_convergence_svg(
            tmp_path / "bad.svg",
            (
                ConvergenceRow(0, -2.0, -1.0, -1.0),
                ConvergenceRow(0, -1.0, -0.5, -0.5),
            ),
            maximum_iterations=10,
            duration_seconds=1.0,
            stop_evidence=stop,
        )
