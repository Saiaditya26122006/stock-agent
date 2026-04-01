"""Smoke tests for 5-factor risk scoring engine."""

from __future__ import annotations

from analysis.risk_scorer import compute_risk_score, should_skip_stock


def _print_result(test_name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {test_name}: {detail}")


def run_tests() -> None:
    # 1) Strong bullish signal
    strong_signal = {
        "overall_signal": "strong_buy",
        "ema": {"trend": "bullish"},
        "rsi": {"signal": "oversold"},
        "macd": {"crossover": "bullish"},
        "bollinger": {"position": "lower"},
        "atr": {"pct_of_price": 1.5},
        "vwap": {"bias": "bullish"},
    }
    strong_result = compute_risk_score(strong_signal, sentiment_score=0.3, symbol="TCS")
    strong_score = float(strong_result.get("risk_score", 0.0))
    _print_result(
        "Strong bullish signal",
        strong_score >= 7.0,
        f"risk_score={strong_score}",
    )

    # 2) Weak bearish signal
    weak_signal = {
        "overall_signal": "sell",
        "ema": {"trend": "bearish"},
        "rsi": {"signal": "overbought"},
        "macd": {"crossover": "bearish"},
        "bollinger": {"position": "upper"},
        "atr": {"pct_of_price": 5.0},
        "vwap": {"bias": "bearish"},
    }
    weak_result = compute_risk_score(weak_signal, sentiment_score=-0.4, symbol="RELIANCE")
    weak_score = float(weak_result.get("risk_score", 0.0))
    weak_skip = should_skip_stock(weak_score, -0.4)
    _print_result(
        "Weak bearish signal",
        weak_score <= 4.0 and weak_skip is True,
        f"risk_score={weak_score}, should_skip={weak_skip}",
    )

    # 3) Neutral signal
    neutral_signal = {
        "overall_signal": "neutral",
        "atr": {"pct_of_price": 2.5},
    }
    neutral_result = compute_risk_score(neutral_signal, sentiment_score=0.0, symbol="INFY")
    neutral_score = float(neutral_result.get("risk_score", 0.0))
    _print_result(
        "Neutral signal",
        4.0 <= neutral_score <= 7.0,
        f"risk_score={neutral_score}",
    )

    # 4) should_skip_stock combinations
    case1 = should_skip_stock(2.5, 0.1)
    case2 = should_skip_stock(7.0, -0.5)
    case3 = should_skip_stock(7.0, 0.1)
    _print_result("should_skip_stock(2.5, 0.1)", case1 is True, f"returned {case1}")
    _print_result("should_skip_stock(7.0, -0.5)", case2 is True, f"returned {case2}")
    _print_result("should_skip_stock(7.0, 0.1)", case3 is False, f"returned {case3}")


if __name__ == "__main__":
    run_tests()
