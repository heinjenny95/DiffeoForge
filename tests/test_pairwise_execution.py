from __future__ import annotations

import pytest

engine = pytest.importorskip("diffeoforge.engine")

PairwiseEvaluationPlan = engine.PairwiseEvaluationPlan


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
    assert plan.engine_id == "diffeoforge_modern_blockwise"


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
