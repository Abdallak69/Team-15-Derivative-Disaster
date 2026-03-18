# Strategy Research & Selection
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** Abdalla (Lead), Sami, Oscar, Wilson
**Date Prepared:** 18 March 2026

---

## 1. Strategy Selection Criteria

Any candidate strategy must satisfy all of the following hard constraints simultaneously:

1. **Long-only** — no shorting, no leverage, no derivatives. Bearish expression is limited to holding USD.
2. **Spot crypto** — 66 USDT-paired assets, all with real Binance price feeds.
3. **Autonomous execution** — no manual intervention for 10 days.
4. **Commission-aware** — 10 bps market / 5 bps limit. High-frequency approaches are economically unviable.
5. **Resource-constrained** — T3.medium (2 vCPU, 4GB RAM). No GPU. No heavy ML training at runtime.
6. **Metric-optimised** — the scoring formula (40% Sortino, 30% Sharpe, 30% Calmar) explicitly rewards asymmetric upside with controlled drawdowns, not raw return maximisation.

---

## 2. Strategies Evaluated

### 2.1 Trend-Following / Cross-Sectional Momentum

**Mechanism:** Rank all 66 assets by trailing N-day returns. Allocate capital to the top K performers. Rebalance daily or when signal strength changes materially.

**Fit with constraints:**
- Long-only compatible: allocate to winners, hold USD for losers. ✅
- Low trade frequency: 1–3 rebalances per day at most. ✅
- Commission impact: ~1–2% over 10 days with limit orders. ✅
- Compute requirements: trivial. ✅

**Historical performance in crypto:**
Cross-sectional momentum in crypto has demonstrated annualised Sharpe ratios between 0.5 and 1.5 in trending markets. Crypto is one of the strongest asset classes for momentum due to herding behaviour and information cascading. A 2024 study by Continoue Capital found that a simple top-decile momentum strategy on crypto returned 180% annualised versus a buy-and-hold benchmark of 85%.

**Weaknesses:**
- Momentum crashes: sudden reversals (e.g., regulatory news, exchange collapses) cause concentrated losses. Crypto momentum has historically experienced ~3–5 sharp reversals per year.
- In ranging/choppy markets, momentum generates whipsaw losses as signals alternate rapidly.
- With a 10-day horizon, there may not be enough time for momentum to develop if the market enters a consolidation phase.

**Sortino profile:** Favourable. Momentum strategies generate right-skewed returns (many small losses from stopped-out trades, occasional large winners from sustained trends). This naturally produces high Sortino ratios.

**Verdict:** ✅ **Primary strategy component.** Best in trending markets.

---

### 2.2 Mean-Reversion (Single-Asset)

**Mechanism:** Buy when price drops below a statistical threshold (e.g., RSI < 30, price below lower Bollinger Band at 2σ). Sell at mean or upper band.

**Fit with constraints:**
- Long-only compatible: buy dips, sell at mean. ✅
- Low frequency: trades triggered by statistical extremes only. ✅
- Compute: trivial. ✅

**Historical performance in crypto:**
Mean-reversion works poorly as a standalone strategy in crypto over multi-day horizons because crypto has strong trend persistence. RSI < 30 in crypto often precedes further declines rather than reversals (unlike equities where mean-reversion is stronger). However, on intraday timeframes (1h–4h candles), mean-reversion performs better — bounces from intraday lows are more reliable.

**Weaknesses:**
- "Catching a falling knife" risk — buying an asset that is declining because of fundamental deterioration, not mean-reversion.
- In a 10-day competition, a mean-reversion trade that enters on Day 2 and hasn't reverted by Day 10 is a locked-in loss.
- Requires careful pair selection and stop-losses to prevent catastrophic drawdowns.

**Sortino profile:** Mixed. The strategy can produce large downside events (failed reversions), which directly damage Sortino.

**Verdict:** ⚠️ **Secondary component only.** Use in ranging markets as a complement to momentum, never as the primary driver.

---

### 2.3 Pairs Trading / Capital Rotation

**Mechanism:** Identify cointegrated asset pairs (e.g., BTC/ETH, SOL/AVAX). When the spread diverges beyond a threshold, sell the outperformer for USD and buy the underperformer, capturing convergence.

**Fit with constraints:**
- Long-only compatible via "capital rotation": sell A → hold USD → buy B. Not a true simultaneous short-long, but captures spread convergence through relative reweighting. ✅
- Low frequency: trades triggered only at statistical extremes. ✅

