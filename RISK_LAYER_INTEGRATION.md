# Risk Layer Integration

## Purpose

This part of the repo owns only the risk layer:

- per-position stop-loss at `-3%`
- daily loss block for new buys at `-2%`
- portfolio circuit breaker:
  - L1 at `-3%` drawdown -> `REDUCE_ALL_50`
  - L2 at `-5%` drawdown -> `LIQUIDATE_ALL` and pause for 24h

It does not place orders by itself. It only returns decisions for the orchestrator / executor.

## Not Covered Here

This layer does not implement execution.

The merged bot still needs the execution / orchestration side to cooperate with these decisions:

- `forced_sells` must be sent to the executor
- `LIQUIDATE_ALL` must map to a real sell-all action
- `REDUCE_ALL_50` must map to a real reduce-position action
- `block_new_buys = True` must be respected by the strategy / order-placement flow
- the returned `state` must be saved and reused next cycle

## Files

- `risk_manager.py`
  - stop-loss logic
  - daily loss block
  - day rollover reset
  - `pending_exit_pairs` maintenance
- `circuit_breaker.py`
  - peak tracking
  - drawdown tracking
  - L1 / L2 trigger logic
  - 24h pause after L2
- `main.py`
  - exposes `run_risk_layer(snapshot, state)`

## Required Input

The orchestrator should call:

```python
from main import run_risk_layer
```

with:

```python
snapshot = {
    "timestamp": 1710000000,  # Unix seconds, numeric
    "total_portfolio_value_usd": 1000000.0,
    "cash_usd": 250000.0,
    "positions": [
        {
            "pair": "BTC/USD",
            "quantity": 1.5,
            "entry_price": 100.0,
            "last_price": 96.5,
            "market_value_usd": 144750.0,
        }
    ],
}
```

Notes:

- `timestamp` should be Unix seconds, not an ISO string.
- `positions` can be an empty list.
- only the fields above are required by the current risk code.

## State Shape

If no state exists yet, pass `None`.

The risk layer will initialize this state:

```python
{
    "peak_value": 1000000.0,
    "max_drawdown": 0.0,
    "day_key": 19791,
    "day_start_value": 1000000.0,
    "daily_loss_hit_today": False,
    "paused_until": None,
    "highest_cb_triggered": 0,
    "pending_exit_pairs": [],
}
```

Meaning:

- `peak_value`: highest portfolio value seen so far
- `max_drawdown`: worst drawdown seen so far
- `day_key`: current day bucket from `timestamp // 86400`
- `day_start_value`: portfolio value at start of day
- `daily_loss_hit_today`: once `True`, new buys stay blocked until next day
- `paused_until`: Unix time until re-entry is blocked
- `highest_cb_triggered`: `0`, `1`, or `2`
- `pending_exit_pairs`: pairs already marked for forced exit, to avoid duplicate stop-loss sells

## How To Call

Minimal orchestrator usage:

```python
result = run_risk_layer(snapshot, state)
state = result["state"]
```

Then handle the result in this order:

```python
if result["cb_action"] == "LIQUIDATE_ALL":
    execute_liquidate_all(snapshot)
elif result["cb_action"] == "REDUCE_ALL_50":
    execute_reduce_all_50(snapshot)
elif result["forced_sells"]:
    execute_forced_sells(result["forced_sells"])
elif not result["block_new_buys"]:
    run_strategy_and_place_buys(snapshot, state)
```

This order matters:

1. circuit breaker first
2. forced stop-loss sells second
3. new buys only if not blocked

## Output

`run_risk_layer(snapshot, state)` returns:

```python
{
    "state": updated_state,
    "cb_action": None or "REDUCE_ALL_50" or "LIQUIDATE_ALL",
    "current_drawdown": 0.0,
    "forced_sells": [
        {
            "pair": "BTC/USD",
            "action": "SELL_FULL",
            "quantity": 1.5,
            "reason": "stop_loss",
        }
    ],
    "block_new_buys": False,
}
```

Rules:

- if `cb_action` is not `None`, it has priority over normal risk output
- during pause, the function returns:
  - `cb_action = None`
  - `forced_sells = []`
  - `block_new_buys = True`

## Current Behavior

### Stop-loss

- triggers when `(last_price - entry_price) / entry_price <= -0.03`
- returns one full-sell instruction
- adds the pair to `pending_exit_pairs`
- does not repeat the sell next cycle if the pair is still pending

### Pending Exit Cleanup

- if a pair disappears from `snapshot["positions"]`, it is removed from `pending_exit_pairs`
- this is how duplicate-exit protection resets after the sell is completed externally

### Daily Loss Block

- compares current portfolio value to `day_start_value`
- if daily return is `<= -0.02`, new buys are blocked
- the block resets automatically when the day changes

### Circuit Breaker

- `peak_value` updates whenever portfolio value makes a new high
- drawdown is calculated from `peak_value`
- `highest_cb_triggered` prevents repeated L1 / L2 firing every cycle
- a new peak resets `highest_cb_triggered` to `0`
- L2 sets `paused_until = timestamp + 86400`

## Merge Notes

- The intended import for teammates is `from main import run_risk_layer`
- The executor / strategy layer should remain outside this risk code
- The returned `state` should be persisted by the main bot between cycles
- If your merged bot already has a different orchestrator file, move or re-export `run_risk_layer` there, but keep this return format unchanged
