"""
Watchlist management module backed by Supabase.

Provides CRUD-style helpers for the `watchlist` table.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from db.supabase_client import supabase_client


logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z]+$")


def _safe_response(resp: Any, context: str) -> List[Dict[str, Any]]:
    """
    Extract data from a Supabase response, logging any errors.

    Returns an empty list on error.
    """

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
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("%s unexpected response handling error: %s", context, exc)
        return []


def get_active_watchlist(user_id: str = "sai_aditya") -> List[Dict[str, Any]]:
    """
    Fetch all active watchlist entries for a given user.

    Args:
        user_id: Owner of the watchlist rows.

    Returns:
        List of dicts: {id, symbol, exchange, added_date, active}, sorted by symbol.
        Returns an empty list on error and logs the issue.
    """

    try:
        resp = (
            supabase_client.table("watchlist")
            .select("id, symbol, exchange, added_date, active")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("symbol", desc=False)
            .execute()
        )
        rows = _safe_response(resp, "get_active_watchlist")
        if not rows:
            logger.info("get_active_watchlist: no active symbols for user %s", user_id)
        return rows
    except Exception as exc:
        logger.error("get_active_watchlist failed: %s", exc)
        return []


def add_symbol(
    symbol: str, exchange: str = "NSE", user_id: str = "sai_aditya"
) -> Dict[str, Any]:
    """
    Add a new symbol to the watchlist or reactivate an existing one.

    Args:
        symbol: Uppercase ticker (letters only, no spaces or digits).
        exchange: 'NSE' or 'BSE'.
        user_id: Owner of the watchlist row.

    Returns:
        {success: bool, message: str, action: 'added'|'reactivated'|'error'}
    """

    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        return {
            "success": False,
            "message": "Symbol must be uppercase letters only (no spaces or numbers).",
            "action": "error",
        }

    try:
        # Does this symbol already exist for this user & exchange?
        resp = (
            supabase_client.table("watchlist")
            .select("id, active")
            .eq("user_id", user_id)
            .eq("symbol", sym)
            .eq("exchange", exchange)
            .limit(1)
            .execute()
        )
        existing_rows = _safe_response(resp, "add_symbol-select")

        if existing_rows:
            row_id = existing_rows[0]["id"]
            # Reactivate instead of inserting a duplicate.
            upd = (
                supabase_client.table("watchlist")
                .update({"active": True})
                .eq("id", row_id)
                .execute()
            )
            if getattr(upd, "error", None):
                logger.error("add_symbol reactivation error: %s", upd.error)
                return {
                    "success": False,
                    "message": "Failed to reactivate existing watchlist symbol.",
                    "action": "error",
                }
            return {
                "success": True,
                "message": f"Symbol {sym} reactivated in watchlist.",
                "action": "reactivated",
            }

        # Insert new row
        ins = (
            supabase_client.table("watchlist")
            .insert(
                {
                    "user_id": user_id,
                    "symbol": sym,
                    "exchange": exchange,
                    "active": True,
                }
            )
            .execute()
        )
        if getattr(ins, "error", None):
            logger.error("add_symbol insert error: %s", ins.error)
            return {
                "success": False,
                "message": "Failed to add symbol to watchlist.",
                "action": "error",
            }
        return {
            "success": True,
            "message": f"Symbol {sym} added to watchlist.",
            "action": "added",
        }
    except Exception as exc:
        logger.error("add_symbol failed: %s", exc)
        return {
            "success": False,
            "message": "Unexpected error while adding symbol.",
            "action": "error",
        }


def remove_symbol(symbol: str, user_id: str = "sai_aditya") -> Dict[str, Any]:
    """
    Soft-delete a symbol from the watchlist by setting active = false.

    Args:
        symbol: Ticker to deactivate.
        user_id: Owner of the watchlist.

    Returns:
        {success: bool, message: str}
    """

    sym = symbol.strip().upper()
    try:
        # Ensure the symbol exists
        resp = (
            supabase_client.table("watchlist")
            .select("id, active")
            .eq("user_id", user_id)
            .eq("symbol", sym)
            .limit(1)
            .execute()
        )
        rows = _safe_response(resp, "remove_symbol-select")
        if not rows:
            return {
                "success": False,
                "message": f"Symbol {sym} not found in watchlist for user {user_id}.",
            }

        row_id = rows[0]["id"]
        upd = (
            supabase_client.table("watchlist")
            .update({"active": False})
            .eq("id", row_id)
            .execute()
        )
        if getattr(upd, "error", None):
            logger.error("remove_symbol update error: %s", upd.error)
            return {
                "success": False,
                "message": f"Failed to deactivate symbol {sym}.",
            }
        return {
            "success": True,
            "message": f"Symbol {sym} deactivated in watchlist.",
        }
    except Exception as exc:
        logger.error("remove_symbol failed: %s", exc)
        return {
            "success": False,
            "message": "Unexpected error while removing symbol.",
        }


def get_symbols_list(user_id: str = "sai_aditya") -> List[str]:
    """
    Return a simple list of active symbols for the given user.

    Args:
        user_id: Owner of the watchlist.

    Returns:
        List of symbol strings, sorted alphabetically. Returns [] on error.
    """

    rows = get_active_watchlist(user_id=user_id)
    return sorted({row["symbol"] for row in rows}) if rows else []


def update_symbol_exchange(
    symbol: str, exchange: str, user_id: str = "sai_aditya"
) -> Dict[str, Any]:
    """
    Update the exchange for an existing watchlist symbol.

    Args:
        symbol: Ticker to update.
        exchange: Target exchange ('NSE' or 'BSE').
        user_id: Owner of the watchlist.

    Returns:
        {success: bool, message: str}
    """

    sym = symbol.strip().upper()
    ex = exchange.strip().upper()
    if ex not in ("NSE", "BSE"):
        return {
            "success": False,
            "message": "Exchange must be either 'NSE' or 'BSE'.",
        }

    try:
        resp = (
            supabase_client.table("watchlist")
            .select("id")
            .eq("user_id", user_id)
            .eq("symbol", sym)
            .limit(1)
            .execute()
        )
        rows = _safe_response(resp, "update_symbol_exchange-select")
        if not rows:
            return {
                "success": False,
                "message": f"Symbol {sym} not found in watchlist for user {user_id}.",
            }

        row_id = rows[0]["id"]
        upd = (
            supabase_client.table("watchlist")
            .update({"exchange": ex})
            .eq("id", row_id)
            .execute()
        )
        if getattr(upd, "error", None):
            logger.error("update_symbol_exchange update error: %s", upd.error)
            return {
                "success": False,
                "message": f"Failed to update exchange for symbol {sym}.",
            }
        return {
            "success": True,
            "message": f"Exchange for symbol {sym} updated to {ex}.",
        }
    except Exception as exc:
        logger.error("update_symbol_exchange failed: %s", exc)
        return {
            "success": False,
            "message": "Unexpected error while updating exchange.",
        }

