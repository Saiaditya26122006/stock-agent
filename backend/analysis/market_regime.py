"""India VIX regime overrides for recommendation and sizing controls."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict


logger = logging.getLogger(__name__)


def get_regime(vix: float) -> str:
    """Map VIX to macro regime bucket."""
    try:
        v = float(vix)
    except Exception:
        v = 15.0
    if v > 20:
        return "DANGER"
    if v >= 15:
        return "CAUTION"
    return "NORMAL"


def get_regime_config(vix: float) -> Dict[str, Any]:
    """Return full regime config for overrides and prompt injection."""
    v = float(vix) if vix is not None else 15.0
    regime = get_regime(v)
    if regime == "DANGER":
        return {
            "regime": "DANGER",
            "vix": v,
            "position_size_multiplier": 0.5,
            "min_risk_score": 8.0,
            "recommendation_limit": 2,
            "alert_emoji": "🔴",
            "description": "High volatility — extreme caution required",
            "trading_advice": "Trade minimum size only. Only highest conviction setups.",
        }
    if regime == "CAUTION":
        return {
            "regime": "CAUTION",
            "vix": v,
            "position_size_multiplier": 0.75,
            "min_risk_score": 6.0,
            "recommendation_limit": 3,
            "alert_emoji": "🟡",
            "description": "Elevated volatility — trade conservatively",
            "trading_advice": "Reduce position sizes. Stick to strong setups only.",
        }
    return {
        "regime": "NORMAL",
        "vix": v,
        "position_size_multiplier": 1.0,
        "min_risk_score": 5.0,
        "recommendation_limit": 5,
        "alert_emoji": "🟢",
        "description": "Normal market conditions",
        "trading_advice": "Full analysis. Standard position sizing.",
    }


def apply_regime_to_position(position_size_result: Dict, regime_config: Dict) -> Dict[str, Any]:
    """Apply regime multiplier to already computed position sizing result."""
    try:
        res = dict(position_size_result or {})
        regime = str((regime_config or {}).get("regime", "NORMAL"))
        mult = float((regime_config or {}).get("position_size_multiplier", 1.0))
        if res.get("action") == "skip":
            res["regime_applied"] = regime
            res["regime_multiplier"] = mult
            return res

        shares = int(res.get("shares", 0))
        entry = float(res.get("entry_price", 0.0))
        new_shares = math.floor(shares * mult)
        if new_shares <= 0:
            return {
                "action": "skip",
                "shares": 0,
                "position_value": 0.0,
                "risk_amount": 0.0,
                "risk_pct_used": 0.0,
                "entry_price": entry,
                "stop_loss": float(res.get("stop_loss", 0.0)),
                "capital": float(res.get("capital", 0.0)),
                "capital_at_risk_pct": 0.0,
                "reason": f"regime_override: {regime} regime reduced position to zero",
                "regime_applied": regime,
                "regime_multiplier": mult,
            }
        new_value = round(new_shares * entry, 2)
        capital = float(res.get("capital", 0.0))
        res["shares"] = new_shares
        res["position_value"] = new_value
        res["capital_at_risk_pct"] = round((new_value / capital) * 100.0, 2) if capital > 0 else 0.0
        res["regime_applied"] = regime
        res["regime_multiplier"] = mult
        return res
    except Exception as exc:
        logger.error("apply_regime_to_position failed: %s", exc)
        return dict(position_size_result or {})


def filter_by_regime(recommendations: Dict[str, Dict], regime_config: Dict) -> Dict[str, Dict]:
    """Filter recommendations by min risk and cap count for regime."""
    try:
        recs = recommendations or {}
        min_risk = float((regime_config or {}).get("min_risk_score", 5.0))
        limit = int((regime_config or {}).get("recommendation_limit", 5))

        scored = []
        for symbol, rec in recs.items():
            risk = float((rec or {}).get("risk_score", 0.0))
            if rec.get("action") in {"BUY", "SELL"} and risk < min_risk:
                rec["regime_filtered"] = True
                continue
            scored.append((symbol, rec, risk))

        actionable = [(s, r, rk) for (s, r, rk) in scored if r.get("action") in {"BUY", "SELL"}]
        actionable.sort(key=lambda x: x[2], reverse=True)
        keep_actionable = {s for (s, _, _) in actionable[:limit]}

        out: Dict[str, Dict] = {}
        for symbol, rec, risk in scored:
            if rec.get("action") in {"BUY", "SELL"} and symbol not in keep_actionable:
                rec["regime_filtered"] = True
                continue
            out[symbol] = rec
        return out
    except Exception as exc:
        logger.error("filter_by_regime failed: %s", exc)
        return recommendations or {}


def get_regime_telegram_header(regime_config: Dict) -> str:
    """Return one-line Telegram header for current regime."""
    regime = str((regime_config or {}).get("regime", "NORMAL"))
    vix = float((regime_config or {}).get("vix", 15.0))
    if regime == "DANGER":
        return f"🔴 DANGER ZONE — VIX {vix:.1f} | Trade minimum size only"
    if regime == "CAUTION":
        return f"🟡 CAUTION — VIX {vix:.1f} | Conservative sizing active"
    return f"🟢 NORMAL — VIX {vix:.1f} | Full recommendations active"


def get_regime_prompt_injection(regime_config: Dict) -> str:
    """Return regime context string for LLM prompt injection."""
    regime = str((regime_config or {}).get("regime", "NORMAL"))
    vix = float((regime_config or {}).get("vix", 15.0))
    advice = str((regime_config or {}).get("trading_advice", "Standard position sizing."))
    mult = float((regime_config or {}).get("position_size_multiplier", 1.0))
    min_risk = float((regime_config or {}).get("min_risk_score", 5.0))
    return (
        f"MARKET REGIME: {regime} (India VIX: {vix:.1f})\n"
        f"{advice}\n"
        f"Position sizing: {mult * 100:.0f}% of normal size.\n"
        f"Only recommend if conviction is HIGH and risk score >= {min_risk}."
    )
