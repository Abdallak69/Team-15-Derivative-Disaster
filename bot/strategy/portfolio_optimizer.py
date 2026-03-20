"""Portfolio optimization — inverse-vol weighting, Kelly constraint, position limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from bot.signals.sector_rotation import classify_symbol


_CASH_FLOORS: dict[str, float] = {
    "bull": 0.20,
    "ranging": 0.40,
    "bear": 0.50,
}


def normalize_weights(
    weights: Mapping[str, float],
    cash_floor: float = 0.0,
) -> dict[str, float]:
    """Scale positive weights to respect the configured cash floor."""
    positive_weights = {
        symbol: max(weight, 0.0)
        for symbol, weight in weights.items()
        if weight > 0
    }
    total_weight = sum(positive_weights.values())
    if total_weight <= 0 or cash_floor >= 1.0:
        return {}

    investable_fraction = 1.0 - max(cash_floor, 0.0)
    return {
        symbol: (weight / total_weight) * investable_fraction
        for symbol, weight in positive_weights.items()
    }


def _apply_inverse_vol_weighting(
    signal_weights: dict[str, float],
    volatilities: Mapping[str, float],
) -> dict[str, float]:
    """Re-weight using inverse-volatility: w_i = (S_i / sigma_i) / sum(S_j / sigma_j)."""
    scored: dict[str, float] = {}
    for symbol, raw_w in signal_weights.items():
        if raw_w <= 0:
            continue
        vol = volatilities.get(symbol, 0.0)
        if vol <= 0:
            scored[symbol] = raw_w
        else:
            scored[symbol] = raw_w / vol

    total = sum(scored.values())
    if total <= 0:
        return {}
    return {s: v / total for s, v in scored.items()}


def _apply_kelly_cap(
    weights: dict[str, float],
    max_position_pct: float = 0.10,
    win_rates: Mapping[str, float] | None = None,
    avg_win_loss: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Cap each position at half-Kelly / hard cap (whichever is tighter).

    kelly = 0.5 * ((win_rate * avg_win/avg_loss) - (1 - win_rate)) / (avg_win/avg_loss)
    Falls back to the flat hard cap when per-asset statistics are unavailable.
    """
    result: dict[str, float] = {}
    for s, w in weights.items():
        cap = max_position_pct
        if win_rates and avg_win_loss and s in win_rates and s in avg_win_loss:
            wr = win_rates[s]
            wl = avg_win_loss[s]
            if wl > 0:
                kelly = 0.5 * ((wr * wl - (1.0 - wr)) / wl)
                cap = min(max(kelly, 0.0), max_position_pct)
        result[s] = min(w, cap)
    return result


def _apply_sector_cap(
    weights: dict[str, float],
    max_sector_pct: float = 0.30,
) -> dict[str, float]:
    """Scale down sectors that exceed the concentration limit."""
    sector_totals: dict[str, float] = {}
    symbol_sectors: dict[str, str] = {}
    for symbol, w in weights.items():
        sector = classify_symbol(symbol)
        symbol_sectors[symbol] = sector
        sector_totals[sector] = sector_totals.get(sector, 0.0) + w

    result: dict[str, float] = {}
    for symbol, w in weights.items():
        sector = symbol_sectors[symbol]
        sector_total = sector_totals[sector]
        if sector_total > max_sector_pct and sector_total > 0:
            result[symbol] = w * (max_sector_pct / sector_total)
        else:
            result[symbol] = w
    return result


def _renormalize(weights: dict[str, float], investable: float) -> dict[str, float]:
    """Re-scale so weights sum to investable fraction after caps."""
    total = sum(weights.values())
    if total <= 0:
        return {}
    if total <= investable:
        return dict(weights)
    return {s: w * (investable / total) for s, w in weights.items()}


def optimize_weights(
    signal_weights: Mapping[str, float],
    *,
    volatilities: Mapping[str, float] | None = None,
    regime: str = "ranging",
    max_position_pct: float = 0.10,
    max_sector_pct: float = 0.30,
    cash_floor_overrides: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Full optimization pipeline: inverse-vol → Kelly cap → sector cap → cash floor.

    Returns {symbol: final_weight} that sums to at most (1 - cash_floor).
    """
    floors = dict(_CASH_FLOORS)
    if cash_floor_overrides:
        floors.update(cash_floor_overrides)
    cash_floor = floors.get(regime.lower(), floors.get("ranging", 0.40))
    investable = 1.0 - cash_floor

    positive = {s: w for s, w in signal_weights.items() if w > 0}
    if not positive:
        return {}

    if volatilities:
        weighted = _apply_inverse_vol_weighting(positive, volatilities)
    else:
        total = sum(positive.values())
        weighted = {s: w / total for s, w in positive.items()} if total > 0 else {}

    if not weighted:
        return {}

    scaled = {s: w * investable for s, w in weighted.items()}
    capped = _apply_kelly_cap(scaled, max_position_pct)
    sector_capped = _apply_sector_cap(capped, max_sector_pct)
    final = _renormalize(sector_capped, investable)
    return final


@dataclass(slots=True)
class PortfolioOptimizer:
    """Regime-aware portfolio optimizer with inverse-vol weighting and risk caps."""

    max_position_pct: float = 0.10
    max_sector_pct: float = 0.30
    cash_floor_bull: float = 0.20
    cash_floor_ranging: float = 0.40
    cash_floor_bear: float = 0.50

    def optimize(
        self,
        weights: Mapping[str, float],
        *,
        volatilities: Mapping[str, float] | None = None,
        regime: str = "ranging",
    ) -> dict[str, float]:
        """Return optimized weights respecting all constraints."""
        overrides = {
            "bull": self.cash_floor_bull,
            "ranging": self.cash_floor_ranging,
            "bear": self.cash_floor_bear,
        }
        return optimize_weights(
            weights,
            volatilities=volatilities,
            regime=regime,
            max_position_pct=self.max_position_pct,
            max_sector_pct=self.max_sector_pct,
            cash_floor_overrides=overrides,
        )
