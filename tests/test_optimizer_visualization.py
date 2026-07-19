from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from diffeoforge.analysis.optimizer_visualization import (  # noqa: E402
    write_optimizer_convergence_svg,
)
from diffeoforge.engine.atlas_optimizer import (  # noqa: E402
    AtlasOptimizationRecord,
    AtlasOptimizationResult,
    AtlasOptimizerSettings,
)


def _result() -> AtlasOptimizationResult:
    settings = AtlasOptimizerSettings(
        max_cycles=3,
        block_order=("momenta", "template", "control_points"),
        momenta_step_size=0.1,
        template_step_size=0.01,
        control_points_step_size=0.01,
        backtracking_factor=0.5,
        armijo_constant=1e-4,
        gradient_tolerance=1e-8,
        minimum_step_size=1e-12,
        max_line_search_iterations=20,
    )
    history = (
        AtlasOptimizationRecord(
            cycle=0,
            block=None,
            status="initial",
            objective=-12.0,
            attachment=-12.0,
            regularity=0.0,
            residuals=(0.2, 0.1),
            gradient_norm=None,
            accepted_step_size=None,
            line_search_evaluations=0,
        ),
        AtlasOptimizationRecord(
            cycle=1,
            block="momenta",
            status="accepted",
            objective=-7.5,
            attachment=-7.3,
            regularity=-0.2,
            residuals=(0.12, 0.08),
            gradient_norm=3.25,
            accepted_step_size=0.05,
            line_search_evaluations=2,
        ),
        AtlasOptimizationRecord(
            cycle=1,
            block="template",
            status="stationary",
            objective=-7.5,
            attachment=-7.3,
            regularity=-0.2,
            residuals=(0.12, 0.08),
            gradient_norm=5e-9,
            accepted_step_size=None,
            line_search_evaluations=0,
        ),
    )
    return AtlasOptimizationResult(
        template_vertices=torch.zeros((3, 3), dtype=torch.float64),
        control_points=torch.zeros((1, 3), dtype=torch.float64),
        momenta=torch.zeros((2, 1, 3), dtype=torch.float64),
        history=history,
        termination_reason="max_cycles",
        converged=False,
        failed_block=None,
        cycles_completed=1,
        total_line_search_evaluations=2,
        settings=settings,
    )


def test_optimizer_convergence_svg_is_deterministic_and_self_describing(
    tmp_path: Path,
) -> None:
    first = write_optimizer_convergence_svg(tmp_path / "first.svg", _result())
    second = write_optimizer_convergence_svg(tmp_path / "second.svg", _result())

    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert "Atlas optimizer convergence" in text
    assert "Termination: max_cycles" in text
    assert "tolerance 1e-08" in text
    assert "font-family: Arial" in text
    assert "<script" not in text.lower()
    assert "href=" not in text.lower()

    root = ET.parse(first).getroot()
    namespace = "{http://www.w3.org/2000/svg}"
    points = [
        element
        for element in root.iter()
        if element.tag == f"{namespace}circle" and element.attrib.get("class") == "objective-point"
    ]
    assert [point.attrib["data-history-index"] for point in points] == ["0", "1", "2"]
    assert [point.attrib["data-block"] for point in points] == [
        "initial",
        "momenta",
        "template",
    ]
    assert [float(point.attrib["data-attachment"]) for point in points] == [
        -12.0,
        -7.3,
        -7.3,
    ]
    gradient_points = [
        element
        for element in root.iter()
        if element.tag == f"{namespace}circle" and element.attrib.get("class") == "gradient-point"
    ]
    assert [point.attrib["data-history-index"] for point in gradient_points] == ["1", "2"]
    assert [float(point.attrib["data-gradient-norm"]) for point in gradient_points] == [
        3.25,
        5e-9,
    ]


def test_optimizer_convergence_svg_refuses_wrong_input(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="AtlasOptimizationResult"):
        write_optimizer_convergence_svg(tmp_path / "bad.svg", object())  # type: ignore[arg-type]
