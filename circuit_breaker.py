CIRCUIT_BREAKER_L1 = 0.03
CIRCUIT_BREAKER_L2 = 0.05

def update_drawdown(snapshot, state):
    value = snapshot["total_portfolio_value_usd"]

    if value > state["peak_value"]:
        state["peak_value"] = value
        state["highest_cb_triggered"] = 0

    current_drawdown = 0.0
    if state["peak_value"] > 0:
        current_drawdown = (state["peak_value"] - value) / state["peak_value"]

    state["max_drawdown"] = max(state["max_drawdown"], current_drawdown)

    return state, current_drawdown

def check_circuit_breaker(snapshot, state):
    state, current_drawdown = update_drawdown(snapshot, state)

    now = snapshot["timestamp"]
    action = None

    if current_drawdown >= CIRCUIT_BREAKER_L2 and state["highest_cb_triggered"] < 2:
        action = "LIQUIDATE_ALL"
        state["highest_cb_triggered"] = 2
        state["paused_until"] = now + 86400
    elif current_drawdown >= CIRCUIT_BREAKER_L1 and state["highest_cb_triggered"] < 1:
        action = "REDUCE_ALL_50"
        state["highest_cb_triggered"] = 1

    return state, action, current_drawdown