**Historical performance in crypto:**
Crypto pairs trading research from 2022–2025 shows mixed results. Cointegration relationships in crypto are less stable than in equities due to protocol upgrades, token unlocks, and narrative shifts. The half-life of mean-reversion for crypto pairs tends to be 2–7 days — which fits the 10-day competition window. Annualised Sharpe for well-selected crypto pairs: 1.0–2.0.

**Weaknesses:**
- Cointegration breakdown: the relationship between two assets can permanently shift during the competition.
- Without true shorting, the "rotation" approach captures only half the profit of a proper pairs trade.
- Requires pre-competition statistical work to identify valid pairs (ADF test, Engle-Granger) using historical Binance data.

**Sortino profile:** Good. Pairs trading produces relatively symmetric returns, but the absence of true shorting reduces downside protection.

**Verdict:** ⚠️ **Tertiary component.** Worth including if pre-competition backtesting confirms stable pairs exist in the 66-asset universe.

---

### 2.4 Sentiment-Driven Trading

**Mechanism:** Use external data (Fear & Greed Index, funding rates, social media metrics, news sentiment) to time entries and exits. Buy on Extreme Fear, reduce on Extreme Greed.

**Fit with constraints:**
- Long-only compatible: sentiment determines position sizing and timing. ✅
- Very low frequency: Fear & Greed Index updates daily; funding rates update every 8 hours. ✅
- Compute: API calls to external services. ✅

**Historical performance in crypto:**
The Alternative.me Fear & Greed Index has demonstrated predictive power for medium-term (1–4 week) crypto returns. Buying at Extreme Fear (<20) and selling at Extreme Greed (>80) has historically produced annualised returns of 60–120% with Sharpe ratios of 0.3–0.7. Binance perpetual funding rates show that deeply negative funding (shorts paying longs) precedes upward mean-reversion in spot markets within 24–72 hours.

**Weaknesses:**
- Sentiment indicators are lagging — by the time Fear & Greed drops to 20, the price has already fallen significantly.
- In a 10-day window, there may only be 1–2 actionable sentiment signals, limiting the strategy's contribution.
- Noisy standalone — Sharpe < 1.0 as a pure strategy.

**Sortino profile:** Neutral. Timing entries on extreme fear tends to produce good risk-adjusted entries, but the signal is too sparse for consistent contribution.

**Verdict:** ⚠️ **Overlay only.** Use as a position-sizing modifier on top of momentum/mean-reversion, never as the sole signal.

---

### 2.5 Grid Trading

**Mechanism:** Place buy orders at fixed price intervals below current price and sell orders above. Profits from range-bound oscillation.

**Fit with constraints:**
- Long-only compatible (buy-side grid only). ✅
- Commission impact: **Severe.** Grid trading generates high trade counts by design. At 5 bps per limit trade, a grid bot with 20 levels executing 5–10 round-trips per day would burn 2.5–5.0% in commissions over 10 days. ❌
- Requires ranging market; large directional moves cause either opportunity cost (upside) or bag-holding (downside). ❌

**Sortino profile:** Poor. Grid trading produces symmetric, thin-margin returns with occasional large drawdowns when trends break through the grid.

**Verdict:** ❌ **Rejected.** Commission structure makes this uneconomical, and the risk profile directly conflicts with the Sortino/Calmar scoring.

---

### 2.6 High-Frequency Scalping

**Mechanism:** Exploit micro-price movements with rapid entries and exits.

**Fit with constraints:**
- API rate limit of 30–60 calls/minute (and potentially 1 trade/minute) makes true HFT impossible. ❌
- Commission of 5–10 bps per trade makes scalping for 1–5 bps of alpha negative-EV. ❌
- T3.medium latency to Roostoo's server is ~1–50ms depending on routing — acceptable but not competitive. ❌

**Verdict:** ❌ **Rejected categorically.** The platform is not designed for this. The Alpha Arena AI Competition 2025 showed that DeepSeek's 92% long-biased, 35-hour average hold strategy crushed Gemini's hyperactive 238-trade approach.

---

### 2.7 Buy-and-Hold (Passive Benchmark)

**Mechanism:** Allocate $1M across BTC, ETH, and a diversified altcoin basket on Day 1. Hold for 10 days.

**Fit with constraints:**
- Fully compliant with all rules. ✅
- Zero commission cost (one entry trade). ✅

**Analysis:**
This is the baseline that any active strategy must beat. If BTC rallies 8% over 10 days, a 100% BTC allocation returns $80K with zero effort. The risk is that if crypto enters a bear phase during the competition, buy-and-hold produces maximum drawdown with no defensive mechanism.

