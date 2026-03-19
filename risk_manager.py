#Assumption 
snapshot = {
    "timestamp": ...,
    "total_portfolio_value_usd": ...,
    "cash_usd": ...,
    "positions": [
        {
            "pair": "BTC/USD",
            "quantity": ...,
            "entry_price": ...,
            "last_price": ...,
            "market_value_usd": ...
        }
    ]
}

stop_loss_pct = 0.03
daily_loss_limit = 0.02

def get_day_key(snapshot):
    return int(snapshot["timestamp"]) // 86400

def make_initial_state(snapshot):
    value = float(snapshot["total_portfolio_value_usd"])
    day_key = get_day_key(snapshot)

    return {
        "peak_value": value,
        "max_drawdown": 0.0,
        "day_key": day_key,
        "day_start_value": value,
        "daily_loss_hit_today": False,
        "paused_until": None,
        "highest_cb_triggered": 0,
        "pending_exit_pairs": [],
    }



def check_position_stop_losses(snapshot, state):
    forced_sells = []
    pending_exit_pairs = state["pending_exit_pairs"]

    for position in snapshot["positions"]:
        pair = position["pair"]

        if pair in pending_exit_pairs:
            continue

        entry_price = position["entry_price"]
        last_price = position["last_price"]

        if entry_price <= 0:
            continue

        pnl_pct = (last_price - entry_price) / entry_price

        if pnl_pct <= -stop_loss_pct:
            forced_sells.append({
                "pair": pair,
                "action": "SELL_FULL",
                "quantity": position["quantity"],
                "reason": "stop_loss",
            })
            pending_exit_pairs.append(pair)

    return forced_sells


def check_daily_loss(snapshot, state):
    current_value = snapshot["total_portfolio_value_usd"]
    day_start_value = state["day_start_value"]

    if day_start_value <= 0:
        return False

    daily_return = (current_value - day_start_value) / day_start_value
    if daily_return <= -daily_loss_limit:
        state["daily_loss_hit_today"] = True

    return state["daily_loss_hit_today"]

def rollover_day_if_needed(snapshot, state):
    day_key = get_day_key(snapshot)

    if day_key != state["day_key"]:
        state["day_key"] = day_key
        state["day_start_value"] = float(snapshot["total_portfolio_value_usd"])
        state["daily_loss_hit_today"] = False

def cleanup_pending_exit_pairs(snapshot, state):
    open_pairs = []

    for position in snapshot["positions"]:
        open_pairs.append(position["pair"])

    state["pending_exit_pairs"] = [
        pair for pair in state["pending_exit_pairs"]
        if pair in open_pairs
    ]

def evaluate_risk(snapshot, state):
    rollover_day_if_needed(snapshot, state)
    cleanup_pending_exit_pairs(snapshot, state)
    forced_sells = check_position_stop_losses(snapshot, state)
    block_new_buys = check_daily_loss(snapshot, state)

    return {
        "state": state,
        "forced_sells": forced_sells,
        "block_new_buys": block_new_buys,
    }
