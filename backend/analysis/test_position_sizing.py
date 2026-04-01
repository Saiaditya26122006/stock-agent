"""Validation checks for position sizing engine."""

from __future__ import annotations

from analysis.position_sizing import (
    calculate_portfolio_exposure,
    calculate_position_size,
    format_position_summary,
)


def _print_result(name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run_tests() -> None:
    # 1) Normal trade
    t1 = calculate_position_size(capital=50000, risk_score=8, entry_price=920, stop_loss=900)
    _print_result(
        "Normal trade",
        t1.get("action") == "trade" and int(t1.get("shares", 0)) > 0,
        f"action={t1.get('action')}, shares={t1.get('shares')}, value={t1.get('position_value')}",
    )

    # 2) High risk score trade
    t2 = calculate_position_size(capital=50000, risk_score=9.5, entry_price=500, stop_loss=480)
    _print_result(
        "High risk score trade",
        t2.get("action") == "trade" and float(t2.get("risk_pct_used", 0.0)) == 0.02,
        f"action={t2.get('action')}, risk_pct_used={t2.get('risk_pct_used')}",
    )

    # 3) Max positions reached
    t3 = calculate_position_size(
        capital=50000,
        risk_score=8,
        entry_price=920,
        stop_loss=900,
        open_positions_count=3,
    )
    _print_result(
        "Max positions reached",
        t3.get("action") == "skip" and t3.get("reason") == "max_positions_reached",
        f"action={t3.get('action')}, reason={t3.get('reason')}",
    )

    # 4) Max capital deployed
    t4 = calculate_position_size(
        capital=50000,
        risk_score=8,
        entry_price=920,
        stop_loss=900,
        capital_deployed=31000,
    )
    _print_result(
        "Max capital deployed",
        t4.get("action") == "skip" and t4.get("reason") == "max_capital_deployed",
        f"action={t4.get('action')}, reason={t4.get('reason')}",
    )

    # 5) Risk score too low
    t5 = calculate_position_size(capital=50000, risk_score=4.0, entry_price=920, stop_loss=900)
    _print_result(
        "Risk score too low",
        t5.get("action") == "skip" and t5.get("reason") == "risk_score_too_low",
        f"action={t5.get('action')}, reason={t5.get('reason')}",
    )

    # 6) Portfolio exposure calculation
    positions = [
        {"entry_price": 500, "shares": 10, "stock": "RELIANCE"},
        {"entry_price": 1000, "shares": 5, "stock": "TCS"},
    ]
    p = calculate_portfolio_exposure(positions, capital=50000)
    _print_result(
        "Portfolio exposure calculation",
        p.get("total_deployed") == 10000.0 and p.get("deployed_pct") == 20.0 and p.get("can_open_new") is True,
        f"total_deployed={p.get('total_deployed')}, deployed_pct={p.get('deployed_pct')}, can_open_new={p.get('can_open_new')}",
    )

    # 7) format_position_summary trade + skip
    trade_msg = format_position_summary(t1, "TCS")
    skip_msg = format_position_summary(t5, "INFY")
    _print_result(
        "format_position_summary",
        "Buy" in trade_msg and "Skipped" in skip_msg,
        f"trade_msg='{trade_msg}' | skip_msg='{skip_msg}'",
    )


if __name__ == "__main__":
    run_tests()
