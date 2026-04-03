"""
Integration test for outcome_logger against Supabase + Upstox.

Run from backend/ with venv activated:
    python -m db.test_outcome_logger

This script:
- inserts one dummy BUY recommendation for today
- runs run_outcome_logger()
- reads the row back and prints outcome fields
- deletes the dummy row to keep the table clean
"""

from __future__ import annotations

from pprint import pprint

import pytz

from db.outcome_logger import run_outcome_logger
from db.supabase_client import supabase_client


def main() -> None:
    ist = pytz.timezone("Asia/Kolkata")
    today = __import__("datetime").datetime.now(ist).date().isoformat()

    dummy = {
        "user_id": "sai_aditya",
        "date": today,
        "stock": "RELIANCE",
        "style": "intraday",
        "entry_price": 100.0,
        # Force WIN for BUY in almost all cases by setting a tiny target
        "target": 0.01,
        "stop_loss": 0.0,
        "risk_score": 5.0,
        "sentiment_score": 0.0,
        "action": "BUY",
        "hold_period": "EOD",
        "confidence": "TEST",
        "reasoning": "DUMMY ROW FOR OUTCOME LOGGER TEST",
    }

    rec_id = None
    try:
        ins = supabase_client.table("recommendations_log").insert(dummy).execute()
        if getattr(ins, "error", None):
            raise RuntimeError(f"Insert failed: {ins.error}")
        rows = getattr(ins, "data", None) or []
        rec_id = (rows[0] or {}).get("id") if rows else None
        if not rec_id:
            raise RuntimeError("Insert succeeded but no id returned.")

        print(f"Inserted dummy recommendation id={rec_id}")

        summary = run_outcome_logger(user_id="sai_aditya")
        print("\nDaily summary:")
        pprint(summary, sort_dicts=False)

        sel = (
            supabase_client.table("recommendations_log")
            .select("id,stock,action,actual_exit,outcome,pnl,agent_correct")
            .eq("id", rec_id)
            .limit(1)
            .execute()
        )
        if getattr(sel, "error", None):
            raise RuntimeError(f"Select failed: {sel.error}")
        data = getattr(sel, "data", None) or []
        row = data[0] if data else {}

        print("\nUpdated row outcome fields:")
        pprint(row, sort_dicts=False)

    except Exception as exc:
        print(f"Test failed: {exc}")
    finally:
        if rec_id:
            try:
                dele = supabase_client.table("recommendations_log").delete().eq("id", rec_id).execute()
                if getattr(dele, "error", None):
                    print(f"Cleanup delete failed for id={rec_id}: {dele.error}")
                else:
                    print(f"\nCleaned up dummy row id={rec_id}")
            except Exception as del_exc:
                print(f"Cleanup exception for id={rec_id}: {del_exc}")


if __name__ == "__main__":
    main()

