"""
Manual smoke test for the Supabase-backed database layer.

Run from the `backend` directory:
    python -m db.test_db
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from pathlib import Path

# Ensure backend root is on sys.path when executed as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.supabase_client import test_connection  # noqa: E402
from db.watchlist import (  # noqa: E402
    add_symbol,
    get_active_watchlist,
    get_symbols_list,
    remove_symbol,
)
from db.recommendations import (  # noqa: E402
    get_todays_recommendations,
    get_win_rate,
    log_recommendation,
)


def _pretty(obj) -> str:
    """Return a pretty JSON string for printing nested structures."""

    return json.dumps(obj, indent=2, sort_keys=True, default=str)


def main() -> None:
    all_ok = True

    try:
        print("--- Supabase connection test ---")
        conn_ok = test_connection()
        print(f"Connection OK: {conn_ok}")
        if not conn_ok:
            all_ok = False
    except Exception as exc:
        all_ok = False
        print(f"Supabase test_connection raised an error: {exc}")
        traceback.print_exc()

    try:
        print("\n--- Active watchlist ---")
        wl = get_active_watchlist()
        print(_pretty(wl))

        print("\n--- Symbols list ---")
        symbols = get_symbols_list()
        print(symbols)
    except Exception as exc:
        all_ok = False
        print(f"Error fetching watchlist: {exc}")
        traceback.print_exc()

    # Test add_symbol / remove_symbol flow with SBIN
    try:
        print("\n--- Add symbol 'SBIN' ---")
        add_res = add_symbol("SBIN")
        print(_pretty(add_res))

        wl_after_add = get_active_watchlist()
        print("\nActive watchlist after adding SBIN:")
        print(_pretty(wl_after_add))

        print("\n--- Remove symbol 'SBIN' ---")
        rem_res = remove_symbol("SBIN")
        print(_pretty(rem_res))

        wl_after_remove = get_active_watchlist()
        print("\nActive watchlist after removing SBIN:")
        print(_pretty(wl_after_remove))
    except Exception as exc:
        all_ok = False
        print(f"Error in SBIN add/remove flow: {exc}")
        traceback.print_exc()

    # Recommendation logging & analytics tests
    try:
        print("\n--- Log fake paper recommendation ---")
        today = date.today().isoformat()
        rec_payload = {
            "user_id": "sai_aditya",
            "date": today,
            "stock": "RELIANCE",
            "style": "intraday",
            "entry_price": 2500.0,
            "target": 2550.0,
            "stop_loss": 2480.0,
            "risk_score": 1.5,
            "sentiment_score": 0.8,
        }
        log_res = log_recommendation(rec_payload)
        print(_pretty(log_res))

        print("\n--- Today's recommendations ---")
        todays = get_todays_recommendations()
        print(_pretty(todays))

        print("\n--- Win rate (last 20) ---")
        win_rate = get_win_rate()
        print(_pretty(win_rate))
    except Exception as exc:
        all_ok = False
        print(f"Error testing recommendations flow: {exc}")
        traceback.print_exc()

    if all_ok:
        print("\n✅ Database layer test complete")
    else:
        print("\n⚠️ Database layer test encountered one or more errors (see above).")


if __name__ == "__main__":
    main()

