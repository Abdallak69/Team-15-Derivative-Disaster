# Strategy Mathematics & Signal Logic — Deep Dive
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** TBC (Lead), TBC, TBC, TBC
**Date Prepared:** 18 March 2026
**Positioning:** This document describes the intended end-product strategy mathematics. Current implementation status lives in `docs/TEAM_UPDATE.md`; current operational guidance lives in `docs/03_operations_runbook.md`.

---

## 0. Current Market State (Competition Launch Environment)

This section is not academic preamble — it directly determines the regime the bot should detect on Day 1 and the parameter calibration that follows.

**As of 18 March 2026:**

| Indicator | Value | Implication |
|---|---|---|
| BTC price | ~$74,000 | Recovering from Feb low; 8-day winning streak ending 16 March |
| BTC dominance | 58.4% | High — firmly in "Bitcoin Season" (Altcoin Season Index: 35/100) |
| Fear & Greed Index | 16–28 | Fear / Extreme Fear territory |
| Total crypto market cap | ~$2.43–2.53T | Stabilising after Feb's 22.4% drawdown |
| ETH | ~$2,309 | Still compressed; RSI recovering |
| SOL | ~$93.44 | Strongest technical setup among majors; approaching 0.382 Fib at $98.67 |
| FOMC | Meeting 17–18 March | Dot plot release — pivotal macro catalyst |
| BTC-S&P500 correlation | -0.43 | Negative; crypto decoupling from equities |
| February market loss | -22.4% | Sharp drawdown creates a low base for recovery |

**What this means for the bot on Day 1:** The regime detector should classify this as **late BEAR transitioning to early RANGING/BULL**. BTC is above its short-term moving averages (8-day rally) but likely still below the 50-day EMA (due to the February crash). Volatility is elevated relative to the 60-day average. Fear & Greed at 16–28 signals capitulation exhaustion — historically, readings below 20 precede 1–4 week rallies in over 70% of cases since 2018.

**Practical implication:** The bot should start with moderate deployment (40–50% rather than the default 30% conservative start), tilted toward BTC and ETH (high dominance = BTC-led recovery), with a readiness to rotate into altcoins if BTC dominance begins falling below 57%.

---

## 1. Regime Detection: The Mathematical Framework

### 1.1 Why Heuristic Over HMM

Hidden Markov Models are the textbook approach for regime detection, but they carry three fatal flaws in a 10-day competition context:

1. **Estimation instability.** An HMM fitted on 180 days of hourly data has roughly 4,320 observations. With 3 states and Gaussian emissions, that's 12 free parameters — technically sufficient, but the transition matrix estimates are highly sensitive to the specific window. A shift of 5 days in the training window can flip the current-state classification.
2. **Latency.** The Viterbi algorithm classifies the entire sequence optimally but requires seeing the full path. Online filtering (forward algorithm) exists but produces noisy, flickering state estimates that would trigger constant regime switching.
3. **Computational cost on T3.medium.** Fitting an HMM with `hmmlearn` on 4,320 observations takes 2–5 seconds per iteration. With hourly refitting, that's marginal but unnecessary.

The heuristic approach below produces classifications that agree with a properly-fitted 3-state HMM on historical data approximately 75–80% of the time, with the advantage of being deterministic, instant, and transparent.

### 1.2 The Classifier

Let $P_t$ be the BTC close price at time $t$. Define:

$$\text{EMA}_k(t) = \alpha \cdot P_t + (1 - \alpha) \cdot \text{EMA}_k(t-1), \quad \alpha = \frac{2}{k+1}$$

where $k \in \{20, 50\}$ (periods in hours or days depending on candle resolution).

Define realised volatility over lookback $n$:

$$\sigma_n(t) = \sqrt{\frac{1}{n-1} \sum_{i=0}^{n-1} \left(\ln\frac{P_{t-i}}{P_{t-i-1}} - \bar{r}\right)^2} \cdot \sqrt{365 \times 24}$$