**Sortino profile:** Entirely market-dependent. In a bull market, buy-and-hold produces a high Sortino (steady appreciation, low downside). In a bear market, it produces the worst possible Calmar (large drawdown, no recovery mechanism).

**Verdict:** ⚠️ **Useful as a benchmark and as a fallback component.** A portion of the portfolio (20–40%) should be allocated to a buy-and-hold "core" in BTC/ETH, with the active strategy managing the remaining "satellite" positions.

---

## 3. Selected Strategy: Regime-Adaptive Ensemble

Based on the evaluation above, the optimal approach is a **multi-module ensemble** that dynamically weights sub-strategies based on detected market regime:

### 3.1 Core Design Principle

The 40/30/30 Sortino/Sharpe/Calmar scoring means:
- **Sortino (40%)** rewards asymmetric upside: many small losses, occasional large wins.
- **Sharpe (30%)** rewards consistency: low variance of daily returns.
- **Calmar (30%)** penalises a single bad day: one 8% drawdown permanently damages the score.

The ideal return profile: **+0.3% to +1.0% on most days, never worse than -1.5% on any day, with occasional +2–5% days when momentum confirms.** Target over 10 days: **+5% to +15% total return, max drawdown under 3%.**

### 3.2 Regime Detection (The Meta-Strategy)

Use a heuristic classifier based on BTC (as market proxy) rather than a fragile statistical model:

**Bull Regime:**
- BTC price > 20-period EMA > 50-period EMA
- 14-day realised volatility ≤ 1.5× 60-day average volatility
- **Action:** Deploy 70–90% of capital. Weight momentum signals highest.

**Ranging Regime:**
- BTC price oscillating around EMAs (no clear trend)
- Volatility at or below average
- **Action:** Deploy 40–60% of capital. Weight mean-reversion and pairs signals highest.

**Bear/Crisis Regime:**
- BTC price < 20-period EMA < 50-period EMA, OR volatility spike > 1.5× average
- **Action:** Deploy 10–30% of capital. Hold majority in USD. Only act on extreme oversold signals.

Re-evaluate every 4 hours. Require 2+ consecutive confirmations before switching regimes (anti-whipsaw).

### 3.3 Sub-Strategy Weights by Regime

| Sub-Strategy | Bull | Ranging | Bear |
|---|---|---|---|
| Cross-sectional momentum | **50%** | 20% | 0% |
| Mean-reversion / pairs | 10% | **50%** | 30% |
| Sentiment overlay | 20% | 30% | 20% |
| BTC dominance / sector rotation | **20%** | 0% | 0% |
| Cash floor (minimum) | 10% | 40% | **50%** |

### 3.4 Signal Generation Detail

**Momentum Module:**
- Rank all 66 assets by 3-day, 5-day, and 7-day trailing returns (equally weighted composite)
- Filter: only assets with RSI(14) > 45, MACD histogram > 0, and price > 20-period EMA pass
- Select top 5–8 assets after filtering
- Weight within the allocation by signal strength (normalised composite rank)

**Mean-Reversion Module:**
- Trigger: RSI(14) < 30 OR price below lower 2σ Bollinger Band (20-period, 2 std dev)
- Additional filter: 24h volume must exceed $10M USD (avoid illiquid assets where "oversold" may reflect delisting risk)
- Entry: limit buy at LastPrice
- Exit: limit sell at 20-period moving average or after 3 days (whichever comes first)
- Hard stop-loss: -5% from entry

**Sentiment Module (Position-Sizing Overlay):**
- Fear & Greed Index < 25: multiply total allocation by 1.3× (aggressive deployment)
- Fear & Greed Index 25–75: no modification
- Fear & Greed Index > 75: multiply total allocation by 0.7× (defensive)
- Binance funding rate deeply negative (< -0.01%) for a specific asset: add 2% allocation bonus to that asset

**Sector Rotation Module:**
- BTC dominance rising + BTC price rising: concentrate 60% of invested capital in BTC/ETH
- BTC dominance falling + total crypto market cap rising: "altcoin season" — spread across DeFi (AAVE, UNI, SUSHI), L1 chains (SOL, AVAX, DOT), and top-momentum mid-caps
- BTC dominance rising + BTC price falling: maximum defensive — 80%+ USD

### 3.5 Position Sizing: Inverse-Volatility with Kelly Constraint

For each selected asset:

