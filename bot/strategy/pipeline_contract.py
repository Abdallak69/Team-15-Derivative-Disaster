"""Strategy runtime contract — pipeline stage readiness checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyPipelineStage:
    """Describe one stage of the eventual live trading pipeline."""

    name: str
    implemented: bool
    summary: str


def current_strategy_pipeline() -> tuple[StrategyPipelineStage, ...]:
    """Return the current project-level view of runtime strategy readiness."""
    return (
        StrategyPipelineStage(
            name="market_data_polling",
            implemented=True,
            summary="Local polling, persistence, and Binance research backfills are wired.",
        ),
        StrategyPipelineStage(
            name="state_reconciliation",
            implemented=True,
            summary="Balance, pending-order, drawdown, and heartbeat state are reconciled.",
        ),
        StrategyPipelineStage(
            name="signal_generation",
            implemented=True,
            summary="Momentum, mean-reversion, pairs rotation, and sector rotation signals are implemented.",
        ),
        StrategyPipelineStage(
            name="ensemble_weighting",
            implemented=True,
            summary="Regime-dependent signal blending (bull/ranging/bear weights) is implemented.",
        ),
        StrategyPipelineStage(
            name="risk_gating",
            implemented=True,
            summary="Portfolio drawdown gates, buy blocking, and forced-exit decisions are reconciled into runtime state.",
        ),
        StrategyPipelineStage(
            name="rebalance_planning",
            implemented=True,
            summary="Weight-to-order conversion with precision, drift filtering, and sell-first ordering is wired.",
        ),
        StrategyPipelineStage(
            name="live_execution",
            implemented=True,
            summary="Order placement via API with inter-order spacing and trade logging is implemented.",
        ),
    )


def summarize_strategy_pipeline_gaps() -> tuple[str, ...]:
    """Summarize the missing stages that still block live trading."""
    return tuple(
        f"{stage.name}: {stage.summary}"
        for stage in current_strategy_pipeline()
        if not stage.implemented
    )


def strategy_pipeline_ready() -> bool:
    """Return whether every stage required for live trading is implemented."""
    return all(stage.implemented for stage in current_strategy_pipeline())
