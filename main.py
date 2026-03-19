from circuit_breaker import check_circuit_breaker
from risk_manager import evaluate_risk, make_initial_state

state = None

def run_risk_layer(snapshot, state):
    if state is None:
        state = make_initial_state(snapshot)

    if state["paused_until"] is not None and snapshot["timestamp"] < state["paused_until"]:
        return {
            "state": state,
            "cb_action": None,
            "current_drawdown": 0.0,
            "forced_sells": [],
            "block_new_buys": True,
        }

    state, cb_action, current_drawdown = check_circuit_breaker(snapshot, state)

    if cb_action is not None:
        return {
            "state": state,
            "cb_action": cb_action,
            "current_drawdown": current_drawdown,
            "forced_sells": [],
            "block_new_buys": True,
        }

    risk_result = evaluate_risk(snapshot, state)

    return {
        "state": risk_result["state"],
        "cb_action": None,
        "current_drawdown": current_drawdown,
        "forced_sells": risk_result["forced_sells"],
        "block_new_buys": risk_result["block_new_buys"],
    }

if __name__ == "__main__":
    snapshot = get_snapshot_somehow()
    result = run_risk_layer(snapshot, state)
    state = result["state"]

    # Orchestrator should:
    # 1. liquidate all if cb_action == "LIQUIDATE_ALL"
    # 2. reduce all positions if cb_action == "REDUCE_ALL_50"
    # 3. execute forced sells if forced_sells is not empty
    # 4. only allow new buys when block_new_buys is False

    print(result)

