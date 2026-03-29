"""Manual smoke test for Claude synthesis layer."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure backend root is on sys.path for script execution.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.claude_synthesis import (  # noqa: E402
    format_morning_briefing,
    get_user_config,
    synthesise_all,
    synthesise_recommendation,
)
from analysis.ta_engine import analyse_stock  # noqa: E402
from data.upstox import get_historical_ohlcv  # noqa: E402


def _pretty(obj) -> str:
    """Pretty-print nested dicts/lists as JSON."""

    return json.dumps(obj, indent=2, sort_keys=True, default=str)


def main() -> None:
    """Run end-to-end synthesis checks for one and multiple symbols."""

    all_ok = True
    sig_rel = None
    user_cfg = get_user_config("sai_aditya")
    try:
        df_rel = get_historical_ohlcv("RELIANCE", "day", 90)
        sig_rel = analyse_stock("RELIANCE", "day", df_rel)
        rec_rel = synthesise_recommendation("RELIANCE", sig_rel, user_cfg)
        print("--- RELIANCE RecommendationDict ---")
        print(_pretty(rec_rel))
    except Exception as exc:
        all_ok = False
        print(f"Single-symbol synthesis failed: {exc}")
        traceback.print_exc()

    try:
        df_tcs = get_historical_ohlcv("TCS", "day", 90)
        sig_tcs = analyse_stock("TCS", "day", df_tcs)

        if sig_rel is None:
            raise RuntimeError("RELIANCE signal was not generated in step 1.")
        two_signals = {
            "RELIANCE": sig_rel,
            "TCS": sig_tcs,
        }
        all_recs = synthesise_all(two_signals, user_cfg)
        briefing = format_morning_briefing(all_recs, user_cfg)

        print("\n--- Multi-symbol recommendations ---")
        print(_pretty(all_recs))
        print("\n--- Morning Briefing ---")
        print(briefing)
    except Exception as exc:
        all_ok = False
        print(f"Multi-symbol synthesis failed: {exc}")
        traceback.print_exc()

    if all_ok:
        print("\n✅ Claude synthesis test complete")
    else:
        print("\n⚠️ Claude synthesis test completed with one or more failures.")


if __name__ == "__main__":
    main()

