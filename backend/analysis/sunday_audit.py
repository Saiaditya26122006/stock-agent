"""
Weekly Sunday audit for trading performance and safety guardrails.

This module computes a 7-day resolved-trade audit from `recommendations_log`,
applies hard paper_mode safety rules in `user_config`, sends an HTML email and
compact Telegram summary, and returns a structured `AuditResult`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape

from db.supabase_client import supabase_client
from notifications.email_sender import send_morning_briefing
from notifications.telegram_sender import send_message

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


@dataclass
class AuditResult:
    week_start: str
    week_end: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float  # 0..1
    avg_pnl_pct: float
    best_trade: Dict[str, Any]
    worst_trade: Dict[str, Any]
    best_style: str
    avg_risk_score: float
    avg_sentiment_score: float
    consecutive_losses: int
    verdict: str
    paper_mode_before: bool
    paper_mode_after: bool
    paper_mode_action: str
    next_steps: List[str]
    email_sent: bool
    telegram_sent: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _jinja_env() -> Environment:
    templates_path = Path(__file__).resolve().parent.parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _safe_rows(resp: Any) -> List[Dict[str, Any]]:
    try:
        err = getattr(resp, "error", None)
        if err:
            logger.error("Supabase query error: %s", err)
            return []
        data = getattr(resp, "data", None)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []
    except Exception as exc:
        logger.error("Supabase response parse failed: %s", exc)
        return []


def _verdict(win_rate: float, total: int) -> str:
    if total == 0:
        return "⚪ NO TRADES THIS WEEK — Nothing to audit"
    if win_rate >= 0.55:
        return "🟢 STRONG WEEK — Agent performing above target"
    if win_rate >= 0.45:
        return "🟡 SOLID WEEK — Agent on track"
    if win_rate >= 0.35:
        return "🟠 BELOW TARGET — Review signal thresholds"
    return "🔴 POOR WEEK — Agent paused, review required"


def _next_steps(verdict: str) -> List[str]:
    if verdict.startswith("🟢"):
        return [
            "Keep current risk controls unchanged for next week.",
            "Continue focusing on setups with strong confluence.",
        ]
    if verdict.startswith("🟡"):
        return [
            "Maintain current sizing, but review weak-loss setups.",
            "Tighten entries for low-confidence signals.",
        ]
    if verdict.startswith("🟠"):
        return [
            "Review TA threshold sensitivity for false positives.",
            "Reduce aggressive entries and prioritize high-confidence trades.",
        ]
    if verdict.startswith("🔴"):
        return [
            "Keep paper mode ON and halt real-capital execution.",
            "Audit loss clusters by style and symbol before resuming.",
        ]
    return [
        "No action needed this week.",
        "Wait for more resolved trades to build signal quality evidence.",
    ]


def _compute_consecutive_losses(rows_desc: List[Dict[str, Any]]) -> int:
    streak = 0
    for row in rows_desc:
        outcome = str(row.get("outcome") or "").upper()
        if outcome == "LOSS":
            streak += 1
            continue
        if outcome == "WIN":
            break
    return streak


def _style_win_rate(rows: List[Dict[str, Any]]) -> str:
    style_stats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        style = str(r.get("style") or "unknown").lower()
        outcome = str(r.get("outcome") or "").upper()
        if style not in style_stats:
            style_stats[style] = {"wins": 0, "total": 0}
        style_stats[style]["total"] += 1
        if outcome == "WIN":
            style_stats[style]["wins"] += 1
    if not style_stats:
        return "N/A"
    best = max(
        style_stats.items(),
        key=lambda kv: ((kv[1]["wins"] / kv[1]["total"]) if kv[1]["total"] else 0.0, kv[1]["total"]),
    )
    return best[0]


def _load_week_rows(user_id: str, week_start: str, week_end: str) -> List[Dict[str, Any]]:
    try:
        resp = (
            supabase_client.table("recommendations_log")
            .select("stock,style,pnl,risk_score,sentiment_score,outcome,date,created_at")
            .eq("user_id", user_id)
            .gte("date", week_start)
            .lte("date", week_end)
            .in_("outcome", ["WIN", "LOSS"])
            .order("date", desc=True)
            .execute()
        )
        return _safe_rows(resp)
    except Exception as exc:
        logger.error("Failed loading weekly rows: %s", exc)
        return []


def _get_paper_mode(user_id: str) -> bool:
    try:
        resp = (
            supabase_client.table("user_config")
            .select("paper_mode")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = _safe_rows(resp)
        if not rows:
            return False
        return bool(rows[0].get("paper_mode"))
    except Exception as exc:
        logger.error("Failed reading paper_mode: %s", exc)
        return False


def _set_paper_mode(user_id: str, value: bool) -> bool:
    try:
        resp = (
            supabase_client.table("user_config")
            .update({"paper_mode": bool(value)})
            .eq("user_id", user_id)
            .execute()
        )
        if getattr(resp, "error", None):
            logger.error("Failed updating paper_mode: %s", resp.error)
            return False
        return True
    except Exception as exc:
        logger.error("Paper_mode update exception: %s", exc)
        return False


def run_sunday_audit(user_id: str = "sai_aditya") -> AuditResult:
    """Run weekly audit, apply safety rule, send email/Telegram, and return result."""
    now = _now_ist()
    week_end_dt = now.date()
    week_start_dt = week_end_dt - timedelta(days=6)
    week_start = week_start_dt.isoformat()
    week_end = week_end_dt.isoformat()

    rows = _load_week_rows(user_id=user_id, week_start=week_start, week_end=week_end)

    total = len(rows)
    wins = sum(1 for r in rows if str(r.get("outcome") or "").upper() == "WIN")
    losses = sum(1 for r in rows if str(r.get("outcome") or "").upper() == "LOSS")
    win_rate = (wins / total) if total else 0.0

    pnl_vals = [float(r.get("pnl") or 0.0) for r in rows] if rows else []
    avg_pnl_pct = (sum(pnl_vals) / len(pnl_vals)) if pnl_vals else 0.0

    best_trade = {"stock": None, "pnl_pct": 0.0}
    worst_trade = {"stock": None, "pnl_pct": 0.0}
    if rows:
        best_row = max(rows, key=lambda r: float(r.get("pnl") or 0.0))
        worst_row = min(rows, key=lambda r: float(r.get("pnl") or 0.0))
        best_trade = {"stock": best_row.get("stock"), "pnl_pct": float(best_row.get("pnl") or 0.0)}
        worst_trade = {"stock": worst_row.get("stock"), "pnl_pct": float(worst_row.get("pnl") or 0.0)}

    best_style = _style_win_rate(rows)

    risk_vals = [float(r.get("risk_score") or 0.0) for r in rows] if rows else []
    sent_vals = [float(r.get("sentiment_score") or 0.0) for r in rows] if rows else []
    avg_risk = (sum(risk_vals) / len(risk_vals)) if risk_vals else 0.0
    avg_sent = (sum(sent_vals) / len(sent_vals)) if sent_vals else 0.0

    consecutive_losses = _compute_consecutive_losses(rows_desc=rows)
    verdict = _verdict(win_rate, total)
    steps = _next_steps(verdict)

    # Hard safety rule must run regardless of notification success.
    paper_before = _get_paper_mode(user_id)
    paper_after = paper_before
    paper_action = "unchanged"

    try:
        if win_rate < 0.35 or consecutive_losses >= 3:
            if not paper_before:
                _set_paper_mode(user_id, True)
                paper_after = True
                paper_action = "⚠️ AUTO-PAUSED (paper_mode=True)"
            else:
                paper_after = True
                paper_action = "unchanged"
        elif win_rate >= 0.45 and consecutive_losses < 3 and paper_before:
            _set_paper_mode(user_id, False)
            paper_after = False
            paper_action = "✅ AUTO-RESUMED (paper_mode=False)"
    except Exception as exc:
        logger.error("Safety rule execution failed: %s", exc)

    email_sent = False
    telegram_sent = False
    try:
        template = _jinja_env().get_template("sunday_audit.html")
        html = template.render(
            week_start=week_start,
            week_end=week_end,
            verdict=verdict,
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate_pct=round(win_rate * 100.0, 2),
            avg_pnl_pct=round(avg_pnl_pct, 4),
            avg_risk_score=round(avg_risk, 3),
            avg_sentiment_score=round(avg_sent, 4),
            consecutive_losses=consecutive_losses,
            best_trade=best_trade,
            worst_trade=worst_trade,
            best_style=best_style,
            paper_mode_before=paper_before,
            paper_mode_after=paper_after,
            paper_mode_action=paper_action,
            next_steps=steps,
            generated_at=now.strftime("%Y-%m-%d %H:%M:%S IST"),
        )
        subject = f"📅 NSE/BSE Sunday Audit — {week_start} to {week_end}"
        email_sent = bool(send_morning_briefing(html_content=html, subject=subject))
    except Exception as exc:
        logger.error("Sunday audit email failed: %s", exc)

    try:
        emoji = verdict.split(" ", 1)[0]
        text = (
            f"{emoji} Audit: WR {win_rate*100:.1f}% | Trades {total} | "
            f"Paper {'ON' if paper_after else 'OFF'}"
        )
        if len(text) > 299:
            text = text[:299]
        telegram_sent = bool(asyncio_run_safe_send(text))
    except Exception as exc:
        logger.error("Sunday audit Telegram failed: %s", exc)

    return AuditResult(
        week_start=week_start,
        week_end=week_end,
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=float(round(win_rate, 4)),
        avg_pnl_pct=float(round(avg_pnl_pct, 4)),
        best_trade=best_trade,
        worst_trade=worst_trade,
        best_style=best_style,
        avg_risk_score=float(round(avg_risk, 4)),
        avg_sentiment_score=float(round(avg_sent, 4)),
        consecutive_losses=int(consecutive_losses),
        verdict=verdict,
        paper_mode_before=paper_before,
        paper_mode_after=paper_after,
        paper_mode_action=paper_action,
        next_steps=steps,
        email_sent=email_sent,
        telegram_sent=telegram_sent,
    )


def asyncio_run_safe_send(text: str) -> bool:
    """Send Telegram message from sync context safely."""
    try:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(send_message(text))
        # Already in event loop: fire-and-wait in thread.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(send_message(text))).result()
    except Exception:
        return False


def get_audit_history(user_id: str = "sai_aditya", weeks: int = 4) -> List[Dict[str, Any]]:
    """
    Rolling weekly summaries from recommendations_log for last N weeks.
    """
    try:
        now = _now_ist().date()
        since = (now - timedelta(days=7 * weeks)).isoformat()
        resp = (
            supabase_client.table("recommendations_log")
            .select("date,outcome,pnl")
            .eq("user_id", user_id)
            .gte("date", since)
            .in_("outcome", ["WIN", "LOSS"])
            .order("date", desc=False)
            .execute()
        )
        rows = _safe_rows(resp)
    except Exception as exc:
        logger.error("get_audit_history query failed: %s", exc)
        return []

    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(str(r.get("date"))).date()
            monday = (d - timedelta(days=d.weekday())).isoformat()
            b = buckets.setdefault(
                monday,
                {"week_start": monday, "total_trades": 0, "wins": 0, "losses": 0, "avg_pnl_pct": 0.0, "_pnls": []},
            )
            b["total_trades"] += 1
            if str(r.get("outcome") or "").upper() == "WIN":
                b["wins"] += 1
            else:
                b["losses"] += 1
            b["_pnls"].append(float(r.get("pnl") or 0.0))
        except Exception:
            continue

    out: List[Dict[str, Any]] = []
    for k in sorted(buckets.keys(), reverse=True)[:weeks]:
        b = buckets[k]
        total = b["total_trades"]
        wins = b["wins"]
        avg_pnl = (sum(b["_pnls"]) / len(b["_pnls"])) if b["_pnls"] else 0.0
        out.append(
            {
                "week_start": b["week_start"],
                "total_trades": total,
                "wins": wins,
                "losses": b["losses"],
                "win_rate": float(round((wins / total) if total else 0.0, 4)),
                "avg_pnl_pct": float(round(avg_pnl, 4)),
            }
        )
    return out

