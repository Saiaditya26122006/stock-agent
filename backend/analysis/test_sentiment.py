"""Basic runtime checks for sentiment module."""

from __future__ import annotations

from analysis.sentiment import (
    fetch_headlines,
    get_stock_sentiment,
    is_sentiment_gate_passed,
)


def _print_result(name: str, passed: bool, detail: str) -> None:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def run_tests() -> None:
    # 1. fetch_headlines("TCS")
    headlines = fetch_headlines("TCS")
    _print_result(
        "fetch_headlines(TCS)",
        isinstance(headlines, list),
        f"{len(headlines)} headlines returned",
    )

    # 2. get_stock_sentiment("TCS")
    tcs = get_stock_sentiment("TCS")
    _print_result(
        "get_stock_sentiment(TCS)",
        isinstance(tcs, dict) and tcs.get("symbol") == "TCS",
        str(tcs),
    )

    # 3. get_stock_sentiment("RELIANCE")
    rel = get_stock_sentiment("RELIANCE")
    rel_score = rel.get("sentiment_score")
    _print_result(
        "get_stock_sentiment(RELIANCE)",
        isinstance(rel, dict) and isinstance(rel_score, (int, float)),
        f"sentiment_score={rel_score}",
    )

    # 4. is_sentiment_gate_passed(-0.5) -> False
    gate_neg = is_sentiment_gate_passed(-0.5)
    _print_result(
        "is_sentiment_gate_passed(-0.5)",
        gate_neg is False,
        f"returned {gate_neg}",
    )

    # 5. is_sentiment_gate_passed(0.1) -> True
    gate_pos = is_sentiment_gate_passed(0.1)
    _print_result(
        "is_sentiment_gate_passed(0.1)",
        gate_pos is True,
        f"returned {gate_pos}",
    )


if __name__ == "__main__":
    run_tests()
