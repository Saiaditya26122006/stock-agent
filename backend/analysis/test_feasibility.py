"""Smoke tests for target feasibility checker."""

from __future__ import annotations

from analysis.feasibility import (
    check_target_feasibility,
    format_feasibility_for_briefing,
    get_india_vix,
    get_market_regime,
)


def _print_result(test_name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {test_name}: {detail}")


def run_tests() -> None:
    # 1) Normal regime test
    normal = check_target_feasibility(
        capital=50000,
        daily_target=2000,
        india_vix=12.0,
        signal_dicts=[{"atr": {"pct_of_price": 2.3}}],
    )
    _print_result(
        "Normal regime test",
        normal.get("market_regime") == "NORMAL",
        str(normal),
    )

    # 2) Caution regime test
    caution = check_target_feasibility(
        capital=50000,
        daily_target=2000,
        india_vix=17.0,
        signal_dicts=[{"atr": {"pct_of_price": 2.3}}],
    )
    _print_result(
        "Caution regime test",
        caution.get("market_regime") == "CAUTION" and float(caution.get("adjusted_target", 0)) < 2000.0,
        f"market_regime={caution.get('market_regime')}, adjusted_target={caution.get('adjusted_target')}",
    )

    # 3) Danger regime test
    danger = check_target_feasibility(
        capital=50000,
        daily_target=2000,
        india_vix=22.0,
        signal_dicts=[{"atr": {"pct_of_price": 2.3}}],
    )
    _print_result(
        "Danger regime test",
        danger.get("market_regime") == "DANGER" and danger.get("is_achievable") is False,
        f"market_regime={danger.get('market_regime')}, is_achievable={danger.get('is_achievable')}",
    )

    # 4) get_market_regime tests
    r1 = get_market_regime(12.0)
    r2 = get_market_regime(17.0)
    r3 = get_market_regime(22.0)
    _print_result("get_market_regime(12.0)", r1 == "NORMAL", f"returned {r1}")
    _print_result("get_market_regime(17.0)", r2 == "CAUTION", f"returned {r2}")
    _print_result("get_market_regime(22.0)", r3 == "DANGER", f"returned {r3}")

    # 5) Live VIX fetch test
    live_vix = get_india_vix()
    _print_result(
        "Live VIX fetch",
        isinstance(live_vix, float) and live_vix > 0,
        f"live_vix={live_vix}",
    )

    # 6) format_feasibility_for_briefing test
    briefing = format_feasibility_for_briefing(caution)
    _print_result(
        "format_feasibility_for_briefing",
        isinstance(briefing, str) and bool(briefing.strip()),
        briefing,
    )


if __name__ == "__main__":
    run_tests()
