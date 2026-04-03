"""
Ad-hoc backtest runner.

Run from backend/ with venv activated:
    python -m analysis.test_backtester
"""

from __future__ import annotations

from pprint import pprint


def main() -> None:
    symbol = "RELIANCE"
    try:
        from analysis.backtester import run_backtest

        res = run_backtest(symbol=symbol, lookback_days=365 * 2, force=True)
        print(f"\nBacktestResult for {symbol}\n" + "-" * 28)
        pprint(res.to_dict(), sort_dicts=False)
    except Exception as exc:
        print(f"Backtest failed for {symbol}: {exc}")


if __name__ == "__main__":
    main()

