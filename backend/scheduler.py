# TO TEST EMAIL: python -m notifications.email_sender
# TO TEST TELEGRAM: python -m notifications.telegram_sender
# TO TRIGGER MORNING JOB MANUALLY: POST http://localhost:8000/scheduler/trigger-morning
# TO CHECK NEXT RUN TIMES: GET http://localhost:8000/scheduler/status

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jinja2 import Environment, FileSystemLoader, select_autoescape

from analysis.claude_synthesis import get_user_config
from db.recommendations import get_todays_recommendations, get_win_rate
from db.supabase_client import supabase_client
from notifications.email_sender import send_eod_report, send_morning_briefing
from notifications.telegram_sender import send_alert, send_message, send_morning_briefing_telegram


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_SCHEDULER: AsyncIOScheduler | None = None


def _now_ist() -> datetime:
    return datetime.now(IST)


def _get_jinja_env() -> Environment:
    templates_path = Path(__file__).resolve().parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _market_mood_color(mood: str) -> str:
    mood_upper = (mood or "").upper()
    if mood_upper == "NORMAL":
        return "#16a34a"
    if mood_upper == "CAUTION":
        return "#f59e0b"
    return "#dc2626"


def _infer_market_mood(india_vix: float) -> str:
    if india_vix < 14:
        return "NORMAL"
    if india_vix < 18:
        return "CAUTION"
    return "DANGER"


def _derive_morning_payload(run_data: Dict[str, Any]) -> Dict[str, Any]:
    recommendations_map = run_data.get("recommendations", {}) or {}
    recommendations_list: List[Dict[str, Any]] = []
    skipped_stocks: List[Dict[str, str]] = []
    for symbol, rec in recommendations_map.items():
        rec_copy = dict(rec)
        rec_copy.setdefault("symbol", symbol)
        rec_copy.setdefault("risk_score", 5)
        if rec_copy.get("action") in {"BUY", "SELL", "WATCH"}:
            recommendations_list.append(rec_copy)
        else:
            skipped_stocks.append({"symbol": symbol, "reason": rec_copy.get("reasoning", "No clear setup.")})

    user_cfg = get_user_config(user_id="sai_aditya")
    india_vix = 15.0
    market_mood = _infer_market_mood(india_vix)
    return {
        "date": _now_ist().strftime("%A, %d %B %Y"),
        "market_mood": market_mood,
        "market_mood_color": _market_mood_color(market_mood),
        "india_vix": india_vix,
        "recommendations": recommendations_list,
        "skipped_stocks": skipped_stocks,
        "total_analysed": int(run_data.get("stocks_analysed", len(recommendations_map))),
        "daily_target": float(user_cfg.get("daily_target", 0.0)),
        "adjusted_target": round(float(user_cfg.get("daily_target", 0.0)) * 0.9, 2),
        "timestamp": _now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
    }


def _log_scheduler_run(job_name: str, status: str, meta: Dict[str, Any] | None = None) -> None:
    try:
        payload = {
            "run_date": _now_ist().date().isoformat(),
            "started_at": _now_ist().isoformat(),
            "completed_at": _now_ist().isoformat(),
            "status": status,
            "stocks_analysed": int((meta or {}).get("stocks_analysed", 0)),
            "recommendations_count": int((meta or {}).get("recommendations_count", 0)),
            "job_name": job_name,
        }
        supabase_client.table("agent_runs").insert(payload).execute()
    except Exception as exc:
        logger.error("Failed to log scheduler run for %s: %s", job_name, exc)


async def morning_analysis_job() -> None:
    """Run morning analysis, then push email + Telegram briefing."""
    try:
        # Import lazily to avoid circular import while main imports scheduler.
        from main import run_analysis_pipeline

        run_data = run_analysis_pipeline(user_id="sai_aditya")
        payload = _derive_morning_payload(run_data)
        template = _get_jinja_env().get_template("morning_briefing.html")
        html = template.render(**payload)
        subject = f"🌅 NSE/BSE Morning Briefing — {payload['date']} [{payload['market_mood']}]"
        email_ok = send_morning_briefing(html_content=html, subject=subject)
        tg_ok = send_morning_briefing_telegram(
            recommendations=payload["recommendations"],
            market_mood=payload["market_mood"],
            market_regime=str(run_data.get("market_regime") or payload["market_mood"]),
            india_vix=float(run_data.get("india_vix", payload.get("india_vix", 15.0))),
            special_day_alert=str(
                ((run_data.get("premarket_context") or {}).get("morning_alert") or "")
            ).strip(),
        )
        _log_scheduler_run(
            job_name="morning_analysis_job",
            status="completed" if (email_ok and tg_ok) else "partial_failure",
            meta={
                "stocks_analysed": payload["total_analysed"],
                "recommendations_count": len(
                    [r for r in payload["recommendations"] if r.get("action") in {"BUY", "SELL"}]
                ),
            },
        )
    except Exception as exc:
        logger.error("morning_analysis_job failed: %s", exc)
        _log_scheduler_run("morning_analysis_job", "failed")


