"""Gift Nifty pre-market analyzer and special-day calendar overrides.

NOTE: Update the hardcoded calendar each year.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def get_special_days_2026() -> List[Dict[str, Any]]:
    """Return hardcoded special event calendar for 2026."""
    return [
        {"date": "2026-02-07", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-04-09", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-06-06", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-08-08", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-10-07", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-12-05", "event": "RBI MPC Decision", "category": "RBI", "impact": "HIGH"},
        {"date": "2026-01-29", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-03-19", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-05-07", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-06-18", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-07-30", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-09-17", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-11-05", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-12-17", "event": "US Fed FOMC Decision", "category": "FED", "impact": "MEDIUM"},
        {"date": "2026-02-01", "event": "Union Budget", "category": "BUDGET", "impact": "HIGH"},
        {"date": "2026-01-29", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-02-26", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-03-26", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-04-30", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-05-28", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-06-25", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-07-30", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-08-27", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-09-24", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-10-29", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-11-26", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
        {"date": "2026-12-31", "event": "NSE F&O Expiry", "category": "FNO_EXPIRY", "impact": "MEDIUM"},
    ]


def check_special_day(check_date: date = None) -> Dict[str, Any]:
    """Check whether date is special day or event eve."""
    try:
        today = check_date or datetime.now(IST).date()
        tomorrow = today + timedelta(days=1)
        events = get_special_days_2026()

        today_match = None
        eve_match = None
        for item in events:
            d = item.get("date")
            if d == today.isoformat():
                today_match = item
                break
            if d == tomorrow.isoformat() and eve_match is None:
                eve_match = item

        if today_match:
            event = str(today_match.get("event", ""))
            return {
                "is_special_day": True,
                "is_eve": False,
                "event": event,
                "category": str(today_match.get("category", "")),
                "impact": str(today_match.get("impact", "")),
                "position_modifier": 0.5,
                "alert_message": f"⚠️ {event} today — reduced exposure mode active (50% position size)",
            }
        if eve_match:
            event = str(eve_match.get("event", ""))
            return {
                "is_special_day": False,
                "is_eve": True,
                "event": event,
                "category": str(eve_match.get("category", "")),
                "impact": str(eve_match.get("impact", "")),
                "position_modifier": 0.75,
                "alert_message": f"📅 {event} tomorrow — cautious sizing active (75% position size)",
            }
        return {
            "is_special_day": False,
            "is_eve": False,
            "event": "",
            "category": "",
            "impact": "",
            "position_modifier": 1.0,
            "alert_message": "",
        }
    except Exception as exc:
        logger.error("check_special_day failed: %s", exc)
        return {
            "is_special_day": False,
            "is_eve": False,
            "event": "",
            "category": "",
            "impact": "",
            "position_modifier": 1.0,
            "alert_message": "",
        }


def get_fo_expiry_weeks() -> List[str]:
    """Return F&O expiry dates for current year."""
    try:
        year = datetime.now(IST).year
        return [
            str(item.get("date"))
            for item in get_special_days_2026()
            if item.get("category") == "FNO_EXPIRY" and str(item.get("date", "")).startswith(f"{year}-")
        ]
    except Exception as exc:
        logger.error("get_fo_expiry_weeks failed: %s", exc)
        return []


def analyze_gift_nifty(gift_nifty_data: Dict) -> Dict[str, Any]:
    """Map Gift Nifty % change into signal and position modifier."""
    try:
        pct_change = float((gift_nifty_data or {}).get("pct_change", 0.0) or 0.0)
    except Exception:
        pct_change = 0.0

    if pct_change > 1.0:
        signal = "strong_bullish"
        description = "Gap up expected — bullish bias"
        modifier = 1.1
    elif pct_change >= 0.5:
        signal = "bullish"
        description = "Mild gap up expected"
        modifier = 1.0
    elif pct_change >= -0.5:
        signal = "neutral"
        description = "Flat open expected"
        modifier = 1.0
    elif pct_change >= -1.0:
        signal = "bearish"
        description = "Mild gap down expected"
        modifier = 0.9
    else:
        signal = "strong_bearish"
        description = "Gap down expected — bearish bias"
        modifier = 0.8

    return {
        "pct_change": float(pct_change),
        "signal": signal,
        "description": description,
        "position_modifier": float(modifier),
        "briefing_line": f"🌅 Gift Nifty: {pct_change:+.2f}% — {description}",
    }


def get_full_premarket_context(gift_nifty_data: Dict, check_date: date = None) -> Dict[str, Any]:
    """Combine Gift Nifty signal with special-day overrides."""
    try:
        gift = analyze_gift_nifty(gift_nifty_data or {})
        special = check_special_day(check_date=check_date)
        combined = float(gift.get("position_modifier", 1.0)) * float(special.get("position_modifier", 1.0))
        combined = max(0.3, combined)

        special_line = ""
        alert = str(special.get("alert_message", ""))
        if alert:
            special_line = f"⚠️ Special Day: {special.get('event')} ({special.get('impact')})"
            morning_alert = f"{alert}\n{gift.get('briefing_line', '')}".strip()
        else:
            morning_alert = ""

        lines = [str(gift.get("briefing_line", ""))]
        if special_line:
            lines.append(special_line)
        lines = [ln for ln in lines if ln]

        return {
            "gift_nifty": gift,
            "special_day": special,
            "combined_position_modifier": float(round(combined, 3)),
            "morning_alert": morning_alert,
            "briefing_lines": lines,
        }
    except Exception as exc:
        logger.error("get_full_premarket_context failed: %s", exc)
        gift = analyze_gift_nifty({})
        return {
            "gift_nifty": gift,
            "special_day": {
                "is_special_day": False,
                "is_eve": False,
                "event": "",
                "category": "",
                "impact": "",
                "position_modifier": 1.0,
                "alert_message": "",
            },
            "combined_position_modifier": 1.0,
            "morning_alert": "",
            "briefing_lines": [gift.get("briefing_line", "")],
        }
