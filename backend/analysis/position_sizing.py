"""Fixed fractional position sizing with hard portfolio caps."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


def _skip_result(capital: float, entry_price: float, stop_loss: float, reason: str) -> Dict[str, Any]:
    return {
        "action": "skip",
        "shares": 0,
        "position_value": 0.0,
        "risk_amount": 0.0,
        "risk_pct_used": 0.0,
        "entry_price": float(entry_price or 0.0),
        "stop_loss": float(stop_loss or 0.0),
        "capital": float(capital or 0.0),
        "capital_at_risk_pct": 0.0,
        "reason": reason,
    }


def get_risk_pct(risk_score: float) -> float:
    """Return risk allocation percentage from composite risk score."""
    try:
        score = float(risk_score)
        if score >= 9.0:
            return 0.02
        if score >= 7.0:
            return 0.015
        if score >= 5.0:
            return 0.01
        return 0.0
    except Exception as exc:
        logger.error("get_risk_pct failed: %s", exc)
        return 0.0


def calculate_position_size(
    capital: float,
    risk_score: float,
    entry_price: float,
    stop_loss: float,
    open_positions_count: int = 0,
    capital_deployed: float = 0.0,
) -> Dict[str, Any]:
    """Compute tradable quantity using fixed fractional method with hard caps."""
    try:
        cap = float(capital)
        entry = float(entry_price)
        sl = float(stop_loss)
        deployed = float(capital_deployed)
        open_count = int(open_positions_count)

        if cap <= 0 or entry <= 0:
            return _skip_result(cap, entry, sl, "invalid_capital_or_entry")

        # Hard cap 1: max simultaneous positions
        if open_count >= 3:
            return _skip_result(cap, entry, sl, "max_positions_reached")

        # Hard cap 2: max capital deployed 60%
        if deployed / cap >= 0.60:
            return _skip_result(cap, entry, sl, "max_capital_deployed")

        risk_pct = get_risk_pct(risk_score)
        if risk_pct <= 0.0:
            return _skip_result(cap, entry, sl, "risk_score_too_low")

        risk_amount = cap * risk_pct
        price_distance = abs(entry - sl)
        if price_distance == 0:
            return _skip_result(cap, entry, sl, "entry_equals_stop_loss")

        shares = math.floor(risk_amount / price_distance)
        position_value = shares * entry

        # Hard cap 3: max 2% capital per trade
        max_position_value = cap * 0.02
        if position_value > max_position_value:
            shares = math.floor(max_position_value / entry)
            position_value = shares * entry

        if shares <= 0:
            return _skip_result(cap, entry, sl, "position_too_small")

        cap_risk_pct = (position_value / cap) * 100.0 if cap else 0.0
        return {
            "action": "trade",
            "shares": int(shares),
            "position_value": float(round(position_value, 2)),
            "risk_amount": float(round(risk_amount, 2)),
            "risk_pct_used": float(risk_pct),
            "entry_price": entry,
            "stop_loss": sl,
            "capital": cap,
            "capital_at_risk_pct": float(round(cap_risk_pct, 2)),
            "reason": "position_sized",
        }
    except Exception as exc:
        logger.error("calculate_position_size failed: %s", exc)
        return _skip_result(capital, entry_price, stop_loss, "calculation_error")


def calculate_portfolio_exposure(open_positions: List[Dict], capital: float) -> Dict[str, Any]:
    """Compute aggregate deployed capital and remaining cash constraints."""
    try:
        cap = float(capital)
        rows: List[Dict[str, Any]] = []
        total_deployed = 0.0
        for pos in open_positions or []:
            if not isinstance(pos, dict):
                continue
            entry = float(pos.get("entry_price") or 0.0)
            shares = int(pos.get("shares") or 0)
            value = round(entry * shares, 2)
            total_deployed += value
            row = dict(pos)
            row["position_value"] = value
            rows.append(row)

        total_deployed = round(total_deployed, 2)
        deployed_pct = round((total_deployed / cap) * 100.0, 2) if cap > 0 else 0.0
        cash_available = round(cap - total_deployed, 2) if cap > 0 else 0.0
        cash_pct = round((cash_available / cap) * 100.0, 2) if cap > 0 else 0.0
        open_count = len(rows)
        can_open_new = deployed_pct < 60.0 and open_count < 3 and cash_pct >= 40.0

        return {
            "total_deployed": total_deployed,
            "deployed_pct": deployed_pct,
            "open_count": open_count,
            "cash_available": cash_available,
            "cash_pct": cash_pct,
            "can_open_new": bool(can_open_new),
            "positions": rows,
        }
    except Exception as exc:
        logger.error("calculate_portfolio_exposure failed: %s", exc)
        return {
            "total_deployed": 0.0,
            "deployed_pct": 0.0,
            "open_count": 0,
            "cash_available": float(capital or 0.0),
            "cash_pct": 100.0 if float(capital or 0.0) > 0 else 0.0,
            "can_open_new": False,
            "positions": [],
        }


def format_position_summary(sizing_result: Dict, symbol: str) -> str:
    """Format human-readable position-sizing summary for alerts."""
    try:
        s = sizing_result if isinstance(sizing_result, dict) else {}
        if s.get("action") == "trade":
            return (
                f"📊 {symbol}: Buy {int(s.get('shares', 0))} shares @ Rs.{float(s.get('entry_price', 0.0))}\n"
                f"Capital deployed: Rs.{float(s.get('position_value', 0.0))} "
                f"({float(s.get('capital_at_risk_pct', 0.0)):.1f}% of capital)\n"
                f"Risk amount: Rs.{float(s.get('risk_amount', 0.0))} | "
                f"SL: Rs.{float(s.get('stop_loss', 0.0))}"
            )
        return f"⏭️ {symbol}: Skipped — {s.get('reason', 'unknown_reason')}"
    except Exception as exc:
        logger.error("format_position_summary failed: %s", exc)
        return f"⏭️ {symbol}: Skipped — summary_format_error"