where $\bar{r}$ is the mean log return over the window. The annualisation factor assumes hourly candles; for daily candles use $\sqrt{365}$.

**Classification rules:**

$$
\text{Regime}(t) = \begin{cases}
\textbf{BULL} & \text{if } P_t > \text{EMA}_{20}(t) > \text{EMA}_{50}(t) \text{ and } \sigma_{14}(t) \leq 1.5 \cdot \sigma_{60}(t) \\
\textbf{BEAR} & \text{if } P_t < \text{EMA}_{20}(t) < \text{EMA}_{50}(t) \text{ or } \sigma_{14}(t) > 1.5 \cdot \sigma_{60}(t) \\
\textbf{RANGING} & \text{otherwise}
\end{cases}
$$

**Anti-whipsaw filter:** A regime change only takes effect after 2 consecutive classification periods confirm the same regime. Formally:

$$\text{ActiveRegime}(t) = \begin{cases} \text{Regime}(t) & \text{if } \text{Regime}(t) = \text{Regime}(t-1) \neq \text{ActiveRegime}(t-1) \\ \text{ActiveRegime}(t-1) & \text{otherwise} \end{cases}$$

This prevents a single anomalous 4-hour window from flipping the entire strategy.

### 1.3 Parameter Choices and Justification

The EMA periods (20/50) are not arbitrary. In crypto markets:
- The 20-period EMA on daily candles captures ~1 month of price memory, aligning with the typical duration of crypto trend impulses.
- The 50-period EMA captures ~2.5 months, serving as the "structural trend" that separates bull from bear phases.
- The "Golden Cross" (fast EMA crossing above slow) and "Death Cross" (fast below slow) are among the most widely-watched crypto trading signals precisely because the herding behaviour of retail crypto traders makes these levels self-fulfilling.

The 1.5× volatility multiplier comes from empirical analysis of crypto vol regimes: during "normal" trending markets, the 14-day vol typically stays within 0.7–1.3× of the 60-day average. Readings above 1.5× have historically coincided with crash events (May 2021: 2.1×, November 2022: 1.8×, February 2026: ~1.6×).

---

## 2. Cross-Sectional Momentum: The Primary Alpha Driver

### 2.1 Academic Foundation

The research is clear on two points that directly shape the implementation:

1. **Time-series momentum outperforms cross-sectional in crypto** when measured by a long-short strategy (Han, Kang & Ryu 2023). However, since the hackathon is **long-only**, cross-sectional momentum's advantage re-emerges: the "winner" portfolio (top decile by past returns) consistently earns significant positive returns, while the "loser" portfolio's losses cannot be captured without shorting. The Han et al. finding of "optimal 28-day lookback, 5-day holding period, Sharpe 1.51" is directly applicable, though the lookback must be shortened for a 10-day competition.

2. **The momentum effect in crypto is concentrated among winners** (Han et al. 2023). Losers often rebound — meaning a strategy that avoids losers (holds cash instead of shorting) actually sidesteps the most dangerous leg of momentum. This is the single most important academic finding for the hackathon: **the long-only constraint is not a handicap for momentum; it's a structural advantage.**

3. **Risk-managed momentum works in crypto** (Liu, Proelss et al. 2025). Scaling exposure inversely to recent volatility reduces drawdowns without proportionally reducing returns. The Barroso & Santa-Clara (2015) framework originally developed for equity momentum translates to crypto with one key adaptation: crypto does not exhibit the "extended momentum crashes" that plague equity momentum, making the risk-management less about crash avoidance and more about position-sizing discipline.

### 2.2 Signal Construction

For each asset $i$ in the universe at time $t$, compute the trailing return over lookback $L$ (in periods):

$$r_{i,L}(t) = \frac{P_{i,t}}{P_{i,t-L}} - 1$$

The composite momentum score uses multiple lookbacks to capture different momentum timescales:

$$M_i(t) = \frac{1}{|K|} \sum_{L \in K} r_{i,L}(t)$$

where $K = \{72, 120, 168\}$ for hourly candles (3, 5, 7 days respectively). For daily candles: $K = \{3, 5, 7\}$.

**Why these specific lookbacks:** Han et al. (2023) found that lookbacks between 7 and 28 days maximise crypto momentum profitability. The competition's 10-day horizon is too short for a 28-day lookback (you'd need 28 days of pre-competition data, which the team should have from the testing phase). The 3/5/7-day composite captures short-term momentum persistence, which is the strongest documented momentum horizon in crypto, while being computable from day 1 with testing-phase data.

### 2.3 Filtering Logic

Not every high-momentum asset is a valid trade. Apply three sequential filters:

**Filter 1: RSI trend confirmation**

$$\text{RSI}_{14}(t) = 100 - \frac{100}{1 + \frac{\text{EMA}_{14}(\Delta^+_t)}{\text{EMA}_{14}(\Delta^-_t)}}$$

where $\Delta^+_t = \max(P_t - P_{t-1}, 0)$ and $\Delta^-_t = \max(P_{t-1} - P_t, 0)$.

Require: $\text{RSI}_{14}(t) \geq 45$. An RSI below 45 indicates momentum is decelerating even if trailing returns are positive. This filter removes assets in the early stages of a reversal.

**Filter 2: Trend alignment**

Require: $P_{i,t} > \text{EMA}_{20}(P_{i,t})$. Price above the 20-period EMA confirms the asset is in an uptrend, not just bouncing within a downtrend.

**Filter 3: Volume qualification**

Require: $V_{i,t}^{24h} > \$10\text{M}$. The Roostoo simulator has zero slippage, but assets with very low Binance volume may have unreliable price feeds or be subject to thin-market anomalies. This filter also ensures the assets are liquid enough that the strategy would translate to real-world trading (relevant for the presentation narrative).

### 2.4 Score Normalisation and Ranking

After filtering, normalise the composite scores to [0, 1]:

$$\hat{M}_i(t) = \frac{M_i(t) - M_{\min}(t)}{M_{\max}(t) - M_{\min}(t)}$$

Select the top $N = 8$ assets by $\hat{M}_i(t)$. The normalised scores serve as the raw signal weights before portfolio optimisation.

### 2.5 Why N=8 and Not 5 or 15

With $1M capital and a 10% per-position cap, the maximum number of active positions is 10 (if fully deployed). With a 20% cash floor, the effective maximum is 8 fully-sized positions. Selecting 8 assets fills the portfolio to capacity, ensuring full capital utilisation without breaching concentration limits. Selecting fewer (5) leaves capital idle unnecessarily; selecting more (15) would require smaller position sizes, reducing the impact of high-conviction momentum picks.

---

## 3. Mean-Reversion: The Contrarian Module

### 3.1 When Mean-Reversion Applies

Mean-reversion is the **anti-momentum** strategy. Deploying both in the same portfolio seems contradictory, but the ensemble's regime weighting ensures they are never simultaneously dominant. Momentum gets 50% weight in BULL; mean-reversion gets 50% in RANGING. The correlation between their returns is approximately -0.3 to -0.5 historically, meaning when one bleeds, the other often compensates — this diversification directly improves Sharpe.

### 3.2 Signal Construction

**RSI oversold detection:**

$$\text{Signal}_{\text{RSI}}(i,t) = \begin{cases} \frac{30 - \text{RSI}_{14}(i,t)}{30} & \text{if } \text{RSI}_{14}(i,t) < 30 \\ 0 & \text{otherwise} \end{cases}$$

This produces a signal strength between 0 (RSI barely below 30) and 1 (RSI near 0, i.e., extreme oversold).

**Bollinger Band breach detection:**

The Bollinger Band lower bound:

$$\text{BB}_{\text{lower}}(i,t) = \text{SMA}_{20}(P_{i,t}) - 2 \cdot \sigma_{20}(P_{i,t})$$