def _render_eod_html(today_recs: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    rows = []
    for rec in today_recs:
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #e5e7eb'>{rec.get('stock','')}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb'>{rec.get('style','')}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb'>{rec.get('outcome','still_open')}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb'>{rec.get('pnl', 0)}</td>"
            "</tr>"
        )
    body_rows = "".join(rows) if rows else "<tr><td colspan='4' style='padding:8px'>No recommendations today.</td></tr>"
    return (
        "<html><body style='font-family:Arial,sans-serif'>"
        f"<h3>NSE/BSE EOD Report — {_now_ist().strftime('%d %b %Y')}</h3>"
        f"<p>Total: {summary['total']} | Closed: {summary['closed']} | Wins: {summary['wins']} | Losses: {summary['losses']}</p>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<tr><th style='padding:8px;border:1px solid #e5e7eb'>Stock</th>"
        "<th style='padding:8px;border:1px solid #e5e7eb'>Style</th>"
        "<th style='padding:8px;border:1px solid #e5e7eb'>Outcome</th>"
        "<th style='padding:8px;border:1px solid #e5e7eb'>PnL</th></tr>"
        f"{body_rows}</table></body></html>"
    )


async def eod_report_job() -> None:
    """Build and send EOD summary on weekdays."""
    try:
        recs = get_todays_recommendations(user_id="sai_aditya")
        closed = [r for r in recs if (r.get("outcome") not in (None, "still_open"))]
        wins = [r for r in closed if r.get("outcome") in ("hit_target", "paper_hit_target")]
        losses = [r for r in closed if r.get("outcome") not in ("hit_target", "paper_hit_target")]
        summary = {
            "total": len(recs),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
        }
        eod_html = _render_eod_html(recs, summary)
        email_ok = send_eod_report(html_content=eod_html)
        tg_text = (
            f"📘 EOD SUMMARY — {_now_ist().strftime('%d %b %Y')}\n"
            f"Total: {summary['total']} | Closed: {summary['closed']}\n"
            f"Wins: {summary['wins']} | Losses: {summary['losses']}"
        )
        tg_ok = await send_message(tg_text)
        _log_scheduler_run(
            job_name="eod_report_job",
            status="completed" if (email_ok and tg_ok) else "partial_failure",
            meta={"stocks_analysed": len(recs), "recommendations_count": len(recs)},
        )
    except Exception as exc:
        logger.error("eod_report_job failed: %s", exc)
        _log_scheduler_run("eod_report_job", "failed")


async def sunday_audit_job() -> None:
    """Compute weekly health and enforce paper_mode guardrails."""
    try:
        stats = get_win_rate(user_id="sai_aditya", last_n=20)
        win_rate = float(stats.get("win_rate", 0.0))
        status_msg = ""
        if win_rate < 45.0:
            try:
                supabase_client.table("user_config").update({"paper_mode": True}).eq(
                    "user_id", "sai_aditya"
                ).execute()
            except Exception as upd_exc:
                logger.error("Failed to set paper_mode=true: %s", upd_exc)
            status_msg = "PAUSE MODE ACTIVATED (paper_mode=true)"
            send_alert("PORTFOLIO", "weekly_audit_pause", f"Win rate dropped to {win_rate}%.")
        elif win_rate >= 55.0:
            status_msg = "HEALTHY PERFORMANCE"
        else:
            status_msg = "NEUTRAL PERFORMANCE"

        tg_text = (
            "📅 SUNDAY AUDIT\n"
            f"Win rate (last 20): {win_rate}%\n"
            f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}\n"
            f"Status: {status_msg}"
        )
        await send_message(tg_text)
        _log_scheduler_run("sunday_audit_job", "completed", meta={"recommendations_count": stats.get("total", 0)})
    except Exception as exc:
        logger.error("sunday_audit_job failed: %s", exc)
        _log_scheduler_run("sunday_audit_job", "failed")


def trigger_morning_now() -> bool:
    """Trigger morning job immediately without waiting for schedule."""
    try:
        scheduler = _SCHEDULER
        if scheduler and scheduler.running:
            scheduler.add_job(morning_analysis_job)
            return True
        return False
    except Exception as exc:
        logger.error("Failed to trigger morning job manually: %s", exc)
        return False


def init_scheduler(_app) -> AsyncIOScheduler:
    """Create and start the shared scheduler for FastAPI runtime."""
    global _SCHEDULER
    if _SCHEDULER and _SCHEDULER.running:
        return _SCHEDULER

    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        morning_analysis_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=8,
        minute=52,
        id="morning_analysis_job",
        replace_existing=True,
    )
    scheduler.add_job(
        eod_report_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=15,
        minute=45,
        id="eod_report_job",
        replace_existing=True,
    )
    scheduler.add_job(
        sunday_audit_job,
        trigger="cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        id="sunday_audit_job",
        replace_existing=True,
    )
    scheduler.start()
    _SCHEDULER = scheduler
    logger.info("Scheduler initialized with Asia/Kolkata timezone.")
    return scheduler


def get_scheduler_status() -> Dict[str, Any]:
    """Expose scheduler health and next run times."""
    scheduler = _SCHEDULER
    if not scheduler:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
        )
    return {"running": bool(scheduler.running), "timezone": "Asia/Kolkata", "jobs": jobs}
