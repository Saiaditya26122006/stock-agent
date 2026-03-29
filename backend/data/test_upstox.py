"""
Manual smoke test for the Upstox connector.

Run from the `backend` directory:
    python -m data.test_upstox
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure `backend` is on sys.path when executed as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.upstox import (  # noqa: E402
    DataFreshnessError,
    freshness_check,
    get_historical_ohlcv,
    get_live_quote,
    test_connection,
)


def main() -> None:
    all_ok = True
    df = None
    try:
        print("--- test_connection() ---")
        if not test_connection():
            all_ok = False

        print("\n--- get_historical_ohlcv('RELIANCE', 'day', 30) ---")
        try:
            df = get_historical_ohlcv("RELIANCE", "day", 30)
            print(f"Shape: {df.shape}")
            print("First 3 rows:")
            print(df.head(3).to_string())
            print("Last 3 rows:")
            print(df.tail(3).to_string())
        except Exception as e:
            all_ok = False
            print(f"Historical OHLCV failed: {e}")

        print("\n--- freshness_check() ---")
        try:
            if df is not None and not df.empty:
                fc = freshness_check(df)
                print(fc)
            else:
                all_ok = False
                print("Skipped freshness_check: empty DataFrame.")
        except DataFreshnessError as e:
            all_ok = False
            print(f"Data freshness error: {e}")
        except Exception as e:
            all_ok = False
            print(f"Freshness check failed: {e}")

        print("\n--- get_live_quote('TCS') ---")
        try:
            q = get_live_quote("TCS")
            print(q)
        except Exception as e:
            all_ok = False
            print(f"Live quote failed: {e}")

        if all_ok:
            print("\n✅ Upstox connector test complete")
        else:
            print("\n⚠️ Upstox connector test finished with one or more failures (see above).")
    except Exception as e:
        print(f"\nFatal error during Upstox connector test: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
