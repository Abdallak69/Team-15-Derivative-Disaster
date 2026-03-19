"""Current strategy runtime contract for the project skeleton."""

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
            implemented=False,
            summary="Live risk reduction and order-level gating are not enforced yet.",
        ),
        StrategyPipelineStage(
            name="rebalance_planning",
            implemented=False,
            summary="Runtime target-weight to order-planning flow is not wired yet.",
        ),
        StrategyPipelineStage(
            name="live_execution",
            implemented=False,
            summary="Production order submission remains intentionally disabled.",
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
