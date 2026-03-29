"""
Manual smoke test for the Technical Analysis engine.

Run from the `backend` directory:
    python -m analysis.test_ta_engine
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure backend root is on sys.path when executed as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.upstox import UpstoxClient, get_historical_ohlcv  # noqa: E402
from analysis.ta_engine import (  # noqa: E402
    analyse_all_timeframes,
    analyse_stock,
    get_summary,
)


def _pretty(obj) -> str:
    """Return a nicely formatted JSON string for printing nested dicts."""

    return json.dumps(obj, indent=2, sort_keys=True, default=str)


def main() -> None:
    all_ok = True

    try:
        print("--- TA Engine test: RELIANCE daily (90 days) ---")
        df = get_historical_ohlcv("RELIANCE", "day", 90)
        print(f"Fetched OHLCV shape: {df.shape}")
        daily_signal = analyse_stock("RELIANCE", "day", df)
        print("SignalDict (RELIANCE day):")
        print(_pretty(daily_signal))
    except Exception as exc:
        all_ok = False
        print(f"Error analysing RELIANCE daily: {exc}")
        traceback.print_exc()

    try:
        print("\n--- TA Engine test: TCS all timeframes ---")
        # UpstoxClient is imported to satisfy the API, but currently analyse_all_timeframes
        # fetches data internally via get_historical_ohlcv.
        client = UpstoxClient()
        all_tf = analyse_all_timeframes("TCS", upstox_client=client)
        print("All timeframe results for TCS:")
        print(_pretty(all_tf))

        summary = get_summary(all_tf)
        print("\nSummary for TCS:")
        print(_pretty(summary))
    except Exception as exc:
        all_ok = False
        print(f"Error analysing TCS multi-timeframe: {exc}")
        traceback.print_exc()

    if all_ok:
        print("\n✅ TA Engine test complete")
    else:
        print("\n⚠️ TA Engine test encountered one or more errors (see above).")


if __name__ == "__main__":
    main()

