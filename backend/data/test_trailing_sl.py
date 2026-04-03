"""
Dry-run test for trailing SL monitor setup (no WebSocket connection).

Run:
    python -m data.test_trailing_sl
"""

from __future__ import annotations

from datetime import datetime
from pprint import pprint

import pytz

from data.upstox import get_instrument_key
from db.supabase_client import supabase_client


def main() -> None:
    ist = pytz.timezone("Asia/Kolkata")
    today = datetime.now(ist).date().isoformat()
    print(f"Checking monitor candidates for date (IST): {today}")

    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("id,stock,entry_price,target,stop_loss,action,outcome,date")
            .eq("date", today)
            .eq("action", "BUY")
            .is_("outcome", "null")
            .execute()
        )
        if getattr(resp, "error", None):
            print(f"Supabase query failed: {resp.error}")
            return
        rows = getattr(resp, "data", None) or []
        print(f"Rows eligible for monitoring: {len(rows)}")
        if not rows:
            return

        out = []
        for r in rows:
            symbol = str(r.get("stock") or "").strip().upper()
            if not symbol:
                continue
            try:
                instrument_key = get_instrument_key(symbol)
                out.append(
                    {
                        "id": r.get("id"),
                        "symbol": symbol,
                        "instrument_key": instrument_key,
                        "entry_price": r.get("entry_price"),
                        "target": r.get("target"),
                        "stop_loss": r.get("stop_loss"),
                    }
                )
            except Exception as exc:
                out.append({"id": r.get("id"), "symbol": symbol, "instrument_key_error": str(exc)})

        pprint(out, sort_dicts=False)
    except Exception as exc:
        print(f"test_trailing_sl failed: {exc}")


if __name__ == "__main__":
    main()

