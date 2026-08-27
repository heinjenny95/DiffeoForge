from __future__ import annotations

import pytest

engine = pytest.importorskip("diffeoforge.engine")
from diffeoforge.engine.execution import (  # noqa: E402
    ENGINE_IMPLEMENTATION_VERSION,
    supports_exact_engine_resume,
)

PairwiseEvaluationPlan = engine.PairwiseEvaluationPlan


def test_exact_resume_compatibility_is_explicit_and_fail_closed() -> None:
    assert supports_exact_engine_resume(ENGINE_IMPLEMENTATION_VERSION) is True
    assert supports_exact_engine_resume("1.6") is True
    assert supports_exact_engine_resume("1.5") is True
    assert supports_exact_engine_resume("1.4") is False
    assert supports_exact_engine_resume(
        ENGINE_IMPLEMENTATION_VERSION,
        successor_implementation="99.0",
    ) is False
    assert supports_exact_engine_resume(None) is False


def test_dense_plan_is_explicit_and_has_no_gaussian_tiles() -> None:
    plan = PairwiseEvaluationPlan()

    assert plan.as_manifest() == {
        "mode": "dense",
        "query_tile_size": None,
        "source_tile_size": None,
    }
    assert plan.gaussian_tile_plan is None
    assert plan.engine_id == "diffeoforge_modern_dense"


def test_blockwise_plan_normalizes_and_constructs_gaussian_tiles() -> None:
    plan = PairwiseEvaluationPlan.from_mapping(
        {
            "mode": "blockwise",
            "query_tile_size": 17,
            "source_tile_size": 23,
        }
    )

    assert plan.gaussian_tile_plan.query_rows == 17
    assert plan.gaussian_tile_plan.source_rows == 23
    assert plan.gaussian_tile_plan.autograd_strategy == "standard"
    assert plan.engine_id == "diffeoforge_modern_blockwise"


def test_blockwise_recompute_plan_is_explicit_in_execution_identity() -> None:
    plan = PairwiseEvaluationPlan.from_mapping(
        {
            "mode": "blockwise",
            "query_tile_size": 17,
            "source_tile_size": 23,
            "autograd_strategy": "recompute",
        }
    )

    assert plan.gaussian_tile_plan.autograd_strategy == "recompute"
    assert plan.engine_id == "diffeoforge_modern_blockwise_recompute"
    assert plan.as_manifest()["autograd_strategy"] == "recompute"


@pytest.mark.parametrize(
    "arguments",
    [
        {"mode": "automatic"},
        {"mode": "dense", "query_tile_size": 1},
        {"mode": "blockwise"},
        {"mode": "blockwise", "query_tile_size": 0, "source_tile_size": 1},
        {"mode": "blockwise", "query_tile_size": True, "source_tile_size": 1},
    ],
)
def test_invalid_execution_plan_combinations_fail(arguments: dict) -> None:
    with pytest.raises((TypeError, ValueError)):
        PairwiseEvaluationPlan(**arguments)


def test_mapping_rejects_missing_or_extra_fields() -> None:
    with pytest.raises(ValueError, match="exactly"):
        PairwiseEvaluationPlan.from_mapping({"mode": "dense"})
    with pytest.raises(ValueError, match="exactly"):
        PairwiseEvaluationPlan.from_mapping(
            {
                "mode": "dense",
                "query_tile_size": None,
                "source_tile_size": None,
                "automatic": True,
            }
        )
