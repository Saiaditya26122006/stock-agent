"""
One-time idempotent watchlist seeding script with sector tags.

Run:
    python -m db.seed_watchlist
"""

from __future__ import annotations

from typing import Dict, List

from db.supabase_client import supabase_client

USER_ID = "sai_aditya"

SECTOR_SYMBOLS: Dict[str, List[str]] = {
    "IT / Technology": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "Banking & Finance": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
    "Crude Oil & Energy": ["RELIANCE", "ONGC", "IOC", "BPCL", "GAIL"],
    "Pharma & Healthcare": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "Auto & EV": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT"],
    "FMCG & Consumer": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR"],
    "Metals & Mining": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "COALINDIA", "VEDL"],
    "Infrastructure & Real Estate": ["LT", "ULTRACEMCO", "ADANIPORTS", "DLF", "NTPC"],
}


def main() -> None:
    inserted = 0
    skipped = 0
    errors = 0

    for sector, symbols in SECTOR_SYMBOLS.items():
        for symbol in symbols:
            try:
                resp = (
                    supabase_client.table("watchlist")
                    .select("id, active")
                    .eq("user_id", USER_ID)
                    .eq("symbol", symbol)
                    .limit(1)
                    .execute()
                )
                if getattr(resp, "error", None):
                    print(f"[ERROR] select {symbol}: {resp.error}")
                    errors += 1
                    continue

                rows = getattr(resp, "data", None) or []
                if rows:
                    upd = (
                        supabase_client.table("watchlist")
                        .update({"active": True, "exchange": "NSE", "sector": sector})
                        .eq("id", rows[0]["id"])
                        .execute()
                    )
                    if getattr(upd, "error", None):
                        print(f"[ERROR] update {symbol}: {upd.error}")
                        errors += 1
                    else:
                        skipped += 1
                    continue

                ins = (
                    supabase_client.table("watchlist")
                    .insert(
                        {
                            "user_id": USER_ID,
                            "symbol": symbol,
                            "exchange": "NSE",
                            "sector": sector,
                            "active": True,
                        }
                    )
                    .execute()
                )
                if getattr(ins, "error", None):
                    print(f"[ERROR] insert {symbol}: {ins.error}")
                    errors += 1
                else:
                    inserted += 1
            except Exception as exc:
                print(f"[ERROR] {symbol}: {exc}")
                errors += 1

    print("\nWatchlist seed complete")
    print(f"Inserted: {inserted}")
    print(f"Updated existing: {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()

