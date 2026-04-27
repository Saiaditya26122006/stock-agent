"""
Recommendations logging and analytics for Supabase-backed storage.

Works with the `recommendations_log` table.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List

import pytz

from db.supabase_client import supabase_client


logger = logging.getLogger(__name__)

VALID_OUTCOMES = {
    "hit_target",
    "hit_sl",
    "still_open",
    "expired",
    "paper_hit_target",
    "paper_hit_sl",
}


def _safe_response_single(resp: Any, context: str) -> List[Dict[str, Any]]:
    try:
        error = getattr(resp, "error", None)
        if error:
            logger.error("%s error: %s", context, error)
            return []
        data = getattr(resp, "data", None)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return [data]
    except Exception as exc:
        logger.error("%s unexpected response handling error: %s", context, exc)
        return []


def log_recommendation(rec_dict: Dict[str, Any]) -> Dict[str, Any]:
    required = {
        "user_id",
        "date",
        "stock",
        "style",
        "entry_price",
        "target",
        "stop_loss",
        "risk_score",
        "sentiment_score",
    }
    missing = [k for k in required if k not in rec_dict]
    if missing:
        return {
            "success": False,
            "id": None,
            "message": f"Missing required recommendation fields: {', '.join(missing)}",
        }

    # Extended optional fields — signal_snapshot and horizon enable RL training
    optional = {
        "reasoning", "hold_period", "action", "confidence",
        "horizon",           # SHORT_TERM | LONG_TERM | BOTH
        "horizon_reasoning", # why the agent picked this horizon
        "signal_snapshot",   # full TA state dict — the RL training data
        "exit_timestamp",    # datetime when trade was closed
        "exit_price",        # actual price at exit
        "bars_held",         # number of candles/days position was open
        "risk_reward",       # risk:reward ratio at entry
    }
    allowed = required | optional
    payload = {k: rec_dict[k] for k in rec_dict if k in allowed}

    # Serialise signal_snapshot dict → JSON string if needed
    if "signal_snapshot" in payload and isinstance(payload["signal_snapshot"], dict):
        import json as _json
        try:
            payload["signal_snapshot"] = _json.dumps(payload["signal_snapshot"])
        except Exception:
            payload.pop("signal_snapshot", None)

    try:
        resp = supabase_client.table("recommendations_log").insert(payload).execute()
        if getattr(resp, "error", None):
            logger.error("log_recommendation insert error: %s", resp.error)
            return {
                "success": False,
                "id": None,
                "message": "Failed to log recommendation.",
            }
        rows = getattr(resp, "data", None) or []
        rec_id = rows[0].get("id") if rows else None
        return {
            "success": True,
            "id": rec_id,
            "message": "Recommendation logged successfully.",
        }
    except Exception as exc:
        logger.error("log_recommendation failed: %s", exc)
        return {
            "success": False,
            "id": None,
            "message": "Unexpected error while logging recommendation.",
        }


def build_signal_snapshot(signal_dict: Dict[str, Any], extra: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Extract the key TA features from a full signal_dict into a compact
    snapshot suitable for RL training.  Pass extra={} for any additional
    fields (e.g. vix, regime, hour_of_day).
    """
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    ema  = signal_dict.get("ema") or {}
    rsi  = signal_dict.get("rsi") or {}
    macd = signal_dict.get("macd") or {}
    atr  = signal_dict.get("atr") or {}
    vwap = signal_dict.get("vwap") or {}
    snapshot = {
        "ema_trend":       ema.get("trend", "neutral"),
        "rsi":             rsi.get("value"),
        "rsi_signal":      rsi.get("signal", "neutral"),
        "macd_histogram":  macd.get("histogram"),
        "macd_crossover":  macd.get("crossover", "neutral"),
        "volume_ratio":    signal_dict.get("volume_ratio"),
        "atr_pct":         atr.get("pct_of_price"),
        "vwap_bias":       vwap.get("bias"),
        "overall_signal":  signal_dict.get("overall_signal", "neutral"),
        "hour_of_day":     now.hour,
        "day_of_week":     now.weekday(),   # 0=Monday
    }
    if extra:
        snapshot.update(extra)
    return snapshot


def get_todays_recommendations(user_id: str = "sai_aditya") -> List[Dict[str, Any]]:
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    today = __import__('datetime').datetime.now(ist).date().isoformat()
    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", today)
            .order("created_at", desc=False)
            .execute()
        )
        return _safe_response_single(resp, "get_todays_recommendations")
    except Exception as exc:
        logger.error("get_todays_recommendations failed: %s", exc)
        return []


def update_outcome(
    rec_id: str,
    outcome: str,
    actual_exit: float,
    pnl: float,
    agent_correct: bool,
    exit_timestamp: str = None,
    exit_price: float = None,
    bars_held: int = None,
) -> Dict[str, Any]:
    if outcome not in VALID_OUTCOMES:
        return {
            "success": False,
            "message": f"Invalid outcome '{outcome}'.",
        }

    payload: Dict[str, Any] = {
        "outcome": outcome,
        "actual_exit": actual_exit,
        "pnl": pnl,
        "agent_correct": agent_correct,
    }
    if exit_timestamp:
        payload["exit_timestamp"] = exit_timestamp
    if exit_price is not None:
        payload["exit_price"] = exit_price
    if bars_held is not None:
        payload["bars_held"] = bars_held

    try:
        resp = (
            supabase_client.table("recommendations_log")
            .update(payload)
            .eq("id", rec_id)
            .execute()
        )
        if getattr(resp, "error", None):
            logger.error("update_outcome error: %s", resp.error)
            return {
                "success": False,
                "message": "Failed to update recommendation outcome.",
            }
        return {
            "success": True,
            "message": "Recommendation outcome updated.",
        }
    except Exception as exc:
        logger.error("update_outcome failed: %s", exc)
        return {
            "success": False,
            "message": "Unexpected error while updating outcome.",
        }


def get_win_rate(user_id: str = "sai_aditya", last_n: int = 20) -> Dict[str, Any]:
    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("outcome")
            .eq("user_id", user_id)
            .not_.is_("outcome", None)
            .neq("outcome", "still_open")
            .order("created_at", desc=True)
            .limit(last_n)
            .execute()
        )
        rows = _safe_response_single(resp, "get_win_rate")
    except Exception as exc:
        logger.error("get_win_rate failed: %s", exc)
        return {"win_rate": 0.0, "total": 0, "wins": 0, "losses": 0}

    if not rows:
        return {"win_rate": 0.0, "total": 0, "wins": 0, "losses": 0}

    wins = 0
    losses = 0
    for row in rows:
        outcome = row.get("outcome")
        if outcome in ("hit_target", "paper_hit_target"):
            wins += 1
        else:
            losses += 1

    total = wins + losses
    win_rate = round(wins / total * 100.0, 2) if total else 0.0
    return {
        "win_rate": win_rate,
        "total": total,
        "wins": wins,
        "losses": losses,
    }