```
raw_weight_i = (1 / vol_i) / sum(1 / vol_j for all j in selected assets)
kelly_upper_bound = 0.5 × ((win_rate × avg_win / avg_loss) - (1 - win_rate)) / (avg_win / avg_loss)
final_weight_i = min(raw_weight_i, kelly_upper_bound, 0.10)  # hard cap at 10% per position
```

This automatically allocates more capital to lower-volatility assets (reducing portfolio variance → improving Sharpe) while capping concentration risk (protecting Calmar).

**Cash floor:** Maintain a minimum of 20% in USD at all times during Bull regime, 40% in Ranging, 50% in Bear.

### 3.6 Rebalancing Protocol

Rebalance when any position drifts **>15% from target weight** rather than on a fixed schedule. This reduces unnecessary trading (commission savings) while maintaining portfolio alignment. Research shows 15% threshold rebalancing outperforms fixed-schedule approaches by 77 bps annually.

Use **limit orders exclusively** for rebalancing. Place at `LastPrice ± 0.01%` (tight enough to fill quickly in a zero-slippage simulator, sufficient to qualify as a limit order and receive the 5 bps rate).

### 3.7 Risk Management Rules (Non-Negotiable)

| Rule | Threshold | Action |
|---|---|---|
| Per-position stop-loss | -3% from entry (or 2× ATR, whichever is tighter) | Sell to USD immediately |
| Per-position profit target | +8% from entry | Sell 50% to lock profit, trail remainder |
| Portfolio circuit breaker Level 1 | Total drawdown reaches -3% | Cut all positions by 50% |
| Portfolio circuit breaker Level 2 | Total drawdown reaches -5% | Sell everything to USD; wait 24h before re-entering |
| Maximum single position | 10% of portfolio | Hard cap in position sizing |
| Maximum sector concentration | 30% in any one sector (e.g., "L1 chains") | Diversification enforcement |
| Daily P&L limit (loss) | -2% in one calendar day | Pause all new entries until next day |

### 3.8 Day 1 Protocol (Calmar Protection)

Day 1 is the most dangerous day for Calmar ratio. An early drawdown sets a permanent floor on max drawdown that can never be erased.

**Day 1 rules:**
- Deploy maximum 30% of portfolio
- Use only BTC and ETH (highest liquidity, lowest idiosyncratic risk)
- All positions entered via limit orders
- Tighter stop-losses: -2% instead of -3%
- Run the regime detector for 6+ hours before committing to full-weight deployment
- Gradually scale from 30% to full allocation over Days 1–3

---

## 4. Backtesting Plan

Before the competition starts, use Binance historical kline data (free, publicly available) to backtest:

1. **Momentum rankings** — compute trailing 3/5/7-day returns across the full 66-asset universe for the past 90 days. Measure: hit rate, average win/loss ratio, Sharpe, Sortino.
2. **Mean-reversion triggers** — identify RSI<30 and Bollinger Band breach events. Measure: reversion probability, average reversion time, profit factor.
3. **Regime detection accuracy** — apply the EMA/volatility heuristic to the past 90 days. Measure: how often the regime classification was "correct" (i.e., momentum worked in "Bull" regime, mean-reversion worked in "Ranging" regime).
4. **Full ensemble simulation** — combine all modules with the proposed weights. Compute 10-day rolling Sharpe, Sortino, and Calmar. Optimise weights on training set, validate on hold-out.

**Target backtesting period:** 180 days (90 train / 90 validate).
**Data source:** Binance API (`GET /api/v3/klines`) for all 66 assets at 1-hour and 1-day intervals.

---

## 5. Why This Strategy Wins

Most competing teams will fall into one of these traps:

1. **Over-trading:** High-frequency bots that generate hundreds of trades, haemorrhaging commissions and producing volatile P&L that destroys Sharpe/Sortino.
2. **Single-strategy rigidity:** A momentum-only bot that fails when the market ranges, or a mean-reversion bot that bleeds in a trending market.
3. **No risk management:** Concentrated bets that produce a spectacular 20% return OR a devastating -15% drawdown. The Calmar scoring makes this a losing proposition.
4. **No external data:** Relying solely on the Roostoo ticker, missing sentiment signals that provide early warning of regime changes.
5. **Poor engineering:** Bots that crash on Day 4 and lose 6 days of trading. The "must trade at least 8 of 10 days" rule makes reliability a hard constraint.

The regime-adaptive ensemble avoids all five traps. It trades infrequently (commission-efficient), adapts to market conditions (regime switching), protects capital ruthlessly (layered risk management), integrates external intelligence (sentiment overlay), and is designed for 10-day unattended operation (systemd, state persistence, crash recovery).

---

*End of Document 2*
