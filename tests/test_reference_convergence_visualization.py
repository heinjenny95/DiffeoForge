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
