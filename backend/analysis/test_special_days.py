"""Tests for special-day calendar and Gift Nifty premarket context."""

from __future__ import annotations

from datetime import date

from analysis.special_days import (
    analyze_gift_nifty,
    check_special_day,
    get_full_premarket_context,
    get_special_days_2026,
)


def _print_result(name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run_tests() -> None:
    # 1
    all_days = get_special_days_2026()
    _print_result("get_special_days_2026", len(all_days) > 20, f"count={len(all_days)}")

    # 2
    rbi_day = check_special_day(date(2026, 4, 9))
    _print_result(
        "check_special_day RBI day",
        rbi_day.get("is_special_day") is True and "RBI MPC Decision" in rbi_day.get("event", ""),
        str(rbi_day),
    )

    # 3
    eve = check_special_day(date(2026, 4, 8))
    _print_result(
        "check_special_day eve",
        eve.get("is_eve") is True,
        str(eve),
    )

    # 4
    normal = check_special_day(date(2026, 6, 15))
    _print_result(
        "check_special_day normal",
        normal.get("is_special_day") is False,
        str(normal),
    )

    # 5
    gb = analyze_gift_nifty({"pct_change": 1.5, "bias": "BULLISH"})
    _print_result("analyze_gift_nifty strong_bullish", gb.get("signal") == "strong_bullish", str(gb))

    # 6
    gs = analyze_gift_nifty({"pct_change": -1.2, "bias": "BEARISH"})
    _print_result("analyze_gift_nifty strong_bearish", gs.get("signal") == "strong_bearish", str(gs))

    # 7
    gn = analyze_gift_nifty({"pct_change": 0.2, "bias": "NEUTRAL"})
    _print_result("analyze_gift_nifty neutral", gn.get("signal") == "neutral", str(gn))

    # 8
    combo = get_full_premarket_context({"pct_change": 0.8, "bias": "BULLISH"}, check_date=date(2026, 4, 9))
    cpm = float(combo.get("combined_position_modifier", 0.0))
    _print_result(
        "full context special+bullish",
        0.3 <= cpm <= 1.2,
        f"combined_position_modifier={cpm}, context={combo}",
    )

    # 9
    combo_normal = get_full_premarket_context({"pct_change": 0.2, "bias": "NEUTRAL"}, check_date=date(2026, 6, 15))
    _print_result(
        "full context normal day",
        combo_normal.get("morning_alert", "") == "",
        str(combo_normal),
    )


if __name__ == "__main__":
    run_tests()
