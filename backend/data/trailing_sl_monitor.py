"""
Live trailing stop-loss monitor.

Runs at 9:20 AM IST on market days (scheduled job).
Polls open BUY positions every 30 seconds using Upstox live quotes.
Uses REST polling instead of WebSocket for simplicity and reliability.

Trailing rules:
  +1% above entry  -> trail SL to breakeven (entry price)
  +2% above entry  -> trail SL to entry + 0.5%
  price <= SL      -> mark hit_sl, send Telegram alert
  price >= target  -> mark hit_target, send Telegram alert

Market hours guard: only runs 9:15 AM to 3:30 PM IST.
Auto-stops when all positions are resolved.
All exceptions caught - never crashes the app.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Poll interval in seconds
_POLL_INTERVAL = 30

# Global positions store with async lock
_ACTIVE_POSITIONS: Dict[str, "_Position"] = {}
_POSITIONS_LOCK: asyncio.Lock = asyncio.Lock()


@dataclass
class _Position:
    rec_id: str
    symbol: str
    action: str             # BUY or SELL
    entry_price: float
    original_sl: float
    current_sl: float
    target: float
    trailed: bool = False   # True once SL has been trailed at least once
    resolved: bool = False


# ---------------------------------------------------------------------------
# Market hours guard
# ---------------------------------------------------------------------------

def _is_market_open() -> bool:
    """Return True if current IST time is within 9:15 AM - 3:30 PM on a weekday."""
    now = datetime.now(IST)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    t = now.time()
    return time(9, 15) <= t <= time(15, 30)


# ---------------------------------------------------------------------------
# Load open positions from Supabase
# ---------------------------------------------------------------------------

def _load_open_positions(user_id: str) -> List[_Position]:
    """Query recommendations_log for open BUY recs with no outcome."""
    try:
        from db.supabase_client import supabase_client
        resp = (
            supabase_client.table("recommendations_log")
            .select("id, stock, action, entry_price, target, stop_loss, outcome")
            .eq("user_id", user_id)
            .eq("date", date.today().isoformat())
            .in_("action", ["BUY", "SELL"])
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        positions = []
        for r in rows:
            if r.get("outcome") not in (None, "still_open"):
                continue   # already resolved
            positions.append(_Position(
                rec_id=str(r["id"]),
                symbol=str(r["stock"]),
                action=str(r.get("action", "BUY")).upper(),
                entry_price=float(r.get("entry_price") or 0.0),
                original_sl=float(r.get("stop_loss") or 0.0),
                current_sl=float(r.get("stop_loss") or 0.0),
                target=float(r.get("target") or 0.0),
            ))
        logger.info("trailing_sl: loaded %d open positions", len(positions))
        return positions
    except Exception as exc:
        logger.error("_load_open_positions failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Live price fetch (REST polling)
# ---------------------------------------------------------------------------

def _fetch_price(symbol: str) -> Optional[float]:
    try:
        from data.upstox import get_live_quote
        q = get_live_quote(symbol)
        p = float(q.get("last_price") or 0.0)
        return p if p > 0 else None
    except Exception as exc:
        logger.warning("trailing_sl: price fetch failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Supabase outcome update
# ---------------------------------------------------------------------------

def _mark_resolved(pos: _Position, outcome: str, exit_price: float) -> None:
    try:
        from db.recommendations import update_outcome
        if pos.entry_price > 0:
            if pos.action == "BUY":
                pnl = round(((exit_price - pos.entry_price) / pos.entry_price) * 100.0, 4)
            else:
                pnl = round(((pos.entry_price - exit_price) / pos.entry_price) * 100.0, 4)
        else:
            pnl = 0.0
        agent_correct = (outcome == "hit_target")
        update_outcome(rec_id=pos.rec_id, outcome=outcome,
                       actual_exit=exit_price, pnl=pnl, agent_correct=agent_correct)
        logger.info("trailing_sl: marked %s %s -> outcome=%s @ %.2f", pos.symbol, pos.action, outcome, exit_price)
    except Exception as exc:
        logger.error("trailing_sl: _mark_resolved failed for %s: %s", pos.symbol, exc)


# ---------------------------------------------------------------------------
# Telegram alert
# ---------------------------------------------------------------------------

def _send_alert(symbol: str, outcome: str, price: float, pnl_pct: float) -> None:
    try:
        from notifications.telegram_sender import send_alert
        emoji = "🎯" if outcome == "hit_target" else "🛑"
        msg = (f"{emoji} {symbol} — {outcome.upper().replace(chr(95), chr(32))}\n"
               f"Exit: Rs.{price:.2f} | P&L: {pnl_pct:+.2f}%")
        send_alert(symbol, outcome, msg)
    except Exception as exc:
        logger.warning("trailing_sl: Telegram alert failed for %s: %s", symbol, exc)


# ---------------------------------------------------------------------------
# Trailing SL logic
# ---------------------------------------------------------------------------

def _apply_trailing_rules(pos: _Position, current_price: float) -> None:
    """Advance the trailing SL based on current price vs entry."""
    if pos.action != "BUY":
        return   # trailing only implemented for BUY positions
    if pos.entry_price <= 0:
        return
    gain_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0
    if gain_pct >= 2.0:
        new_sl = round(pos.entry_price * 1.005, 2)   # entry + 0.5%
        if new_sl > pos.current_sl:
            logger.info("trailing_sl: %s trail SL %.2f -> %.2f (+2%% rule)", pos.symbol, pos.current_sl, new_sl)
            pos.current_sl = new_sl
            pos.trailed = True
    elif gain_pct >= 1.0:
        new_sl = pos.entry_price   # breakeven
        if new_sl > pos.current_sl:
            logger.info("trailing_sl: %s trail SL %.2f -> %.2f (breakeven)", pos.symbol, pos.current_sl, new_sl)
            pos.current_sl = new_sl
            pos.trailed = True


async def _monitor_position(pos: _Position) -> None:
    """Poll price for a single position until resolved or market close."""
    logger.info("trailing_sl: monitoring %s entry=%.2f sl=%.2f target=%.2f",
                pos.symbol, pos.entry_price, pos.current_sl, pos.target)
    while not pos.resolved and _is_market_open():
        try:
            price = _fetch_price(pos.symbol)
            if price is None:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            _apply_trailing_rules(pos, price)

            if pos.action == "BUY":
                sl_hit     = price <= pos.current_sl
                target_hit = price >= pos.target
            else:
                sl_hit     = price >= pos.current_sl
                target_hit = price <= pos.target

            if target_hit:
                pos.resolved = True
                pnl = _calc_pnl(pos, price)
                _mark_resolved(pos, "hit_target", price)
                _send_alert(pos.symbol, "hit_target", price, pnl)
                logger.info("trailing_sl: TARGET HIT %s @ %.2f", pos.symbol, price)
            elif sl_hit:
                pos.resolved = True
                pnl = _calc_pnl(pos, price)
                _mark_resolved(pos, "hit_sl", price)
                _send_alert(pos.symbol, "hit_sl", price, pnl)
                logger.info("trailing_sl: SL HIT %s @ %.2f", pos.symbol, price)

        except Exception as exc:
            logger.error("trailing_sl: _monitor_position error for %s: %s", pos.symbol, exc)

        if not pos.resolved:
            await asyncio.sleep(_POLL_INTERVAL)


def _calc_pnl(pos: _Position, exit_price: float) -> float:
    if pos.entry_price <= 0:
        return 0.0
    if pos.action == "BUY":
        return round(((exit_price - pos.entry_price) / pos.entry_price) * 100.0, 4)
    return round(((pos.entry_price - exit_price) / pos.entry_price) * 100.0, 4)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def start_trailing_sl_monitor(user_id: str = "sai_aditya") -> None:
    """
    Load open positions and monitor all of them concurrently.
    Called by the 9:20 AM scheduler job.
    Auto-exits when all positions are resolved or market closes.
    Never raises.
    """
    global _ACTIVE_POSITIONS
    try:
        if not _is_market_open():
            logger.info("trailing_sl: market is closed — monitor not started")
            return

        positions = _load_open_positions(user_id=user_id)
        if not positions:
            logger.info("trailing_sl: no open positions to monitor")
            return

        async with _POSITIONS_LOCK:
            _ACTIVE_POSITIONS = {p.symbol: p for p in positions}

        logger.info("trailing_sl: starting monitor for %d positions: %s",
                    len(positions), [p.symbol for p in positions])

        tasks = [asyncio.create_task(_monitor_position(p)) for p in positions]
        await asyncio.gather(*tasks, return_exceptions=True)

        async with _POSITIONS_LOCK:
            _ACTIVE_POSITIONS = {}

        logger.info("trailing_sl: all positions resolved or market closed")

    except Exception as exc:
        logger.error("start_trailing_sl_monitor failed: %s", exc)


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------

async def get_monitor_status() -> Dict[str, Any]:
    """Return current active positions for health checks."""
    async with _POSITIONS_LOCK:
        return {
            "active_count": len(_ACTIVE_POSITIONS),
            "market_open": _is_market_open(),
            "positions": [
                {
                    "symbol": p.symbol,
                    "action": p.action,
                    "entry": p.entry_price,
                    "current_sl": p.current_sl,
                    "original_sl": p.original_sl,
                    "target": p.target,
                    "trailed": p.trailed,
                    "resolved": p.resolved,
                }
                for p in _ACTIVE_POSITIONS.values()
            ],
        }
