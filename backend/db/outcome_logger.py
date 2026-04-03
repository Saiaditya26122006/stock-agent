"""
Recommendation outcome logger - runs at 3:45 PM IST via EOD scheduler job.

Idempotent: rows where outcome IS NOT NULL (already closed) are skipped.
Pipeline-safe: every operation is wrapped in try/except - never raises.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from db.supabase_client import supabase_client
from db.recommendations import update_outcome

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> str:
    return date.today().isoformat()


def _get_open_recommendations(user_id: str) -> List[Dict[str, Any]]:
    """Fetch today BUY/SELL rows where outcome is NULL or still_open."""
    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("id, stock, action, entry_price, target, stop_loss, outcome")
            .eq("user_id", user_id)
            .eq("date", _today_ist())
            .in_("action", ["BUY", "SELL"])
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        return [r for r in rows if r.get("outcome") in (None, "still_open")]
    except Exception as exc:
        logger.error("_get_open_recommendations failed: %s", exc)
        return []


def _get_live_price(symbol: str) -> Optional[float]:
    """Fetch current market price from Upstox. Returns None on any failure."""
    try:
        from data.upstox import get_live_quote
        quote = get_live_quote(symbol)
        price = float(quote.get("last_price") or quote.get("ltp") or 0.0)
        return price if price > 0 else None
    except Exception as exc:
        logger.warning("Live price fetch failed for %s: %s", symbol, exc)
        return None


def _determine_outcome(action, current_price, entry_price, target, stop_loss) -> str:
    """Return hit_target, hit_sl, or still_open."""
    if action == "BUY":
        if current_price >= target:
            return "hit_target"
        if current_price <= stop_loss:
            return "hit_sl"
    elif action == "SELL":
        if current_price <= target:
            return "hit_target"
        if current_price >= stop_loss:
            return "hit_sl"
    return "still_open"


def _calc_pnl_pct(action: str, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    if action == "BUY":
        return round(((exit_price - entry) / entry) * 100.0, 4)
    if action == "SELL":
        return round(((entry - exit_price) / entry) * 100.0, 4)
    return 0.0


def run_outcome_logger(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """
    Check all open BUY/SELL recs for today and update outcomes.
    Returns {date, total_open, wins, losses, still_open, win_rate, avg_pnl_pct}.
    Idempotent and never raises.
    """
    summary: Dict[str, Any] = {
        "date": _today_ist(),
        "total_open": 0,
        "wins": 0,
        "losses": 0,
        "still_open": 0,
        "win_rate": 0.0,
        "avg_pnl_pct": 0.0,
        "errors": [],
    }
    try:
        open_recs = _get_open_recommendations(user_id=user_id)
        summary["total_open"] = len(open_recs)
        if not open_recs:
            logger.info("outcome_logger: no open recs for %s on %s", user_id, _today_ist())
            return summary
        pnl_values: List[float] = []
        for rec in open_recs:
            rec_id    = rec.get("id")
            symbol    = rec.get("stock", "")
            action    = str(rec.get("action", "BUY")).upper()
            entry     = float(rec.get("entry_price") or 0.0)
            target    = float(rec.get("target") or 0.0)
            stop_loss = float(rec.get("stop_loss") or 0.0)
            if not rec_id or not symbol:
                continue
            try:
                current_price = _get_live_price(symbol)
                if current_price is None:
                    summary["still_open"] += 1
                    continue
                outcome = _determine_outcome(action, current_price, entry, target, stop_loss)
                pnl_pct = _calc_pnl_pct(action, entry, current_price)
                agent_correct = (outcome == "hit_target") if outcome != "still_open" else None
                update_outcome(
                    rec_id=rec_id,
                    outcome=outcome,
                    actual_exit=current_price,
                    pnl=pnl_pct,
                    agent_correct=agent_correct,
                )
                if outcome == "hit_target":
                    summary["wins"] += 1
                    pnl_values.append(pnl_pct)
                elif outcome == "hit_sl":
                    summary["losses"] += 1
                    pnl_values.append(pnl_pct)
                else:
                    summary["still_open"] += 1
                logger.info("outcome_logger: %s %s -> %s @ %.2f (%.2f%%)",
                            symbol, action, outcome, current_price, pnl_pct)
            except Exception as exc:
                logger.error("outcome_logger: error for %s: %s", symbol, exc)
                summary["errors"].append(f"{symbol}: {exc}")
        closed = summary["wins"] + summary["losses"]
        summary["win_rate"]    = round((summary["wins"] / closed) * 100.0, 2) if closed > 0 else 0.0
        summary["avg_pnl_pct"] = round(sum(pnl_values) / len(pnl_values), 4) if pnl_values else 0.0
        logger.info("outcome_logger done: wins=%d losses=%d still_open=%d",
                    summary["wins"], summary["losses"], summary["still_open"])
    except Exception as exc:
        logger.error("run_outcome_logger failed: %s", exc)
        summary["errors"].append(str(exc))
    return summary


def get_outcomes_summary(user_id: str = "sai_aditya", last_days: int = 30) -> Dict[str, Any]:
    """Aggregate outcome stats for the last N days."""
    try:
        cutoff = (date.today() - timedelta(days=last_days)).isoformat()
        resp = (
            supabase_client.table("recommendations_log")
            .select("outcome, pnl, agent_correct")
            .eq("user_id", user_id)
            .in_("action", ["BUY", "SELL"])
            .gte("date", cutoff)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        wins       = sum(1 for r in rows if r.get("outcome") == "hit_target")
        losses     = sum(1 for r in rows if r.get("outcome") == "hit_sl")
        still_open = sum(1 for r in rows if r.get("outcome") in (None, "still_open"))
        closed     = wins + losses
        pnl_vals   = [float(r["pnl"]) for r in rows if r.get("pnl") is not None]
        return {
            "period_days": last_days,
            "total": len(rows),
            "wins": wins,
            "losses": losses,
            "still_open": still_open,
            "win_rate": round((wins / closed) * 100.0, 2) if closed > 0 else 0.0,
            "avg_pnl_pct": round(sum(pnl_vals) / len(pnl_vals), 4) if pnl_vals else 0.0,
        }
    except Exception as exc:
        logger.error("get_outcomes_summary failed: %s", exc)
        return {"error": str(exc), "period_days": last_days}