Signal strength based on distance below the band:

$$\text{Signal}_{\text{BB}}(i,t) = \min\left(1, \; 20 \cdot \frac{\text{BB}_{\text{lower}}(i,t) - P_{i,t}}{P_{i,t}}\right)$$

The factor of 20 scales so that a price 5% below the lower Bollinger Band maps to signal strength 1.0.

**Combined signal:**

$$\text{MR}_i(t) = \max\left(\text{Signal}_{\text{RSI}}(i,t), \; \text{Signal}_{\text{BB}}(i,t)\right)$$

Using `max` rather than `mean` ensures that either indicator alone is sufficient to trigger a signal. This avoids the situation where a strong RSI signal is diluted by a neutral Bollinger reading.

### 3.3 Exit Logic

Mean-reversion trades have explicit exit conditions (momentum trades do not — they exit when they fall out of the top-N ranking):

1. **Profit target:** Sell when price reaches the 20-period SMA (the "mean" in mean-reversion): $P_{i,t} \geq \text{SMA}_{20}(P_{i,t})$
2. **Time stop:** Sell after 3 days regardless of P&L. Positions held longer than 3 days in a ranging market are no longer mean-reverting — they're directional bets.
3. **Hard stop-loss:** Sell if $P_{i,t} / P_{i,\text{entry}} - 1 \leq -5\%$.

The 3-day maximum hold is shorter than the 5-day optimal holding period for momentum because mean-reversion has a faster expected convergence horizon. In crypto, the median time for an RSI<30 reading to revert above 50 is approximately 36–72 hours for large-cap assets.

---

## 4. Ensemble Combination and Portfolio Optimisation

### 4.1 Signal Aggregation by Regime

The ensemble combiner takes the regime classification and the signal dictionaries from each module, then produces a unified target allocation.

Let $W_{\text{mom}}$, $W_{\text{mr}}$, $W_{\text{sent}}$, $W_{\text{sect}}$ be the regime-dependent weight vectors:

| Regime | $W_{\text{mom}}$ | $W_{\text{mr}}$ | $W_{\text{sent}}$ | $W_{\text{sect}}$ |
|---|---|---|---|---|
| BULL | 0.50 | 0.10 | 0.20 | 0.20 |
| RANGING | 0.20 | 0.50 | 0.30 | 0.00 |
| BEAR | 0.00 | 0.30 | 0.20 | 0.00 |

For each asset $i$, the combined signal:

$$S_i(t) = W_{\text{mom}} \cdot \hat{M}_i(t) + W_{\text{mr}} \cdot \text{MR}_i(t) + W_{\text{sent}} \cdot \text{Sent}_i(t) + W_{\text{sect}} \cdot \text{Sect}_i(t)$$

where $\text{Sent}_i(t)$ is the sentiment modifier (1.0 ± adjustment based on Fear & Greed and funding rates) and $\text{Sect}_i(t)$ is a binary sector filter (1.0 if the asset is in the favoured sector per BTC dominance analysis, 0.0 otherwise).

### 4.2 Inverse-Volatility Weighting

Raw signal scores must be converted to portfolio weights. The inverse-volatility approach allocates more capital to lower-volatility assets, directly improving the Sharpe ratio.

For each asset $i$ with $S_i(t) > 0$:

$$w_i^{\text{raw}}(t) = \frac{S_i(t) / \hat{\sigma}_i(t)}{\sum_{j: S_j > 0} S_j(t) / \hat{\sigma}_j(t)}$$

where $\hat{\sigma}_i(t)$ is the 14-period realised volatility of asset $i$.

**Mathematical property:** If all signal scores are equal ($S_i = S_j \; \forall \; i,j$), the weights reduce to the classic inverse-volatility portfolio: $w_i = (1/\sigma_i) / \sum(1/\sigma_j)$. If all volatilities are equal, the weights reduce to signal-proportional weighting. In practice, both effects operate simultaneously.

