"""Tests for pre-trade gate engine."""

from __future__ import annotations

from analysis.gates import (
    format_gate_result_for_log,
    run_all_gates,
    run_gate_2_liquidity,
    run_gate_3_event_risk,
    run_gate_5_volatility,
)


def _print_result(name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run_tests() -> None:
    # 1) Gate 1 fail: at circuit
    t1 = run_all_gates(
        symbol="RELIANCE",
        signal_dict={"volume_ratio": 1.0},
        sentiment_score=0.1,
        circuit_data={"at_circuit": True},
        announcements=[],
    )
    _print_result(
        "Gate 1 circuit fail",
        t1.get("passed") is False and t1.get("failed_gate") == 1,
        f"passed={t1.get('passed')}, failed_gate={t1.get('failed_gate')}",
    )

    # 2) Gate 2 fail: low volume ratio
    t2 = run_all_gates(
        symbol="TCS",
        signal_dict={"volume_ratio": 0.3},
        sentiment_score=0.1,
        circuit_data={"at_circuit": False},
        announcements=[],
    )
    _print_result(
        "Gate 2 liquidity fail",
        t2.get("passed") is False and t2.get("failed_gate") == 2,
        f"passed={t2.get('passed')}, failed_gate={t2.get('failed_gate')}",
    )

    # 3) Gate 2 pass when missing volume ratio
    g2_missing = run_gate_2_liquidity({})
    _print_result(
        "Gate 2 missing volume pass",
        g2_missing.get("passed") is True,
        f"passed={g2_missing.get('passed')}, reason={g2_missing.get('reason')}",
    )

    # 4) Gate 3 warning on near event
    g3_warn = run_gate_3_event_risk([{"days_away": 2, "description": "Board Meeting"}])
    _print_result(
        "Gate 3 event warning",
        g3_warn.get("passed") is True and g3_warn.get("warning") is True and g3_warn.get("flag") == "event_risk",
        f"warning={g3_warn.get('warning')}, flag={g3_warn.get('flag')}",
    )

    # 5) Gate 4 sentiment fail
    t5 = run_all_gates(
        symbol="INFY",
        signal_dict={"volume_ratio": 1.0},
        sentiment_score=-0.5,
        circuit_data={"at_circuit": False},
        announcements=[],
    )
    _print_result(
        "Gate 4 sentiment fail",
        t5.get("passed") is False and t5.get("failed_gate") == 4,
        f"passed={t5.get('passed')}, failed_gate={t5.get('failed_gate')}",
    )

    # 6) Gate 5 high volatility warning
    g5_warn = run_gate_5_volatility({"atr": {"pct_of_price": 5.0}})
    _print_result(
        "Gate 5 volatility warning",
        g5_warn.get("passed") is True and g5_warn.get("warning") is True and g5_warn.get("flag") == "high_volatility",
        f"warning={g5_warn.get('warning')}, flag={g5_warn.get('flag')}",
    )

    # 7) Full gate run all pass
    t7 = run_all_gates(
        symbol="TCS",
        signal_dict={"volume_ratio": 1.2, "atr": {"pct_of_price": 2.0}},
        sentiment_score=0.1,
        circuit_data={"at_circuit": False},
        announcements=[],
    )
    _print_result(
        "Full run all pass",
        t7.get("passed") is True and t7.get("hard_failure") is False and float(t7.get("position_modifier", 0.0)) == 1.0,
        f"passed={t7.get('passed')}, position_modifier={t7.get('position_modifier')}",
    )

    # 8) Full run with both warnings
    t8 = run_all_gates(
        symbol="HDFCBANK",
        signal_dict={"volume_ratio": 1.3, "atr": {"pct_of_price": 5.0}},
        sentiment_score=0.2,
        circuit_data={"at_circuit": False},
        announcements=[{"days_away": 2}],
    )
    _print_result(
        "Full run both warnings",
        t8.get("passed") is True and abs(float(t8.get("position_modifier", 0.0)) - 0.375) < 1e-9,
        f"position_modifier={t8.get('position_modifier')}, warnings={t8.get('warnings')}",
    )

    # 9) format_gate_result_for_log cases
    log_pass = format_gate_result_for_log(t7)
    log_warn = format_gate_result_for_log(t8)
    log_fail = format_gate_result_for_log(t5)
    _print_result(
        "format_gate_result_for_log",
        log_pass.startswith("✅") and log_warn.startswith("⚠️") and log_fail.startswith("❌"),
        f"pass='{log_pass}' | warn='{log_warn}' | fail='{log_fail}'",
    )


if __name__ == "__main__":
    run_tests()
