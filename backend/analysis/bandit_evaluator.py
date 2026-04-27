"""
Bandit Evaluator — pulls closed trades from Supabase and feeds them back
into the SignalBandit so weights are always in sync with real outcomes.

Run on demand or call from the Sunday audit scheduler job.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from db.supabase_client import supabase_client
from analysis.signal_bandit import get_bandit, SIGNALS, REGIMES

logger = logging.getLogger(__name__)

WIN_OUTCOMES = {"hit_target", "paper_hit_target"}
LOSS_OUTCOMES = {"hit_sl", "paper_hit_sl", "expired"}


def _parse_signal_snapshot(snapshot_raw: Any) -> List[str]:
    """
    Extract the list of active signal names from a stored signal_snapshot.
    The snapshot is stored as a JSON string in Supabase.
    Returns list of signal names that overlap with SIGNALS.
    """
    if not snapshot_raw:
        return []
    try:
        if isinstance(snapshot_raw, str):
            snapshot = json.loads(snapshot_raw)
        else:
            snapshot = snapshot_raw
    except Exception:
        return []

    active: List[str] = []

    # ema_trend
    if snapshot.get("ema_trend") in ("bullish", "bearish"):
        active.append("ema_trend")

    # rsi — signal is "oversold" or "overbought"
    if snapshot.get("rsi_signal") in ("oversold", "overbought"):
        active.append("rsi")

    # macd — crossover or strong histogram
    if snapshot.get("macd_crossover") in ("bullish_crossover", "bearish_crossover"):
        active.append("macd")
    elif snapshot.get("macd_histogram") is not None:
        try:
            if abs(float(snapshot["macd_histogram"])) > 0.1:
                active.append("macd")
        except (TypeError, ValueError):
            pass

    # volume — ratio > 1.5
    try:
        if float(snapshot.get("volume_ratio") or 0) > 1.5:
            active.append("volume")
    except (TypeError, ValueError):
        pass

    # vwap
    if snapshot.get("vwap_bias") in ("above", "below"):
        active.append("vwap")

    # candlestick — overall_signal strong
    if snapshot.get("overall_signal") in ("strong_buy", "strong_sell"):
        active.append("candlestick")

    return active


def _infer_regime(snapshot_raw: Any) -> str:
    """Best-effort regime from snapshot. Defaults to NORMAL."""
    try:
        if isinstance(snapshot_raw, str):
            snapshot = json.loads(snapshot_raw)
        else:
            snapshot = snapshot_raw or {}
        regime = snapshot.get("regime") or snapshot.get("market_regime")
        if regime and regime.upper() in REGIMES:
            return regime.upper()
    except Exception:
        pass
    return "NORMAL"


def run_bandit_evaluation(
    user_id: str = "sai_aditya",
    last_n: int = 500,
) -> Dict[str, Any]:
    """
    Pull the last `last_n` closed trades from Supabase and update the bandit.

    Returns a summary dict with counts and updated weights per regime.
    """
    logger.info("BanditEvaluator: fetching last %d closed trades for %s", last_n, user_id)

    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("id, outcome, signal_snapshot, action")
            .eq("user_id", user_id)
            .in_("outcome", list(WIN_OUTCOMES | LOSS_OUTCOMES))
            .order("created_at", desc=False)
            .limit(last_n)
            .execute()
        )
        trades = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.error("BanditEvaluator: DB fetch failed: %s", exc)
        return {"success": False, "error": str(exc)}

    if not trades:
        logger.info("BanditEvaluator: no closed trades found.")
        return {"success": True, "processed": 0, "skipped": 0}

    bandit = get_bandit()
    processed = 0
    skipped = 0

    for trade in trades:
        outcome = trade.get("outcome", "")
        snapshot_raw = trade.get("signal_snapshot")

        if outcome in WIN_OUTCOMES:
            won = True
        elif outcome in LOSS_OUTCOMES:
            won = False
        else:
            skipped += 1
            continue

        signals_used = _parse_signal_snapshot(snapshot_raw)
        regime = _infer_regime(snapshot_raw)

        if not signals_used:
            # No snapshot data — update all signals equally (conservative)
            signals_used = SIGNALS
            skipped += 1   # count as partial

        for sig in signals_used:
            bandit.update(signal=sig, regime=regime, won=won)

        processed += 1

    bandit.save()
    logger.info("BanditEvaluator: processed=%d skipped=%d total_updates=%d",
                processed, skipped, bandit.total_updates)

    # Build summary of current weights per regime
    weights_summary = {
        regime: bandit.get_weights(regime)
        for regime in REGIMES
    }
    stats_summary = {
        regime: bandit.get_raw_stats(regime)
        for regime in REGIMES
    }

    return {
        "success": True,
        "processed": processed,
        "skipped": skipped,
        "total_bandit_updates": bandit.total_updates,
        "trusted": bandit.total_updates >= 200,
        "weights": weights_summary,
        "stats": stats_summary,
    }


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)
    result = run_bandit_evaluation()
    pprint.pprint(result)
