"""Explicit pairwise-kernel execution plans shared by engine workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from typing import Any, Literal

from diffeoforge.engine.dense import GaussianTilePlan

ENGINE_IMPLEMENTATION_VERSION = "1.0"


@dataclass(frozen=True)
class PairwiseEvaluationPlan:
    """Declare dense or exact blockwise all-pairs kernel evaluation."""

    mode: Literal["dense", "blockwise"] = "dense"
    query_tile_size: int | None = None
    source_tile_size: int | None = None
    autograd_strategy: Literal["standard", "recompute"] = "standard"

    def __post_init__(self) -> None:
        if self.mode not in {"dense", "blockwise"}:
            raise ValueError("mode must be 'dense' or 'blockwise'")
        if self.mode == "dense":
            if self.query_tile_size is not None or self.source_tile_size is not None:
                raise ValueError("dense mode requires null query/source tile sizes")
            if self.autograd_strategy != "standard":
                raise ValueError("dense mode requires the standard autograd strategy")
            return
        if self.autograd_strategy not in {"standard", "recompute"}:
            raise ValueError("autograd_strategy must be 'standard' or 'recompute'")
        for name in ("query_tile_size", "source_tile_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise TypeError(f"blockwise {name} must be an integer")
            if int(value) < 1:
                raise ValueError(f"blockwise {name} must be at least 1")
            object.__setattr__(self, name, int(value))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PairwiseEvaluationPlan:
        """Construct a strict plan from the public configuration shape."""

        if not isinstance(value, Mapping):
            raise TypeError("pairwise_evaluation must be a mapping")
        required = {"mode", "query_tile_size", "source_tile_size"}
        if not required <= set(value) or not set(value) <= required | {"autograd_strategy"}:
            raise ValueError(
                "pairwise_evaluation must contain exactly mode, query_tile_size, "
                "source_tile_size, and optionally autograd_strategy"
            )
        return cls(
            mode=value["mode"],
            query_tile_size=value["query_tile_size"],
            source_tile_size=value["source_tile_size"],
            autograd_strategy=value.get("autograd_strategy", "standard"),
        )

    @property
    def gaussian_tile_plan(self) -> GaussianTilePlan | None:
        """Return the declared tile plan, or ``None`` for the dense oracle."""

        if self.mode == "dense":
            return None
        return GaussianTilePlan(
            query_rows=self.query_tile_size,
            source_rows=self.source_tile_size,
            autograd_strategy=self.autograd_strategy,
        )

    @property
    def engine_id(self) -> str:
        """Return the immutable engine identifier for this evaluation mode."""

        suffix = (
            "_recompute"
            if self.mode == "blockwise" and self.autograd_strategy == "recompute"
            else ""
        )
        return f"diffeoforge_modern_{self.mode}{suffix}"

    def as_manifest(self) -> dict[str, str | int | None]:
        """Return the exact JSON-compatible provenance record."""

        manifest: dict[str, str | int | None] = {
            "mode": self.mode,
            "query_tile_size": self.query_tile_size,
            "source_tile_size": self.source_tile_size,
        }
        if self.autograd_strategy != "standard":
            manifest["autograd_strategy"] = self.autograd_strategy
        return manifest
