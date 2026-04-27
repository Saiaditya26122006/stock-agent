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

from analysis.gemini_synthesis import get_user_config
from db.recommendations import get_todays_recommendations, get_win_rate
from db.outcome_logger import run_outcome_logger
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
    india_vix = float(run_data.get("india_vix", 15.0))
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
        from db.watchlist import get_symbols_list

        symbols = get_symbols_list(user_id="sai_aditya")
        run_data = run_analysis_pipeline(user_id="sai_aditya")
        payload = _derive_morning_payload(run_data)
        template = _get_jinja_env().get_template("morning_briefing.html")
        html = template.render(**payload)
        subject = f"🌅 NSE/BSE Morning Briefing — {payload['date']} [{payload['market_mood']}]"
        try:
            email_ok = send_morning_briefing(html_content=html, subject=subject)
            logger.info(f"Morning briefing email result: {email_ok}")
        except Exception as e:
            logger.error(f"Morning briefing email FAILED: {e}")
            email_ok = False
        tg_ok = send_morning_briefing_telegram(
            recommendations=payload["recommendations"],
            market_mood=payload["market_mood"],
            market_regime=str(run_data.get("market_regime") or payload["market_mood"]),
            india_vix=float(run_data.get("india_vix", payload.get("india_vix", 15.0))),
            special_day_alert=str(
                ((run_data.get("premarket_context") or {}).get("morning_alert") or "")
            ).strip(),
            stocks_analysed=len(symbols),
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
        from notifications.eod_report import send_eod_report as execute_eod_report
        report = execute_eod_report()
        
        status = "completed" if report else "partial_failure"
        stocks_analysed = report.total_recommendations if report else 0
        
        _log_scheduler_run(
            job_name="eod_report_job",
            status=status,
            meta={"stocks_analysed": stocks_analysed, "recommendations_count": stocks_analysed},
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

        # Re-train the contextual bandit with latest closed trades
        try:
            from analysis.bandit_evaluator import run_bandit_evaluation
            bandit_result = run_bandit_evaluation(user_id="sai_aditya", last_n=500)
            bandit_status = f"Bandit: {bandit_result.get('processed', 0)} trades | trusted={bandit_result.get('trusted', False)}"
        except Exception as exc:
            logger.warning("sunday_audit_job: bandit evaluation failed: %s", exc)
            bandit_status = "Bandit update: skipped"

        tg_text = (
            "📅 SUNDAY AUDIT\n"
            f"Win rate (last 20): {win_rate}%\n"
            f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}\n"
            f"Status: {status_msg}\n"
            f"🤖 {bandit_status}"
        )
        await send_message(tg_text)
        _log_scheduler_run("sunday_audit_job", "completed", meta={"recommendations_count": stats.get("total", 0)})
    except Exception as exc:
        logger.error("sunday_audit_job failed: %s", exc)
        _log_scheduler_run("sunday_audit_job", "failed")


async def trailing_sl_monitor_job() -> None:
    """9:20 AM: start trailing SL WebSocket monitor for open intraday positions."""
    try:
        logger.info("Trailing SL monitor job started")
        from data.trailing_sl_monitor import start_trailing_sl_monitor
        await start_trailing_sl_monitor()
    except Exception as exc:
        logger.error("Trailing SL monitor job failed: %s", exc)
        _log_scheduler_run("trailing_sl_monitor_job", "failed")


async def weekly_portfolio_job() -> None:
    """Sunday 10 AM: send weekly long-term portfolio health digest."""
    try:
        from notifications.telegram_sender import send_weekly_portfolio_digest
        from db.outcome_logger import get_outcomes_summary
        rolling = get_outcomes_summary(user_id="sai_aditya", last_days=7)
        await send_weekly_portfolio_digest(rolling_summary=rolling)
        _log_scheduler_run("weekly_portfolio_job", "completed",
                           meta={"recommendations_count": rolling.get("total", 0)})
    except Exception as exc:
        logger.error("weekly_portfolio_job failed: %s", exc)
        _log_scheduler_run("weekly_portfolio_job", "failed")


async def intraday_exit_alert_job() -> None:
    """3:10 PM Mon-Fri: warn about any intraday positions still open near market close."""
    try:
        from db.recommendations import get_todays_recommendations
        from notifications.telegram_sender import send_exit_alert
        today_recs = get_todays_recommendations(user_id="sai_aditya")
        open_intraday = [
            r for r in today_recs
            if r.get("style") == "intraday"
            and r.get("outcome") in (None, "still_open")
            and r.get("action") in ("BUY", "SELL")
        ]
        for rec in open_intraday:
            await send_exit_alert(
                symbol=rec.get("stock", ""),
                reason="Market closes in 20 minutes — exit all intraday positions now.",
                current_price=None,
                entry_price=float(rec.get("entry_price", 0.0)),
            )
        _log_scheduler_run("intraday_exit_alert_job", "completed",
                           meta={"recommendations_count": len(open_intraday)})
    except Exception as exc:
        logger.error("intraday_exit_alert_job failed: %s", exc)
        _log_scheduler_run("intraday_exit_alert_job", "failed")


async def drawdown_check_job() -> None:
    """11 AM Mon-Fri: check long-term holdings for >8% drawdown and alert."""
    try:
        from db.recommendations import get_todays_recommendations
        from data.upstox import get_live_quote
        from notifications.telegram_sender import send_drawdown_alert
        # Pull recent BUY/LONG_TERM recs still open
        from db.supabase_client import supabase_client
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        resp = (
            supabase_client.table("recommendations_log")
            .select("stock, entry_price, horizon, outcome")
            .eq("user_id", "sai_aditya")
            .eq("horizon", "LONG_TERM")
            .eq("action", "BUY")
            .in_("outcome", ["still_open", None])
            .gte("date", cutoff)
            .execute()
        )
        holdings = getattr(resp, "data", None) or []
        for h in holdings:
            try:
                symbol = h.get("stock", "")
                entry  = float(h.get("entry_price") or 0.0)
                if entry <= 0 or not symbol:
                    continue
                quote = get_live_quote(symbol)
                price = float(quote.get("last_price") or quote.get("ltp") or 0.0)
                if price <= 0:
                    continue
                drawdown_pct = ((entry - price) / entry) * 100.0
                if drawdown_pct >= 8.0:
                    await send_drawdown_alert(
                        symbol=symbol,
                        entry_price=entry,
                        current_price=price,
                        drawdown_pct=round(drawdown_pct, 2),
                    )
            except Exception as exc:
                logger.warning("drawdown_check_job: error for %s: %s", h.get("stock"), exc)
        _log_scheduler_run("drawdown_check_job", "completed",
                           meta={"stocks_analysed": len(holdings)})
    except Exception as exc:
        logger.error("drawdown_check_job failed: %s", exc)
        _log_scheduler_run("drawdown_check_job", "failed")


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
        trailing_sl_monitor_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=9,
        minute=20,
        id="trailing_sl_monitor_job",
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
    # Weekly long-term portfolio health digest — Sunday 10 AM
    scheduler.add_job(
        weekly_portfolio_job,
        trigger="cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        id="weekly_portfolio_job",
        replace_existing=True,
    )
    # Intraday time-based exit alert — 3:10 PM Mon-Fri (warn before 3:30 close)
    scheduler.add_job(
        intraday_exit_alert_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=15,
        minute=10,
        id="intraday_exit_alert_job",
        replace_existing=True,
    )
    # Long-term drawdown check — 11 AM Mon-Fri
    scheduler.add_job(
        drawdown_check_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour=11,
        minute=0,
        id="drawdown_check_job",
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