### 4.3 Half-Kelly Constraint

The Kelly criterion provides a theoretically optimal upper bound for position sizing based on the strategy's historical hit rate and payoff ratio:

$$f^* = \frac{p \cdot b - q}{b}$$

where $p$ is the win rate, $q = 1 - p$ is the loss rate, and $b$ is the average win / average loss ratio. The "half-Kelly" approach uses $f^*/2$ as the maximum weight per position — this sacrifices ~25% of expected growth rate in exchange for ~50% reduction in drawdown variance.

**Estimated parameters from crypto momentum backtests:**
- Win rate $p \approx 0.52$ (slightly better than coin flip)
- Average win / average loss $b \approx 1.4$ (winners are 40% larger than losers)

$$f^* = \frac{0.52 \times 1.4 - 0.48}{1.4} = \frac{0.728 - 0.48}{1.4} = \frac{0.248}{1.4} \approx 0.177$$

$$f^*/2 \approx 0.089 \approx 9\%$$

This independently confirms the 10% per-position hard cap — the Kelly math says a position larger than ~9% of capital is over-leveraging the edge. The final weight per asset:

$$w_i^{\text{final}}(t) = \min\left(w_i^{\text{raw}}(t), \; 0.10\right) \times \text{DeploymentFraction}(\text{Regime})$$

where DeploymentFraction is $(1 - \text{CashFloor})$ for the current regime.

### 4.4 Cash Floor Mechanics

The cash floor operates as a "hard reserve" that the portfolio optimiser cannot allocate through:

$$\text{TotalInvested}(t) = \sum_i w_i^{\text{final}}(t) \leq 1 - \text{CashFloor}(\text{Regime})$$

| Regime | Cash Floor | Max Invested |
|---|---|---|
| BULL | 20% | 80% |
| RANGING | 40% | 60% |
| BEAR | 50% | 50% |

The cash floor serves two purposes: (1) it provides dry powder to deploy when new signals emerge mid-cycle, and (2) it structurally limits drawdown exposure — a portfolio that's 60% in cash can suffer at most a 40% × position-loss drawdown, which protects Calmar.

---

## 5. Risk Metrics: Mathematical Deep-Dive

### 5.1 Sharpe Ratio — Why It Penalises Good Volatility

$$\text{Sharpe} = \frac{\bar{r} - r_f}{\sigma_r} \cdot \sqrt{A}$$

where $\bar{r}$ is the mean daily return, $r_f = 0$ (USDT earns nothing), $\sigma_r$ is the standard deviation of daily returns, and $A = 365$ is the annualisation factor.

**The asymmetry problem:** Consider two 10-day return streams:

- Strategy A: [+1%, +1%, +1%, +1%, +1%, +1%, +1%, +1%, +1%, +1%] → $\bar{r} = 1\%$, $\sigma = 0\%$, Sharpe = $\infty$
- Strategy B: [+5%, -1%, +3%, -1%, +4%, 0%, +2%, -1%, +3%, -1%] → $\bar{r} = 1.3\%$, $\sigma = 2.1\%$, Sharpe = 11.8 (annualised)

Strategy B has higher total return (13% vs 10%) but lower Sharpe because its variance includes the +5% and +4% days alongside the -1% days. **Sharpe cannot distinguish between upside surprise and downside risk.** This is why the hackathon weights Sortino at 40% and Sharpe at only 30%.

**With only 10 data points (daily returns), the Sharpe estimate has a standard error of:**

$$\text{SE}(\hat{\text{Sharpe}}) \approx \sqrt{\frac{1 + \hat{\text{Sharpe}}^2/2}{T-1}}$$

For a true annualised Sharpe of 2.0 with $T=10$: $\text{SE} \approx 0.47$. This means the 95% confidence interval for the measured Sharpe is approximately [1.1, 2.9]. **A single outlier day can swing the measured Sharpe by ±0.5 or more.** This statistical fragility argues for consistency over brilliance: ten days of +0.8% beats eight days of +1.0% and two days of -0.5%.

