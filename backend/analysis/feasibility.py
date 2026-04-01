"""Daily target feasibility checker using VIX and ATR-based movement."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx


logger = logging.getLogger(__name__)
NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
}


def get_india_vix() -> float:
    """Fetch INDIA VIX from NSE public API, fallback to 15.0."""
    try:
        with httpx.Client(timeout=10.0, headers=NSE_HEADERS, follow_redirects=True) as client:
            resp = client.get(NSE_ALL_INDICES_URL)
        if resp.status_code != 200:
            return 15.0
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return 15.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("index", "")).strip().upper() == "INDIA VIX":
                last = row.get("last")
                return float(last)
        return 15.0
    except Exception as exc:
        logger.error("get_india_vix failed, falling back to 15.0: %s", exc)
        return 15.0


def get_market_regime(vix: float) -> str:
    """Map VIX to risk regime."""
    try:
        value = float(vix)
    except Exception:
        value = 15.0
    if value > 20.0:
        return "DANGER"
    if value >= 15.0:
        return "CAUTION"
    return "NORMAL"


def get_average_intraday_move(signal_dicts: List[Dict]) -> float:
    """Average ATR% across signals; default 2.0 when unavailable."""
    try:
        items = signal_dicts or []
        if not items:
            return 2.0
        vals: List[float] = []
        for sig in items:
            if not isinstance(sig, dict):
                vals.append(2.0)
                continue
            atr = sig.get("atr") if isinstance(sig.get("atr"), dict) else {}
            pct = atr.get("pct_of_price", 2.0)
            try:
                vals.append(float(pct))
            except Exception:
                vals.append(2.0)
        if not vals:
            return 2.0
        return float(sum(vals) / len(vals))
    except Exception as exc:
        logger.error("get_average_intraday_move failed: %s", exc)
        return 2.0


def check_target_feasibility(
    capital: float,
    daily_target: float,
    india_vix: float,
    signal_dicts: List[Dict] = None,
) -> Dict[str, Any]:
    """Assess whether current daily target is realistic for market conditions."""
    try:
        cap = float(capital or 0.0)
        target = float(daily_target or 0.0)
        vix = float(india_vix or 15.0)
        required_return_pct = (target / cap) * 100.0 if cap > 0 else 0.0
        regime = get_market_regime(vix)
        avg_move = get_average_intraday_move(signal_dicts or [])

        if regime == "NORMAL":
            effective_move = avg_move * 1.0
        elif regime == "CAUTION":
            effective_move = avg_move * 0.8
        else:
            effective_move = avg_move * 0.5

        realistic_target = cap * (effective_move / 100.0) * 0.5
        is_achievable = required_return_pct <= (effective_move * 0.5)
        adjusted_target = round(realistic_target / 100.0) * 100.0

        if is_achievable:
            msg = (
                f"Target Rs.{target} is achievable. Market regime: {regime} "
                f"(VIX: {round(vix, 2)})"
            )
        else:
            msg = (
                f"Target Rs.{target} may be too aggressive. Realistic target today: "
                f"Rs.{adjusted_target} given VIX {round(vix, 2)} ({regime})"
            )

        return {
            "capital": float(round(cap, 2)),
            "daily_target": float(round(target, 2)),
            "required_return_pct": float(round(required_return_pct, 2)),
            "india_vix": float(round(vix, 2)),
            "market_regime": regime,
            "avg_intraday_move_pct": float(round(avg_move, 2)),
            "effective_move_pct": float(round(effective_move, 2)),
            "realistic_target": float(round(realistic_target, 2)),
            "is_achievable": bool(is_achievable),
            "adjusted_target": float(round(adjusted_target, 2)),
            "message": msg,
        }
    except Exception as exc:
        logger.error("check_target_feasibility failed: %s", exc)
        return {
            "capital": float(capital or 0.0),
            "daily_target": float(daily_target or 0.0),
            "required_return_pct": 0.0,
            "india_vix": float(india_vix or 15.0),
            "market_regime": get_market_regime(float(india_vix or 15.0)),
            "avg_intraday_move_pct": 2.0,
            "effective_move_pct": 1.6,
            "realistic_target": 0.0,
            "is_achievable": False,
            "adjusted_target": 0.0,
            "message": "Feasibility check fallback used due to calculation error.",
        }


def format_feasibility_for_briefing(feasibility_result: Dict) -> str:
    """Format compact feasibility summary for morning briefing."""
    try:
        fr = feasibility_result if isinstance(feasibility_result, dict) else {}
        line1 = (
            f"🎯 Daily Target: Rs.{fr.get('daily_target', 0)} | "
            f"Realistic: Rs.{fr.get('adjusted_target', 0)}"
        )
        line2 = (
            f"📊 Market Regime: {fr.get('market_regime', 'NORMAL')} | "
            f"VIX: {fr.get('india_vix', 15.0)} | "
            f"Avg Move: {float(fr.get('avg_intraday_move_pct', 2.0)):.1f}%"
        )
        if not bool(fr.get("is_achievable", False)):
            line3 = "⚠️ Target adjusted — avoid forcing trades on low-volatility day"
            return f"{line1}\n{line2}\n{line3}"
        return f"{line1}\n{line2}"
    except Exception as exc:
        logger.error("format_feasibility_for_briefing failed: %s", exc)
        return (
            "🎯 Daily Target: Rs.0 | Realistic: Rs.0\n"
            "📊 Market Regime: NORMAL | VIX: 15.0 | Avg Move: 2.0%"
        )