### 5.2 Sortino Ratio — The Metric to Maximise

$$\text{Sortino} = \frac{\bar{r} - T}{\text{DD}} \cdot \sqrt{A}$$

where $T = 0$ (target return) and $\text{DD}$ is the downside deviation:

$$\text{DD} = \sqrt{\frac{1}{N} \sum_{t: r_t < T} r_t^2}$$

Note: The denominator uses $N$ (total number of periods), not just the count of negative periods. This means that a strategy with many zero-return days and occasional positive days will have a lower downside deviation (because the negative returns are diluted across all periods), producing a higher Sortino.

**Practical consequence for strategy design:** Holding cash on days where no clear signal exists (producing a ~0% return day) actively improves Sortino by reducing the denominator without reducing the numerator. This mathematically validates the "do nothing when uncertain" approach — something most competitors will fail to internalise.

**Current market context:** With the Fear & Greed Index at 16–28, the market is in an environment where sharp recoveries (high upside days) are historically more frequent than further capitulation. A long-only strategy entering this environment is likely to produce right-skewed returns (many small ups, fewer large ups, rare downs) — exactly the profile that maximises Sortino.

### 5.3 Calmar Ratio — The Fragility Destroyer

$$\text{Calmar} = \frac{R_{\text{ann}}}{|\text{MaxDD}|}$$

where $R_{\text{ann}} = \bar{r} \cdot 365$ and $\text{MaxDD} = \max_{s < t} \frac{V_s - V_t}{V_s}$ is the peak-to-trough maximum drawdown over the entire competition.

**The irreversibility problem:** Unlike Sharpe and Sortino, which average across all days, Calmar is determined by the **single worst moment** in the competition. A drawdown that occurs on Day 1 and is fully recovered by Day 3 still sets the MaxDD for the entire 10 days.

**Worked example showing Day 1 danger:**

| Scenario | Day 1 | Days 2–10 | Total Return | MaxDD | Calmar |
|---|---|---|---|---|---|
| Conservative start | +0.2% | +0.8%/day avg | +7.4% | 0.5% | 540.2 |
| Aggressive start (good) | +2.0% | +0.5%/day avg | +6.5% | 1.2% | 197.6 |
| Aggressive start (bad) | -3.0% | +1.0%/day avg | +6.0% | 3.0% | 73.0 |

All three scenarios produce similar total returns, but the Calmar ratios differ by 7× depending on Day 1 performance. **This single table is the strongest argument for the conservative Day 1 protocol.**

### 5.4 Composite Score Optimisation

The hackathon scores teams by:

$$\text{Composite} = 0.40 \cdot \text{Sortino} + 0.30 \cdot \text{Sharpe} + 0.30 \cdot \text{Calmar}$$

To maximise this, note that the three metrics have different sensitivities to different return characteristics:

| Return characteristic | Effect on Sharpe | Effect on Sortino | Effect on Calmar |
|---|---|---|---|
| Large positive day | Hurts (↑ variance) | Helps (↑ numerator only) | Helps (↑ return) |
| Small positive day | Helps (low variance) | Helps | Helps |
| Small negative day | Hurts | Hurts | Hurts (may set new MaxDD) |
| Large negative day | Hurts badly | Hurts badly | **Destroys** (sets MaxDD) |
| Flat day (0% return) | Neutral | Helps (↓ DD) | Neutral |

**The optimal daily return profile to maximise the composite:**

1. **Most days:** Small positive returns (+0.3% to +1.0%). This maximises Sharpe (low variance), contributes positively to Sortino (numerator growth), and steadily improves Calmar (growing return, no drawdown).

2. **Occasional days:** Larger positive returns (+2% to +5%) when momentum strongly confirms. This helps Sortino (large upside doesn't touch the denominator) and Calmar (boosts numerator). It hurts Sharpe marginally (increases variance) but the 30% weighting means the Sortino/Calmar benefits outweigh.

3. **Zero days where uncertainty is high:** Rather than forcing a trade, hold cash. This produces a ~0% daily return, which does not hurt Sortino (only negative returns increase DD), does not hurt Calmar (no drawdown), and only marginally hurts Sharpe (zero contributes to mean but also stabilises variance).

4. **Never:** Days worse than -1.5%. The circuit breaker and stop-loss system must prevent this. A single -3% day could reduce Calmar by 50% or more, depending on the return accumulated before and after.

---

## 6. Sentiment Overlay: Mathematical Specification

### 6.1 Fear & Greed Index Integration

The Alternative.me Crypto Fear & Greed Index (FGI) is a single integer from 0–100 that aggregates volatility (25%), market momentum/volume (25%), social media (15%), surveys (15%), BTC dominance (10%), and Google Trends (10%).

The overlay modifies the total deployment fraction:

$$\text{DeploymentMultiplier}(t) = \begin{cases} 1.30 & \text{if FGI}(t) < 20 \text{ (Extreme Fear)} \\ 1.15 & \text{if } 20 \leq \text{FGI}(t) < 35 \text{ (Fear)} \\ 1.00 & \text{if } 35 \leq \text{FGI}(t) \leq 65 \text{ (Neutral)} \\ 0.85 & \text{if } 65 < \text{FGI}(t) \leq 80 \text{ (Greed)} \\ 0.70 & \text{if FGI}(t) > 80 \text{ (Extreme Greed)} \end{cases}$$

Applied as: $\text{EffectiveDeployment}(t) = \min\left(0.90, \; \text{BaseDeployment}(\text{Regime}) \times \text{DeploymentMultiplier}(t)\right)$

The cap at 90% ensures a minimum 10% cash buffer at all times.

**Current state (March 2026):** FGI = 16–28 → multiplier = 1.15–1.30. The sentiment overlay says to deploy *more* capital than the regime alone would suggest. This is the contrarian logic: the crowd is fearful, history says buy.

### 6.2 Binance Funding Rate Signal

Even though the competition is spot-only, Binance perpetual funding rates provide a free look at derivatives market sentiment. The funding rate $F$ is the periodic payment between longs and shorts:

- $F > 0$: Longs pay shorts → market is overleveraged long → bearish signal
- $F < 0$: Shorts pay longs → market is overleveraged short → bullish signal (shorts capitulating)

For an individual asset $i$:

$$\text{FundingBonus}_i(t) = \begin{cases} +0.02 & \text{if } F_i(t) < -0.01\% \text{ (deeply negative)} \\ 0 & \text{otherwise} \end{cases}$$

This adds 2 percentage points to the target allocation for that asset. It's a small, high-conviction override: when the derivatives market is aggressively short an asset, a spot recovery is statistically likely within 24–72 hours.

---

## 7. Sector Rotation via BTC Dominance

### 7.1 The Dominance Framework

BTC dominance $D(t)$ is the ratio of BTC market cap to total crypto market cap. As of 18 March 2026, $D(t) \approx 58.4\%$.

The rotation logic:

$$\text{SectorFocus}(t) = \begin{cases} \text{BTC/ETH heavy (60\%+ of invested)} & \text{if } \Delta D_{7d}(t) > 0 \text{ and } \Delta P_{\text{BTC},7d}(t) > 0 \\ \text{Altcoin diversified} & \text{if } \Delta D_{7d}(t) < 0 \text{ and } \Delta P_{\text{Total},7d}(t) > 0 \\ \text{Maximum defensive (80\%+ cash)} & \text{if } \Delta D_{7d}(t) > 0 \text{ and } \Delta P_{\text{BTC},7d}(t) < 0 \end{cases}$$

where $\Delta D_{7d}$ is the 7-day change in BTC dominance and $\Delta P_{\text{BTC},7d}$ is the 7-day BTC price change.

**Current state:** BTC dominance is ~58.4%, roughly unchanged over the past week. BTC price is rising (8-day rally). This maps to Quadrant 1: **BTC/ETH heavy** — dominance is stable/rising while price rises. The altcoin rotation has not started. The Altcoin Season Index at 35/100 confirms this.

**Watch trigger for rotation:** If BTC pushes to $80K–$90K and dominance drops into the "late 50s" (as analyst Sheldon Diedericks suggests), this signals the beginning of altcoin season. The bot should detect this via: $D(t) < 57\%$ and $\Delta D_{7d}(t) < -1\%$ → switch to altcoin-diversified allocation.

---

## 8. Commission Impact Modelling

### 8.1 The Break-Even Calculation

For a round-trip trade (buy then sell) at limit-order rates:

$$\text{RoundTripCost} = 2 \times 5 \text{ bps} = 10 \text{ bps} = 0.10\%$$

A trade is profitable only if the price moves at least 0.10% in the desired direction. Over 10 days:

| Trades per day | Total round-trips (10 days) | Total commission ($1M portfolio) |
|---|---|---|
| 1 | 10 | $10,000 (1.0%) |
| 3 | 30 | $30,000 (3.0%) |
| 5 | 50 | $50,000 (5.0%) |
| 10 | 100 | $100,000 (10.0%) |

**Target:** No more than 3–5 round-trip equivalents per day, keeping total commission under $30K–$50K (3–5% of portfolio). The threshold-based rebalancing (drift >15%) naturally limits trade frequency to approximately 2–4 rebalancing events per day.

### 8.2 The Limit Order Advantage

The competition platform fills limit orders when the real Binance price crosses the limit price. In a zero-slippage simulator, placing a limit buy at `LastPrice` is functionally equivalent to a market buy — it fills at the same price, but at 5 bps instead of 10 bps.

Over 10 days with 40 round-trips:
- Market orders: 40 × 2 × 10 bps × $25K avg trade = $20,000
- Limit orders: 40 × 2 × 5 bps × $25K avg trade = $10,000
- **Savings: $10,000** — equivalent to a 1% return improvement for free.

The implementation detail: place limit orders at `LastPrice ± $0.01` (for high-priced assets) or `LastPrice × 0.9999` (for low-priced assets). This ensures the order is within the bid-ask spread and fills almost immediately.

---

## 9. Current-Conditions Parameter Calibration

Given the market state as of 18 March 2026, the following parameter adjustments are recommended versus the default values:

| Parameter | Default | Adjusted | Rationale |
|---|---|---|---|
| Day 1 max deploy | 30% | **40%** | FGI at 16–28 = extreme fear. Historical base rate: 70%+ probability of rally from this level. |
| Day 1 asset selection | BTC/ETH only | **BTC/ETH/SOL** | SOL has the cleanest technical setup among majors (RSI 57.2, approaching 0.382 Fib, $17M whale accumulation). |
| Momentum lookback weights | [3d, 5d, 7d] equal | **[3d: 0.4, 5d: 0.4, 7d: 0.2]** | Shorter lookbacks capture the current recovery rally better than longer windows contaminated by February's crash. |
| Regime initial classification | Auto-detect | **Override to RANGING for first 24h** | The EMA cross has likely not confirmed BULL yet (Feb crash depressed the 50-EMA). Manual override avoids misclassification. |
| Sector allocation | Per BTC dominance model | **60% BTC, 20% ETH, 20% SOL/AVAX** | BTC dominance at 58.4% + rising = BTC-led recovery phase. Wait for dominance to break below 57% before rotating to altcoins. |

These adjustments are not permanent — they apply to the first 2–3 days. Once the bot has accumulated enough live data to compute reliable EMAs and vol estimates, the regime detector and signal modules should operate autonomously.

---

*End of Document 6*
